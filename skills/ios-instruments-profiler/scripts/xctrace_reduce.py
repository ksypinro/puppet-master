#!/usr/bin/env python3
"""Reduce one exported xctrace table or track detail to a bounded, typed summary.

Analyzers cover the tables most performance questions need: time-profile and cpu-profile (top
functions), potential-hangs, OSSignpostIntervals and os-signpost, hitches and the hitches-* frame
tables, core-data-fetch/-save/-fault, and the Allocations Statistics, Allocations List and Leaks track
details. Any other export gets a generic per-column summary. Columns come from the export's own
<schema>, id/ref values are resolved across rows, stacks are leaf-first as xctrace writes them, and
durations are reported in milliseconds. Status "empty" means no row matched, which is "not captured",
not proof that the activity did not happen.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = "ios.xctrace.reduce.v1"
BACKTRACE_TAGS = {"backtrace", "tagged-backtrace", "text-backtrace"}
NO_STACK = {"", "<Call stack limit reached>"}
# Binaries under these prefixes belong to the OS or toolchain; the first other frame is the app frame.
SYSTEM_PREFIXES = ("/System/", "/usr/lib/", "/usr/libexec/", "/Library/Apple/", "/Library/Developer/")
HOME_PATH = re.compile(r"/Users/[^/\s\"]+")
HEX_ADDRESS = re.compile(r"0x[0-9a-fA-F]+")
TEXT_LIMIT = 160
DISTINCT_LIMIT = 10_000


@dataclass(frozen=True)
class Binary:
    name: str
    path: str


@dataclass(frozen=True)
class Frame:
    name: str
    binary: str
    system: bool

    @property
    def label(self) -> str:
        return f"{self.name} [{self.binary}]" if self.binary else self.name

    @property
    def symbolicated(self) -> bool:
        return bool(self.name) and not HEX_ADDRESS.fullmatch(self.name)


@dataclass(frozen=True)
class Value:
    fmt: str
    raw: str

    def number(self) -> float | None:
        try:
            return float(self.raw)
        except ValueError:
            return None


@dataclass
class Options:
    top: int = 15
    binary: str | None = None
    seconds: float | None = None
    schema: str | None = None


@dataclass
class Filters:
    process: str | None = None
    thread: str | None = None
    start_ms: float | None = None
    end_ms: float | None = None

    def describe(self) -> dict[str, Any]:
        return {key: value for key, value in vars(self).items() if value is not None}

    def match(self, row: dict[str, Any]) -> bool:
        if self.process:
            owners = " ".join(filter(None, (text(row.get("process")), text(row.get("thread")), text(row.get("start-thread")))))
            if self.process.casefold() not in owners.casefold():
                return False
        if self.thread:
            thread = text(row.get("thread")) or text(row.get("start-thread")) or ""
            if self.thread.casefold() not in thread.casefold():
                return False
        if self.start_ms is not None or self.end_ms is not None:
            at = number(row.get("time")) if row.get("time") is not None else number(row.get("start"))
            if at is None:
                return False
            if self.start_ms is not None and at / 1e6 < self.start_ms:
                return False
            if self.end_ms is not None and at / 1e6 > self.end_ms:
                return False
        return True


def text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Value):
        return value.fmt
    if isinstance(value, Frame):
        return value.label
    if isinstance(value, Binary):
        return value.name
    if isinstance(value, tuple):
        return value[0].label if value else None
    return str(value)


def number(value: Any) -> float | None:
    return value.number() if isinstance(value, Value) else None


def to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clip(value: str) -> str:
    return value if len(value) <= TEXT_LIMIT else value[:TEXT_LIMIT] + "…"


def bump(counter: Counter, key: Any, amount: float = 1) -> None:
    """Count a key, but stop admitting new keys once a counter holds DISTINCT_LIMIT of them."""
    if key in counter or len(counter) < DISTINCT_LIMIT:
        counter[key] += amount


def ms(nanoseconds: float) -> float:
    return round(nanoseconds / 1e6, 3)


def mb(size: float) -> float:
    return round(size / 1e6, 2)


def quantile_type7(ordered: list[float], probability: float) -> float:
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def duration_summary(values_ns: list[float]) -> dict[str, Any]:
    if not values_ns:
        return {"count": 0}
    ordered = sorted(values_ns)
    return {
        "count": len(ordered),
        "min_ms": ms(ordered[0]),
        "median_ms": ms(statistics.median(ordered)),
        "p90_ms": ms(quantile_type7(ordered, 0.9)),
        "max_ms": ms(ordered[-1]),
        "total_ms": ms(sum(ordered)),
    }


def top(counter: Counter, limit: int, key: str = "value") -> list[dict[str, Any]]:
    return [{key: clip(str(item)), "count": count} for item, count in counter.most_common(limit)]


class Resolver:
    """Resolves xctrace id/ref values; ids are unique within one export and refs may point to earlier rows."""

    def __init__(self) -> None:
        self.ids: dict[str, Any] = {}
        self.missing_refs = 0

    def resolve(self, elem: ET.Element) -> Any:
        ref = elem.get("ref")
        if ref is not None:
            if ref not in self.ids:
                self.missing_refs += 1
                return None
            return self.ids[ref]
        tag = elem.tag
        if tag == "sentinel":
            result: Any = None
        elif tag == "binary":
            result = Binary(elem.get("name", ""), elem.get("path", ""))
        elif tag == "frame":
            binary = elem.find("binary")
            owner = self.resolve(binary) if binary is not None else None
            owner = owner if isinstance(owner, Binary) else Binary("", "")
            result = Frame(elem.get("name") or elem.get("addr") or "<unnamed>", owner.name, owner.path.startswith(SYSTEM_PREFIXES))
        elif tag in BACKTRACE_TAGS:
            frames = (self.resolve(child) for child in elem if child.tag == "frame")
            result = tuple(frame for frame in frames if isinstance(frame, Frame))
        else:
            for child in elem:  # register nested ids, such as the process inside a thread
                self.resolve(child)
            raw = (elem.text or "").strip()
            result = Value(elem.get("fmt") or raw or elem.get("name") or "", raw)
        ident = elem.get("id")
        if ident is not None:
            self.ids[ident] = result
        return result


def iter_export(path: Path, max_rows: int) -> Iterator[tuple[str, Any]]:
    """Yield ("schema", (name, columns)), ("row", values), ("detail", attributes) and bookkeeping events."""
    resolver = Resolver()
    columns: list[dict[str, str]] = []
    parent: ET.Element | None = None
    rows = 0
    for event, elem in ET.iterparse(path, events=("start", "end")):
        if event == "start":
            if elem.tag == "node":
                parent = elem
            continue
        if elem.tag == "schema":
            columns = [
                {
                    "mnemonic": col.findtext("mnemonic") or f"column-{index}",
                    "name": col.findtext("name") or "",
                    "type": col.findtext("engineering-type") or "",
                }
                for index, col in enumerate(elem.findall("col"))
            ]
            yield "schema", (elem.get("name"), columns)
        elif elem.tag == "row":
            if columns:
                values = {}
                for index, child in enumerate(elem):
                    if index >= len(columns):
                        break
                    values[columns[index]["mnemonic"]] = resolver.resolve(child)
                yield "row", values
            else:
                yield "detail", dict(elem.attrib)
            rows += 1
            (parent if parent is not None else elem).clear()
            if rows >= max_rows:
                yield "truncated", rows
                break
    yield "missing-refs", resolver.missing_refs


class Reducer:
    name = "generic"
    notes: tuple[str, ...] = ()

    def __init__(self, columns: list[dict[str, str]], options: Options) -> None:
        self.columns = columns
        self.options = options

    def add(self, row: dict[str, Any]) -> None:
        raise NotImplementedError

    def result(self) -> dict[str, Any]:
        raise NotImplementedError


class ProfileReducer(Reducer):
    name = "profile"
    notes = (
        "Sample weight is CPU time (or cycles) the sampler attributed to a stack, not elapsed time.",
        "Self = leaf frame; inclusive = every distinct frame in the stack; app frame = first frame from the leaf "
        "outside system libraries, or inside --binary when given.",
    )

    def __init__(self, columns: list[dict[str, str]], options: Options) -> None:
        super().__init__(columns, options)
        self.cycles = next((c["type"] for c in columns if c["mnemonic"] == "weight"), "") == "cycle-weight"
        self.samples = self.no_stack = self.leaf_symbolicated = 0
        self.total = 0.0
        self.self_weight, self.self_samples = Counter(), Counter()
        self.inclusive_weight, self.inclusive_samples = Counter(), Counter()
        self.app_weight, self.app_samples = Counter(), Counter()
        self.threads, self.processes, self.states = Counter(), Counter(), Counter()

    def add(self, row: dict[str, Any]) -> None:
        weight = number(row.get("weight")) or 0.0
        self.samples += 1
        self.total += weight
        bump(self.threads, text(row.get("thread")) or "unknown")
        bump(self.processes, text(row.get("process")) or "unknown")
        bump(self.states, text(row.get("thread-state")) or "unknown")
        stack = row.get("stack")
        if not isinstance(stack, tuple) or not stack:
            self.no_stack += 1
            return
        leaf = stack[0]
        self.leaf_symbolicated += leaf.symbolicated
        bump(self.self_weight, leaf.label, weight)
        bump(self.self_samples, leaf.label)
        for label in {frame.label for frame in stack}:
            bump(self.inclusive_weight, label, weight)
            bump(self.inclusive_samples, label)
        wanted = self.options.binary
        app = next((f for f in stack if (f.binary == wanted if wanted else not f.system)), None)
        if app is not None:
            bump(self.app_weight, app.label, weight)
            bump(self.app_samples, app.label)

    def convert(self, weight: float) -> float:
        return round(weight) if self.cycles else ms(weight)

    def ranked(self, weights: Counter, samples: Counter) -> list[dict[str, Any]]:
        by_weight = self.total > 0
        keys = sorted(samples, key=lambda key: weights[key] if by_weight else samples[key], reverse=True)
        ranked = []
        for key in keys[: self.options.top]:
            share = weights[key] / self.total if by_weight else samples[key] / self.samples
            item: dict[str, Any] = {"function": clip(key), "samples": samples[key], "share": round(share, 4)}
            if by_weight:
                item["weight"] = self.convert(weights[key])
            ranked.append(item)
        return ranked

    def result(self) -> dict[str, Any]:
        with_stack = self.samples - self.no_stack
        return {
            "samples": self.samples,
            "weight_unit": "cycles" if self.cycles else "ms",
            "total_weight": self.convert(self.total),
            "samples_without_stack": self.no_stack,
            "leaf_symbolication": {"symbolicated": self.leaf_symbolicated, "unsymbolicated": with_stack - self.leaf_symbolicated},
            "threads": top(self.threads, self.options.top),
            "processes": top(self.processes, self.options.top),
            "thread_states": top(self.states, self.options.top),
            "top_self": self.ranked(self.self_weight, self.self_samples),
            "top_inclusive": self.ranked(self.inclusive_weight, self.inclusive_samples),
            "top_app_frames": self.ranked(self.app_weight, self.app_samples),
        }


class HangsReducer(Reducer):
    name = "hangs"
    notes = (
        "Each row is a main-thread stall longer than the recording's hang threshold; Apple counts 250 ms and longer as a hang.",
        "In testing Hangs reported app processes only: a command-line tool blocking its run loop for 1.5 s produced no rows.",
    )

    def __init__(self, columns: list[dict[str, str]], options: Options) -> None:
        super().__init__(columns, options)
        self.durations: list[float] = []
        self.types, self.threads = Counter(), Counter()
        self.longest: list[tuple[float, float | None, str, str]] = []

    def add(self, row: dict[str, Any]) -> None:
        duration = number(row.get("duration")) or 0.0
        self.durations.append(duration)
        bump(self.types, text(row.get("hang-type")) or "unknown")
        bump(self.threads, text(row.get("thread")) or "unknown")
        self.longest.append((duration, number(row.get("start")), text(row.get("hang-type")) or "", text(row.get("thread")) or ""))
        if len(self.longest) > 4 * self.options.top:
            self.longest = sorted(self.longest, key=lambda item: item[0], reverse=True)[: self.options.top]

    def result(self) -> dict[str, Any]:
        longest = sorted(self.longest, key=lambda item: item[0], reverse=True)[: self.options.top]
        return {
            "hangs": len(self.durations),
            "duration": duration_summary(self.durations),
            "by_type": top(self.types, self.options.top),
            "by_thread": top(self.threads, self.options.top),
            "longest": [
                {"start_ms": ms(start) if start is not None else None, "duration_ms": ms(duration), "type": kind, "thread": clip(thread)}
                for duration, start, kind, thread in longest
            ],
        }


class SignpostIntervalsReducer(Reducer):
    name = "signpost-intervals"
    notes = ("Interval durations come from matched begin/end signposts, so they are elapsed time for the named phase.",)

    def __init__(self, columns: list[dict[str, str]], options: Options) -> None:
        super().__init__(columns, options)
        self.groups: dict[tuple[str, str, str], list[float]] = defaultdict(list)

    def add(self, row: dict[str, Any]) -> None:
        key = (text(row.get("subsystem")) or "", text(row.get("category")) or "", text(row.get("name")) or "")
        if key in self.groups or len(self.groups) < DISTINCT_LIMIT:
            self.groups[key].append(number(row.get("duration")) or 0.0)

    def result(self) -> dict[str, Any]:
        ranked = sorted(self.groups.items(), key=lambda item: sum(item[1]), reverse=True)[: self.options.top]
        return {
            "intervals": sum(len(values) for values in self.groups.values()),
            "names": len(self.groups),
            "groups": [
                {"name": clip(name), "category": clip(category), "subsystem": clip(subsystem), **duration_summary(values)}
                for (subsystem, category, name), values in ranked
            ],
        }


class SignpostEventsReducer(Reducer):
    name = "signpost-events"
    notes = ("os-signpost lists individual events; export OSSignpostIntervals for interval durations.",)

    def __init__(self, columns: list[dict[str, str]], options: Options) -> None:
        super().__init__(columns, options)
        self.events: Counter = Counter()
        self.total = 0

    def add(self, row: dict[str, Any]) -> None:
        self.total += 1
        bump(self.events, (text(row.get("name")) or "", text(row.get("event-type")) or ""))

    def result(self) -> dict[str, Any]:
        groups = []
        for (name, event_type), count in self.events.most_common(self.options.top):
            groups.append({"name": clip(name), "event_type": event_type, "count": count})
        return {"events": self.total, "groups": groups}


class FramesReducer(Reducer):
    name = "frames"
    notes = (
        "0 rows in hitches means no hitch was detected, not that no frames were drawn; hitches-frame-lifetimes counts frames.",
        "Pass --seconds (the recording length) to get hitch time per second.",
    )

    def __init__(self, columns: list[dict[str, str]], options: Options) -> None:
        super().__init__(columns, options)
        self.durations: list[float] = []
        self.processes, self.issues, self.colors = Counter(), Counter(), Counter()

    def add(self, row: dict[str, Any]) -> None:
        self.durations.append(number(row.get("duration")) or 0.0)
        if row.get("process") is not None:
            bump(self.processes, text(row.get("process")) or "unknown")
        if row.get("narrative-description") is not None:
            bump(self.issues, text(row.get("narrative-description")) or "")
        if row.get("frame-color") is not None:
            bump(self.colors, text(row.get("frame-color")) or "")

    def result(self) -> dict[str, Any]:
        summary = duration_summary(self.durations)
        result: dict[str, Any] = {"rows": len(self.durations), "duration": summary}
        if self.processes:
            result["by_process"] = top(self.processes, self.options.top)
        if self.issues:
            result["potential_issues"] = top(self.issues, self.options.top)
        if self.colors:
            result["frame_colors"] = top(self.colors, self.options.top)
        if self.options.schema == "hitches" and self.options.seconds:
            result["hitch_ms_per_second"] = round(summary.get("total_ms", 0.0) / self.options.seconds, 3)
        return result


class CoreDataReducer(Reducer):
    name = "core-data"
    notes = ("Durations are the wall time of each Core Data or SwiftData operation on its thread.",)

    def __init__(self, columns: list[dict[str, str]], options: Options) -> None:
        super().__init__(columns, options)
        self.durations: list[float] = []
        self.result_counts: list[float] = []
        self.entities, self.callers, self.threads = Counter(), Counter(), Counter()

    def add(self, row: dict[str, Any]) -> None:
        self.durations.append(number(row.get("duration")) or 0.0)
        if row.get("fetch-entity") is not None:
            bump(self.entities, text(row.get("fetch-entity")) or "")
        fetched = number(row.get("fetch-count"))
        if fetched is not None:
            self.result_counts.append(fetched)
        bump(self.threads, text(row.get("thread")) or "unknown")
        stack = row.get("backtrace")
        if isinstance(stack, tuple) and stack:
            wanted = self.options.binary
            caller = next((f for f in stack if (f.binary == wanted if wanted else not f.system)), None)
            bump(self.callers, caller.label if caller else "<system frames only>")

    def result(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "operations": len(self.durations),
            "duration": duration_summary(self.durations),
            "threads": top(self.threads, self.options.top),
            "app_callers": top(self.callers, self.options.top),
        }
        if self.entities:
            result["entities"] = top(self.entities, self.options.top)
        if self.result_counts:
            ordered = sorted(self.result_counts)
            result["objects_returned"] = {"min": ordered[0], "median": statistics.median(ordered), "max": ordered[-1]}
        return result


class AllocationStatisticsReducer(Reducer):
    name = "allocation-statistics"
    notes = (
        "Live (persistent) bytes were still allocated when recording ended; allocated (total) bytes include freed memory.",
        "Compare equivalent lifecycle points across repeated runs before calling growth a leak.",
    )

    def __init__(self, columns: list[dict[str, str]], options: Options) -> None:
        super().__init__(columns, options)
        self.rows: list[dict[str, str]] = []

    def add(self, row: dict[str, Any]) -> None:
        if len(self.rows) < DISTINCT_LIMIT:
            self.rows.append(row)

    def result(self) -> dict[str, Any]:
        def value(row: dict[str, str], key: str) -> float:
            return to_float(row.get(key)) or 0.0

        overall = next((row for row in self.rows if row.get("category") == "All Heap & Anonymous VM"), None)
        categories = sorted(
            (row for row in self.rows if not str(row.get("category", "")).startswith("All ")),
            key=lambda row: value(row, "persistent-bytes"),
            reverse=True,
        )
        return {
            "categories": len(categories),
            "overall": None if overall is None else {
                "live_mb": mb(value(overall, "persistent-bytes")),
                "live_count": int(value(overall, "count-persistent")),
                "allocated_mb": mb(value(overall, "total-bytes")),
                "allocated_count": int(value(overall, "count-total")),
                "transient_count": int(value(overall, "count-transient")),
            },
            "top_live_categories": [
                {
                    "category": clip(row.get("category", "")),
                    "live_mb": mb(value(row, "persistent-bytes")),
                    "live_count": int(value(row, "count-persistent")),
                    "allocated_mb": mb(value(row, "total-bytes")),
                    "allocated_count": int(value(row, "count-total")),
                }
                for row in categories[: self.options.top]
            ],
        }


STACK_NOTE = ("<Call stack limit reached> means no stack was recorded. In testing that covered objects allocated before an "
              "attach (about 40% of rows attached, 0–2% when the recorder launched the target); launch the target when stacks matter.")


class AllocationListReducer(Reducer):
    name = "allocation-list"
    notes = (
        STACK_NOTE,
        "The responsible caller is often the Swift or Objective-C allocator; the app frame above it is in the full "
        "backtrace, which this detail does not export.",
    )

    def __init__(self, columns: list[dict[str, str]], options: Options) -> None:
        super().__init__(columns, options)
        self.count = self.live = self.no_stack = 0
        self.bytes = 0.0
        self.category_count, self.category_bytes = Counter(), Counter()
        self.callers, self.libraries = Counter(), Counter()

    def add(self, row: dict[str, Any]) -> None:
        size = to_float(row.get("size")) or 0.0
        self.count += 1
        self.bytes += size
        self.live += row.get("live") == "true"
        category = row.get("category") or "unknown"
        bump(self.category_count, category)
        bump(self.category_bytes, category, size)
        caller = row.get("responsible-caller", "")
        if caller in NO_STACK:
            self.no_stack += 1
        else:
            bump(self.callers, caller)
            bump(self.libraries, row.get("responsible-library") or "unknown")

    def result(self) -> dict[str, Any]:
        categories = sorted(self.category_bytes, key=lambda key: self.category_bytes[key], reverse=True)[: self.options.top]
        return {
            "allocations": self.count,
            "live_allocations": self.live,
            "mb": mb(self.bytes),
            "without_stack": self.no_stack,
            "without_stack_share": round(self.no_stack / self.count, 4) if self.count else None,
            "top_categories": [
                {"category": clip(key), "count": self.category_count[key], "mb": mb(self.category_bytes[key])} for key in categories
            ],
            "responsible_callers": top(self.callers, self.options.top),
            "responsible_libraries": top(self.libraries, self.options.top),
        }


class LeaksReducer(Reducer):
    name = "leaks"
    notes = (
        "Leaks reports memory that was unreachable at its snapshots; confirm with repeated lifecycle runs.",
        STACK_NOTE,
    )

    def __init__(self, columns: list[dict[str, str]], options: Options) -> None:
        super().__init__(columns, options)
        self.objects = self.no_stack = 0
        self.bytes = 0.0
        self.object_count, self.object_bytes = Counter(), Counter()
        self.frames, self.libraries = Counter(), Counter()

    def add(self, row: dict[str, Any]) -> None:
        count = int(to_float(row.get("count")) or 1)
        size = to_float(row.get("size")) or 0.0
        self.objects += count
        self.bytes += size
        leaked = row.get("leaked-object") or "unknown"
        bump(self.object_count, leaked, count)
        bump(self.object_bytes, leaked, size)
        frame = row.get("responsible-frame", "")
        if frame in NO_STACK:
            self.no_stack += count
        else:
            bump(self.frames, frame, count)
            bump(self.libraries, row.get("responsible-library") or "unknown", count)

    def result(self) -> dict[str, Any]:
        leaked = sorted(self.object_bytes, key=lambda key: self.object_bytes[key], reverse=True)[: self.options.top]
        return {
            "leaked_objects": self.objects,
            "leaked_mb": mb(self.bytes),
            "without_stack": self.no_stack,
            "without_stack_share": round(self.no_stack / self.objects, 4) if self.objects else None,
            "by_object": [{"object": clip(key), "count": self.object_count[key], "mb": mb(self.object_bytes[key])} for key in leaked],
            "responsible_frames": top(self.frames, self.options.top),
            "responsible_libraries": top(self.libraries, self.options.top),
        }


class GenericTableReducer(Reducer):
    name = "generic-table"
    notes = ("Generic summary: column coverage and most common values only; no units, meanings or derived metrics are inferred.",)

    def __init__(self, columns: list[dict[str, str]], options: Options) -> None:
        super().__init__(columns, options)
        self.rows = 0
        self.present: Counter = Counter()
        self.values: dict[str, Counter] = defaultdict(Counter)

    def add(self, row: dict[str, Any]) -> None:
        self.rows += 1
        for mnemonic, value in row.items():
            shown = text(value)
            if shown:
                self.present[mnemonic] += 1
                bump(self.values[mnemonic], clip(shown))

    def result(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "columns": [
                {
                    "mnemonic": column["mnemonic"],
                    "name": column["name"],
                    "type": column["type"],
                    "rows_with_value": self.present[column["mnemonic"]],
                    "distinct": len(self.values[column["mnemonic"]]),
                    "distinct_capped": len(self.values[column["mnemonic"]]) >= DISTINCT_LIMIT,
                    "top": top(self.values[column["mnemonic"]], min(self.options.top, 8)),
                }
                for column in self.columns
            ],
        }


class GenericDetailReducer(Reducer):
    name = "generic-detail"
    notes = ("Generic summary of a track detail: attribute coverage, common values and numeric sums only.",)

    def __init__(self, columns: list[dict[str, str]], options: Options) -> None:
        super().__init__(columns, options)
        self.rows = 0
        self.values: dict[str, Counter] = defaultdict(Counter)
        self.sums: Counter = Counter()
        self.non_numeric: set[str] = set()

    def add(self, row: dict[str, Any]) -> None:
        self.rows += 1
        for name, value in row.items():
            parsed = to_float(value)
            if parsed is None:
                self.non_numeric.add(name)
            else:
                self.sums[name] += parsed
            bump(self.values[name], clip(value))

    def result(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "attributes": [
                {
                    "name": name,
                    "distinct": len(counter),
                    **({"top": top(counter, min(self.options.top, 8))} if name in self.non_numeric else {"sum": self.sums[name]}),
                }
                for name, counter in self.values.items()
            ],
        }


ANALYZERS: dict[str, type[Reducer]] = {
    cls.name: cls
    for cls in (
        ProfileReducer, HangsReducer, SignpostIntervalsReducer, SignpostEventsReducer, FramesReducer, CoreDataReducer,
        AllocationStatisticsReducer, AllocationListReducer, LeaksReducer, GenericTableReducer, GenericDetailReducer,
    )
}


def pick_analyzer(schema: str | None, first_detail: dict[str, str] | None) -> type[Reducer]:
    if first_detail is not None:
        if "leaked-object" in first_detail:
            return LeaksReducer
        if "persistent-bytes" in first_detail:
            return AllocationStatisticsReducer
        if "responsible-caller" in first_detail:
            return AllocationListReducer
        return GenericDetailReducer
    name = schema or ""
    if name in ("time-profile", "cpu-profile"):
        return ProfileReducer
    if name == "potential-hangs":
        return HangsReducer
    if name == "OSSignpostIntervals":
        return SignpostIntervalsReducer
    if name == "os-signpost":
        return SignpostEventsReducer
    if name == "hitches" or name.startswith("hitches-"):
        return FramesReducer
    if name.startswith("core-data-"):
        return CoreDataReducer
    return GenericTableReducer


def reduce_file(
    path: Path,
    analyzer: str = "auto",
    filters: Filters | None = None,
    binary: str | None = None,
    seconds: float | None = None,
    top_n: int = 15,
    max_rows: int = 2_000_000,
) -> dict[str, Any]:
    filters = filters or Filters()
    options = Options(top=top_n, binary=binary, seconds=seconds)
    schema: str | None = None
    columns: list[dict[str, str]] = []
    reducer: Reducer | None = None
    export_kind = "unknown"
    rows_read = matched = missing_refs = 0
    truncated = False
    for kind, payload in iter_export(path, max_rows):
        if kind == "schema":
            if schema is not None and payload[0] != schema:
                raise RuntimeError("the export holds more than one table; export one table at a time")
            schema, columns = payload
            options.schema = schema
        elif kind in ("row", "detail"):
            rows_read += 1
            if reducer is None:
                export_kind = "table" if kind == "row" else "track-detail"
                chosen = ANALYZERS[analyzer] if analyzer != "auto" else pick_analyzer(schema, payload if kind == "detail" else None)
                reducer = chosen(columns, options)
            if kind == "row" and not filters.match(payload):
                continue
            matched += 1
            reducer.add(payload)
        elif kind == "truncated":
            truncated = True
        elif kind == "missing-refs":
            missing_refs = payload
    if reducer is None:
        export_kind = "table" if columns else "unknown"
        reducer = (ANALYZERS[analyzer] if analyzer != "auto" else pick_analyzer(schema, None))(columns, options)
    notes = list(reducer.notes)
    if matched == 0:
        notes.append("No row matched: report this as not captured, not as zero activity, unless the instrument is known to capture this target.")
    if export_kind == "track-detail" and filters.describe():
        notes.append("Process, thread and time filters apply to table rows only; this track detail was not filtered.")
    if missing_refs:
        notes.append(f"{missing_refs} ref values pointed at ids missing from the export and were treated as unknown.")
    result = {
        "schema_version": SCHEMA_VERSION,
        "input": str(path),
        "input_bytes": path.stat().st_size,
        "export_kind": export_kind,
        "schema": schema,
        "analyzer": reducer.name,
        "status": "ok" if matched else "empty",
        "rows_read": rows_read,
        "rows_matched": matched,
        "truncated": truncated,
        "filters": filters.describe(),
        "summary": reducer.result(),
        "notes": notes,
    }
    return json.loads(HOME_PATH.sub("/Users/<redacted>", json.dumps(result)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True, help="XML written by xctrace_export.py table")
    parser.add_argument("--analyzer", choices=["auto", *ANALYZERS], default="auto")
    parser.add_argument("--process", help="Keep rows whose process or thread contains this text")
    parser.add_argument("--thread", help="Keep rows whose thread contains this text, e.g. 'Main Thread'")
    parser.add_argument("--start-ms", type=float, help="Keep rows starting at or after this trace time")
    parser.add_argument("--end-ms", type=float, help="Keep rows starting at or before this trace time")
    parser.add_argument("--binary", help="Attribute stacks to the first frame in this binary instead of the first non-system frame")
    parser.add_argument("--seconds", type=float, help="Recording length, for per-second rates such as hitch time")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--max-rows", type=int, default=2_000_000)
    parser.add_argument("--max-input-bytes", type=int, default=1024 * 1024 * 1024)
    parser.add_argument("--save", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    try:
        source = args.input.expanduser().resolve()
        if not source.is_file():
            raise RuntimeError(f"export does not exist: {source}")
        if source.stat().st_size > args.max_input_bytes:
            raise RuntimeError(f"input is {source.stat().st_size} bytes, above --max-input-bytes; narrow the export")
        filters = Filters(args.process, args.thread, args.start_ms, args.end_ms)
        result = reduce_file(source, args.analyzer, filters, args.binary, args.seconds, args.top, args.max_rows)
        rendered = json.dumps(result, indent=2, sort_keys=True)
        if args.save:
            destination = args.save.expanduser().resolve()
            if destination.exists() and not args.force:
                raise RuntimeError(f"output already exists: {destination}; pass --force to replace it")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0
    except (RuntimeError, OSError, ET.ParseError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
