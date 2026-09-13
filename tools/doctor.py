#!/usr/bin/env python3
"""Repository-level capability probe for the Puppet Master skills.

Answers one question: which of the skills can actually run here, and what
is missing for the ones that cannot. It is read-only -- it installs nothing,
boots nothing, and changes no settings.

This is deliberately *not* a replacement for each skill's own doctor. Those
probe deeply (templates, instruments, driver sessions, LLDB runtime support).
This probes the shared substrate they all sit on and points at the right
per-skill doctor for the rest.

    python3 tools/doctor.py             # human-readable report
    python3 tools/doctor.py --json      # machine-readable capability manifest
    python3 tools/doctor.py --json -o run/capabilities.json

Exit status: 0 if at least one skill is operational, 1 if none are.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"

MIN_PYTHON = (3, 9)

# Optional UI drivers. None is required on its own, but ios-simulator-driver
# needs at least one of them to synthesize input; simctl cannot.
UI_DRIVERS = ("axe", "idb", "appium", "xcodebuildmcp")

# skill -> (required binaries, per-skill doctor command)
SKILL_REQUIREMENTS = {
    "ios-simulator-driver": (
        ["xcrun", "simctl"],
        "python3 skills/ios-simulator-driver/scripts/simulator_doctor.py",
    ),
    "ios-view-hierarchy-debugger": (
        ["xcrun", "simctl", "lldb"],
        "python3 skills/ios-view-hierarchy-debugger/scripts/ui_evidence.py --help",
    ),
    "lldb-code-state-debugger": (
        ["xcrun", "lldb"],
        "python3 skills/lldb-code-state-debugger/scripts/debugger.py doctor",
    ),
    "ios-instruments-profiler": (
        ["xcrun", "xcodebuild", "xctrace"],
        "python3 skills/ios-instruments-profiler/scripts/xctrace_doctor.py",
    ),
    "ios-test-engineer": (
        ["xcrun", "xcodebuild"],
        "python3 skills/ios-test-engineer/scripts/test_doctor.py --destinations",
    ),
    "ios-memory-debugger": (
        ["leaks", "heap", "vmmap", "malloc_history"],
        "python3 skills/ios-memory-debugger/scripts/test_selftest.py",
    ),
}


def run(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    """Run a command, returning (exit_status, combined_output)."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def have(binary: str) -> bool:
    """True if `binary` is runnable, directly or as an xcrun-provided tool."""
    if shutil.which(binary):
        return True
    # xctrace, simctl and friends live inside the active Xcode, not on PATH.
    status, _ = run(["xcrun", "--find", binary], timeout=10)
    return status == 0


def probe_host() -> dict:
    return {
        "os": platform.system(),
        "os_version": platform.mac_ver()[0] or platform.release(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "python_ok": sys.version_info >= MIN_PYTHON,
    }


def probe_xcode() -> dict:
    """Distinguish full Xcode from the standalone Command Line Tools.

    xctrace, Instruments templates and the iOS Simulator runtimes ship only
    with full Xcode, so this distinction decides whether half the toolkit works.
    """
    info: dict = {"selected_path": None, "version": None, "is_full_xcode": False}

    status, out = run(["xcode-select", "-p"])
    if status != 0:
        info["error"] = out or "xcode-select not available"
        return info
    info["selected_path"] = out

    status, out = run(["xcodebuild", "-version"])
    if status == 0:
        info["version"] = " ".join(out.splitlines()[:2])
        info["is_full_xcode"] = True
    else:
        info["error"] = (
            "xcodebuild is unavailable. The standalone Command Line Tools are "
            "selected. Install Xcode and run: "
            "sudo xcode-select -s /Applications/Xcode.app/Contents/Developer"
        )
    return info


def probe_simulators() -> dict:
    status, out = run(["xcrun", "simctl", "list", "devices", "available", "-j"], 40)
    if status != 0:
        return {"available": False, "booted": [], "count": 0}
    try:
        devices = json.loads(out).get("devices", {})
    except json.JSONDecodeError:
        return {"available": False, "booted": [], "count": 0}

    booted, count = [], 0
    for runtime, entries in devices.items():
        for dev in entries:
            count += 1
            if dev.get("state") == "Booted":
                booted.append(
                    {
                        "name": dev.get("name"),
                        "udid": dev.get("udid"),
                        "runtime": runtime.rsplit(".", 1)[-1],
                    }
                )
    return {"available": True, "booted": booted, "count": count}


def probe_drivers() -> dict:
    return {name: have(name) for name in UI_DRIVERS}


def evaluate_skills(xcode: dict, drivers: dict) -> dict:
    """Decide per-skill readiness from the probed substrate."""
    results: dict = {}
    for name, (binaries, doctor_cmd) in SKILL_REQUIREMENTS.items():
        if not (SKILLS_DIR / name / "SKILL.md").exists():
            results[name] = {"status": "missing", "blockers": ["skill not present in repo"]}
            continue

        blockers = [b for b in binaries if not have(b)]
        if name == "ios-instruments-profiler" and not xcode["is_full_xcode"]:
            blockers.append("full Xcode (xctrace is not in the Command Line Tools)")

        warnings = []
        if name == "ios-simulator-driver" and not any(drivers.values()):
            warnings.append(
                "no UI driver found (axe / idb / appium / xcodebuildmcp). "
                "The skill can observe and screenshot but cannot synthesize "
                "taps, swipes or text -- simctl provides no such verbs."
            )

        results[name] = {
            "status": "blocked" if blockers else "ready",
            "blockers": blockers,
            "warnings": warnings,
            "doctor": doctor_cmd,
        }
    return results


def build_report() -> dict:
    host = probe_host()
    xcode = probe_xcode()
    drivers = probe_drivers()
    simulators = probe_simulators() if xcode["is_full_xcode"] else {"available": False, "booted": [], "count": 0}
    skills = evaluate_skills(xcode, drivers)

    return {
        "schema": "puppet-master/capabilities/1",
        "repo_root": str(REPO_ROOT),
        "host": host,
        "xcode": xcode,
        "simulators": simulators,
        "ui_drivers": drivers,
        "skills": skills,
        "ready_count": sum(1 for s in skills.values() if s["status"] == "ready"),
    }


GREEN, YELLOW, RED, DIM, BOLD, RESET = (
    ("\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m")
    if sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    else ("", "", "", "", "", "")
)


def print_report(r: dict) -> None:
    host, xcode = r["host"], r["xcode"]

    print(f"\n{BOLD}Puppet Master — capability report{RESET}")
    print(f"{DIM}{r['repo_root']}{RESET}\n")

    if host["os"] != "Darwin":
        print(f"{RED}✗ {host['os']} is not supported. Every skill requires macOS.{RESET}\n")
        return

    ok = f"{GREEN}✓{RESET}"
    warn = f"{YELLOW}!{RESET}"
    bad = f"{RED}✗{RESET}"

    print(f"  {ok if host['python_ok'] else bad} Python {host['python']} "
          f"{DIM}(need {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+, stdlib only){RESET}")
    print(f"  {ok} macOS {host['os_version']} ({host['arch']})")

    if xcode["is_full_xcode"]:
        print(f"  {ok} {xcode['version']}")
        print(f"    {DIM}{xcode['selected_path']}{RESET}")
    else:
        print(f"  {bad} Full Xcode not selected")
        print(f"    {DIM}{xcode.get('error', '')}{RESET}")

    sims = r["simulators"]
    if sims["available"]:
        booted = sims["booted"]
        line = f"  {ok} {sims['count']} Simulator device(s) available"
        if booted:
            line += f", {len(booted)} booted"
        print(line)
        for dev in booted:
            print(f"    {DIM}{dev['name']}  {dev['udid']}  {dev['runtime']}{RESET}")
    else:
        print(f"  {warn} No Simulator devices enumerated")

    found = [d for d, present in r["ui_drivers"].items() if present]
    if found:
        print(f"  {ok} UI driver(s): {', '.join(found)}")
    else:
        print(f"  {warn} No standalone UI driver on PATH "
              f"{DIM}(axe / idb / appium / xcodebuildmcp){RESET}")

    print(f"\n{BOLD}Skills{RESET}")
    for name, info in r["skills"].items():
        mark = {"ready": ok, "blocked": bad, "missing": bad}[info["status"]]
        print(f"  {mark} {name}")
        for blocker in info.get("blockers", []):
            print(f"      {RED}missing:{RESET} {blocker}")
        for warning in info.get("warnings", []):
            print(f"      {YELLOW}note:{RESET} {warning}")
        if info["status"] == "ready":
            print(f"      {DIM}deep check: {info['doctor']}{RESET}")

    print(f"\n{r['ready_count']}/{len(r['skills'])} skills operational.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="emit a capability manifest")
    parser.add_argument("-o", "--output", type=Path, help="write the manifest to a file")
    args = parser.parse_args()

    report = build_report()

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(f"wrote {args.output}")
    elif args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)

    return 0 if report["ready_count"] else 1


if __name__ == "__main__":
    sys.exit(main())
