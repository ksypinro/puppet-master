#!/usr/bin/env python3
"""Shared helpers for memory-graph capture and query.

Not a command. Imported by memory_capture.py and memgraph_query.py.

Two things live here because getting them wrong is how a memory investigation
reports something false:

1. `classify_artifact` inspects a file BEFORE any Apple reader touches it.
   Measured on this toolchain, the readers fail in ways that are hard to tell
   apart afterwards:

       empty file      exit 255  "data couldn't be read ... isn't in the correct format"
       non-memgraph    exit 255  "data couldn't be read ... isn't in the correct format"   <- identical
       truncated       exit 134  uncaught NSRangeException -- a SIGABRT, not an error
       no permission   exit 255  "couldn't be opened because you don't have permission"
       missing         exit 255  "couldn't be opened because there is no such file"
       directory       exit 255  "couldn't be opened."

   Empty and malformed are indistinguishable from the reader alone, and
   truncation crashes rather than erroring. A stat first makes all six distinct.

2. `LEAK_FINDING_MODES` records which `leaks` invocations put the finding in the
   exit status. Measured on one graph with four leaks:

       leaks / --fullStacks / --groupByType      exit 1
       --referenceTree / --autoreleasePools      exit 0
       --debug=...                               exit 0

   Inferring "exit 0 means clean" is right for three modes and wrong for three
   others, on identical evidence.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_TIMEOUT = 300

# Both are valid graphs produced by `leaks --outputGraph` on this toolchain.
# `MEMGRAPH` appears when --fullStackHistory was used; a capture without it
# writes a bare binary plist. A validator that demands the documented
# `MEMGRAPH` magic rejects every ordinary Simulator capture.
GRAPH_MAGICS = (b"MEMGRAPH", b"bplist00")

# Smallest artifact worth handing to a reader. A truncated graph aborts the
# reader with SIGABRT, so the cheap size floor is a real guard, not a nicety.
MIN_GRAPH_BYTES = 4096

# leaks invocations whose exit status encodes "leaks were found".
LEAK_FINDING_MODES = {
    "": True,                  # plain `leaks <graph>`
    "--fullStacks": True,
    "--groupByType": True,
    "--referenceTree": False,
    "--autoreleasePools": False,
    "--debug": False,
    "--trace": False,
    "--traceTree": False,
    "--diffFrom": True,
}

# The shell reports a signal death as 128+signum (SIGABRT -> 134), but Python's
# subprocess reports it as a NEGATIVE return code (-6). Both must be recognised
# or a truncated graph is misfiled as an ordinary rejection.
SIGABRT_EXIT = 134
SIGABRT_NEGATIVE = -6


def died_on_signal(status: Optional[int]) -> bool:
    """True when the child was killed by a signal rather than exiting.

    Python's subprocess reports a signal death as a negative return code, which
    is unambiguous. The shell's 128+signum convention is also accepted, but only
    within the real signal range (1-31 -> 129-159): `leaks` uses 255 for an
    ordinary read failure, and treating that as a crash would misfile every
    missing or malformed graph as corruption.
    """
    if status is None:
        return False
    if status < 0:
        return True
    return 128 < status <= 128 + 31


class ToolError(RuntimeError):
    pass


def run(argv: List[str], timeout: int = DEFAULT_TIMEOUT,
        cwd: Optional[str] = None) -> Dict[str, Any]:
    """Run a command as an argument vector. Never through a shell.

    A bundle id, class pattern, address or path can contain characters that
    change the meaning of a shell program; passing a vector removes the
    question entirely.
    """
    if not shutil.which(argv[0]) and not argv[0].startswith("/"):
        raise ToolError(f"{argv[0]} not found on PATH")
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, check=False, cwd=cwd)
    except subprocess.TimeoutExpired:
        return {"argv": argv, "exit": None, "timedOut": True,
                "stdout": "", "stderr": f"timed out after {timeout}s"}
    except OSError as exc:
        return {"argv": argv, "exit": 127, "timedOut": False,
                "stdout": "", "stderr": str(exc)}
    return {"argv": argv, "exit": proc.returncode, "timedOut": False,
            "stdout": proc.stdout, "stderr": proc.stderr}


def classify_artifact(path: Path) -> Dict[str, Any]:
    """Decide whether a file is safe to hand to an Apple reader, and why not.

    Returns a `status` that is always one of:
      ok | missing | not-a-file | no-permission | empty | too-small |
      unknown-format
    """
    p = Path(path).expanduser()

    if not p.exists():
        return {"status": "missing", "readable": False, "bytes": None,
                "detail": f"{p} does not exist"}
    if p.is_dir():
        return {"status": "not-a-file", "readable": False, "bytes": None,
                "detail": f"{p} is a directory, not a graph"}
    if not p.is_file():
        return {"status": "not-a-file", "readable": False, "bytes": None,
                "detail": f"{p} is not a regular file"}
    if not os.access(p, os.R_OK):
        return {"status": "no-permission", "readable": False, "bytes": None,
                "detail": f"{p} exists but is not readable by this user"}

    size = p.stat().st_size
    if size == 0:
        return {"status": "empty", "readable": False, "bytes": 0,
                "detail": (f"{p} is zero bytes. A reader would report "
                           f"'isn't in the correct format', which is the same "
                           f"message it gives for a corrupt file.")}

    try:
        head = p.open("rb").read(8)
    except OSError as exc:
        return {"status": "no-permission", "readable": False, "bytes": size,
                "detail": str(exc)}

    magic = next((m for m in GRAPH_MAGICS if head.startswith(m)), None)
    if magic is None:
        return {"status": "unknown-format", "readable": False, "bytes": size,
                "magic": head.hex(),
                "detail": (f"{p} does not begin with a known graph signature "
                           f"({' or '.join(m.decode() for m in GRAPH_MAGICS)}). "
                           f"Treat as not a memory graph.")}

    if size < MIN_GRAPH_BYTES:
        return {"status": "too-small", "readable": False, "bytes": size,
                "magic": magic.decode(),
                "detail": (f"{p} has a valid signature but is only {size} bytes. "
                           f"A truncated graph aborts the Apple readers with "
                           f"SIGABRT (exit {SIGABRT_EXIT}) rather than failing "
                           f"cleanly, so it is rejected here instead.")}

    return {
        "status": "ok", "readable": True, "bytes": size,
        "magic": magic.decode(),
        # Recorded, not required: it tells the caller whether allocation history
        # is likely present, which decides what questions the graph can answer.
        "fullStackHistory": magic == b"MEMGRAPH",
        "detail": None,
    }


def probe_readable(path: Path, timeout: int = 120) -> Dict[str, Any]:
    """Confirm an Apple reader can actually open the graph.

    `classify_artifact` is a static check and cannot detect truncation past the
    size floor: a graph cut at 200 KB still carries a valid signature and still
    aborts every reader. The only honest test is to try the cheapest reader and
    classify how it fails.

    SIGABRT (exit 134) means a corrupt or truncated artifact. It is NOT a
    transient fault and must never be retried.
    """
    result = run(["vmmap", "-summary", str(path)], timeout=timeout)

    if result.get("timedOut"):
        return {"probe": "timed-out", "readable": False, "exit": None,
                "detail": f"vmmap did not return within {timeout}s"}
    if died_on_signal(result["exit"]):
        return {"probe": "aborted", "readable": False, "exit": result["exit"],
                "detail": ("The reader aborted (SIGABRT). The graph is "
                           "truncated or corrupt. Do not retry -- re-capture."),
                "stderr": (result["stderr"] or "")[:300]}
    if result["exit"] != 0:
        return {"probe": "rejected", "readable": False, "exit": result["exit"],
                "detail": (result["stderr"] or result["stdout"] or "").strip()[:300]}
    return {"probe": "ok", "readable": True, "exit": 0, "detail": None}


def require_graph(path: Path, deep: bool = True) -> Dict[str, Any]:
    """classify_artifact, raising on anything a reader should not be given.

    With `deep`, also probes an actual reader, which is the only way to catch a
    large truncated graph before it aborts the real query.
    """
    info = classify_artifact(path)
    if not info["readable"]:
        raise ToolError(f"{info['status']}: {info['detail']}")
    if deep:
        probe = probe_readable(path)
        info["probe"] = probe["probe"]
        if not probe["readable"]:
            raise ToolError(f"{probe['probe']}: {probe['detail']}")
    return info


def leaks_mode_of(args: List[str]) -> str:
    """Which LEAK_FINDING_MODES key an argument list corresponds to."""
    for a in args:
        head = a.split("=", 1)[0]
        if head in LEAK_FINDING_MODES and head:
            return head
    return ""


def exit_carries_finding(args: List[str]) -> bool:
    """True when this leaks invocation encodes the finding in its exit status."""
    return LEAK_FINDING_MODES.get(leaks_mode_of(args), False)


def interpret_leaks(result: Dict[str, Any], args: List[str]) -> Dict[str, Any]:
    """Separate 'the command worked' from 'leaks were found'.

    These are different facts, and for half of leaks' modes the exit status
    says nothing at all about the second one.
    """
    status, out = result["exit"], result["stdout"]
    mode = leaks_mode_of(args)
    carries = exit_carries_finding(args)

    summary = None
    count = total = None
    for line in out.splitlines():
        if " leaks for " in line and "total leaked bytes" in line:
            summary = line.strip()
            parts = line.split()
            try:
                count = int(parts[parts.index("leaks") - 1])
                total = int(parts[parts.index("total") - 1])
            except (ValueError, IndexError):
                pass
            break

    if result.get("timedOut"):
        operation = "timed-out"
    elif died_on_signal(status):
        operation = "crashed"
    elif status in (0, 1):
        operation = "ok"
    else:
        operation = "failed"

    if operation != "ok":
        finding = "unknown"
    elif summary is not None:
        finding = "leaks-found" if (count or 0) > 0 else "no-leaks-detected"
    elif carries:
        finding = "leaks-found" if status == 1 else "no-leaks-detected"
    else:
        # This mode's exit status says nothing about leaks and no summary line
        # was printed. Reporting "clean" here would be an invention.
        finding = "unknown"

    return {
        "operation": operation,
        "exit": status,
        "mode": mode or "(plain)",
        "exitCarriesFinding": carries,
        "finding": finding,
        "leakCount": count,
        "leakedBytes": total,
        "summaryLine": summary,
        "stderr": (result["stderr"] or "").strip()[:600],
        "note": (None if carries else
                 f"`leaks {mode}` returns 0 whether or not leaks exist; this "
                 f"verdict comes from the summary line, not the exit status."),
    }


def human_bytes(n: Optional[int]) -> str:
    if n is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024.0
    return str(n)
