#!/usr/bin/env python3
"""Run tests with bounded execution and a reproducibility manifest.

    build   build once, produce .xctestrun files for later runs
    test    run tests and write an .xcresult
    plan    print the exact command without running it

Examples

    # discover first -- never guess a scheme or destination
    python3 test_doctor.py --destinations

    # build once, run many (the right shape for repeated or matrix runs)
    python3 run_tests.py build --scheme MyApp --destination-id <UDID> --out run/
    python3 run_tests.py test  --xctestrun run/Build/Products/MyApp_Fast_*.xctestrun \\
        --destination-id <UDID> --out run/fast

    # one-shot
    python3 run_tests.py test --scheme MyApp --plan Fast \\
        --destination-id <UDID> --coverage --out run/fast

    # flake protocol -- see references/failure-triage.md
    python3 run_tests.py test ... --repetition retry      --out run/mode-retry
    python3 run_tests.py test ... --repetition relaunch   --out run/mode-relaunch

WHAT THIS GUARANTEES

* Arguments are passed as a vector, never interpolated into a shell string. A
  bundle id, test filter or path containing shell metacharacters cannot change
  the meaning of the command.
* A watchdog bounds the run. A hung UI test cannot stall a session forever.
* Every run writes manifest.json with the toolchain, the exact argv, the
  destination, timings and the exit status -- enough to reproduce it or to
  explain later why two runs are not comparable.
* The output directory must not already contain a result bundle, so one run
  never silently overwrites another's evidence.

WHAT IT DELIBERATELY DOES NOT DO

* It does not retry. Retrying without classifying the failure first is how
  regressions reach production -- run `test_results.py triage` and decide.
* It does not model all of xcodebuild. Pass anything else through with
  `--extra`.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_TIMEOUT = 1800  # 30 minutes; UI suites are slow but not unbounded

# The three repetition modes produce three DIFFERENT verdicts on identical
# code. Verified: retry -> SUCCEEDED, relaunch -> FAILED, on the same test.
# Whichever is used must be reported alongside the result.
REPETITION_MODES = {
    "retry": {
        "flags": ["-retry-tests-on-failure"],
        "meaning": ("Re-runs a failed test in the SAME process. A test that "
                    "fails then passes makes the run report SUCCEEDED and "
                    "leaves an empty testFailures array -- the failure survives "
                    "only as a Repetition node. Always follow with "
                    "`test_results.py triage`."),
    },
    "relaunch": {
        "flags": ["-test-repetition-relaunch-enabled", "YES"],
        "meaning": ("Fresh process per iteration. Catches per-process state "
                    "leakage that `retry` hides. The honest mode for deciding "
                    "whether a failure is real."),
    },
    "until-failure": {
        "flags": ["-run-tests-until-failure"],
        "meaning": "Stops at the first failure. For reproducing a rare flake.",
    },
}


class RunError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# command construction
# --------------------------------------------------------------------------

def _container_args(args) -> List[str]:
    if args.workspace:
        return ["-workspace", str(args.workspace)]
    if args.project:
        return ["-project", str(args.project)]
    return []


def _destination(args) -> Optional[str]:
    if args.destination:
        return args.destination
    if args.destination_id:
        # An explicit UDID is the only unambiguous target. `booted` and bare
        # names can resolve to a different device between runs.
        platform_name = args.platform or "iOS Simulator"
        return f"platform={platform_name},id={args.destination_id}"
    return None


def build_argv(args, action: str) -> List[str]:
    argv = ["xcodebuild", action]
    argv += _container_args(args)

    if args.xctestrun:
        argv += ["-xctestrun", str(args.xctestrun)]
    else:
        if not args.scheme:
            raise RunError("--scheme is required unless --xctestrun is given")
        argv += ["-scheme", args.scheme]
        if args.plan:
            # -testPlan works with -scheme, never with -xctestrun.
            argv += ["-testPlan", args.plan]

    dest = _destination(args)
    if dest:
        argv += ["-destination", dest]
    elif action != "build-for-testing":
        raise RunError("a destination is required: pass --destination-id <UDID> "
                       "or --destination '<spec>'")

    if args.derived_data:
        argv += ["-derivedDataPath", str(args.derived_data)]

    if action == "build-for-testing":
        if args.test_products:
            argv += ["-testProductsPath", str(args.test_products)]
        return argv + list(args.extra or [])

    argv += ["-resultBundlePath", str(args.result_bundle)]

    if args.coverage:
        argv += ["-enableCodeCoverage", "YES"]

    for t in args.only or []:
        argv += [f"-only-testing:{t}"]
    for t in args.skip or []:
        argv += [f"-skip-testing:{t}"]

    if args.repetition:
        argv += REPETITION_MODES[args.repetition]["flags"]
        if args.iterations and args.repetition != "retry":
            argv += ["-test-iterations", str(args.iterations)]
        elif args.iterations:
            argv += ["-test-iterations", str(args.iterations)]

    if args.parallel:
        argv += ["-parallel-testing-enabled", "YES"]
        if args.workers:
            argv += ["-parallel-testing-worker-count", str(args.workers)]

    if args.language:
        argv += ["-testLanguage", args.language]
    if args.region:
        argv += ["-testRegion", args.region]

    return argv + list(args.extra or [])


# --------------------------------------------------------------------------
# execution
# --------------------------------------------------------------------------

def toolchain_record() -> Dict[str, Any]:
    rec: Dict[str, Any] = {
        "macOS": platform.mac_ver()[0],
        "arch": platform.machine(),
        "python": platform.python_version(),
    }
    for key, argv in (("developerDir", ["xcode-select", "-p"]),
                      ("xcodebuild", ["xcodebuild", "-version"])):
        try:
            proc = subprocess.run(argv, capture_output=True, text=True,
                                  timeout=30, check=False)
            if proc.returncode == 0:
                rec[key] = proc.stdout.strip().replace("\n", " | ")
        except (OSError, subprocess.SubprocessError):
            pass
    return rec


def execute(argv: List[str], out_dir: Path, timeout: int,
            label: str) -> Dict[str, Any]:
    log_path = out_dir / f"{label}.log"
    started = time.time()
    timed_out = False

    with log_path.open("w", encoding="utf-8") as log:
        log.write(" ".join(shlex.quote(a) for a in argv) + "\n\n")
        log.flush()
        proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT,
                                text=True)
        try:
            status = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            # Terminate only the process this run created. Never pkill
            # xcodebuild -- another job may own one.
            proc.terminate()
            try:
                status = proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                status = proc.wait()

    return {
        "argv": argv,
        "command": " ".join(shlex.quote(a) for a in argv),
        "exitStatus": status,
        "timedOut": timed_out,
        "durationSeconds": round(time.time() - started, 3),
        "log": str(log_path),
    }


def _pretty(argv: List[str]) -> str:
    """Render argv one flag-and-value pair per line, so it can be read."""
    lines, i = [], 0
    while i < len(argv):
        token = argv[i]
        takes_value = (token.startswith("-")
                       and i + 1 < len(argv)
                       and not argv[i + 1].startswith("-"))
        if takes_value:
            lines.append(f"{token} {shlex.quote(argv[i + 1])}")
            i += 2
        else:
            lines.append(shlex.quote(token))
            i += 1
    return "  " + " \\\n    ".join(lines)


def prepare_out(out: Path, force: bool) -> Path:
    out = out.expanduser().resolve()
    existing = list(out.glob("*.xcresult"))
    if existing and not force:
        raise RunError(
            f"{out} already contains {existing[0].name}. Refusing to overwrite "
            f"evidence from a previous run -- choose a new --out, or pass "
            f"--force if you really mean to replace it.")
    if existing and force:
        for e in existing:
            shutil.rmtree(e, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    return out


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("action", choices=["build", "test", "plan"])

    src = p.add_argument_group("what to test")
    src.add_argument("--workspace", type=Path)
    src.add_argument("--project", type=Path)
    src.add_argument("--scheme")
    src.add_argument("--plan", help="test plan name (requires --scheme)")
    src.add_argument("--xctestrun", type=Path,
                     help="run a prebuilt .xctestrun (build once, run many)")

    tgt = p.add_argument_group("where to run")
    tgt.add_argument("--destination-id", help="device or simulator UDID (preferred)")
    tgt.add_argument("--platform", default=None,
                     help="platform for --destination-id (default: iOS Simulator)")
    tgt.add_argument("--destination", help="full -destination spec, used verbatim")

    sel = p.add_argument_group("selection")
    sel.add_argument("--only", action="append", metavar="Target/Class/method")
    sel.add_argument("--skip", action="append", metavar="Target/Class/method")
    sel.add_argument("--language")
    sel.add_argument("--region")

    rep = p.add_argument_group("repetition and parallelism")
    rep.add_argument("--repetition", choices=sorted(REPETITION_MODES))
    rep.add_argument("--iterations", type=int)
    rep.add_argument("--parallel", action="store_true")
    rep.add_argument("--workers", type=int)

    out = p.add_argument_group("output")
    out.add_argument("--out", type=Path, required=True, help="run directory")
    out.add_argument("--derived-data", type=Path)
    out.add_argument("--test-products", type=Path)
    out.add_argument("--coverage", action="store_true",
                     help="enable code coverage (cannot be added afterwards)")
    out.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    out.add_argument("--force", action="store_true",
                     help="replace an existing result bundle in --out")
    out.add_argument("--extra", nargs=argparse.REMAINDER,
                     help="everything after this is passed to xcodebuild verbatim")

    args = p.parse_args()

    if not shutil.which("xcrun"):
        print("error: requires macOS with full Xcode", file=sys.stderr)
        return 2

    action = {"build": "build-for-testing", "test": "test-without-building"
              if args.xctestrun else "test", "plan": None}[args.action]

    try:
        if args.action == "plan":
            args.result_bundle = Path(args.out).resolve() / "Run.xcresult"
            probe = "build-for-testing" if not args.scheme or args.xctestrun else "test"
            argv = build_argv(args, probe if not args.xctestrun else "test-without-building")
            print("\n" + _pretty(argv) + "\n")
            if args.repetition:
                print(f"  repetition mode `{args.repetition}`:")
                print(f"    {REPETITION_MODES[args.repetition]['meaning']}\n")
            return 0

        out_dir = prepare_out(args.out, args.force)
        args.result_bundle = out_dir / "Run.xcresult"
        if args.action == "build" and not args.derived_data:
            args.derived_data = out_dir / "DerivedData"

        argv = build_argv(args, action)
    except RunError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"\n$ {' '.join(shlex.quote(a) for a in argv)}\n")
    result = execute(argv, out_dir, args.timeout, args.action)

    manifest: Dict[str, Any] = {
        "schema": "ios-test-engineer/run/1",
        "action": action,
        "toolchain": toolchain_record(),
        "destination": _destination(args),
        "scheme": args.scheme,
        "testPlan": args.plan,
        "xctestrun": str(args.xctestrun) if args.xctestrun else None,
        "coverage": bool(args.coverage),
        "repetitionMode": args.repetition,
        "repetitionMeaning": (REPETITION_MODES[args.repetition]["meaning"]
                              if args.repetition else None),
        "iterations": args.iterations,
        "parallel": bool(args.parallel),
        "workers": args.workers,
        "onlyTesting": args.only or [],
        "skipTesting": args.skip or [],
        "execution": result,
    }

    if args.action == "build":
        found = sorted(glob.glob(str(out_dir / "**" / "*.xctestrun"), recursive=True))
        manifest["xctestrunFiles"] = found
    else:
        # A killed or crashed run can leave a bundle DIRECTORY with no
        # Info.plist. That is an unusable shell, not evidence -- do not point
        # the caller at it as though it were readable.
        complete = (args.result_bundle / "Info.plist").exists()
        manifest["resultBundle"] = str(args.result_bundle) if complete else None
        manifest["resultBundleIncomplete"] = (
            args.result_bundle.exists() and not complete)

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"exit {result['exitStatus']}"
          f"{'  (TIMED OUT)' if result['timedOut'] else ''}"
          f"   {result['durationSeconds']}s")
    print(f"log      {result['log']}")
    print(f"manifest {out_dir / 'manifest.json'}")

    if args.action == "build":
        for f in manifest.get("xctestrunFiles", []):
            print(f"xctestrun {f}")
        return 0 if manifest.get("xctestrunFiles") else 1

    if manifest["resultBundle"]:
        print(f"bundle   {manifest['resultBundle']}")
        print(f"\nNext: python3 test_results.py triage {manifest['resultBundle']}")
        if result["timedOut"]:
            print("      The run was killed by the watchdog. Treat the bundle as "
                  "partial evidence, not a verdict.")
    elif manifest.get("resultBundleIncomplete"):
        print(f"\nA result bundle directory was created but is incomplete (no "
              f"Info.plist), so it cannot be read:\n  {args.result_bundle}")
        print("This is a run failure, not a test failure. Read the log; do not "
              "report a test verdict from this run.")
    else:
        print("\nNo result bundle was produced. Read the log before concluding "
              "anything about the tests -- this is a run failure, not a test "
              "failure.")

    # A non-zero xcodebuild status means tests failed OR the run failed. Only
    # the bundle can tell those apart, so the caller must triage.
    return 0 if result["exitStatus"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
