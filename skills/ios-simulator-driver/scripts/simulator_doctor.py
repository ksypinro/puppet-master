#!/usr/bin/env python3
"""Read-only capability and iOS Simulator inventory probe."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from typing import Any


def run(argv: list[str], timeout: float = 20.0) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "argv": argv,
            "exitCode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    except FileNotFoundError as exc:
        return {"argv": argv, "exitCode": None, "error": str(exc)}
    except subprocess.TimeoutExpired as exc:
        return {
            "argv": argv,
            "exitCode": None,
            "error": "timeout",
            "stdout": (exc.stdout or "").strip() if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "").strip() if isinstance(exc.stderr, str) else "",
        }


def tool_info(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    return {"available": path is not None, "path": path}


def parse_devices(result: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    if result.get("exitCode") != 0:
        return [], "simctl list failed"
    try:
        payload = json.loads(result.get("stdout", ""))
    except json.JSONDecodeError as exc:
        return [], f"invalid simctl JSON: {exc}"

    devices: list[dict[str, Any]] = []
    for runtime, runtime_devices in payload.get("devices", {}).items():
        for device in runtime_devices:
            if not device.get("isAvailable", True):
                continue
            devices.append(
                {
                    "udid": device.get("udid"),
                    "name": device.get("name"),
                    "state": device.get("state"),
                    "runtime": runtime,
                    "isAvailable": device.get("isAvailable", True),
                }
            )
    return devices, None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print a read-only JSON report for iOS Simulator automation."
    )
    parser.add_argument("--udid", help="Explicit target UDID to validate")
    args = parser.parse_args()

    report: dict[str, Any] = {
        "schema": "ios.simulator.doctor",
        "schemaVersion": 1,
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "developerDir": os.environ.get("DEVELOPER_DIR"),
        },
        "tools": {
            name: tool_info(name)
            for name in ("xcrun", "xcodebuild", "axe", "xcodebuildmcp", "agent-device", "idb")
        },
        "requestedUDID": args.udid,
    }

    if report["tools"]["xcodebuild"]["available"]:
        report["xcode"] = run(["xcodebuild", "-version"])
    else:
        report["xcode"] = {"exitCode": None, "error": "xcodebuild not found"}

    if report["tools"]["xcrun"]["available"]:
        simctl_result = run(["xcrun", "simctl", "list", "devices", "available", "-j"])
        devices, parse_error = parse_devices(simctl_result)
        report["simctl"] = {
            "exitCode": simctl_result.get("exitCode"),
            "stderr": simctl_result.get("stderr", ""),
            "parseError": parse_error,
        }
        report["devices"] = devices
    else:
        report["simctl"] = {"exitCode": None, "error": "xcrun not found"}
        report["devices"] = []

    booted = [device for device in report["devices"] if device.get("state") == "Booted"]
    report["bootedDevices"] = booted

    if args.udid:
        matches = [device for device in report["devices"] if device.get("udid") == args.udid]
        report["target"] = matches[0] if len(matches) == 1 else None
        report["targetSelection"] = "explicit-match" if len(matches) == 1 else "explicit-not-found"
    elif len(booted) == 1:
        report["target"] = booted[0]
        report["targetSelection"] = "single-booted-candidate"
    else:
        report["target"] = None
        report["targetSelection"] = "ambiguous-or-none"

    ui_drivers = [
        name
        for name in ("agent-device", "xcodebuildmcp", "axe", "idb")
        if report["tools"][name]["available"]
    ]
    report["detectedCLIUIDrivers"] = ui_drivers
    report["canCaptureScreenshot"] = (
        report["tools"]["xcrun"]["available"] and report["simctl"].get("exitCode") == 0
    )
    report["canInjectUIWithDetectedCLI"] = bool(ui_drivers)

    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")

    if platform.system() != "Darwin" or not report["tools"]["xcrun"]["available"]:
        return 2
    if report["simctl"].get("exitCode") != 0:
        return 3
    if args.udid and report["target"] is None:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
