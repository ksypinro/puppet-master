#!/usr/bin/env python3
"""Capability doctor for xctrace-based iOS performance work.

Read-only by default. It checks the selected Xcode, inventories, device visibility, disk space, and known
defects of the installed xctrace build. With --smoke-record it also records each requested template, and
the requested instrument set on the Blank template, for a few seconds through xctrace_record.py, so a
template or instrument that Xcode rejects for this target is found before a measurement campaign. Smoke
traces go to a temporary directory that is removed afterwards unless --keep-smoke names a directory.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


RECORDER = Path(__file__).resolve().with_name("xctrace_record.py")

# Defects observed on specific xctrace builds. "simulator" issues block recording on Simulator targets;
# the others are informational because the helpers already work around them.
KNOWN_ISSUES: dict[str, list[dict[str, Any]]] = {
    "27A5194q": [
        {
            "id": "simulator-recording-never-starts",
            "applies_to": "simulator",
            "blocking": True,
            "detail": "xctrace record never starts a recording for Simulator targets on Xcode 27 beta 27A5194q "
                      "(Apple 183624872; fixed in the Xcode 27 RC, which needs macOS Tahoe 26.6). None of 26 templates "
                      "recorded on the iOS 27 Simulator in testing. Record on a Mac or a device, use XCTest metrics on "
                      "the Simulator, or update Xcode.",
        },
        {
            "id": "launched-target-asleep",
            "applies_to": "launch",
            "blocking": False,
            "detail": "Launch-owned App Launch and Time Profiler recordings sometimes left the target asleep (2 CPU samples "
                      "in 6 s in one run, 1 in another), while a later App Launch recording of the same target ran normally. "
                      "Blank with Time Profiler launched normally in both attempts. xctrace_record.py fails asleep traces "
                      "as target-inactive.",
        },
        {
            "id": "export-time-window-ignored",
            "applies_to": "export",
            "blocking": False,
            "detail": "xctrace export accepts --time-start, --time-end and --duration but ignores them; filter by time "
                      "with xctrace_reduce.py --start-ms/--end-ms.",
        },
        {
            "id": "launch-exit-54",
            "applies_to": "launch",
            "blocking": False,
            "detail": "xctrace exits 54 after terminating a launched target at the time limit although the trace is "
                      "complete; xctrace_record.py accepts 54 only in that case.",
        },
    ],
}


def run(argv: list[str], timeout: float = 30.0) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
        output = completed.stdout.strip()
        truncated = len(output) > 4000
        if truncated:
            output = output[:4000] + "\n…<truncated>"
        return {
            "argv": argv,
            "exit_code": completed.returncode,
            "output": output,
            "output_truncated": truncated,
        }
    except FileNotFoundError as exc:
        return {"argv": argv, "exit_code": 127, "output": str(exc)}
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return {"argv": argv, "exit_code": 124, "output": output.strip(), "timed_out": True}


def inventory_lines(text: str) -> list[str]:
    result: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("=="):
            continue
        result.append(line)
    return result


def device_sections(text: str) -> dict[str, list[str]]:
    """Group `xctrace list devices` entries by their `== Section ==` header."""
    sections: dict[str, list[str]] = {}
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("==") and line.endswith("=="):
            current = line.strip("= ")
            continue
        sections.setdefault(current, []).append(line)
    return sections


def is_online_section(name: str) -> bool:
    return "offline" not in name.casefold()


def device_visibility(device: str, sections: dict[str, list[str]]) -> tuple[bool, dict[str, Any]]:
    """A device is visible only if it is listed outside every offline section."""
    online = [line for name, lines in sections.items() if is_online_section(name) for line in lines]
    offline = [line for name, lines in sections.items() if not is_online_section(name) for line in lines]
    needle = device.casefold()
    matches = [line for line in online if needle in line.casefold()]
    offline_matches = [line for line in offline if needle in line.casefold()]
    exact = any(f"({device})" in line or line == device for line in online)
    detail: dict[str, Any] = {"matches": matches}
    if offline_matches:
        detail["offline_matches"] = offline_matches
    if not matches and offline_matches:
        detail["reason"] = "listed only under an offline section"
    return exact or len(matches) == 1, detail


def device_kind(device: str, sections: dict[str, list[str]]) -> str | None:
    """"simulator" or "device" for the online section that lists this target, else None."""
    needle = device.casefold()
    for name, lines in sections.items():
        if is_online_section(name) and any(needle in line.casefold() for line in lines):
            return "simulator" if "simulator" in name.casefold() else "device"
    return None


def xctrace_build(version_text: str) -> str | None:
    """Build identifier from `xctrace version` output such as 'xctrace version 16.0 (27A5194q)'."""
    match = re.search(r"\(([0-9A-Za-z]+)\)", version_text)
    return match.group(1) if match else None


def known_issues(build: str | None, kind: str | None) -> list[dict[str, Any]]:
    return [
        {**issue, "applies_now": issue["applies_to"] != "simulator" or kind == "simulator"}
        for issue in KNOWN_ISSUES.get(build or "", [])
    ]


def nearest_existing_parent(path: Path) -> Path:
    candidate = path.expanduser().resolve()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def add_check(checks: list[dict[str, Any]], name: str, ok: bool, detail: Any) -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})


def smoke_plans(templates: list[str], instruments: list[str]) -> list[dict[str, Any]]:
    plans = [{"name": f"template:{name}", "template": name, "instruments": []} for name in templates]
    if instruments:
        plans.append({"name": "instruments:" + " + ".join(instruments), "template": "Blank", "instruments": instruments})
    return plans


def smoke_record(plan: dict[str, Any], args: argparse.Namespace, directory: Path) -> dict[str, Any]:
    """Record one short throwaway trace through the recorder and report whether it passed its gates."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", plan["name"]).strip("-").lower()
    output = directory / f"smoke-{slug}.trace"
    argv = [
        sys.executable, str(RECORDER),
        "--template", plan["template"],
        "--time-limit", f"{args.smoke_seconds:g}s",
        "--start-timeout", f"{args.smoke_start_timeout:g}",
        "--no-prompt",
        "--output", str(output),
    ]
    for instrument in plan["instruments"]:
        argv.extend(["--instrument", instrument])
    if args.device:
        argv.extend(["--device", args.device])
    if args.smoke_launch:
        argv.extend(["--launch", args.smoke_launch])
    elif args.smoke_attach:
        argv.extend(["--attach", args.smoke_attach])
    else:
        argv.append("--all-processes")
    probe = run(argv, timeout=args.smoke_start_timeout + args.smoke_seconds + 1800)
    try:
        manifest = json.loads(output.with_suffix(".trace.manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    return {
        "name": plan["name"],
        "recordable": bool(manifest.get("valid")),
        "status": manifest.get("status") or f"recorder-exit-{probe['exit_code']}",
        "recorder_errors": manifest.get("recorder_errors", []),
        "target_activity": manifest.get("target_activity"),
        "wall_seconds": manifest.get("wall_seconds"),
    }


def run_smoke(args: argparse.Namespace, directory: Path) -> list[dict[str, Any]]:
    results = []
    for plan in smoke_plans(args.template, args.instrument):
        result = smoke_record(plan, args, directory)
        results.append(result)
        # When an instrument set fails, record each instrument alone to name the one Xcode rejects.
        if not result["recordable"] and len(plan["instruments"]) > 1:
            for instrument in plan["instruments"]:
                single = {"name": f"instrument:{instrument}", "template": "Blank", "instruments": [instrument]}
                results.append(smoke_record(single, args, directory))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--template", action="append", default=[], help="Required template name; repeatable")
    parser.add_argument("--instrument", action="append", default=[], help="Required instrument name; repeatable")
    parser.add_argument("--device", help="Required device name or UDID as shown by xctrace")
    parser.add_argument("--simulator-udid", help="Simulator UDID for an installed-app check")
    parser.add_argument("--bundle-id", help="Bundle identifier paired with --simulator-udid")
    parser.add_argument("--output-dir", type=Path, help="Planned artifact directory")
    parser.add_argument("--min-free-gb", type=float, default=2.0, help="Required free space at output location")
    parser.add_argument("--smoke-record", action="store_true",
                        help="Record each template, and the instrument set on Blank, for a few seconds")
    smoke_target = parser.add_mutually_exclusive_group()
    smoke_target.add_argument("--smoke-attach", metavar="PID_OR_NAME", help="Smoke-record attached to this process")
    smoke_target.add_argument("--smoke-launch", metavar="BUNDLE_ID_OR_PATH", help="Smoke-record launching this target")
    parser.add_argument("--smoke-seconds", type=float, default=2.0)
    parser.add_argument("--smoke-start-timeout", type=float, default=45.0)
    parser.add_argument("--keep-smoke", type=Path, help="Keep smoke traces in this directory instead of deleting them")
    parser.add_argument("--save", type=Path, help="Also save the JSON report here")
    args = parser.parse_args()

    if bool(args.simulator_udid) != bool(args.bundle_id):
        parser.error("--simulator-udid and --bundle-id must be supplied together")
    if args.smoke_record and not (args.template or args.instrument):
        parser.error("--smoke-record needs at least one --template or --instrument")

    probes = {
        "developer_dir": run(["xcode-select", "-p"]),
        "xcode": run(["xcodebuild", "-version"]),
        "xctrace": run(["xcrun", "xctrace", "version"]),
        "devices": run(["xcrun", "xctrace", "list", "devices"]),
        "templates": run(["xcrun", "xctrace", "list", "templates"]),
        "instruments": run(["xcrun", "xctrace", "list", "instruments"]),
    }

    template_lines = (
        inventory_lines(probes["templates"]["output"])
        if probes["templates"]["exit_code"] == 0
        else []
    )
    instrument_lines = (
        inventory_lines(probes["instruments"]["output"])
        if probes["instruments"]["exit_code"] == 0
        else []
    )
    sections = device_sections(probes["devices"]["output"]) if probes["devices"]["exit_code"] == 0 else {}
    device_lines = [line for name, lines in sections.items() if is_online_section(name) for line in lines]
    offline_device_lines = [line for name, lines in sections.items() if not is_online_section(name) for line in lines]
    template_set = set(template_lines)
    instrument_set = set(instrument_lines)
    checks: list[dict[str, Any]] = []

    developer_dir = probes["developer_dir"]["output"]
    full_xcode = (
        probes["developer_dir"]["exit_code"] == 0
        and developer_dir.endswith(".app/Contents/Developer")
        and probes["xctrace"]["exit_code"] == 0
    )
    add_check(checks, "full_xcode_selected", full_xcode, developer_dir or "unavailable")
    add_check(checks, "xcodebuild_responds", probes["xcode"]["exit_code"] == 0, probes["xcode"]["output"])
    add_check(checks, "xctrace_responds", probes["xctrace"]["exit_code"] == 0, probes["xctrace"]["output"])
    add_check(checks, "device_inventory_available", probes["devices"]["exit_code"] == 0, f"{len(device_lines)} entries")
    add_check(checks, "template_inventory_available", probes["templates"]["exit_code"] == 0, f"{len(template_lines)} entries")
    add_check(checks, "instrument_inventory_available", probes["instruments"]["exit_code"] == 0, f"{len(instrument_lines)} entries")

    for name in args.template:
        add_check(checks, f"template:{name}", name in template_set, "installed" if name in template_set else "missing")
    for name in args.instrument:
        add_check(checks, f"instrument:{name}", name in instrument_set, "installed" if name in instrument_set else "missing")

    kind = None
    if args.device:
        visible, detail = device_visibility(args.device, sections)
        add_check(checks, "device_visible_to_xctrace", visible, detail)
        kind = device_kind(args.device, sections)

    build = xctrace_build(probes["xctrace"]["output"])
    issues = known_issues(build, kind)
    blocking = [issue for issue in issues if issue["blocking"] and issue["applies_now"]]
    for issue in blocking:
        add_check(checks, f"toolchain:{issue['id']}", False, issue["detail"])

    if args.simulator_udid and args.bundle_id:
        app_probe = run(
            [
                "xcrun",
                "simctl",
                "get_app_container",
                args.simulator_udid,
                args.bundle_id,
                "app",
            ]
        )
        probes["simulator_app"] = app_probe
        add_check(
            checks,
            "simulator_app_installed",
            app_probe["exit_code"] == 0,
            app_probe["output"],
        )

    output_info: dict[str, Any] | None = None
    if args.output_dir:
        requested = args.output_dir.expanduser().resolve()
        existing = nearest_existing_parent(requested)
        try:
            disk = shutil.disk_usage(existing)
            free_gb = disk.free / (1024**3)
            writable = os.access(existing, os.W_OK | os.X_OK)
            enough = free_gb >= args.min_free_gb
            output_info = {
                "requested": str(requested),
                "checked_parent": str(existing),
                "exists": requested.exists(),
                "writable_parent": writable,
                "free_gb": round(free_gb, 2),
                "minimum_free_gb": args.min_free_gb,
            }
            add_check(checks, "output_location_writable", writable, output_info)
            add_check(checks, "output_space_sufficient", enough, output_info)
        except OSError as exc:
            output_info = {"requested": str(requested), "error": str(exc)}
            add_check(checks, "output_location_writable", False, output_info)

    smoke: list[dict[str, Any]] | None = None
    smoke_skipped: str | None = None
    if args.smoke_record:
        if not full_xcode:
            smoke_skipped = "full Xcode with a responding xctrace is required"
        elif blocking:
            smoke_skipped = "a blocking known issue applies to this target: " + ", ".join(issue["id"] for issue in blocking)
        elif args.keep_smoke:
            directory = args.keep_smoke.expanduser().resolve()
            directory.mkdir(parents=True, exist_ok=True)
            smoke = run_smoke(args, directory)
        else:
            with tempfile.TemporaryDirectory(prefix="xctrace-smoke-") as scratch:
                smoke = run_smoke(args, Path(scratch))
        for result in smoke or []:
            add_check(checks, f"recordable:{result['name']}", result["recordable"], result)

    report = {
        "schema_version": "ios.xctrace.doctor.v2",
        "ready": all(check["ok"] for check in checks),
        "checks": checks,
        "selected_developer_dir": developer_dir or None,
        "xcode": probes["xcode"]["output"] or None,
        "xctrace": probes["xctrace"]["output"] or None,
        "xctrace_build": build,
        "target_kind": kind,
        "known_issues": issues,
        "smoke_record": smoke,
        "smoke_record_skipped": smoke_skipped,
        "inventory": {
            "devices": device_lines,
            "offline_devices": offline_device_lines,
            "templates": template_lines,
            "instruments": instrument_lines,
        },
        "output": output_info,
        "probe_failures": {
            name: probe
            for name, probe in probes.items()
            if probe.get("exit_code") != 0
        },
    }

    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.save:
        destination = args.save.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    sys.exit(main())
