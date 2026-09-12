#!/usr/bin/env python3
"""Bounded xctrace export, TOC inventory (tables and track details), and generic XML preview helpers."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SENSITIVE_PATTERNS = [
    (re.compile(r"(?i)(authorization|cookie|token|secret|password)(\s*[:=]\s*)\S+"), r"\1\2<redacted>"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer <redacted>"),
    (re.compile(r"/Users/[^/\s]+"), "/Users/<redacted>"),
]
# Largest HAR file whose entries are counted; bigger files are reported without a count.
HAR_ENTRY_COUNT_LIMIT = 64 * 1024 * 1024
EMPTY_SELECTION_WARNING = (
    "The selection exported 0 rows: this trace recorded nothing for it. That is not proof the activity did not happen; "
    "see the instrument conditions in references/instrument-selection.md."
)


def run(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"command timed out after {timeout}s") from exc


def local(path: Path) -> str:
    return path.expanduser().resolve().as_posix()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def redact_text(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    for pattern, replacement in SENSITIVE_PATTERNS:
        compact = pattern.sub(replacement, compact)
    return compact[:limit] + ("…" if len(compact) > limit else "")


def bounded_text(value: str, limit: int = 4000) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    return value[:limit] + "\n…<truncated>", True


def summarize_toc(path: Path) -> dict[str, Any]:
    """Schemas, runs, external formats, and track details (Allocations, Leaks, VM Tracker...) in a TOC."""
    schemas: set[str] = set()
    runs: list[dict[str, Any]] = []
    external_formats: list[dict[str, str]] = []
    tracks: list[dict[str, Any]] = []
    details: list[dict[str, str]] = []
    table_count = 0
    current_run: str | None = None
    in_track = False
    try:
        for event, elem in ET.iterparse(path, events=("start", "end")):
            tag = local_name(elem.tag)
            if event == "start":
                if tag == "run":
                    current_run = elem.attrib.get("number")
                elif tag == "track":
                    in_track, details = True, []
                continue
            schema = elem.attrib.get("schema")
            if schema:
                schemas.add(schema)
            if tag == "table":
                table_count += 1
            elif tag == "external-format":
                external_formats.append(dict(elem.attrib))
            elif tag == "detail" and in_track:
                details.append({key: value for key, value in elem.attrib.items() if key in {"name", "kind"}})
            elif tag == "track":
                tracks.append({"run": current_run, "track": elem.attrib.get("name"), "details": details})
                in_track = False
            elif tag == "run":
                item = {key: value for key, value in elem.attrib.items() if key in {"number", "name"}}
                if item and item not in runs:
                    runs.append(item)
            elem.clear()
    except ET.ParseError as exc:
        raise RuntimeError(f"invalid TOC XML: {exc}") from exc
    return {
        "toc": str(path.resolve()),
        "schemas": sorted(schemas),
        "runs": runs,
        "table_count": table_count,
        "tracks": tracks,
        "external_formats": external_formats,
    }


def toc_external_formats(path: Path) -> list[dict[str, str]]:
    """External formats (such as HAR) that a trace's TOC says can be exported."""
    return summarize_toc(path)["external_formats"]


def xpath_literal(value: str) -> str:
    if '"' not in value:
        return f'"{value}"'
    if "'" not in value:
        return f"'{value}'"
    raise RuntimeError(f"name contains both quote characters and cannot be selected by name: {value!r}")


def selection_xpath(xpath: str | None, schema: str | None, track: str | None, detail: str | None, run_number: int) -> str:
    """XPath for an explicit selection, a schema table, or a track detail."""
    if xpath:
        return xpath
    if schema:
        return f'/trace-toc/run[@number="{run_number}"]/data/table[@schema={xpath_literal(schema)}]'
    if track and detail:
        return (
            f'/trace-toc/run[@number="{run_number}"]/tracks/track[@name={xpath_literal(track)}]'
            f"/details/detail[@name={xpath_literal(detail)}]"
        )
    raise RuntimeError("select a table with --xpath, --schema, or --track together with --detail")


def check_selection(inventory: dict[str, Any], schema: str | None, track: str | None, detail: str | None, run_number: int) -> None:
    """Refuse a named selection the TOC does not list, and say what it does list."""
    if schema and schema not in inventory["schemas"]:
        listed = ", ".join(inventory["schemas"][:20])
        raise RuntimeError(f"the TOC has no table with schema {schema!r}; it lists {len(inventory['schemas'])}: {listed}")
    if track:
        available = [
            (item["track"], entry.get("name"))
            for item in inventory["tracks"]
            if item.get("run") in (None, str(run_number))
            for entry in item["details"]
        ]
        if (track, detail) not in available:
            listed = "; ".join(f"{name} / {entry}" for name, entry in available) or "none"
            raise RuntimeError(f"the TOC has no track detail {track!r} / {detail!r} in run {run_number}; available: {listed}")


def count_rows(path: Path) -> int:
    """Stream an XML export and count its <row> elements."""
    count = 0
    try:
        for _, elem in ET.iterparse(path, events=("end",)):
            if local_name(elem.tag) == "row":
                count += 1
            elem.clear()
    except ET.ParseError as exc:
        raise RuntimeError(f"invalid XML export: {exc}") from exc
    return count


def window_effect(bounded_rows: int, unbounded_rows: int) -> str:
    """Classify whether a time-bounded export actually returned fewer rows."""
    if unbounded_rows == 0:
        return "unknown-empty-table"
    if bounded_rows < unbounded_rows:
        return "applied"
    return "no-change" if bounded_rows == unbounded_rows else "inconsistent"


def ensure_output(path: Path, force: bool) -> Path:
    output = path.expanduser().resolve()
    if output.exists() and not force:
        raise RuntimeError(f"output already exists: {output}; pass --force to replace it")
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def export_toc_to(trace: Path, destination: Path, timeout: float) -> None:
    completed = run(["xcrun", "xctrace", "export", "--input", str(trace), "--toc", "--output", str(destination)], timeout)
    if completed.returncode != 0 or not destination.exists():
        raise RuntimeError(f"could not export the TOC ({completed.returncode}): {completed.stdout.strip()}")


def verify_window(args: argparse.Namespace, trace: Path, xpath: str, bounded: Path, window: list[str]) -> dict[str, Any]:
    """Compare a time-bounded export with an unbounded one; xctrace can accept a window and ignore it."""
    with tempfile.TemporaryDirectory() as scratch:
        unbounded = Path(scratch) / "unbounded.xml"
        completed = run(["xcrun", "xctrace", "export", "--input", str(trace), "--xpath", xpath,
                         "--output", str(unbounded)], args.timeout)
        if completed.returncode != 0 or not unbounded.exists():
            raise RuntimeError(f"unbounded comparison export failed ({completed.returncode}): {completed.stdout.strip()}")
        unbounded_rows = count_rows(unbounded)
    bounded_rows = count_rows(bounded)
    effect = window_effect(bounded_rows, unbounded_rows)
    result: dict[str, Any] = {
        "requested": dict(zip(window[0::2], window[1::2])),
        "rows": bounded_rows,
        "unbounded_rows": unbounded_rows,
        "effect": effect,
    }
    if effect in ("no-change", "inconsistent"):
        result["warning"] = (
            "xctrace accepted the time window, but the export does not have fewer rows than an unbounded export. "
            "The window may span the whole table, or this xctrace ignores it (Xcode 27 beta 27A5194q does). "
            "Filter by time with xctrace_reduce.py --start-ms/--end-ms instead."
        )
    return result


def export_har(args: argparse.Namespace, trace: Path) -> dict[str, Any]:
    """Export HAR files into a directory, after confirming the TOC declares HAR data."""
    with tempfile.TemporaryDirectory() as scratch:
        toc = Path(scratch) / "toc.xml"
        export_toc_to(trace, toc, args.timeout)
        formats = [item for item in toc_external_formats(toc) if item.get("format") == "har"]
    if not formats:
        raise RuntimeError('trace exposes no HAR data: its TOC lists no external-format with format="har"')
    output = args.output.expanduser().resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise RuntimeError(f"HAR output must be a new or empty directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    completed = run(["xcrun", "xctrace", "export", "--input", str(trace), "--har", "--output", str(output)], args.timeout)
    if completed.returncode != 0:
        raise RuntimeError(f"xctrace export failed ({completed.returncode}): {completed.stdout.strip()}")
    files = sorted(path for path in output.iterdir() if path.is_file())
    if not files:
        raise RuntimeError("xctrace reported success but wrote no HAR files")
    total = sum(path.stat().st_size for path in files)
    if total > args.max_output_bytes:
        raise RuntimeError(f"HAR export is {total} bytes, above the {args.max_output_bytes}-byte limit")
    har_files = []
    for path in files:
        entries = None
        if path.stat().st_size <= HAR_ENTRY_COUNT_LIMIT:
            try:
                entries = len(json.loads(path.read_text(encoding="utf-8"))["log"]["entries"])
            except (OSError, ValueError, KeyError, TypeError):
                entries = None
        har_files.append({"path": str(path), "bytes": path.stat().st_size, "entries": entries})
    command_output, command_output_truncated = bounded_text(completed.stdout.strip())
    result: dict[str, Any] = {
        "schema_version": "ios.xctrace.export.v1",
        "mode": "har",
        "trace": str(trace),
        "output": str(output),
        "output_bytes": total,
        "har_files": har_files,
        "source_schemas": [item.get("source-schema") for item in formats],
        "command_output": command_output,
        "command_output_truncated": command_output_truncated,
    }
    if any(item["entries"] == 0 for item in har_files):
        result["warning"] = "A HAR file has no entries: the trace captured no HTTP transactions for it."
    return result


def export(args: argparse.Namespace, mode: str) -> dict[str, Any]:
    trace = args.trace.expanduser().resolve()
    if not trace.exists():
        raise RuntimeError(f"trace does not exist: {trace}")
    if mode == "har":
        return export_har(args, trace)
    output = ensure_output(args.output, args.force)
    argv = ["xcrun", "xctrace", "export", "--input", str(trace)]
    window: list[str] = []
    xpath = ""
    if mode == "toc":
        argv.append("--toc")
    elif mode == "table":
        xpath = selection_xpath(args.xpath, args.schema, args.track, args.detail, args.run)
        if args.schema or args.track:
            with tempfile.TemporaryDirectory() as scratch:
                toc = Path(scratch) / "toc.xml"
                export_toc_to(trace, toc, args.timeout)
                check_selection(summarize_toc(toc), args.schema, args.track, args.detail, args.run)
        argv.extend(["--xpath", xpath])
        for flag, value in (("--time-start", args.time_start), ("--time-end", args.time_end), ("--duration", args.duration)):
            if value:
                window.extend([flag, value])
        argv.extend(window)
    else:
        raise RuntimeError(f"unknown export mode: {mode}")
    argv.extend(["--output", str(output)])
    completed = run(argv, args.timeout)
    if completed.returncode != 0:
        raise RuntimeError(f"xctrace export failed ({completed.returncode}): {completed.stdout.strip()}")
    if not output.exists():
        raise RuntimeError("xctrace reported success but did not create the output")
    size = output.stat().st_size
    if size > args.max_output_bytes:
        raise RuntimeError(
            f"export is {size} bytes, above the {args.max_output_bytes}-byte limit; narrow the query"
        )
    command_output, command_output_truncated = bounded_text(completed.stdout.strip())
    result: dict[str, Any] = {
        "schema_version": "ios.xctrace.export.v1",
        "mode": mode,
        "trace": str(trace),
        "output": str(output),
        "output_bytes": size,
        "command_output": command_output,
        "command_output_truncated": command_output_truncated,
    }
    if mode == "toc":
        result["inventory"] = summarize_toc(output)
    else:
        result["selection"] = xpath
        result["rows"] = count_rows(output)
        if result["rows"] == 0:
            result["warning"] = EMPTY_SELECTION_WARNING
    if window:
        result["time_window"] = verify_window(args, trace, xpath, output, window)
    return result


def element_preview(elem: ET.Element, budget: list[int], depth: int, max_depth: int, text_limit: int) -> Any:
    if budget[0] <= 0:
        return {"truncated": True}
    budget[0] -= 1
    item: dict[str, Any] = {"tag": local_name(elem.tag)}
    if elem.attrib:
        item["attributes"] = {
            key: redact_text(value, text_limit) for key, value in sorted(elem.attrib.items())
        }
    if elem.text and elem.text.strip():
        item["text"] = redact_text(elem.text, text_limit)
    if depth < max_depth:
        children = []
        for child in list(elem):
            if budget[0] <= 0:
                children.append({"truncated": True})
                break
            children.append(element_preview(child, budget, depth + 1, max_depth, text_limit))
        if children:
            item["children"] = children
    elif list(elem):
        item["children_truncated"] = True
    return item


def preview(args: argparse.Namespace) -> dict[str, Any]:
    source = args.input.expanduser().resolve()
    if not source.is_file():
        raise RuntimeError(f"XML export does not exist: {source}")
    size = source.stat().st_size
    if size > args.max_input_bytes:
        raise RuntimeError(
            f"input is {size} bytes, above the {args.max_input_bytes}-byte preview limit; narrow the export"
        )

    rows: list[Any] = []
    schemas: set[str] = set()
    rows_seen = 0
    truncated = False
    row_depth = 0
    try:
        for event, elem in ET.iterparse(source, events=("start", "end")):
            if event == "start":
                schema = elem.attrib.get("schema")
                if local_name(elem.tag) == "schema":
                    schema = schema or elem.attrib.get("name")
                if schema:
                    schemas.add(schema)
                if local_name(elem.tag) == "row":
                    row_depth += 1
                continue

            if local_name(elem.tag) == "row":
                rows_seen += 1
                if len(rows) < args.max_rows:
                    budget = [args.max_nodes_per_row]
                    rows.append(element_preview(elem, budget, 0, args.max_depth, args.max_text))
                else:
                    truncated = True
                    elem.clear()
                    break
                row_depth -= 1
                elem.clear()
            elif row_depth == 0:
                elem.clear()
    except ET.ParseError as exc:
        raise RuntimeError(f"invalid XML export: {exc}") from exc

    result = {
        "schema_version": "ios.xctrace.preview.v1",
        "warning": "Structural preview only; no metric semantics, units, stack order, or causality are inferred.",
        "input": str(source),
        "input_bytes": size,
        "schemas_seen": sorted(schemas),
        "rows_collected": len(rows),
        "rows_seen_before_stop": rows_seen,
        "truncated": truncated,
        "rows": rows,
    }
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.save:
        destination = ensure_output(args.save, args.force)
        destination.write_text(rendered + "\n", encoding="utf-8")
    return result


def add_export_common(parser: argparse.ArgumentParser, output_help: str = "Output file") -> None:
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help=output_help)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-output-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--force", action="store_true")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    toc_parser = subparsers.add_parser("toc", help="Export and summarize the trace table of contents")
    add_export_common(toc_parser)

    table_parser = subparsers.add_parser("table", help="Export one TOC-proven table or track detail")
    add_export_common(table_parser)
    selection = table_parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--xpath", help="Explicit XPath into the TOC")
    selection.add_argument("--schema", help="Table schema listed in the TOC, e.g. time-profile")
    selection.add_argument("--track", help="Track with a detail view, e.g. Allocations, Leaks, VM Tracker; needs --detail")
    table_parser.add_argument("--detail", help="Detail name within --track, e.g. Statistics, Allocations List, Leaks")
    table_parser.add_argument("--run", type=int, default=1, help="Run number for --schema or --track (default 1)")
    table_parser.add_argument("--time-start", help="Xcode 27+; verified against an unbounded export")
    table_parser.add_argument("--time-end", help="Xcode 27+; verified against an unbounded export")
    table_parser.add_argument("--duration", help="Xcode 27+; verified against an unbounded export")

    har_parser = subparsers.add_parser("har", help="Export HTTP Archive files when the TOC declares HAR data")
    add_export_common(har_parser, "New or empty directory; xctrace writes one .har file per run")

    preview_parser = subparsers.add_parser("preview", help="Stream a bounded structural preview of exported XML")
    preview_parser.add_argument("--input", type=Path, required=True)
    preview_parser.add_argument("--save", type=Path)
    preview_parser.add_argument("--max-input-bytes", type=int, default=256 * 1024 * 1024)
    preview_parser.add_argument("--max-rows", type=int, default=20)
    preview_parser.add_argument("--max-nodes-per-row", type=int, default=80)
    preview_parser.add_argument("--max-depth", type=int, default=8)
    preview_parser.add_argument("--max-text", type=int, default=240)
    preview_parser.add_argument("--force", action="store_true")

    args = parser.parse_args()
    if args.command == "table" and bool(args.track) != bool(args.detail):
        parser.error("--track and --detail must be used together")
    try:
        if args.command == "preview":
            result = preview(args)
        else:
            result = export(args, args.command)
        print(json.dumps(result, indent=2, sort_keys=True))
        # Exit 3 when a requested time window could not be shown to bound the export.
        return 3 if (result.get("time_window") or {}).get("effect") in ("no-change", "inconsistent") else 0
    except RuntimeError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
