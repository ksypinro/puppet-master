#!/usr/bin/env python3
"""Build a public UIKit capture dylib for an explicitly selected Simulator arch."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

sys.dont_write_bytecode = True
from lldb_ui import compiled_probe_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, help="new absolute directory; its parent must exist")
    parser.add_argument("--arch", choices=("arm64", "x86_64"), required=True,
                        help="architecture from the actual iOS Simulator target triple")
    parser.add_argument("--minimum-ios", default="17.0")
    parser.add_argument("--timeout", type=int, default=60, help="timeout for each build/sign step, 1..60 seconds")
    args = parser.parse_args()
    output = Path(args.output_dir)
    if not output.is_absolute() or output.exists() or os.path.lexists(output):
        parser.error("output-dir must be a new absolute path; existing files/directories are never replaced")
    if not output.parent.is_dir():
        parser.error("output-dir parent must already exist")
    if platform.system() != "Darwin":
        parser.error("building a Simulator probe requires macOS and full Xcode")
    if not re.fullmatch(r"\d{1,2}\.\d{1,2}(?:\.\d{1,2})?", args.minimum_ios):
        parser.error("minimum-ios must be a numeric version such as 17.0")
    if not 1 <= args.timeout <= 60:
        parser.error("timeout must be 1..60 seconds")

    output.mkdir(mode=0o700)
    manifest = {
        "format": "ios-ui-compiled-probe-build/v1",
        "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "platform": "iOS Simulator only",
        "architecture": args.arch,
        "minimumIOS": args.minimum_ios,
        "targetTriple": "%s-apple-ios%s-simulator" % (args.arch, args.minimum_ios),
        "commands": [],
        "status": "building",
        "doesNotAttachLaunchOrLoad": True,
    }

    def run(argv):
        record = {"argv": argv, "timeoutSeconds": args.timeout}
        manifest["commands"].append(record)
        try:
            result = subprocess.run(argv, text=True, capture_output=True, timeout=args.timeout, check=False)
        except subprocess.TimeoutExpired:
            record["timedOut"] = True
            raise RuntimeError("command timed out: " + argv[0])
        record.update(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
        if result.returncode:
            raise RuntimeError("command failed: %s\n%s" % (argv[0], result.stderr.strip()))
        return result.stdout.strip()

    try:
        sdk = run(["xcrun", "--sdk", "iphonesimulator", "--show-sdk-path"])
        if not Path(sdk).is_dir():
            raise RuntimeError("xcrun did not return an existing Simulator SDK")
        manifest["sdkPath"] = sdk
        manifest["xcodeVersion"] = run(["xcodebuild", "-version"])
        manifest["compilerVersion"] = run(["xcrun", "--sdk", "iphonesimulator", "clang", "--version"])
        source = output / "PuppetUIProbe.mm"
        dylib = output / "PuppetUIProbe.dylib"
        with source.open("x", encoding="utf-8") as handle:
            handle.write(compiled_probe_source())
        source.chmod(0o600)
        run(["xcrun", "--sdk", "iphonesimulator", "clang", "-x", "objective-c++", "-fblocks",
             "-dynamiclib", "-fvisibility=hidden", "-O0", "-Wno-deprecated-declarations",
             "-isysroot", sdk, "-target", manifest["targetTriple"],
             "-framework", "UIKit", "-framework", "QuartzCore", "-framework", "Foundation",
             "-framework", "CoreGraphics", "-framework", "CoreFoundation", "-lobjc",
             str(source), "-o", str(dylib)])
        # Only the new generated dylib is signed; no app/project signing is changed.
        run(["codesign", "--force", "--sign", "-", "--timestamp=none", str(dylib)])
        run(["codesign", "--verify", "--strict", str(dylib)])
        dylib.chmod(0o700)
        manifest["exportedSymbols"] = run(["xcrun", "nm", "-gU", str(dylib)])
        for symbol in ("PuppetUICapture", "PuppetUIIsMainThread", "PuppetUIFree"):
            if "_" + symbol not in manifest["exportedSymbols"]:
                raise RuntimeError("compiled probe is missing " + symbol)
        manifest["sourceSHA256"] = hashlib.sha256(source.read_bytes()).hexdigest()
        manifest["dylibSHA256"] = hashlib.sha256(dylib.read_bytes()).hexdigest()
        manifest["dylib"] = str(dylib)
        manifest["status"] = "built-and-signature-verified"
        print(str(dylib))
    except (OSError, RuntimeError) as exc:
        manifest["status"] = "failed"
        manifest["error"] = str(exc)
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        with (output / "build.json").open("x", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2)
            handle.write("\n")
        (output / "build.json").chmod(0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
