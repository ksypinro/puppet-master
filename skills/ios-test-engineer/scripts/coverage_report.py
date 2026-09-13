#!/usr/bin/env python3
"""Region-aware code coverage from an .xcresult bundle.

    report   <bundle>                    per-target and per-file coverage
    gaps     <bundle> [--file NAME]      what is uncovered, and what it really is
    changed  <bundle> --base <bundle>    coverage delta between two runs
    hot      <bundle>                    functions your tests exercise hardest

Add --json for machine-readable output, --include-tests to keep test bundles in
the numbers, and --fail-under N to exit non-zero below a threshold.

WHY THIS EXISTS

Subtracting `coveredLines` from `executableLines` and calling the difference
"untested lines" is wrong on Swift, and confidently so. Verified on a real
project at 98.11% line coverage, every one of its "uncovered lines" was a
compiler-synthesised region sharing a line with covered code:

    line 47  index[key] = Array(Set(index[key] ?? [])).sorted()
             implicit closure #2 in NoteIndex.init(notes:)
             region executed 0x -- but the LINE executed 336x
             the `?? []` fallback never fired because the lookup never
             returned nil

    line 27  XCTAssertNotEqual(count.label, before, "the count did not change")
             implicit closure #5 in testSearchFiltersTheList()
             region executed 0x -- but the LINE executed 1x
             the failure message only evaluates WHEN THE ASSERTION FAILS,
             so it is uncovered precisely BECAUSE the test passed

Telling a developer to "cover line 27" asks them to break their own assertion.
So this tool reports the region name and its enclosing line's hit count, and
separates genuinely dead lines from sub-expressions that merely never fired.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_TIMEOUT = 180

# Regions the Swift compiler synthesises. A zero-execution region whose name
# matches one of these is almost never dead code.
SYNTHESISED = re.compile(
    r"implicit closure|autoclosure|default argument|thunk|"
    r"protocol witness|@objc |partial apply|reabstraction", re.I)

# `NN: <count>` or `NN: *` at the head of an --archive line. Lines may carry a
# trailing `[ (startCol, endCol, hits) ]` sub-region block, which is ignored
# here -- the function-level records already give region granularity.
ARCHIVE_LINE = re.compile(r"^\s*(\d+):\s+(\*|\d+)", re.M)

TEST_BUNDLE = re.compile(r"\.(xctest|appex)$|Tests?\.xctest$")


class ToolError(RuntimeError):
    pass


def _run(argv: List[str], timeout: int = DEFAULT_TIMEOUT) -> str:
    if not shutil.which("xcrun"):
        raise ToolError("xcrun not found. Requires macOS with full Xcode.")
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise ToolError(f"timed out after {timeout}s: {' '.join(argv[:4])}")
    if proc.returncode != 0:
        raise ToolError(f"{argv[1]} failed ({proc.returncode}): "
                        f"{(proc.stderr or proc.stdout).strip()[:400]}")
    return proc.stdout


class NoCoverage(ToolError):
    """The bundle was recorded without coverage. Not recoverable after the fact."""


def load_report(bundle: Path) -> Dict[str, Any]:
    try:
        out = _run(["xcrun", "xccov", "view", "--report", "--json", str(bundle)])
    except ToolError as exc:
        if "No coverage data" in str(exc):
            raise NoCoverage(
                f"{bundle.name} contains no coverage data.\n"
                f"  Coverage must be requested at run time and cannot be added "
                f"afterwards.\n"
                f"  Re-run with:  run_tests.py test … --coverage\n"
                f"  or set the test plan's codeCoverage option "
                f"(test_doctor.py reports it per plan).")
        raise
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise ToolError(f"xccov returned invalid JSON: {exc}")


def line_hits(bundle: Path, source: str) -> Dict[int, str]:
    """Per-line hit counts. '*' means the line is not executable."""
    try:
        out = _run(["xcrun", "xccov", "view", "--archive",
                    "--file", source, str(bundle)])
    except ToolError:
        return {}
    return {int(m.group(1)): m.group(2)
            for m in ARCHIVE_LINE.finditer(out)}


def resolve_bundle(path: Path) -> Path:
    b = path.expanduser().resolve()
    if not b.exists():
        raise ToolError(f"no such bundle: {b}")
    if not (b / "Info.plist").exists():
        raise ToolError(f"not an .xcresult bundle: {b}")
    return b


def _is_test_target(name: str) -> bool:
    return bool(TEST_BUNDLE.search(name or ""))


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def report(bundle: Path, include_tests: bool = False) -> Dict[str, Any]:
    raw = load_report(bundle)

    targets = []
    prod_covered = prod_exec = 0
    for t in raw.get("targets", []):
        is_test = _is_test_target(t.get("name", ""))
        if is_test and not include_tests:
            continue
        if not is_test:
            prod_covered += t.get("coveredLines", 0)
            prod_exec += t.get("executableLines", 0)
        targets.append({
            "name": t.get("name"),
            "isTestTarget": is_test,
            "lineCoverage": t.get("lineCoverage"),
            "coveredLines": t.get("coveredLines"),
            "executableLines": t.get("executableLines"),
            "files": [
                {
                    "name": os.path.basename(f.get("path", "")),
                    "path": f.get("path"),
                    "lineCoverage": f.get("lineCoverage"),
                    "coveredLines": f.get("coveredLines"),
                    "executableLines": f.get("executableLines"),
                    "gap": f.get("executableLines", 0) - f.get("coveredLines", 0),
                    "functionCount": len(f.get("functions", []) or []),
                }
                for f in t.get("files", []) or []
            ],
        })

    return {
        "targets": targets,
        # Product coverage excludes test bundles, which measure tests testing
        # themselves and always inflate the headline number.
        "productCoverage": (prod_covered / prod_exec) if prod_exec else None,
        "productCoveredLines": prod_covered,
        "productExecutableLines": prod_exec,
        "includedTestTargets": include_tests,
    }


# --------------------------------------------------------------------------
# gaps -- the part that is usually reported wrongly
# --------------------------------------------------------------------------

def gaps(bundle: Path, only_file: Optional[str] = None,
         include_tests: bool = False) -> Dict[str, Any]:
    raw = load_report(bundle)

    dead: List[Dict[str, Any]] = []
    regions: List[Dict[str, Any]] = []

    for t in raw.get("targets", []):
        if _is_test_target(t.get("name", "")) and not include_tests:
            continue
        for f in t.get("files", []) or []:
            if f.get("coveredLines", 0) >= f.get("executableLines", 0):
                continue
            path = f.get("path", "")
            if only_file and only_file not in path:
                continue

            hits = line_hits(bundle, path)
            src = _read_source(path)

            for fn in f.get("functions", []) or []:
                if fn.get("coveredLines", 0) >= fn.get("executableLines", 0):
                    continue
                n = fn.get("lineNumber")
                enclosing = hits.get(n, "?")
                name = fn.get("name", "")
                synthetic = bool(SYNTHESISED.search(name))
                # A line whose own hit count is > 0 cannot be dead code, no
                # matter what the region-level count says.
                line_ran = enclosing not in ("*", "0", "?") and enclosing.isdigit() \
                    and int(enclosing) > 0

                entry = {
                    "target": t.get("name"),
                    "file": os.path.basename(path),
                    "path": path,
                    "line": n,
                    "source": (src[n - 1].strip() if src and n and n <= len(src)
                               else None),
                    "region": name,
                    "regionExecutions": fn.get("executionCount", 0),
                    "enclosingLineHits": (int(enclosing) if enclosing.isdigit()
                                          else None),
                    "syntheticRegion": synthetic,
                    "executableLines": fn.get("executableLines"),
                }

                if line_ran or synthetic:
                    entry["verdict"] = "sub-expression never evaluated"
                    entry["explanation"] = _explain(entry)
                    regions.append(entry)
                else:
                    entry["verdict"] = "never executed"
                    entry["explanation"] = (
                        "This code genuinely never ran. It is the real "
                        "coverage gap -- write a test that reaches it.")
                    dead.append(entry)

    return {
        "deadCount": len(dead),
        "regionCount": len(regions),
        # Only this number belongs in a coverage gate.
        "deadLines": dead,
        "neverEvaluatedRegions": regions,
        "note": ("`deadLines` is real untested code. `neverEvaluatedRegions` are "
                 "sub-expressions on lines that DID run -- gating on them "
                 "produces false alarms."),
    }


def _explain(entry: Dict[str, Any]) -> str:
    src = (entry.get("source") or "")
    line_hits_n = entry.get("enclosingLineHits")
    ran = f"the enclosing line ran {line_hits_n}x" if line_hits_n else \
        "the enclosing line executed"

    if "??" in src:
        return (f"A `??` fallback that never fired -- {ran}, but the left-hand "
                f"side was never nil. To reach it, add a case where the value "
                f"is absent.")
    if re.search(r"XCTAssert|#expect|#require|precondition|assert\(", src):
        return (f"An assertion's failure message, which only evaluates WHEN THE "
                f"ASSERTION FAILS -- {ran}. It is uncovered because the test "
                f"PASSED. Do not try to cover this.")
    if "||" in src or "&&" in src:
        return (f"A short-circuited operand -- {ran}, but the preceding term "
                f"already decided the result. Reaching it needs an input that "
                f"flips the first term.")
    if entry.get("syntheticRegion"):
        return (f"A compiler-synthesised region ({entry['region']}) -- {ran}. "
                f"Not source you wrote, and usually not actionable.")
    return (f"A sub-expression that never evaluated while {ran}. Inspect the "
            f"line to see which branch was not taken.")


def _read_source(path: str) -> Optional[List[str]]:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        # Common in CI: the bundle was produced under a different checkout root.
        return None


# --------------------------------------------------------------------------
# changed -- coverage delta
# --------------------------------------------------------------------------

def _common_root(paths: List[str]) -> str:
    """Longest shared directory prefix of a set of absolute paths."""
    if not paths:
        return ""
    parts = [p.split("/") for p in paths]
    shared: List[str] = []
    for segs in zip(*parts):
        if len(set(segs)) != 1:
            break
        shared.append(segs[0])
    return "/".join(shared)


def _normalise_keys(current: Dict[str, Any], baseline: Dict[str, Any],
                    strip: Optional[str]) -> tuple:
    """Make two bundles' file paths comparable across checkout roots.

    The same source built on CI and on a laptop has different absolute paths,
    so an exact-path diff reports every file as removed+added and fully covered
    code shows as 0%. Strip each side's own common root and compare what is
    left, which is the repository-relative path.
    """
    if strip:
        norm = lambda p: p[len(strip):].lstrip("/") if p.startswith(strip) else p
        return ({norm(k): v for k, v in current.items()},
                {norm(k): v for k, v in baseline.items()}, strip, "explicit")

    if set(current) & set(baseline):
        return current, baseline, None, "none-needed"

    cur_root, base_root = _common_root(list(current)), _common_root(list(baseline))
    if not cur_root or not base_root:
        return current, baseline, None, "not-possible"

    rel_cur = {k[len(cur_root):].lstrip("/"): v for k, v in current.items()}
    rel_base = {k[len(base_root):].lstrip("/"): v for k, v in baseline.items()}
    if set(rel_cur) & set(rel_base):
        return rel_cur, rel_base, f"{cur_root} | {base_root}", "common-root"

    # Last resort: match on filename alone. Ambiguous when a name repeats, so
    # only used when it is unambiguous on both sides.
    names_cur = [k.rsplit("/", 1)[-1] for k in current]
    names_base = [k.rsplit("/", 1)[-1] for k in baseline]
    if len(set(names_cur)) == len(names_cur) and len(set(names_base)) == len(names_base):
        return ({k.rsplit("/", 1)[-1]: v for k, v in current.items()},
                {k.rsplit("/", 1)[-1]: v for k, v in baseline.items()},
                None, "basename")
    return current, baseline, None, "failed"


def changed(bundle: Path, base: Path, include_tests: bool = False,
            strip_prefix: Optional[str] = None) -> Dict[str, Any]:
    cur = {f["path"]: f for t in report(bundle, include_tests)["targets"]
           for f in t["files"]}
    old = {f["path"]: f for t in report(base, include_tests)["targets"]
           for f in t["files"]}

    cur, old, stripped, strategy = _normalise_keys(cur, old, strip_prefix)

    rows = []
    for path in sorted(set(cur) | set(old)):
        c, o = cur.get(path), old.get(path)
        cov_c = c["lineCoverage"] if c else None
        cov_o = o["lineCoverage"] if o else None
        if cov_c is not None and cov_o is not None:
            delta = cov_c - cov_o
            state = "unchanged" if abs(delta) < 1e-9 else (
                "improved" if delta > 0 else "regressed")
        elif cov_c is None:
            delta, state = None, "removed"
        else:
            delta, state = None, "added"
        rows.append({
            "file": os.path.basename(path), "path": path,
            "baseline": cov_o, "current": cov_c,
            "delta": delta, "state": state,
        })

    regressed = [r for r in rows if r["state"] == "regressed"]
    added = [r for r in rows if r["state"] == "added"]
    removed = [r for r in rows if r["state"] == "removed"]

    notes = {
        "none-needed": "Paths matched directly; no normalisation was needed.",
        "explicit": f"Stripped the prefix you supplied: {stripped}",
        "common-root": (f"Paths did not match, so each side's common root was "
                        f"stripped and the repository-relative paths compared "
                        f"({stripped})."),
        "basename": ("Paths did not match and roots did not help, so files were "
                     "matched on filename alone. Unambiguous here, but verify "
                     "before trusting it."),
        "not-possible": "Paths did not match and could not be normalised.",
        "failed": ("Paths did not match and could not be normalised safely "
                   "(duplicate filenames). Every file will read as "
                   "removed+added -- pass --strip-prefix."),
    }

    warnings = []
    if strategy in ("not-possible", "failed") and added and removed:
        warnings.append(
            "Every file shows as removed+added, which almost always means the "
            "two bundles were built under different checkout roots rather than "
            "that the files really changed. Do not report this as a coverage "
            "regression.")

    return {
        "files": rows,
        "regressedCount": len(regressed),
        "regressed": regressed,
        "improved": [r for r in rows if r["state"] == "improved"],
        "added": added,
        "removed": removed,
        "pathNormalisation": {"strategy": strategy, "stripped": stripped},
        "warnings": warnings,
        "note": notes[strategy],
    }


# --------------------------------------------------------------------------
# hot -- what the suite actually exercises
# --------------------------------------------------------------------------

def hot(bundle: Path, limit: int = 20, include_tests: bool = False) -> Dict[str, Any]:
    raw = load_report(bundle)
    fns = []
    for t in raw.get("targets", []):
        if _is_test_target(t.get("name", "")) and not include_tests:
            continue
        for f in t.get("files", []) or []:
            for fn in f.get("functions", []) or []:
                fns.append({
                    "name": fn.get("name"),
                    "file": os.path.basename(f.get("path", "")),
                    "line": fn.get("lineNumber"),
                    "executions": fn.get("executionCount", 0),
                    "lineCoverage": fn.get("lineCoverage"),
                })
    fns.sort(key=lambda x: x["executions"], reverse=True)
    return {
        "functions": fns[:limit],
        "totalFunctions": len(fns),
        "note": ("Execution counts show what your suite exercises hardest -- "
                 "useful for choosing what to profile, fuzz, or optimise."),
    }


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _bar(fraction: Optional[float], width: int = 18) -> str:
    if fraction is None:
        return " " * width
    filled = int(round(fraction * width))
    return "█" * filled + "·" * (width - filled)


def _render_report(d: Dict[str, Any]) -> None:
    print()
    for t in d["targets"]:
        tag = "  (test target)" if t["isTestTarget"] else ""
        print(f"{t['name']}{tag}")
        print(f"  {_bar(t['lineCoverage'])}  {t['lineCoverage']*100:6.2f}%   "
              f"{t['coveredLines']}/{t['executableLines']} lines")
        for f in t["files"]:
            flag = "!" if f["gap"] else " "
            print(f"    {flag} {f['name'][:34]:36s} {f['lineCoverage']*100:6.2f}%  "
                  f"{f['coveredLines']:5d}/{f['executableLines']:<5d}"
                  f"{'  gap ' + str(f['gap']) if f['gap'] else ''}")
        print()
    if d["productCoverage"] is not None:
        print(f"Product coverage (test targets excluded): "
              f"{d['productCoverage']*100:.2f}%  "
              f"{d['productCoveredLines']}/{d['productExecutableLines']}\n")


def _render_gaps(d: Dict[str, Any]) -> None:
    print(f"\n{d['deadCount']} genuinely uncovered  ·  "
          f"{d['regionCount']} sub-expression(s) that never evaluated\n")

    if d["deadLines"]:
        print("REAL COVERAGE GAPS — write tests for these")
        print("=" * 74)
        for e in d["deadLines"]:
            print(f"\n  {e['file']}:{e['line']}   [{e['target']}]")
            if e["source"]:
                print(f"    {e['source'][:96]}")
            print(f"    region {e['region']}")
            print(f"    → {e['explanation']}")
        print()

    if d["neverEvaluatedRegions"]:
        print("NOT REAL GAPS — sub-expressions on lines that did run")
        print("=" * 74)
        for e in d["neverEvaluatedRegions"]:
            print(f"\n  {e['file']}:{e['line']}   [{e['target']}]")
            if e["source"]:
                print(f"    {e['source'][:96]}")
            print(f"    region   {e['region']}")
            print(f"    executed {e['regionExecutions']}x, "
                  f"enclosing line ran {e['enclosingLineHits']}x")
            print(f"    → {e['explanation']}")
        print()
    print(f"  {d['note']}\n")


def _render_changed(d: Dict[str, Any]) -> None:
    print()
    for r in d["files"]:
        if r["state"] == "unchanged":
            continue
        base = f"{r['baseline']*100:6.2f}%" if r["baseline"] is not None else "   —  "
        cur = f"{r['current']*100:6.2f}%" if r["current"] is not None else "   —  "
        delta = f"{r['delta']*100:+6.2f}" if r["delta"] is not None else "     —"
        print(f"  {r['state']:10s} {r['file'][:32]:34s} {base} → {cur}  {delta}")
    print(f"\n  regressed {d['regressedCount']}   improved {len(d['improved'])}   "
          f"added {len(d['added'])}   removed {len(d['removed'])}")
    print(f"\n  path matching: {d['pathNormalisation']['strategy']}")
    print(f"  {d['note']}")
    for w in d["warnings"]:
        print(f"\n  ! {w}")
    print()


def _render_hot(d: Dict[str, Any]) -> None:
    print(f"\nMost-exercised functions ({d['totalFunctions']} total)\n")
    for f in d["functions"]:
        print(f"  {f['executions']:9d}×  {f['file']}:{f['line']:<5d} "
              f"{(f['name'] or '')[:56]}")
    print(f"\n  {d['note']}\n")


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["report", "gaps", "changed", "hot"])
    p.add_argument("bundle", type=Path)
    p.add_argument("--base", type=Path, help="baseline bundle (for `changed`)")
    p.add_argument("--file", help="restrict `gaps` to paths containing this")
    p.add_argument("--limit", type=int, default=20, help="`hot` result count")
    p.add_argument("--include-tests", action="store_true",
                   help="keep test bundles in the numbers")
    p.add_argument("--strip-prefix", metavar="PATH",
                   help="`changed`: strip this path prefix from both bundles "
                        "before comparing, for bundles built under different "
                        "checkout roots (auto-detected when omitted)")
    p.add_argument("--fail-under", type=float, metavar="PCT",
                   help="exit 1 if product coverage is below this percentage")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    try:
        bundle = resolve_bundle(args.bundle)
        if args.command == "report":
            result = report(bundle, args.include_tests)
            render = _render_report
        elif args.command == "gaps":
            result = gaps(bundle, args.file, args.include_tests)
            render = _render_gaps
        elif args.command == "hot":
            result = hot(bundle, args.limit, args.include_tests)
            render = _render_hot
        else:
            if not args.base:
                p.error("changed requires --base")
            result = changed(bundle, resolve_bundle(args.base),
                             args.include_tests, args.strip_prefix)
            render = _render_changed
    except ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        render(result)

    if args.fail_under is not None and args.command == "report":
        actual = (result["productCoverage"] or 0) * 100
        if actual < args.fail_under:
            print(f"FAIL: product coverage {actual:.2f}% is below "
                  f"{args.fail_under:.2f}%", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
