#!/usr/bin/env python3
"""Record one bounded xctrace bundle with owned-process watchdogs and validation."""

from __future__ import annotations

import argparse
import json
import os
import re
import selectors
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# xctrace announces "Starting recording with the ... template" before it launches or
# attaches to the target; only "Ctrl-C to stop the recording" shows that recording
# began. A Simulator recorder has been observed to announce and then never start.
START_PATTERNS = [
    re.compile(r"ctrl-c\s+to\s+stop\s+the\s+recording", re.IGNORECASE),
    re.compile(r"recording\s+started", re.IGNORECASE),
]
ANNOUNCE_PATTERN = re.compile(r"starting\s+recording", re.IGNORECASE)
FATAL_PATTERNS = [
    re.compile(r"failed\s+to\s+(start|attach|launch|record)", re.IGNORECASE),
    re.compile(r"lost\s+connection", re.IGNORECASE),
    re.compile(r"permission\s+denied", re.IGNORECASE),
]
# Observed with Xcode 27.0 beta (27A5194q): xctrace exits 54 after it terminates a
# --launch target that is still running at the time limit, although it saved a
# complete trace. Accept that code only in exactly that situation.
LAUNCH_TIME_LIMIT_EXIT = 54
TIME_LIMIT_PATTERN = re.compile(r"reached\s+specified\s+time\s+limit", re.IGNORECASE)
SAVED_PATTERN = re.compile(r"output\s+file\s+saved", re.IGNORECASE)
FAILED_PATTERN = re.compile(r"recording\s+failed", re.IGNORECASE)

# Time allowed after the time limit for xctrace to finish saving. Observed on an M1 Mac with
# Xcode 27 beta: saving 4 s of System Trace took about 315 s, File Activity about 180 s and
# Blank + Metal GPU Counters about 115 s; every other template saved within about 70 s.
# Each cost class maps to (minimum seconds, seconds per recorded second).
DEFAULT_COMPLETION_GRACE = 120.0
SAVE_ALLOWANCE = {
    "System Trace": (600.0, 120.0),
    "File Activity": (360.0, 75.0),
    "Metal GPU Counters": (300.0, 60.0),
    "SwiftUI": (180.0, 20.0),
}
# Instruments assumed to carry the save cost of the template they come from.
INSTRUMENT_COST_CLASS = {
    "Thread State Trace": "System Trace",
    "System Call Trace": "System Trace",
    "Virtual Memory Trace": "System Trace",
    "Filesystem Activity": "File Activity",
    "Filesystem Suggestions": "File Activity",
    "Disk I/O Latency": "File Activity",
    "Metal GPU Counters": "Metal GPU Counters",
    "SwiftUI": "SwiftUI",
}
KERNEL_EVENT_CLASSES = {"System Trace", "File Activity"}
KERNEL_EVENT_WINDOW_SECONDS = 10.0
PROFILE_SCHEMAS = ("time-profile", "cpu-profile")


def is_start_evidence(line: str) -> bool:
    return any(pattern.search(line) for pattern in START_PATTERNS)


def recorder_exit_accepted(exit_code: int | None, launched: bool, log_text: str) -> bool:
    if exit_code == 0:
        return True
    return (
        launched
        and exit_code == LAUNCH_TIME_LIMIT_EXIT
        and TIME_LIMIT_PATTERN.search(log_text) is not None
        and SAVED_PATTERN.search(log_text) is not None
        and FAILED_PATTERN.search(log_text) is None
    )


def cost_classes(template: str, instruments: list[str]) -> set[str]:
    classes = {template} & set(SAVE_ALLOWANCE)
    classes.update(INSTRUMENT_COST_CLASS[name] for name in instruments if name in INSTRUMENT_COST_CLASS)
    return classes


def default_completion_grace(template: str, instruments: list[str], duration_seconds: float) -> float:
    """Save allowance for a template and instrument set, scaled by the recording length."""
    grace = DEFAULT_COMPLETION_GRACE
    for name in cost_classes(template, instruments):
        floor, per_second = SAVE_ALLOWANCE[name]
        grace = max(grace, floor, per_second * duration_seconds)
    return grace


def parse_expect_rows(value: str) -> tuple[str, int]:
    """SCHEMA or SCHEMA:MIN, where MIN defaults to 1."""
    schema, separator, minimum = value.rpartition(":")
    if separator and schema and minimum.isdigit():
        return schema, int(minimum)
    return value, 1


def launch_activity(samples: int | None, duration_seconds: float, minimum: int) -> dict[str, Any]:
    """Judge from its CPU sample count whether a target actually ran during the recording."""
    if samples is None:
        return {"samples": None, "minimum": minimum, "verdict": "unknown"}
    return {
        "samples": samples,
        "minimum": minimum,
        "samples_per_second": round(samples / duration_seconds, 2) if duration_seconds else None,
        "verdict": "active" if samples >= minimum else "inactive",
    }


def recorder_errors(log_text: str) -> list[str]:
    """Error lines xctrace printed, such as instruments it rejected for this target."""
    return [line.strip() for line in log_text.splitlines() if "[Error]" in line][:20]


def split_trailing_args(argv: list[str]) -> tuple[list[str], list[str]]:
    """Split this script's own options from launch arguments written after a standalone `--`.

    argparse reads a value that starts with a dash as an option, so `--launch-arg -XCTest` fails. Arguments
    after `--` avoid that entirely and match how xctrace itself passes a command line to a launched target.
    """
    if "--" in argv:
        index = argv.index("--")
        return argv[:index], argv[index + 1:]
    return argv, []


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_duration(value: str) -> float:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(ms|s|m|h)\s*", value)
    if not match:
        raise argparse.ArgumentTypeError("duration must look like 500ms, 8s, 2m, or 1h")
    number = float(match.group(1))
    factor = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}[match.group(2)]
    return number * factor


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_toc(path: Path) -> dict[str, Any]:
    schemas: set[str] = set()
    runs: list[dict[str, str]] = []
    tables = 0
    for _, elem in ET.iterparse(path, events=("end",)):
        schema = elem.attrib.get("schema")
        if schema:
            schemas.add(schema)
        if local_name(elem.tag) == "table":
            tables += 1
        if local_name(elem.tag) == "run":
            run = {key: value for key, value in elem.attrib.items() if key in {"number", "name"}}
            if run and run not in runs:
                runs.append(run)
        elem.clear()
    return {"schemas": sorted(schemas), "runs": runs, "table_count": tables}


def count_table_rows(trace: Path, schema: str, timeout: float) -> int | None:
    """Rows in one schema table of run 1, or None when the table cannot be exported."""
    with tempfile.TemporaryDirectory() as scratch:
        destination = Path(scratch) / "table.xml"
        argv = [
            "xcrun", "xctrace", "export", "--input", str(trace),
            "--xpath", f'/trace-toc/run[@number="1"]/data/table[@schema="{schema}"]',
            "--output", str(destination),
        ]
        try:
            completed = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                       timeout=timeout, check=False)
        except (subprocess.TimeoutExpired, OSError):
            return None
        if completed.returncode != 0 or not destination.exists():
            return None
        count = 0
        try:
            for _, elem in ET.iterparse(destination, events=("end",)):
                if local_name(elem.tag) == "row":
                    count += 1
                elem.clear()
        except ET.ParseError:
            return None
        return count


def terminate_owned_group(process: subprocess.Popen[str], grace: float = 5.0) -> str:
    if process.poll() is not None:
        return "already-exited"
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return "already-exited"
    try:
        process.wait(timeout=grace)
        return "terminated"
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=grace)
        return "killed"


def safe_command_text(argv: list[str]) -> str:
    redacted: list[str] = []
    redact_next_env = False
    for item in argv:
        if redact_next_env:
            key = item.split("=", 1)[0]
            redacted.append(f"{key}=<redacted>")
            redact_next_env = False
        else:
            redacted.append(item)
            if item == "--env":
                redact_next_env = True
    return shlex.join(redacted)


def bounded_text(value: str, limit: int = 4000) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    return value[:limit] + "\n…<truncated>", True


def trace_file_summary(trace: Path) -> dict[str, Any]:
    if not trace.exists():
        return {"exists": False, "files": 0, "bytes": 0, "non_run_issue_files": 0}
    files = [path for path in trace.rglob("*") if path.is_file()] if trace.is_dir() else [trace]
    non_run_issue = [
        path
        for path in files
        if "RunIssues.storedata" not in path.as_posix() and path.stat().st_size > 0
    ]
    return {
        "exists": True,
        "files": len(files),
        "bytes": sum(path.stat().st_size for path in files),
        "non_run_issue_files": len(non_run_issue),
    }


def build_command(args: argparse.Namespace) -> list[str]:
    argv = ["xcrun", "xctrace", "record", "--template", args.template]
    for instrument in args.instrument:
        argv.extend(["--instrument", instrument])
    if args.device:
        argv.extend(["--device", args.device])
    argv.extend(["--time-limit", args.time_limit])
    if args.window:
        argv.extend(["--window", args.window])
    if args.run_name:
        argv.extend(["--run-name", args.run_name])
    if args.recording_options:
        argv.extend(["--recording-options", str(args.recording_options.expanduser().resolve())])
    for env_entry in args.env:
        if "=" not in env_entry or env_entry.startswith("="):
            raise RuntimeError(f"invalid --env value {env_entry!r}; expected KEY=VALUE")
        argv.extend(["--env", env_entry])
    if args.no_prompt:
        argv.append("--no-prompt")
    argv.extend(["--output", str(args.output.expanduser().resolve())])
    if args.launch is not None:
        argv.extend(["--launch", "--", args.launch, *args.launch_arg])
    elif args.attach is not None:
        argv.extend(["--attach", args.attach])
    else:
        argv.append("--all-processes")
    return argv


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True)
    parser.add_argument("--instrument", action="append", default=[])
    parser.add_argument("--device")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--launch", metavar="BUNDLE_ID_OR_PATH")
    mode.add_argument("--attach", metavar="PID_OR_NAME")
    mode.add_argument("--all-processes", action="store_true")
    parser.add_argument("--launch-arg", action="append", default=[],
                        help="Argument for the launched target; for values starting with a dash use --launch-arg=-flag, "
                             "or write the arguments after a standalone -- instead")
    parser.add_argument("--env", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--time-limit", default="10s")
    parser.add_argument("--window")
    parser.add_argument("--run-name")
    parser.add_argument("--recording-options", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--toc", type=Path)
    parser.add_argument("--expect-schema", action="append", default=[])
    parser.add_argument("--expect-rows", action="append", default=[], metavar="SCHEMA[:MIN]",
                        help="Require at least MIN rows (default 1) in this table; implies --expect-schema")
    parser.add_argument("--min-launch-samples", type=int, default=20,
                        help="With --launch, require this many CPU samples when the trace has a profile table; 0 disables")
    parser.add_argument("--start-timeout", type=float, default=45.0)
    parser.add_argument("--completion-grace", type=float,
                        help="Seconds allowed after the time limit for saving; default depends on the template")
    parser.add_argument("--export-timeout", type=float, default=300.0)
    parser.add_argument("--no-prompt", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    own_argv, trailing_args = split_trailing_args(sys.argv[1:])
    args = parser.parse_args(own_argv)
    args.launch_arg = [*args.launch_arg, *trailing_args]

    if args.launch_arg and args.launch is None:
        parser.error("--launch-arg, and arguments after --, require --launch")
    try:
        duration_seconds = parse_duration(args.time_limit)
        if args.window:
            parse_duration(args.window)
        command = build_command(args)
    except (RuntimeError, argparse.ArgumentTypeError) as exc:
        parser.error(str(exc))

    output = args.output.expanduser().resolve()
    if output.suffix != ".trace":
        parser.error("--output must end in .trace so validation targets one known bundle")
    manifest_path = (
        args.manifest.expanduser().resolve()
        if args.manifest
        else output.with_suffix(output.suffix + ".manifest.json")
    )
    log_path = args.log.expanduser().resolve() if args.log else output.with_suffix(output.suffix + ".log")
    toc_path = args.toc.expanduser().resolve() if args.toc else output.with_suffix(output.suffix + ".toc.xml")

    expect_rows = [parse_expect_rows(value) for value in args.expect_rows]
    recommended_grace = default_completion_grace(args.template, args.instrument, duration_seconds)
    grace = args.completion_grace if args.completion_grace is not None else recommended_grace
    grace_source = "user" if args.completion_grace is not None else (
        "template" if recommended_grace > DEFAULT_COMPLETION_GRACE else "default"
    )
    warnings: list[str] = []
    heavy = cost_classes(args.template, args.instrument) & KERNEL_EVENT_CLASSES
    if heavy and duration_seconds > KERNEL_EVENT_WINDOW_SECONDS:
        warnings.append(
            f"{', '.join(sorted(heavy))} records every kernel event: in testing, 4 s of System Trace took about 5 minutes "
            "to save and 4 s of File Activity about 3 minutes. Keep the time limit to a few seconds around the action, "
            "or use --window."
        )
    if args.completion_grace is not None and args.completion_grace < recommended_grace:
        warnings.append(
            f"--completion-grace {args.completion_grace:g}s is below the {recommended_grace:g}s this template needed "
            "to save in testing; the watchdog may stop xctrace while it is still saving."
        )

    dry_manifest = {
        "schema_version": "ios.xctrace.record.v2",
        "status": "dry-run",
        "command": safe_command_text(command),
        "output": str(output),
        "manifest": str(manifest_path),
        "log": str(log_path),
        "toc": str(toc_path),
        "expected_schemas": sorted(set(args.expect_schema) | {schema for schema, _ in expect_rows}),
        "expected_rows": {schema: minimum for schema, minimum in expect_rows},
        "min_launch_samples": args.min_launch_samples,
        "duration_seconds": duration_seconds,
        "start_timeout_seconds": args.start_timeout,
        "completion_grace_seconds": grace,
        "completion_grace_source": grace_source,
        "environment_keys": sorted(entry.split("=", 1)[0] for entry in args.env),
        "warnings": warnings,
    }
    if args.dry_run:
        print(json.dumps(dry_manifest, indent=2, sort_keys=True))
        return 0

    conflicts = [path for path in (output, manifest_path, log_path, toc_path) if path.exists()]
    if conflicts:
        print(
            json.dumps(
                {"status": "error", "error": "refusing to overwrite", "paths": [str(path) for path in conflicts]},
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    toc_path.parent.mkdir(parents=True, exist_ok=True)

    started_at = time.monotonic()
    started_wall = utc_now()
    output_lines: list[str] = []
    start_evidence_at: float | None = None
    termination_reason: str | None = None
    owned_process_action: str | None = None

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        failure = {**dry_manifest, "status": "infrastructure-failure", "error": str(exc)}
        write_json(manifest_path, failure)
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 2

    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    selector.register(process.stdout, selectors.EVENT_READ)
    hard_deadline = started_at + max(args.start_timeout, 0.0) + duration_seconds + grace

    while True:
        now = time.monotonic()
        events = selector.select(timeout=0.25)
        for key, _ in events:
            line = key.fileobj.readline()
            if line:
                output_lines.append(line)
                if start_evidence_at is None and is_start_evidence(line):
                    start_evidence_at = now
                if any(pattern.search(line) for pattern in FATAL_PATTERNS):
                    termination_reason = "fatal-recorder-output"
            elif process.poll() is not None:
                try:
                    selector.unregister(key.fileobj)
                except Exception:
                    pass

        if termination_reason == "fatal-recorder-output" and process.poll() is None:
            owned_process_action = terminate_owned_group(process)

        if process.poll() is not None:
            remaining = process.stdout.read()
            if remaining:
                output_lines.append(remaining)
            break

        if args.start_timeout > 0 and start_evidence_at is None and now - started_at > args.start_timeout:
            termination_reason = "start-timeout"
            owned_process_action = terminate_owned_group(process)
            break

        completion_deadline = (
            start_evidence_at + duration_seconds + grace
            if start_evidence_at is not None
            else hard_deadline
        )
        if now > completion_deadline:
            termination_reason = "completion-timeout"
            owned_process_action = terminate_owned_group(process)
            break

    selector.close()
    exit_code = process.poll()
    finished_wall = utc_now()
    log_text = "".join(output_lines)
    log_path.write_text(log_text, encoding="utf-8")

    trace_summary = trace_file_summary(output)
    toc_result: dict[str, Any] = {"exported": False, "schemas": [], "runs": [], "table_count": 0}
    if trace_summary["exists"]:
        toc_command = [
            "xcrun",
            "xctrace",
            "export",
            "--input",
            str(output),
            "--toc",
            "--output",
            str(toc_path),
        ]
        try:
            completed = subprocess.run(
                toc_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=120,
                check=False,
            )
            toc_result["exit_code"] = completed.returncode
            toc_output, toc_output_truncated = bounded_text(completed.stdout.strip())
            toc_result["command_output"] = toc_output
            toc_result["command_output_truncated"] = toc_output_truncated
            if completed.returncode == 0 and toc_path.exists() and toc_path.stat().st_size > 0:
                toc_result.update(parse_toc(toc_path))
                toc_result["exported"] = True
        except (subprocess.TimeoutExpired, ET.ParseError, OSError) as exc:
            toc_result["error"] = str(exc)

    expected = set(dry_manifest["expected_schemas"])
    found = set(toc_result.get("schemas", []))
    missing = sorted(expected - found)

    # Row gates: a trace can finalize with every expected table present yet hold no evidence,
    # for example a launched target that never ran.
    row_counts: dict[str, int | None] = {}
    rows_below_minimum: list[dict[str, Any]] = []
    target_activity: dict[str, Any] | None = None
    if toc_result.get("exported"):
        for schema, minimum in expect_rows:
            if schema not in found:
                continue
            rows = count_table_rows(output, schema, args.export_timeout)
            row_counts[schema] = rows
            if rows is None or rows < minimum:
                rows_below_minimum.append({"schema": schema, "rows": rows, "minimum": minimum})
        profile_schema = next((schema for schema in PROFILE_SCHEMAS if schema in found), None)
        targeted = args.launch is not None or args.attach is not None
        if profile_schema and targeted and args.min_launch_samples > 0:
            if profile_schema not in row_counts:
                row_counts[profile_schema] = count_table_rows(output, profile_schema, args.export_timeout)
            target_activity = {
                "schema": profile_schema,
                "mode": "launch" if args.launch is not None else "attach",
                **launch_activity(row_counts[profile_schema], duration_seconds, args.min_launch_samples),
            }
            if target_activity["mode"] == "attach" and target_activity["verdict"] == "inactive":
                warnings.append(
                    f"The attached target recorded {target_activity['samples']} CPU samples; it may have been idle. "
                    "That is valid for an idle target, but it is not CPU evidence."
                )
    target_inactive = (
        target_activity is not None and target_activity["mode"] == "launch" and target_activity["verdict"] == "inactive"
    )

    exit_accepted = recorder_exit_accepted(exit_code, args.launch is not None, log_text)
    valid = (
        exit_accepted
        and termination_reason is None
        and trace_summary["exists"]
        and trace_summary["non_run_issue_files"] > 0
        and toc_result.get("exported") is True
        and not missing
        and not rows_below_minimum
        and not target_inactive
    )
    if valid:
        status = "valid"
    elif termination_reason:
        status = termination_reason
    elif not trace_summary["exists"]:
        status = "missing-trace"
    elif trace_summary["non_run_issue_files"] == 0:
        status = "partial-or-empty-trace"
    elif not exit_accepted:
        status = "recorder-failed"
    elif not toc_result.get("exported"):
        status = "toc-export-failed"
    elif missing:
        status = "expected-schema-missing"
    elif rows_below_minimum:
        status = "expected-rows-missing"
    elif target_inactive:
        status = "target-inactive"
    else:
        status = "recorder-failed"
    if target_inactive:
        warnings.append(
            f"The launched target produced {target_activity['samples']} CPU samples in {duration_seconds:g} s, so it "
            "probably never ran. On Xcode 27 beta 27A5194q, launch-owned App Launch and Time Profiler recordings sometimes "
            "left the target asleep; the Blank template with the same instruments launched normally in testing. Re-record, "
            "or pass --min-launch-samples 0 if the target is expected to idle."
        )

    manifest = {
        **dry_manifest,
        "status": status,
        "valid": valid,
        "started_at": started_wall,
        "finished_at": finished_wall,
        "wall_seconds": round(time.monotonic() - started_at, 3),
        "recorder_announced": ANNOUNCE_PATTERN.search(log_text) is not None,
        "recording_start_evidence": start_evidence_at is not None,
        "exit_code": exit_code,
        "exit_code_accepted": exit_accepted,
        "exit_code_note": (
            "launched target still running at the time limit; xctrace terminated it and saved the trace"
            if exit_accepted and exit_code == LAUNCH_TIME_LIMIT_EXIT
            else None
        ),
        "recorder_errors": recorder_errors(log_text),
        "termination_reason": termination_reason,
        "owned_process_action": owned_process_action,
        "trace_summary": trace_summary,
        "toc_result": toc_result,
        "missing_expected_schemas": missing,
        "row_counts": row_counts,
        "rows_below_minimum": rows_below_minimum,
        "target_activity": target_activity,
        "warnings": warnings,
    }
    write_json(manifest_path, manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if valid else 3


if __name__ == "__main__":
    sys.exit(main())
