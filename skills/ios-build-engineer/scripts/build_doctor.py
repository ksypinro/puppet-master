#!/usr/bin/env python3
"""Report whether this machine can build, sign, install and launch an iOS app.

Read-only. Answers the preconditions separately, because they fail separately:
a machine can build for Simulator with no signing material at all, compile for
device with no credentials, and still be unable to install on hardware.

    python3 build_doctor.py
    python3 build_doctor.py --path /abs/project
"""

from __future__ import annotations

import argparse
import plistlib
import re
import shutil
import subprocess
from pathlib import Path

from build_util import (
    BuildError, Container, developer_dir, emit, find_containers,
    list_schemes, run, run_json, shared_schemes,
)

IDENTITY = re.compile(r'^\s*\d+\)\s+([0-9A-F]{40})\s+"(.+?)"(?:\s+\((.+?)\))?\s*$', re.M)
PROFILE_DIRS = [
    Path.home() / "Library/Developer/Xcode/UserData/Provisioning Profiles",
    Path.home() / "Library/MobileDevice/Provisioning Profiles",
]


def check_toolchain():
    checks = []
    dev = developer_dir()
    import os
    checks.append({
        "check": "developer directory",
        "ok": bool(dev),
        "detail": dev or "unset",
        "source": "DEVELOPER_DIR" if os.environ.get("DEVELOPER_DIR") else "xcode-select",
        "note": "DEVELOPER_DIR overrides xcode-select per invocation and needs no sudo",
    })

    version = run(["xcodebuild", "-version"])
    checks.append({
        "check": "xcodebuild",
        "ok": version.returncode == 0,
        "detail": " ".join(version.stdout.split()) or version.stderr.strip(),
    })

    full_xcode = shutil.which("xcrun") is not None and \
        run(["xcrun", "--find", "simctl"]).returncode == 0
    checks.append({
        "check": "full Xcode (not Command Line Tools)",
        "ok": full_xcode,
        "detail": "simctl present" if full_xcode else "simctl missing",
        "remedy": None if full_xcode else
                  "Install Xcode.app; the CLT package cannot build or run iOS apps",
    })

    first_launch = run(["xcodebuild", "-checkFirstLaunchStatus"])
    checks.append({
        "check": "first-launch tasks",
        "ok": first_launch.returncode == 0,
        "detail": "complete" if first_launch.returncode == 0 else "pending",
        "remedy": None if first_launch.returncode == 0 else "xcodebuild -runFirstLaunch",
    })
    return checks


def check_sdks():
    sdks = run_json(["xcodebuild", "-showsdks", "-json"]) or []
    ios = sorted({
        s.get("canonicalName", "") for s in sdks
        if str(s.get("platform", "")).startswith("iphone")
    })
    return {
        "check": "iOS SDKs",
        "ok": bool(ios),
        "detail": ", ".join(ios) or "none installed",
        "remedy": None if ios else "xcodebuild -downloadPlatform iOS",
    }


def check_simulators():
    data = run_json(["xcrun", "simctl", "list", "devices", "-j"]) or {}
    available, booted = [], []
    for runtime, devices in (data.get("devices") or {}).items():
        for device in devices:
            if device.get("isAvailable"):
                available.append(device)
                if device.get("state") == "Booted":
                    booted.append(device["name"])
    return {
        "check": "simulators",
        "ok": bool(available),
        "detail": "%d available, %d booted%s" % (
            len(available), len(booted),
            (" (%s)" % ", ".join(booted[:3])) if booted else "",
        ),
        "remedy": None if available else "xcodebuild -downloadPlatform iOS",
    }


def check_locale():
    import os
    values = [os.environ.get("LANG", ""), os.environ.get("LC_ALL", "")]
    utf8 = any("UTF-8" in v.upper() for v in values if v)
    return {
        "check": "locale is UTF-8",
        "ok": utf8,
        "detail": "LANG=%s LC_ALL=%s" % (values[0] or "<unset>", values[1] or "<unset>"),
        "severity": "advisory",
        "remedy": None if utf8 else
                  "export LANG=en_US.UTF-8 — a non-UTF-8 locale surfaces as US-ASCII build errors",
    }


def signing_inventory():
    """Reported, never gated. Simulator work needs none of this."""
    proc = run(["security", "find-identity", "-v", "-p", "codesigning"])
    identities = []
    for sha1, name, note in IDENTITY.findall(proc.stdout):
        identities.append({"sha1": sha1, "commonName": name,
                           "status": note or "valid", "usable": not note})
    usable = [i for i in identities if i["usable"]]

    names = {}
    for ident in identities:
        names.setdefault(ident["commonName"], []).append(ident["sha1"])
    ambiguous = {k: v for k, v in names.items() if len(v) > 1}

    profiles = []
    for folder in PROFILE_DIRS:
        if folder.is_dir():
            profiles.extend(folder.glob("*.mobileprovision"))

    return {
        "identities": {
            "total": len(identities),
            "usable": len(usable),
            "unusable": len(identities) - len(usable),
            "ambiguousCommonNames": ambiguous,
        },
        "provisioningProfiles": len(profiles),
        "lanes": {
            "buildForSimulator": "ready — needs no identity and no profile",
            "buildForDevice": "ready — compiles with CODE_SIGNING_ALLOWED=NO and no credentials",
            "installOnDevice": (
                "ready" if usable and profiles else
                "blocked — needs at least one usable identity AND a matching profile"
            ),
        },
    }


def inspect_project(path):
    try:
        container = Container.discover(path)
    except BuildError as exc:
        return {"ok": False, "detail": str(exc)}
    found = find_containers(Path(path).resolve())
    info = {
        "ok": True,
        "resolved": container.describe(),
        "containersFound": {
            "workspaces": [p.name for p in found["workspaces"]],
            "projects": [p.name for p in found["projects"]],
            "packages": bool(found["packages"]),
        },
    }
    if found["workspaces"] and found["projects"]:
        info["note"] = ("both a workspace and a project exist; the workspace is used, "
                        "matching what Xcode itself opens")
    try:
        listing = list_schemes(container)
        shared = shared_schemes(container)
        info["schemes"] = [
            {"name": s, "shared": s in shared} for s in listing["schemes"]
        ]
        unshared = [s for s in listing["schemes"] if s not in shared]
        if unshared:
            info["unsharedSchemeWarning"] = (
                "not visible to CI or teammates: %s — move each into "
                "<project>.xcodeproj/xcshareddata/xcschemes/" % ", ".join(unshared)
            )
        info["configurations"] = listing["configurations"]
    except BuildError as exc:
        info["schemeError"] = str(exc)
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--path", help="project directory to inspect as well")
    args = parser.parse_args()

    checks = check_toolchain()
    checks.append(check_sdks())
    checks.append(check_simulators())
    checks.append(check_locale())

    report = {
        "ok": all(c["ok"] for c in checks
                  if c.get("severity", "blocking") == "blocking"),
        "checks": checks,
        "signing": signing_inventory(),
    }
    if args.path:
        report["project"] = inspect_project(args.path)

    blocking = [c["check"] for c in checks
                if not c["ok"] and c.get("severity", "blocking") == "blocking"]
    advisory = [c["check"] for c in checks
                if not c["ok"] and c.get("severity") == "advisory"]
    report["blocking"] = blocking
    report["advisory"] = advisory
    emit(report)
    raise SystemExit(0 if not blocking else 1)


if __name__ == "__main__":
    try:
        main()
    except BuildError as exc:
        emit({"ok": False, "error": str(exc)})
        raise SystemExit(2)
