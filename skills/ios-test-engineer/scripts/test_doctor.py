#!/usr/bin/env python3
"""Discover what is testable in a project before running anything.

    python3 test_doctor.py                      discover from the current directory
    python3 test_doctor.py --path ~/src/MyApp   discover elsewhere
    python3 test_doctor.py --destinations       also probe destinations per scheme
    python3 test_doctor.py --json               machine-readable

Read-only. Builds nothing, boots nothing, changes no settings.

Answers the questions that have to be settled before a single test runs:
which schemes exist, which of them are SHARED, which test plans each carries,
which destinations each actually supports, and what the toolchain is.

THE SHARED-SCHEME TRAP

Xcode schemes live in two places:

    <project>/xcshareddata/xcschemes/     committed, everyone has them
    <project>/xcuserdata/<user>.xcuserdatad/xcschemes/     yours alone

`xcodebuild -list` on your Mac shows both. On a CI runner or a teammate's fresh
clone, the second set does not exist -- so targets silently vanish from the run
and the suite still reports green. On a multi-target project this is the single
most common reason "all tests pass" means less than it appears to.

This tool reads the filesystem directly to tell them apart, which `-list`
cannot do.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

LIST_TIMEOUT = 90
DESTINATION_TIMEOUT = 120


class ToolError(RuntimeError):
    pass


def run(argv: List[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True,
                          timeout=timeout, check=False)


# --------------------------------------------------------------------------
# toolchain
# --------------------------------------------------------------------------

def toolchain() -> Dict[str, Any]:
    info: Dict[str, Any] = {"fullXcode": False}
    if not shutil.which("xcrun"):
        info["error"] = "xcrun not found; install the Xcode Command Line Tools"
        return info

    proc = run(["xcode-select", "-p"], 20)
    info["developerDir"] = proc.stdout.strip() if proc.returncode == 0 else None

    proc = run(["xcodebuild", "-version"], 30)
    if proc.returncode == 0:
        lines = proc.stdout.strip().splitlines()
        info["xcode"] = lines[0] if lines else None
        info["build"] = lines[1].replace("Build version ", "") if len(lines) > 1 else None
        info["fullXcode"] = True
    else:
        info["error"] = ("xcodebuild unavailable: the standalone Command Line "
                         "Tools are selected, not full Xcode. Fix with: "
                         "sudo xcode-select -s /Applications/Xcode.app/Contents/Developer")

    proc = run(["swift", "--version"], 30)
    if proc.returncode == 0:
        info["swift"] = proc.stdout.strip().splitlines()[0]
    return info


# --------------------------------------------------------------------------
# project container
# --------------------------------------------------------------------------

def find_container(root: Path) -> Dict[str, Any]:
    """Locate the workspace, project, or Swift package to test.

    A workspace wins over a project when both exist, because that is what
    xcodebuild resolves dependencies against.
    """
    workspaces = [p for p in root.glob("*.xcworkspace")
                  if not p.name.startswith(".")]
    # A project's own embedded workspace is not a real workspace.
    workspaces = [w for w in workspaces if w.parent.suffix != ".xcodeproj"]
    projects = list(root.glob("*.xcodeproj"))
    package = root / "Package.swift"

    if workspaces:
        return {"kind": "workspace", "path": str(workspaces[0]),
                "flag": "-workspace", "name": workspaces[0].name}
    if projects:
        return {"kind": "project", "path": str(projects[0]),
                "flag": "-project", "name": projects[0].name}
    if package.exists():
        return {"kind": "swiftpm", "path": str(package),
                "flag": None, "name": "Package.swift"}
    return {"kind": None, "error": f"no .xcworkspace, .xcodeproj or Package.swift in {root}"}


# --------------------------------------------------------------------------
# schemes -- and whether they are shared
# --------------------------------------------------------------------------

def _scheme_files(root: Path) -> Dict[str, Dict[str, Any]]:
    """Map scheme name -> {shared, path, owner} by reading the filesystem."""
    found: Dict[str, Dict[str, Any]] = {}
    for container in list(root.glob("*.xcodeproj")) + list(root.glob("*.xcworkspace")):
        shared = container / "xcshareddata" / "xcschemes"
        for f in shared.glob("*.xcscheme"):
            found[f.stem] = {"shared": True, "path": str(f), "owner": None,
                             "container": container.name}
        for userdir in (container / "xcuserdata").glob("*.xcuserdatad"):
            for f in (userdir / "xcschemes").glob("*.xcscheme"):
                if f.stem not in found:
                    found[f.stem] = {"shared": False, "path": str(f),
                                     "owner": userdir.stem, "container": container.name}
    return found


def _scheme_has_tests(scheme_path: str) -> Optional[bool]:
    """True when the scheme's TestAction references at least one testable."""
    try:
        text = Path(scheme_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"<TestAction\b.*?</TestAction>", text, re.S)
    if not m:
        return False
    block = m.group(0)
    return ("<TestableReference" in block) or ("TestPlanReference" in block)


def schemes(root: Path, container: Dict[str, Any]) -> Dict[str, Any]:
    on_disk = _scheme_files(root)

    listed: List[str] = []
    if container.get("flag"):
        proc = run(["xcodebuild", container["flag"], container["path"], "-list", "-json"],
                   LIST_TIMEOUT)
        if proc.returncode == 0:
            try:
                data = json.loads(proc.stdout)
                node = data.get("workspace") or data.get("project") or {}
                listed = node.get("schemes", []) or []
            except json.JSONDecodeError:
                pass

    rows = []
    for name in sorted(set(listed) | set(on_disk)):
        meta = on_disk.get(name, {})
        rows.append({
            "name": name,
            "shared": meta.get("shared"),
            "owner": meta.get("owner"),
            "container": meta.get("container"),
            "listedByXcodebuild": name in listed,
            "hasTestAction": _scheme_has_tests(meta["path"]) if meta.get("path") else None,
            "path": meta.get("path"),
        })

    unshared = [r for r in rows if r["shared"] is False]
    testable = [r for r in rows if r["hasTestAction"]]
    return {
        "schemes": rows,
        "count": len(rows),
        "sharedCount": sum(1 for r in rows if r["shared"]),
        "unsharedCount": len(unshared),
        "unshared": [r["name"] for r in unshared],
        "testableCount": len(testable),
        "testable": [r["name"] for r in testable],
    }


# --------------------------------------------------------------------------
# test plans
# --------------------------------------------------------------------------

def test_plans(root: Path, container: Dict[str, Any], scheme: str) -> Dict[str, Any]:
    plans: List[str] = []
    if container.get("flag"):
        proc = run(["xcodebuild", container["flag"], container["path"],
                    "-scheme", scheme, "-showTestPlans"], LIST_TIMEOUT)
        if proc.returncode == 0:
            # xcodebuild echoes its own invocation first, then a header line,
            # then the plan names indented beneath it. Only read after the
            # header, or the command line itself lands in the list.
            in_section = False
            for raw_line in proc.stdout.splitlines():
                if re.search(r"[Tt]est plans? associated", raw_line):
                    in_section = True
                    continue
                if not in_section:
                    continue
                line = raw_line.strip()
                if not line:
                    # A blank line ends the section.
                    if plans:
                        break
                    continue
                if line.startswith("/") or " -scheme " in line:
                    continue
                plans.append(line)

    files = []
    for f in root.rglob("*.xctestplan"):
        if any(part in (".build", "DerivedData", "Pods") for part in f.parts):
            continue
        entry: Dict[str, Any] = {"name": f.stem, "path": str(f)}
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
            entry["configurations"] = [c.get("name") for c in doc.get("configurations", [])]
            opts = doc.get("defaultOptions", {}) or {}
            entry["codeCoverage"] = opts.get("codeCoverage")
            entry["testTimeoutsEnabled"] = opts.get("testTimeoutsEnabled")
            entry["targetCount"] = len(doc.get("testTargets", []) or [])
            entry["hasSkippedTests"] = any(
                t.get("skippedTests") for t in doc.get("testTargets", []) or [])
        except (OSError, json.JSONDecodeError, ValueError):
            entry["parseError"] = True
        files.append(entry)

    return {"reportedByScheme": plans, "filesOnDisk": files}


# --------------------------------------------------------------------------
# destinations -- valid per scheme, which is the whole matrix problem
# --------------------------------------------------------------------------

DEST_RE = re.compile(
    r"\{\s*platform:([^,}]+?)(?:,\s*arch:([^,}]+?))?(?:,\s*id:([^,}]+?))?"
    r"(?:,\s*OS:([^,}]+?))?(?:,\s*name:([^,}]+?))?\s*\}")


def destinations(container: Dict[str, Any], scheme: str) -> Dict[str, Any]:
    if not container.get("flag"):
        return {"scheme": scheme, "destinations": [], "note": "SwiftPM: no destinations"}

    proc = run(["xcodebuild", container["flag"], container["path"],
                "-scheme", scheme, "-showdestinations"], DESTINATION_TIMEOUT)
    if proc.returncode != 0:
        return {"scheme": scheme, "destinations": [],
                "error": (proc.stderr or proc.stdout).strip()[:300]}

    valid, ineligible = [], []
    section = "valid"
    for line in proc.stdout.splitlines():
        low = line.strip().lower()
        if "ineligible destinations" in low:
            section = "ineligible"
            continue
        if "available destinations" in low:
            section = "valid"
            continue
        m = DEST_RE.search(line)
        if not m:
            continue
        entry = {
            "platform": (m.group(1) or "").strip(),
            "arch": (m.group(2) or "").strip() or None,
            "id": (m.group(3) or "").strip() or None,
            "os": (m.group(4) or "").strip() or None,
            "name": (m.group(5) or "").strip() or None,
        }
        (valid if section == "valid" else ineligible).append(entry)

    platforms = sorted({d["platform"] for d in valid if d["platform"]})
    return {
        "scheme": scheme,
        "destinations": valid,
        "ineligible": ineligible,
        "platforms": platforms,
        "validCount": len(valid),
    }


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------

def discover(root: Path, probe_destinations: bool = False) -> Dict[str, Any]:
    tc = toolchain()
    container = find_container(root)

    result: Dict[str, Any] = {
        "root": str(root),
        "toolchain": tc,
        "container": container,
        "schemes": {"schemes": [], "count": 0},
        "plans": {},
        "destinations": [],
        "warnings": [],
    }

    if container.get("error"):
        result["warnings"].append(container["error"])
        return result
    if not tc.get("fullXcode") and container["kind"] != "swiftpm":
        result["warnings"].append(
            "Full Xcode is not selected; scheme and destination discovery will fail.")
        return result

    sch = schemes(root, container)
    result["schemes"] = sch

    if sch["unsharedCount"]:
        result["warnings"].append(
            f"{sch['unsharedCount']} scheme(s) are NOT shared "
            f"({', '.join(sch['unshared'])}). They live in xcuserdata and are "
            f"not in version control, so CI and other developers will not see "
            f"them. Share them in Xcode (Product > Scheme > Manage Schemes > "
            f"Shared) before relying on them.")

    for row in sch["schemes"]:
        if row["hasTestAction"]:
            result["plans"][row["name"]] = test_plans(root, container, row["name"])

    if probe_destinations:
        for name in sch["testable"]:
            result["destinations"].append(destinations(container, name))
        platform_sets = {d["scheme"]: set(d.get("platforms") or [])
                         for d in result["destinations"]}
        if len({frozenset(v) for v in platform_sets.values()}) > 1:
            result["warnings"].append(
                "Schemes support different platform sets, so the "
                "scheme x destination matrix is not a full cross product. "
                "Build it from each scheme's own -showdestinations output.")

    if sch["testableCount"] == 0:
        result["warnings"].append(
            "No scheme has a test action. Nothing can be tested until one does.")
    return result


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def render(d: Dict[str, Any]) -> None:
    tc, c = d["toolchain"], d["container"]
    print(f"\nProject discovery — {d['root']}\n")

    print("  toolchain")
    if tc.get("error"):
        print(f"    ✗ {tc['error']}")
    else:
        print(f"    ✓ {tc.get('xcode')}  build {tc.get('build')}")
        print(f"      {tc.get('developerDir')}")
        if tc.get("swift"):
            print(f"      {tc['swift']}")

    print("\n  container")
    if c.get("error"):
        print(f"    ✗ {c['error']}")
        _warnings(d)
        return
    print(f"    {c['kind']}: {c['name']}")

    sch = d["schemes"]
    print(f"\n  schemes — {sch['count']} total, {sch['sharedCount']} shared, "
          f"{sch['testableCount']} with a test action")
    for r in sch["schemes"]:
        if r["shared"] is True:
            mark, tag = "✓", "shared"
        elif r["shared"] is False:
            mark, tag = "!", f"NOT SHARED (xcuserdata/{r['owner']})"
        else:
            mark, tag = "?", "not found on disk"
        tests = "  tests" if r["hasTestAction"] else ""
        print(f"    {mark} {r['name'][:34]:36s} {tag}{tests}")

    if d["plans"]:
        print("\n  test plans")
        for scheme, p in d["plans"].items():
            names = p["reportedByScheme"] or ["(none reported)"]
            print(f"    {scheme}: {', '.join(names)}")
            for f in p["filesOnDisk"]:
                cov = f.get("codeCoverage")
                cov_s = "coverage on" if cov else "coverage off" if cov is False else "coverage ?"
                print(f"      {f['name']:22s} {f.get('targetCount','?')} targets  "
                      f"{cov_s}"
                      f"{'  has skippedTests' if f.get('hasSkippedTests') else ''}")

    if d["destinations"]:
        print("\n  destinations per scheme")
        for entry in d["destinations"]:
            if entry.get("error"):
                print(f"    {entry['scheme']}: error — {entry['error'][:70]}")
                continue
            print(f"    {entry['scheme']}: {entry['validCount']} valid  "
                  f"[{', '.join(entry.get('platforms') or [])}]")

    _warnings(d)


def _warnings(d: Dict[str, Any]) -> None:
    if d["warnings"]:
        print("\n  warnings")
        for w in d["warnings"]:
            print(f"    ! {w}")
    print()


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--path", type=Path, default=Path.cwd())
    p.add_argument("--destinations", action="store_true",
                   help="probe -showdestinations per testable scheme (slower)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    root = args.path.expanduser().resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    try:
        result = discover(root, args.destinations)
    except subprocess.TimeoutExpired as exc:
        print(f"error: discovery timed out: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        render(result)

    return 0 if result["schemes"]["testableCount"] or \
        result["container"].get("kind") == "swiftpm" else 1


if __name__ == "__main__":
    sys.exit(main())
