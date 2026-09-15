#!/usr/bin/env python3
"""Package and verify build products: XCFrameworks, artifact manifests, and the
platform check that catches a build that targeted the wrong OS.

    python3 package_products.py verify-platform --binary /abs/App.app/App --expect ios
    python3 package_products.py manifest --app /abs/App.app --dsym /abs/App.app.dSYM
    python3 package_products.py xcframework --package /abs/pkg --scheme Lib --output /abs/Lib.xcframework
"""

from __future__ import annotations

import argparse
import plistlib
import re
import shutil
import tempfile
from pathlib import Path

from build_util import (
    TIMEOUT_BUILD, BuildError, emit, run,
)

PLATFORM = re.compile(r"^\s*platform\s+(\S+)", re.M)
MINOS = re.compile(r"^\s*minos\s+(\S+)", re.M)
SDKV = re.compile(r"^\s*sdk\s+(\S+)", re.M)
UUID_LINE = re.compile(r"UUID:\s+([0-9A-Fa-f-]{36})\s+\((\w+)\)")

EXPECTED = {
    "ios": {"IOS"},
    "ios-simulator": {"IOSSIMULATOR", "IOS"},
    "macos": {"MACOS"},
}


def binary_of(app):
    """Resolve the Mach-O inside a bundle via its Info.plist."""
    app = Path(app)
    if app.is_file():
        return app
    info = app / "Info.plist"
    if info.is_file():
        try:
            name = plistlib.loads(info.read_bytes()).get("CFBundleExecutable")
            if name and (app / name).is_file():
                return app / name
        except Exception:
            pass
    candidate = app / app.stem
    if candidate.is_file():
        return candidate
    raise BuildError("could not locate the executable inside %s" % app)


def platform_of(binary):
    proc = run(["vtool", "-show-build", str(binary)], timeout=120)
    blob = proc.stdout + proc.stderr
    platforms = [m.upper() for m in PLATFORM.findall(blob)]
    archs = run(["lipo", "-archs", str(binary)], timeout=120).stdout.split()
    return {
        "platforms": platforms,
        "minos": MINOS.search(blob).group(1) if MINOS.search(blob) else None,
        "sdk": SDKV.search(blob).group(1) if SDKV.search(blob) else None,
        "architectures": archs,
    }


def cmd_verify_platform(args):
    """Guard against a build that silently targeted the wrong platform.

    `swift build --triple arm64-apple-ios...` is accepted, exits 0, prints
    "Build complete!" and produces macOS objects. Nothing in the exit status
    reveals it; only the Mach-O load command does.
    """
    target = Path(args.binary or args.app)
    binary = binary_of(target)
    info = platform_of(binary)
    expected = EXPECTED.get(args.expect)
    if expected is None:
        raise BuildError("--expect must be one of %s" % ", ".join(sorted(EXPECTED)))
    seen = set(info["platforms"])
    ok = bool(seen & expected)
    emit({
        "ok": ok,
        "binary": str(binary),
        "expected": args.expect,
        "found": info,
        "verdict": ("platform matches" if ok else
                    "PLATFORM MISMATCH — this binary is %s, not %s. A zero exit status "
                    "from the build does not rule this out."
                    % (", ".join(info["platforms"]) or "unknown", args.expect)),
    })
    raise SystemExit(0 if ok else 1)


def cmd_manifest(args):
    """An artifact manifest that a later agent can match a crash report against."""
    app = Path(args.app).resolve()
    if not app.exists():
        raise BuildError("not found: %s" % app)
    binary = binary_of(app)

    info_plist = {}
    info_path = app / "Info.plist" if app.is_dir() else None
    if info_path and info_path.is_file():
        try:
            info_plist = plistlib.loads(info_path.read_bytes())
        except Exception:
            info_plist = {}

    def uuids(path):
        proc = run(["dwarfdump", "--uuid", str(path)], timeout=180)
        return [{"uuid": u, "arch": a} for u, a in UUID_LINE.findall(proc.stdout)]

    signature = run(["codesign", "-dv", "--verbose=2", str(app)], timeout=120)
    blob = signature.stderr or signature.stdout
    team = re.search(r"TeamIdentifier=(\S+)", blob)

    manifest = {
        "ok": True,
        "app": str(app),
        "bundleId": info_plist.get("CFBundleIdentifier"),
        "shortVersion": info_plist.get("CFBundleShortVersionString"),
        "buildVersion": info_plist.get("CFBundleVersion"),
        "minimumOSVersion": info_plist.get("MinimumOSVersion"),
        "executable": str(binary),
        "binaryUUIDs": uuids(binary),
        "platform": platform_of(binary),
        "signed": "Signature size" in blob,
        "teamIdentifier": team.group(1) if team else None,
        "sizeBytes": sum(f.stat().st_size for f in app.rglob("*") if f.is_file())
                     if app.is_dir() else app.stat().st_size,
    }
    if args.dsym:
        dsym = Path(args.dsym)
        if not dsym.exists():
            raise BuildError("dSYM not found: %s" % dsym)
        manifest["dsym"] = {"path": str(dsym), "uuids": uuids(dsym)}
        binary_ids = {u["uuid"] for u in manifest["binaryUUIDs"]}
        dsym_ids = {u["uuid"] for u in manifest["dsym"]["uuids"]}
        manifest["dsymMatches"] = bool(binary_ids & dsym_ids)
        if not manifest["dsymMatches"]:
            manifest["dsymWarning"] = (
                "no shared UUID — this dSYM cannot symbolicate this binary"
            )
    emit(manifest)


# ---------------------------------------------------------------- xcframework

PRODUCT_DIRS = [
    ("generic/platform=iOS", "ios", "iphoneos"),
    ("generic/platform=iOS Simulator", "simulator", "iphonesimulator"),
]


def cmd_xcframework(args):
    """Build a Swift package into a multi-platform XCFramework.

    `xcodebuild archive` does not work for SwiftPM library products: it reports
    ARCHIVE SUCCEEDED and leaves a bare .o under Products/Users/<user>/Objects
    with no .a and no .framework. The static library has to be made here.
    """
    package = Path(args.package).resolve()
    output = Path(args.output).resolve()
    if not (package / "Package.swift").is_file():
        raise BuildError("no Package.swift in %s" % package)

    work = Path(tempfile.mkdtemp(prefix="xcf-"))
    slices, built = [], []
    try:
        for destination, tag, sdk_suffix in PRODUCT_DIRS:
            derived = work / ("dd-" + tag)
            cmd = ["xcodebuild", "-scheme", args.scheme, "-destination", destination,
                   "-derivedDataPath", str(derived), "build",
                   "BUILD_LIBRARY_FOR_DISTRIBUTION=YES"]
            if args.configuration:
                cmd += ["-configuration", args.configuration]
            proc = run(cmd, cwd=str(package), timeout=TIMEOUT_BUILD)
            if proc.returncode != 0:
                raise BuildError(
                    "build failed for %s:\n%s" % (destination, proc.stdout[-1500:])
                )
            config = args.configuration or "Debug"
            products = derived / "Build" / "Products" / ("%s-%s" % (config, sdk_suffix))
            objects = sorted(products.glob("*.o"))
            modules = sorted(products.glob("*.swiftmodule"))
            if not objects:
                raise BuildError("no object files in %s" % products)

            slice_dir = work / tag
            slice_dir.mkdir(parents=True, exist_ok=True)
            library = slice_dir / ("lib%s.a" % args.scheme)
            archive = run(["libtool", "-static", "-o", str(library)] +
                          [str(o) for o in objects], timeout=600)
            if archive.returncode != 0:
                raise BuildError("libtool failed: %s" % archive.stderr.strip())
            # The .swiftmodule must sit as a SIBLING of the .a. -create-xcframework
            # then places it at the slice root by itself. Passing -headers for a
            # pure-Swift library instead creates a redundant Headers/ copy that
            # leads consumers to -I <slice>/Headers, which does not resolve.
            for module in modules:
                shutil.copytree(module, slice_dir / module.name, dirs_exist_ok=True)
            slices += ["-library", str(library)]
            built.append({"destination": destination, "library": str(library),
                          "swiftmodules": [m.name for m in modules]})

        if output.exists():
            shutil.rmtree(output)
        create = run(["xcodebuild", "-create-xcframework"] + slices +
                     ["-output", str(output)], timeout=900)
        if create.returncode != 0:
            raise BuildError("create-xcframework failed: %s"
                             % (create.stdout + create.stderr)[-1500:])

        info = plistlib.loads((output / "Info.plist").read_bytes())
        emit({
            "ok": True,
            "output": str(output),
            "built": built,
            "slices": [{
                "identifier": lib["LibraryIdentifier"],
                "architectures": lib["SupportedArchitectures"],
                "platform": lib["SupportedPlatform"],
                "variant": lib.get("SupportedPlatformVariant", "device"),
                "library": lib["LibraryPath"],
            } for lib in info["AvailableLibraries"]],
            "consume": ("swiftc -I <xcframework>/<slice> -L <xcframework>/<slice> -l%s "
                        "— the slice ROOT, never <slice>/Headers" % args.scheme),
        })
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("verify-platform")
    p.add_argument("--binary"); p.add_argument("--app")
    p.add_argument("--expect", default="ios",
                   help="ios | ios-simulator | macos")
    p.set_defaults(func=cmd_verify_platform)

    p = sub.add_parser("manifest")
    p.add_argument("--app", required=True); p.add_argument("--dsym")
    p.set_defaults(func=cmd_manifest)

    p = sub.add_parser("xcframework")
    p.add_argument("--package", required=True)
    p.add_argument("--scheme", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--configuration")
    p.set_defaults(func=cmd_xcframework)

    args = parser.parse_args()
    if getattr(args, "command", None) == "verify-platform" and not (args.binary or args.app):
        parser.error("verify-platform needs --binary or --app")
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except BuildError as exc:
        emit({"ok": False, "error": str(exc)})
        raise SystemExit(2)
