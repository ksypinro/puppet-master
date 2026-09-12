#!/usr/bin/env python3
"""Capture one Simulator PNG and emit a machine-readable evidence record."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
from typing import Any


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise ValueError("captured file is not a valid PNG")
    return struct.unpack(">II", header[16:24])


def emit(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture an iOS Simulator screenshot.")
    parser.add_argument("--udid", required=True, help="Explicit Simulator UDID")
    parser.add_argument("--output", required=True, type=Path, help="Absolute PNG path")
    parser.add_argument("--force", action="store_true", help="Allow replacing an existing file")
    args = parser.parse_args()

    output = args.output.expanduser()
    if not output.is_absolute():
        emit({"ok": False, "error": "output path must be absolute"})
        return 2
    if output.suffix.lower() != ".png":
        emit({"ok": False, "error": "output path must end in .png"})
        return 2
    if output.exists() and not args.force:
        emit({"ok": False, "error": "output exists; pass --force to replace it", "path": str(output)})
        return 2

    output.parent.mkdir(parents=True, exist_ok=True)
    argv = ["xcrun", "simctl", "io", args.udid, "screenshot", "--type=png", str(output)]
    try:
        completed = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=30)
    except FileNotFoundError as exc:
        emit({"ok": False, "error": str(exc)})
        return 3
    except subprocess.TimeoutExpired:
        emit({"ok": False, "error": "simctl screenshot timed out"})
        return 3
    if completed.returncode != 0:
        emit(
            {
                "ok": False,
                "error": "simctl screenshot failed",
                "exitCode": completed.returncode,
                "stderr": completed.stderr.strip(),
            }
        )
        return 3

    try:
        width, height = png_dimensions(output)
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
    except (OSError, ValueError) as exc:
        emit({"ok": False, "error": str(exc), "path": str(output)})
        return 4

    emit(
        {
            "schema": "ios.simulator.screenshot",
            "schemaVersion": 1,
            "ok": True,
            "udid": args.udid,
            "path": str(output),
            "format": "png",
            "widthPixels": width,
            "heightPixels": height,
            "bytes": output.stat().st_size,
            "sha256": digest,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
