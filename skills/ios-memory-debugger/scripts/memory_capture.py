#!/usr/bin/env python3
"""Capture a memory graph safely, or explain exactly why it cannot be captured.

    resolve  --bundle-id ID --udid UDID   find the process, unambiguously
    probe    --pid N                      what can be captured from this target
    capture  --pid N --out DIR            capture, then validate the artifact
    validate <graph>                      is this artifact usable?

WHY THIS EXISTS

The canonical recipe

    leaks --noContent --fullStackHistory --outputGraph=<GRAPH> <PID>

FAILS on any process not launched with FULL MallocStackLogging, and the failure
is fatal -- exit 255, no artifact at all. Measured on a real Simulator app:

    default (no logging)   [fatal] Cannot save a memgraph with
                           '--fullStackHistory' because MallocStackLogging was
                           not enabled for pid 65213
    MallocStackLogging=lite [fatal] ... because it ran with MallocStackLogging
                           lite mode. Please run the process with full
                           MallocStackLogging.
    no --fullStackHistory  exit 0, 1,711,499 byte artifact

`lite` is rejected by name, so `--fullStackHistory` and
`SIMCTL_CHILD_MallocStackLogging=lite` cannot be used together. This script
probes for the flag instead of assuming it, and degrades to a structural
capture rather than losing the capture entirely.

It also handles two things a hand-run command does not:

* A PID can exist and still be uncapturable --
  "[fatal] Process exists but has not fully started -- dyld has initialized but
  libSystem has not" -- so readiness is waited for, not assumed.
* A capture that succeeds can still produce an unusable artifact, so the result
  is validated before it is reported as evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from memgraph_util import (  # noqa: E402
    ToolError, classify_artifact, died_on_signal, human_bytes,
    probe_readable, run,
)

READY_TIMEOUT = 30
CAPTURE_TIMEOUT = 900

# Fatal messages leaks emits, and what each means for the next step.
NOT_READY = re.compile(r"has not fully started|dyld has initialized", re.I)
NO_LOGGING = re.compile(r"MallocStackLogging was not enabled", re.I)
LITE_LOGGING = re.compile(r"ran with MallocStackLogging lite mode", re.I)
NO_ACCESS = re.compile(r"Unable to (get|obtain) task|not permitted|"
                       r"requires root|denied", re.I)
GONE = re.compile(r"No such process|does not exist|cannot examine", re.I)


# --------------------------------------------------------------------------
# resolve -- a first pgrep match is not resolution
# --------------------------------------------------------------------------

def resolve(bundle_id: Optional[str], udid: Optional[str],
            name: Optional[str]) -> Dict[str, Any]:
    """Find candidate host PIDs and refuse to guess between them."""
    container = None
    if bundle_id and udid:
        r = run(["xcrun", "simctl", "get_app_container", udid, bundle_id, "app"],
                timeout=60)
        if r["exit"] == 0:
            container = r["stdout"].strip()

    needle = name or (bundle_id.rsplit(".", 1)[-1] if bundle_id else None)
    if not needle:
        raise ToolError("give --bundle-id or --name")

    r = run(["ps", "-ax", "-o", "pid=,lstart=,comm="], timeout=60)
    candidates = []
    for line in r["stdout"].splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        pid_s, rest = parts
        if needle.lower() not in rest.lower():
            continue
        # lstart is 5 fields, then the command.
        bits = rest.split(None, 5)
        started = " ".join(bits[:5]) if len(bits) >= 5 else "?"
        command = bits[5] if len(bits) > 5 else rest
        try:
            pid = int(pid_s)
        except ValueError:
            continue
        candidates.append({
            "pid": pid, "started": started, "command": command,
            # A Simulator app's executable lives under the device's container.
            "simulatorDevice": (udid in command if udid else None),
            "matchesContainer": bool(container and container in command),
        })

    exact = [c for c in candidates if c["matchesContainer"]] or candidates
    return {
        "needle": needle, "bundleId": bundle_id, "udid": udid,
        "container": container,
        "candidateCount": len(candidates),
        "candidates": candidates,
        "resolved": exact[0]["pid"] if len(exact) == 1 else None,
        "ambiguous": len(exact) > 1,
        "note": (None if len(exact) == 1 else
                 "More than one process matched. Resolve it explicitly -- an "
                 "extension, a WebContent process, another Simulator or a stale "
                 "PID can all match the same name."),
    }


# --------------------------------------------------------------------------
# probe -- what can this target actually give us?
# --------------------------------------------------------------------------

def probe(pid: int, wait: int = READY_TIMEOUT) -> Dict[str, Any]:
    """Decide which capture flags this process supports, without capturing."""
    alive = run(["ps", "-p", str(pid), "-o", "pid="], timeout=30)
    if alive["exit"] != 0 or not alive["stdout"].strip():
        return {"pid": pid, "alive": False, "capturable": False,
                "detail": f"no process {pid}"}

    # `leaks --outputGraph=X` APPENDS `.memgraph` when X lacks it, so a probe
    # cannot write to /dev/null -- it would become /dev/null.memgraph. Use a
    # real scratch path and discard it.
    scratch = Path(tempfile.mkdtemp(prefix="memprobe-"))
    throwaway = scratch / "probe.memgraph"
    ready = False
    deadline = time.time() + max(0, wait)
    last = ""

    def _clean():
        for f in scratch.glob("*"):
            try:
                f.unlink()
            except OSError:
                pass

    while True:
        _clean()
        r = run(["leaks", "--noContent", f"--outputGraph={throwaway}", str(pid)],
                timeout=180)
        last = (r["stderr"] or "") + (r["stdout"] or "")
        if r["exit"] == 0:
            ready = True
            break
        if NOT_READY.search(last):
            # The process exists but libSystem has not finished initialising.
            if time.time() >= deadline:
                break
            time.sleep(0.5)
            continue
        break

    if NOT_READY.search(last) and not ready:
        return {"pid": pid, "alive": True, "capturable": False,
                "reason": "not-ready",
                "detail": ("Process exists but has not fully started. Wait "
                           "longer, or capture after the app reaches a "
                           "verified UI checkpoint.")}
    if NO_ACCESS.search(last):
        return {"pid": pid, "alive": True, "capturable": False,
                "reason": "no-access",
                "detail": "Capture was denied for this process."}
    if GONE.search(last):
        return {"pid": pid, "alive": False, "capturable": False,
                "reason": "gone", "detail": "Process exited during the probe."}
    if not ready:
        return {"pid": pid, "alive": True, "capturable": False,
                "reason": "unknown", "detail": last.strip()[:300]}

    # Structural capture works. Does full history?
    _clean()
    r = run(["leaks", "--noContent", "--fullStackHistory",
             f"--outputGraph={throwaway}", str(pid)], timeout=180)
    hist = (r["stderr"] or "") + (r["stdout"] or "")
    _clean()
    try:
        scratch.rmdir()
    except OSError:
        pass

    if r["exit"] == 0:
        logging_mode, history = "full", True
    elif LITE_LOGGING.search(hist):
        logging_mode, history = "lite", False
    elif NO_LOGGING.search(hist):
        logging_mode, history = "none", False
    else:
        logging_mode, history = "unknown", False

    return {
        "pid": pid, "alive": True, "capturable": True,
        "mallocStackLogging": logging_mode,
        "fullStackHistoryAvailable": history,
        "recommendedFlags": (["--noContent", "--fullStackHistory"] if history
                             else ["--noContent"]),
        "detail": (None if history else
                   f"MallocStackLogging is '{logging_mode}'. "
                   f"--fullStackHistory would fail fatally and produce NO "
                   f"artifact, so it is omitted. Allocation-history questions "
                   f"need a relaunch with full logging "
                   f"(SIMCTL_CHILD_MallocStackLogging=full); that destroys the "
                   f"current state, so preserve a structural capture first."),
    }


# --------------------------------------------------------------------------
# capture
# --------------------------------------------------------------------------

def capture(pid: int, out_dir: Path, label: str = "graph",
            want_history: Optional[bool] = None, content: bool = False,
            wait: int = READY_TIMEOUT) -> Dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    # leaks appends `.memgraph` when the given path lacks it, so name the
    # final path explicitly rather than checking for a file that was never
    # written under the name we asked for.
    graph = out_dir / (label if label.endswith(".memgraph") else f"{label}.memgraph")
    if graph.exists():
        raise ToolError(f"{graph} already exists; choose a new --out or --label. "
                        f"Refusing to overwrite captured evidence.")

    capability = probe(pid, wait=wait)
    if not capability.get("capturable"):
        return {"captured": False, "capability": capability,
                "detail": capability.get("detail")}

    flags = ["--noContent"] if not content else []
    history = capability["fullStackHistoryAvailable"]
    if want_history is True and not history:
        return {"captured": False, "capability": capability,
                "detail": ("--fullStackHistory was requested but this process "
                           f"ran with MallocStackLogging "
                           f"'{capability['mallocStackLogging']}'. The capture "
                           f"would fail and write nothing. Relaunch with full "
                           f"logging, or drop the history requirement.")}
    if history and want_history is not False:
        flags.append("--fullStackHistory")

    argv = ["leaks"] + flags + [f"--outputGraph={graph}", str(pid)]
    started = time.time()
    result = run(argv, timeout=CAPTURE_TIMEOUT)
    elapsed = round(time.time() - started, 3)

    record: Dict[str, Any] = {
        "captured": False,
        "argv": argv,
        "exit": result["exit"],
        "durationSeconds": elapsed,
        "graph": str(graph),
        "capability": capability,
        "stderr": (result["stderr"] or "").strip()[:600],
    }

    if result.get("timedOut") or died_on_signal(result["exit"]) or result["exit"] != 0:
        record["detail"] = ("Capture did not complete. The target's state is "
                            "uncertain; verify it before acting.")
        return record

    # A zero exit is not proof of a usable artifact.
    info = classify_artifact(graph)
    record["artifact"] = info
    if not info["readable"]:
        record["detail"] = (f"leaks exited 0 but the artifact is "
                            f"{info['status']}: {info['detail']}")
        return record

    deep = probe_readable(graph)
    record["artifact"]["probe"] = deep["probe"]
    if not deep["readable"]:
        record["detail"] = f"artifact is not readable: {deep['detail']}"
        return record

    record["captured"] = True
    record["bytes"] = info["bytes"]
    record["hasAllocationHistory"] = info.get("fullStackHistory", False)
    record["detail"] = None
    (out_dir / f"{label}.capture.json").write_text(
        json.dumps(record, indent=2) + "\n")
    return record


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _render_resolve(d: Dict[str, Any]) -> None:
    print(f"\nmatching '{d['needle']}' — {d['candidateCount']} candidate(s)")
    if d.get("container"):
        print(f"  container: {d['container']}")
    for c in d["candidates"]:
        mark = "→" if c["pid"] == d.get("resolved") else " "
        print(f"  {mark} pid {c['pid']:<7} started {c['started']}")
        print(f"      {c['command'][:96]}")
    if d["resolved"]:
        print(f"\n  resolved: {d['resolved']}")
    else:
        print(f"\n  NOT RESOLVED — {d['note']}")
    print()


def _render_probe(d: Dict[str, Any]) -> None:
    print(f"\npid {d['pid']}")
    if not d.get("capturable"):
        print(f"  capturable: no ({d.get('reason','?')})")
        print(f"  {d.get('detail','')}")
        print()
        return
    print(f"  capturable:            yes")
    print(f"  MallocStackLogging:    {d['mallocStackLogging']}")
    print(f"  allocation history:    "
          f"{'available' if d['fullStackHistoryAvailable'] else 'NOT available'}")
    print(f"  recommended flags:     {' '.join(d['recommendedFlags'])}")
    if d.get("detail"):
        print(f"\n  {d['detail']}")
    print()


def _render_capture(d: Dict[str, Any]) -> None:
    if not d["captured"]:
        print(f"\nCAPTURE FAILED")
        print(f"  {d.get('detail','')}")
        if d.get("stderr"):
            print(f"  stderr: {d['stderr'][:200]}")
        print()
        return
    a = d["artifact"]
    print(f"\ncaptured {human_bytes(d['bytes'])} in {d['durationSeconds']}s")
    print(f"  graph:   {d['graph']}")
    print(f"  format:  {a['magic']}"
          f"   allocation history: "
          f"{'yes' if d['hasAllocationHistory'] else 'no'}")
    print(f"  flags:   {' '.join(d['argv'][1:-2])}")
    if not d["hasAllocationHistory"]:
        print(f"\n  This graph answers reachability questions, not 'when was "
              f"this allocated'.")
    print()


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["resolve", "probe", "capture", "validate"])
    p.add_argument("graph", nargs="?", type=Path, help="graph (for validate)")
    p.add_argument("--pid", type=int)
    p.add_argument("--bundle-id")
    p.add_argument("--udid")
    p.add_argument("--name")
    p.add_argument("--out", type=Path, help="run directory (for capture)")
    p.add_argument("--label", default="graph")
    p.add_argument("--history", dest="history", action="store_true",
                   help="require allocation history; fail if unavailable")
    p.add_argument("--no-history", dest="history", action="store_false",
                   help="never request history even when available")
    p.add_argument("--content", action="store_true",
                   help="omit --noContent (exposes allocation contents)")
    p.add_argument("--wait", type=int, default=READY_TIMEOUT)
    p.add_argument("--json", action="store_true")
    p.set_defaults(history=None)
    args = p.parse_args()

    try:
        if args.command == "resolve":
            result, render = resolve(args.bundle_id, args.udid, args.name), _render_resolve
        elif args.command == "probe":
            if not args.pid:
                p.error("probe requires --pid")
            result, render = probe(args.pid, args.wait), _render_probe
        elif args.command == "capture":
            if not args.pid or not args.out:
                p.error("capture requires --pid and --out")
            result = capture(args.pid, args.out, args.label, args.history,
                             args.content, args.wait)
            render = _render_capture
        else:
            if not args.graph:
                p.error("validate requires a graph path")
            info = classify_artifact(args.graph)
            if info["readable"]:
                info.update(probe_readable(args.graph))
            result = info
            render = lambda d: print(
                f"\n  status: {d['status']}"
                f"{'  probe: ' + d['probe'] if 'probe' in d else ''}"
                f"\n  bytes:  {human_bytes(d.get('bytes'))}"
                f"{chr(10) + '  ' + d['detail'] if d.get('detail') else ''}\n")
    except ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        render(result)

    ok = {
        "resolve": lambda r: r.get("resolved") is not None,
        "probe": lambda r: bool(r.get("capturable")),
        "capture": lambda r: bool(r.get("captured")),
        "validate": lambda r: bool(r.get("readable")),
    }[args.command](result)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
