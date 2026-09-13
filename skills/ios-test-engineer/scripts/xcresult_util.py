#!/usr/bin/env python3
"""Shared helpers for reading Xcode result bundles.

Not a command. Imported by test_results.py, coverage_report.py and
compare_runs.py.

WHY THIS EXISTS

Each of those scripts grew its own copy of the same three things: an error
class, a subprocess wrapper, and bundle resolution. Three copies of
`resolve_bundle` had drifted to three different error messages for the same
condition, and five separate `ToolError` classes meant `except ToolError` in one
module could not catch an exception raised by another. `ios-memory-debugger`
already keeps these in `memgraph_util.py`; this mirrors that arrangement so both
skills read the same way.

The timeouts differ per operation on purpose -- see TIMEOUTS below.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

# Result-bundle schema this skill's parsers were written against. Apple
# versions the test-results schema; preserve unknown fields rather than
# failing, but record which version was verified.
SCHEMA_TESTED = "0.4.0"

# Per-operation timeouts. These are not one number because the operations are
# not one shape: reading a summary is fast, merging a matrix of bundles is not.
TIMEOUTS = {
    "read": 180,        # get/export against a single bundle
    "compare": 300,     # two bundles, more work
    "merge": 900,       # N bundles, content-addressed but still large
    "enumerate": 120,   # -enumerate-tests without running
}
DEFAULT_TIMEOUT = TIMEOUTS["read"]


class ToolError(RuntimeError):
    """Any failure to obtain evidence. Raised by every helper here.

    One class, imported everywhere, so `except ToolError` behaves the same in
    every script in this skill.
    """


def _require_xcrun() -> None:
    if not shutil.which("xcrun"):
        raise ToolError(
            "xcrun not found. This skill requires macOS with full Xcode; the "
            "standalone Command Line Tools are not sufficient.")


def run(argv: List[str], timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """Run a command as an argument vector and return the full result.

    Never through a shell: a bundle id, test identifier, class pattern or path
    can contain characters that change the meaning of a shell program.

    Unlike the raising helpers below, this returns the outcome so a caller can
    treat a non-zero status as data -- which matters because `xcodebuild` and
    `leaks` both use exit codes to report findings, not just failures.
    """
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {"argv": argv, "exit": None, "timedOut": True,
                "stdout": "", "stderr": f"timed out after {timeout}s"}
    except OSError as exc:
        return {"argv": argv, "exit": 127, "timedOut": False,
                "stdout": "", "stderr": str(exc)}
    return {"argv": argv, "exit": proc.returncode, "timedOut": False,
            "stdout": proc.stdout, "stderr": proc.stderr}


def _checked(argv: List[str], timeout: int, label: str) -> str:
    _require_xcrun()
    result = run(argv, timeout)
    if result["timedOut"]:
        raise ToolError(f"{label} timed out after {timeout}s: "
                        f"{' '.join(argv[1:4])}")
    if result["exit"] != 0:
        detail = (result["stderr"] or result["stdout"]).strip()[:400]
        raise ToolError(f"{label} failed ({result['exit']}): {detail}")
    return result["stdout"]


def xcresulttool(args: List[str], timeout: int = DEFAULT_TIMEOUT) -> str:
    """Run `xcrun xcresulttool`, raising on anything but success."""
    return _checked(["xcrun", "xcresulttool"] + args, timeout, "xcresulttool")


def xcresulttool_json(bundle: Path, *parts: str,
                      timeout: int = DEFAULT_TIMEOUT) -> Any:
    """`xcresulttool get ... --format json`, parsed.

    Note `compare` does NOT accept `--format` -- it emits JSON natively and
    rejects the flag -- so comparison callers use `xcresulttool()` directly.
    """
    out = xcresulttool(list(parts) + ["--path", str(bundle), "--format", "json"],
                       timeout=timeout)
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise ToolError(f"xcresulttool returned invalid JSON for "
                        f"{' '.join(parts)}: {exc}")


def xccov(args: List[str], timeout: int = DEFAULT_TIMEOUT) -> str:
    """Run `xcrun xccov`, raising on anything but success."""
    return _checked(["xcrun", "xccov"] + args, timeout, "xccov")


def resolve_bundle(path: Path) -> Path:
    """Validate that a path is a readable .xcresult before any reader sees it.

    An `.xcresult` is a directory, so `exists()` is not enough -- a
    watchdog-killed or crashed run leaves the directory without its Info.plist,
    and pointing a reader at that shell produces a confusing failure rather
    than a clear one.
    """
    bundle = Path(path).expanduser().resolve()
    if not bundle.exists():
        raise ToolError(f"no such bundle: {bundle}")
    if bundle.is_file():
        raise ToolError(f"{bundle} is a file; an .xcresult is a directory")
    if not (bundle / "Info.plist").exists():
        raise ToolError(
            f"not a readable .xcresult bundle (no Info.plist): {bundle}. "
            f"A run that was killed or crashed can leave the directory "
            f"without one -- that is a run failure, not a test verdict.")
    return bundle
