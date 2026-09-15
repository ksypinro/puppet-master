#!/usr/bin/env python3
"""Discover what can be built, where it can run, and where the product lands.

Read-only. Never guess a scheme, a destination, or a product path: every answer
here comes from the toolchain rather than from a convention.

    python3 build_targets.py schemes      --path /abs/project
    python3 build_targets.py destinations --path /abs/project --scheme App
    python3 build_targets.py settings     --path /abs/project --scheme App --destination '...'
    python3 build_targets.py product      --path /abs/project --scheme App --simulator
"""

from __future__ import annotations

import argparse
import re

from build_util import (
    BuildError, Container, build_settings, emit, find_containers, list_schemes,
    resolve_product, run, run_json, shared_schemes,
)

# `-showdestinations` is the one query flag with no -json form. Its output is a
# brace format that has to be parsed, and it lists incompatible destinations
# alongside compatible ones — consuming those as usable targets is a real bug.
BRACES = re.compile(r"\{\s*(.*?)\s*\}")


def parse_destinations(text):
    compatible, ignoring = [], True
    for line in text.splitlines():
        low = line.lower()
        if "available destinations" in low or "destinations compatible" in low:
            ignoring = False
            continue
        if "incompatible" in low:
            ignoring = True
            continue
        if ignoring:
            continue
        match = BRACES.search(line)
        if not match:
            continue
        entry = {}
        for part in match.group(1).split(","):
            key, sep, value = part.partition(":")
            if sep:
                entry[key.strip()] = value.strip()
        if entry and "error" not in entry:
            compatible.append(entry)
    return compatible


def cmd_containers(args):
    found = find_containers(__import__("pathlib").Path(args.path).resolve())
    emit({
        "ok": True,
        "workspaces": [str(p) for p in found["workspaces"]],
        "projects": [str(p) for p in found["projects"]],
        "packages": [str(p) for p in found["packages"]],
        "resolved": Container.discover(args.path).describe(),
        "rule": "a workspace wins over a project — that is what Xcode itself opens",
    })


def cmd_schemes(args):
    container = Container.discover(args.path)
    listing = list_schemes(container)
    shared = shared_schemes(container)
    schemes = [{"name": s, "shared": s in shared} for s in listing["schemes"]]
    unshared = [s["name"] for s in schemes if not s["shared"]]
    payload = {
        "ok": True,
        "container": container.describe(),
        "kind": listing["kind"],
        "name": listing["name"],
        "schemes": schemes,
        "targets": listing["targets"],
        "configurations": listing["configurations"],
    }
    if unshared:
        payload["warning"] = {
            "unsharedSchemes": unshared,
            "why": ("a scheme under xcuserdata/ is not in version control: CI and "
                    "teammates cannot see it, and xcodebuild will not list it there"),
            "fix": "move the .xcscheme into <container>/xcshareddata/xcschemes/",
        }
    emit(payload)


def cmd_destinations(args):
    container = Container.discover(args.path, scheme=args.scheme)
    scheme_dests = []
    if container.scheme:
        proc = run(["xcodebuild", "-showdestinations"] + container.common(),
                   cwd=container.cwd, timeout=240)
        scheme_dests = parse_destinations(proc.stdout)

    simulators = []
    data = run_json(["xcrun", "simctl", "list", "devices", "-j"]) or {}
    for runtime, devices in (data.get("devices") or {}).items():
        for device in devices:
            if device.get("isAvailable"):
                simulators.append({
                    "udid": device["udid"],
                    "name": device["name"],
                    "state": device["state"],
                    "runtime": runtime.rsplit(".", 1)[-1],
                })

    hardware, core_simulators = [], []
    core = run_json(["xcrun", "devicectl", "list", "devices",
                     "--json-output", "/dev/stdout", "-q"]) or {}
    for device in ((core.get("result") or {}).get("devices") or []):
        props = device.get("hardwareProperties") or {}
        entry = {
            "udid": device.get("identifier"),
            "name": (device.get("deviceProperties") or {}).get("name"),
            "platform": props.get("platform"),
            "reality": props.get("reality"),
            "state": (device.get("connectionProperties") or {}).get("tunnelState"),
        }
        # Xcode 27 surfaces Simulators through CoreDevice too. Treating every
        # devicectl row as hardware is a live bug, so they are split here.
        (hardware if props.get("reality") == "physical" else core_simulators).append(entry)

    emit({
        "ok": True,
        "scheme": container.scheme,
        "schemeDestinations": scheme_dests,
        "schemeDestinationNote": (
            "-showdestinations has no -json form; this is parsed from its brace "
            "format and includes only the compatible section"
        ),
        "simulators": simulators,
        "physicalDevices": hardware,
        "simulatorsViaDevicectl": core_simulators,
        "genericDestinations": {
            "device": "generic/platform=iOS",
            "simulator": "generic/platform=iOS Simulator",
        },
    })


def _destination_for(args, container):
    if args.destination:
        return args.destination
    if args.device_id:
        return "platform=iOS Simulator,id=%s" % args.device_id if args.simulator \
            else "platform=iOS,id=%s" % args.device_id
    if args.simulator:
        return "generic/platform=iOS Simulator"
    return "generic/platform=iOS"


def cmd_settings(args):
    container = Container.discover(
        args.path, scheme=args.scheme, configuration=args.configuration,
        derived_data=args.derived_data,
    )
    if not container.scheme:
        raise BuildError("--scheme is required for settings")
    destination = _destination_for(args, container)
    settings = build_settings(container, destination, extra=args.setting)

    if args.all:
        selected = settings
    else:
        keys = [
            "PRODUCT_NAME", "PRODUCT_BUNDLE_IDENTIFIER", "PRODUCT_TYPE",
            "FULL_PRODUCT_NAME", "WRAPPER_NAME", "EXECUTABLE_PATH",
            "TARGET_BUILD_DIR", "BUILT_PRODUCTS_DIR", "CONFIGURATION_BUILD_DIR",
            "CONFIGURATION", "PLATFORM_NAME", "EFFECTIVE_PLATFORM_NAME",
            "SDKROOT", "ARCHS", "IPHONEOS_DEPLOYMENT_TARGET", "SUPPORTED_PLATFORMS",
            "CODE_SIGNING_ALLOWED", "CODE_SIGNING_REQUIRED", "CODE_SIGN_IDENTITY",
            "CODE_SIGN_STYLE", "DEVELOPMENT_TEAM", "PROVISIONING_PROFILE_SPECIFIER",
            "BUILD_LIBRARY_FOR_DISTRIBUTION", "SKIP_INSTALL", "SWIFT_VERSION",
        ]
        selected = {k: settings[k] for k in keys if k in settings}

    emit({
        "ok": True,
        "container": container.describe(),
        "destination": destination,
        "settings": selected,
        "product": resolve_product(settings),
    })


def cmd_product(args):
    container = Container.discover(
        args.path, scheme=args.scheme, configuration=args.configuration,
        derived_data=args.derived_data,
    )
    if not container.scheme:
        raise BuildError("--scheme is required for product")
    destination = _destination_for(args, container)
    settings = build_settings(container, destination, extra=args.setting)
    product = resolve_product(settings)
    import os
    product["exists"] = os.path.exists(product["appPath"])
    if not product["exists"]:
        product["note"] = ("the path is resolved from build settings but nothing is "
                           "there yet — build first")
    emit({"ok": True, "destination": destination, "product": product})


def add_common(parser, need_scheme=True):
    parser.add_argument("--path", default=".", help="project directory")
    if need_scheme:
        parser.add_argument("--scheme")
        parser.add_argument("--configuration")
        parser.add_argument("--derived-data", dest="derived_data")
        parser.add_argument("--destination", help="explicit -destination string")
        parser.add_argument("--device-id", dest="device_id", help="UDID")
        parser.add_argument("--simulator", action="store_true",
                            help="target the Simulator platform instead of device")
        parser.add_argument("--setting", action="append",
                            help="extra KEY=VALUE build setting (repeatable)")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("containers"); add_common(p, False); p.set_defaults(func=cmd_containers)
    p = sub.add_parser("schemes");    add_common(p, False); p.set_defaults(func=cmd_schemes)
    p = sub.add_parser("destinations")
    p.add_argument("--path", default="."); p.add_argument("--scheme")
    p.set_defaults(func=cmd_destinations)
    p = sub.add_parser("settings"); add_common(p)
    p.add_argument("--all", action="store_true", help="emit every build setting")
    p.set_defaults(func=cmd_settings)
    p = sub.add_parser("product"); add_common(p); p.set_defaults(func=cmd_product)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except BuildError as exc:
        emit({"ok": False, "error": str(exc)})
        raise SystemExit(2)
