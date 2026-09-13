#!/usr/bin/env python3
"""Query a captured memory graph without inventing certainty.

    summary  <graph>                  footprint, heap and scanner totals
    classes  <graph> [--match TEXT]   list real class names (find the full one)
    objects  <graph> <class>          instances, with a full-match guard
    layout   <graph> <address>        fields, offsets, incoming/outgoing edges
    paths    <graph> <address>        retaining paths toward roots
    diff     <before> <after>         what changed between two checkpoints

Add --json for machine-readable output.

TWO TRAPS THIS EXISTS TO CLOSE

1. `heap -addresses` matches the WHOLE class name, not a substring. Measured
   against a class that exists, agreeing with Python's re.fullmatch on 8 of 8
   patterns:

       'MemoryResearchNode'   2 matches
       'MemoryResearch'       0 matches   <- prefix
       'Node'                 0 matches   <- suffix
       '.*Node'               2 matches
       '^MemoryResearchNode$' invalid -- dumps help, exit 255

   A partial class name returns ZERO at exit 0, which is indistinguishable from
   "no such class". On Swift mangled names nobody types the full symbol by
   hand, so this is the default failure. `objects` refuses to report an empty
   result until it has checked whether the class exists under another spelling.

2. `leaks` puts the finding in its exit status for only some modes. On one
   graph with four leaks: plain / --fullStacks / --groupByType exit 1, while
   --referenceTree / --autoreleasePools / --debug exit 0. Every leaks call here
   goes through interpret_leaks, which reports operation and finding
   separately and says "unknown" rather than guessing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from memgraph_util import (  # noqa: E402
    ToolError, human_bytes, interpret_leaks, require_graph, run,
)

HEX = re.compile(r"^0x[0-9a-fA-F]+$")
# `0xADDR: ClassName (N bytes)` from heap -addresses
ADDR_ROW = re.compile(r"^(0x[0-9a-f]+):\s+(.+?)\s+\((\d+)\s+bytes?\)")
# heap's per-class inventory rows: count bytes avg CLASS ...
CLASS_ROW = re.compile(r"^\s*(\d+)\s+([\d.]+\w*)\s+[\d.]+\s+(\S+)")
HEAP_HEADER = "Active blocks in all zones that match pattern"


def _validate_address(addr: str) -> str:
    if not HEX.match(addr):
        raise ToolError(f"'{addr}' is not a hexadecimal address. Addresses must "
                        f"be taken from the selected snapshot, not typed.")
    return addr


# --------------------------------------------------------------------------
# summary
# --------------------------------------------------------------------------

def summary(graph: Path) -> Dict[str, Any]:
    info = require_graph(graph)

    fp = run(["vmmap", "-summary", str(graph)])
    footprint = None
    for line in fp["stdout"].splitlines():
        if line.strip().lower().startswith("physical footprint:"):
            footprint = line.split(":", 1)[1].strip()
            break

    # The two tools word this line differently:
    #   leaks: "Process 96979: 888 nodes malloced for 351 KB"
    #   heap:  "All zones: 888 nodes malloced - Sizes: 160KB[1] ..."
    # leaks carries the byte total, so prefer it and fall back to heap.
    lk_first = run(["leaks", str(graph)])
    nodes = total = None
    m = re.search(r"([\d,]+) nodes malloced for ([\d,.]+\s*\w+)",
                  lk_first["stdout"])
    if m:
        nodes, total = m.group(1), m.group(2)
    else:
        hp = run(["heap", str(graph)])
        m = re.search(r"([\d,]+) nodes malloced", hp["stdout"])
        if m:
            nodes = m.group(1)

    leak = interpret_leaks(lk_first, [])

    return {
        "graph": str(graph),
        "artifact": {k: info[k] for k in ("bytes", "magic", "fullStackHistory")},
        "physicalFootprint": footprint,
        "nodesMalloced": nodes,
        "heapTotal": total,
        "leaks": leak,
        "note": ("Heap payload, resident/dirty regions, virtual size, physical "
                 "footprint and scanner-leaked bytes measure different things. "
                 "Never sum them."),
        "historyNote": (None if info["fullStackHistory"] else
                        "This graph has no allocation history, so 'when was "
                        "this allocated' cannot be answered from it."),
    }


# --------------------------------------------------------------------------
# classes -- so the caller can find the FULL name before querying by it
# --------------------------------------------------------------------------

def classes(graph: Path, match: Optional[str] = None,
            limit: int = 40) -> Dict[str, Any]:
    require_graph(graph)
    r = run(["heap", "-sortBySize", str(graph)])

    found = []
    for line in r["stdout"].splitlines():
        m = CLASS_ROW.match(line)
        if not m:
            continue
        count, size, name = m.group(1), m.group(2), m.group(3)
        if match and match.lower() not in name.lower():
            continue
        found.append({"class": name, "count": int(count), "bytes": size})

    return {
        "match": match,
        "total": len(found),
        "classes": found[:limit],
        "truncated": len(found) > limit,
        "note": ("These are the exact spellings `objects` will accept. "
                 "heap matches the WHOLE name, so a prefix will not work."),
    }


# --------------------------------------------------------------------------
# objects -- the full-match guard
# --------------------------------------------------------------------------

def objects(graph: Path, pattern: str, limit: int = 50) -> Dict[str, Any]:
    require_graph(graph)

    if pattern.startswith("^"):
        raise ToolError(
            f"'{pattern}' begins with '^'. heap -addresses is already anchored "
            f"to the whole class name; a leading '^' makes the pattern invalid "
            f"and heap prints its help text instead of results. Drop the "
            f"anchors.")

    r = run(["heap", "-addresses", pattern, str(graph)])
    out = r["stdout"]
    header = HEAP_HEADER in out

    rows = []
    for line in out.splitlines():
        m = ADDR_ROW.match(line.strip())
        if m:
            rows.append({"address": m.group(1), "class": m.group(2),
                         "bytes": int(m.group(3))})

    result: Dict[str, Any] = {
        "pattern": pattern,
        "exit": r["exit"],
        "headerPresent": header,
        "count": len(rows),
        "objects": rows[:limit],
        "truncated": len(rows) > limit,
    }

    if not header:
        # No header means heap rejected the pattern -- it dumped usage.
        result["status"] = "invalid-pattern"
        result["detail"] = ("heap did not recognise this pattern and printed "
                            "its help instead. This is NOT 'no such class'.")
        return result

    if rows:
        result["status"] = "ok"
        return result

    # Empty result. Before reporting it, find out whether the class exists
    # under a different spelling -- the full-match rule makes this the most
    # likely explanation.
    inventory = classes(graph, match=re.sub(r"[.*+?^$\[\]()|\\]", "", pattern),
                        limit=10)
    suggestions = [c["class"] for c in inventory["classes"]]

    result["status"] = "no-match"
    result["suggestions"] = suggestions
    result["detail"] = (
        (f"No objects matched. heap matches the WHOLE class name, and these "
         f"real classes contain your text: {', '.join(suggestions[:5])}. "
         f"Use one of those exactly, or a pattern that spans the full name "
         f"such as '.*{pattern}.*'.")
        if suggestions else
        "No objects matched, and no class in this graph contains that text. "
        "The class is genuinely absent from this snapshot.")
    return result


# --------------------------------------------------------------------------
# layout and paths
# --------------------------------------------------------------------------

def layout(graph: Path, address: str) -> Dict[str, Any]:
    require_graph(graph)
    _validate_address(address)

    r = run(["leaks", "--debug=layout", f"--debug={address}", str(graph)])
    out = r["stdout"]

    fields, incoming, outgoing = [], [], []
    refs_to = None
    for line in out.splitlines():
        s = line.strip()
        m = re.match(r"^REFERENCES TO THIS:\s*(\d+)", s)
        if m:
            refs_to = int(m.group(1))
            continue
        m = re.match(r"^(\d+):\s+(.*?)\s+(\w+)\s*(-->.*)?$", s)
        if m and "LAYOUT" not in s:
            fields.append({"offset": int(m.group(1)), "type": m.group(2),
                           "name": m.group(3),
                           "target": (m.group(4) or "").replace("-->", "").strip()
                           or None})
        if s.startswith("+") and "-->" in s:
            outgoing.append(s)
        elif s.startswith("<") and "-->" in s:
            incoming.append(s)

    return {
        "address": address,
        "exit": r["exit"],
        "referencesToThis": refs_to,
        "fields": fields,
        "outgoing": outgoing[:20],
        "incoming": incoming[:20],
        "raw": out[:4000],
        "note": ("No field output does not prove the object has no fields or "
                 "no owners -- it can mean the layout is unavailable for this "
                 "type. `--debug=references` only reports allocations with "
                 "reference count > 1, so empty output there is not 'no "
                 "references'."),
    }


def paths(graph: Path, address: str) -> Dict[str, Any]:
    require_graph(graph)
    _validate_address(address)

    trace = run(["leaks", f"--trace={address}", str(graph)])
    tree = run(["leaks", f"--traceTree={address}", str(graph)])

    root_paths = [l for l in tree["stdout"].splitlines() if l.strip()]
    return {
        "address": address,
        "trace": trace["stdout"][:2000],
        "traceTree": tree["stdout"][:4000],
        "rootPathLines": len(root_paths),
        "note": ("Zero paths to roots is EXPECTED for an unreachable leaked "
                 "cycle -- it is not a failed query. Distinguish it from a "
                 "filtered or incomplete graph. Inspect every incoming path "
                 "before proposing to remove one owner."),
    }


# --------------------------------------------------------------------------
# diff
# --------------------------------------------------------------------------

def diff(before: Path, after: Path) -> Dict[str, Any]:
    require_graph(before)
    require_graph(after)

    h = run(["heap", "-diffFrom", str(before), str(after)])
    l = run(["leaks", f"--diffFrom={before}", str(after)])

    new_classes = []
    for line in h["stdout"].splitlines():
        m = CLASS_ROW.match(line)
        if m:
            new_classes.append({"class": m.group(3), "count": int(m.group(1)),
                                "bytes": m.group(2)})

    return {
        "before": str(before),
        "after": str(after),
        "heapDiffExit": h["exit"],
        "newOrGrown": new_classes[:30],
        "leaks": interpret_leaks(l, ["--diffFrom"]),
        "note": ("Addresses are reused and are not durable identity. Compare "
                 "same-process checkpoints only; across launches compare types "
                 "and normalised stacks, never pointers."),
    }


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _render_summary(d: Dict[str, Any]) -> None:
    a = d["artifact"]
    print(f"\n{d['graph']}")
    print(f"  {human_bytes(a['bytes'])}  format {a['magic']}  "
          f"allocation history: {'yes' if a['fullStackHistory'] else 'no'}")
    print(f"\n  physical footprint : {d['physicalFootprint'] or '—'}")
    print(f"  heap               : {d['nodesMalloced'] or '—'} nodes, "
          f"{d['heapTotal'] or '—'}")
    lk = d["leaks"]
    print(f"  scanner            : {lk['finding']}", end="")
    if lk["leakCount"] is not None:
        print(f"  ({lk['leakCount']} leaks, {lk['leakedBytes']:,} bytes)")
    else:
        print()
    print(f"\n  {d['note']}")
    if d["historyNote"]:
        print(f"  {d['historyNote']}")
    print()


def _render_classes(d: Dict[str, Any]) -> None:
    print(f"\n{d['total']} class(es)"
          f"{' matching ' + repr(d['match']) if d['match'] else ''}\n")
    for c in d["classes"]:
        print(f"  {c['count']:>8}  {c['bytes']:>10}  {c['class']}")
    if d["truncated"]:
        print(f"  … truncated")
    print(f"\n  {d['note']}\n")


def _render_objects(d: Dict[str, Any]) -> None:
    print(f"\npattern {d['pattern']!r} — {d['status']}")
    if d["status"] == "ok":
        print(f"  {d['count']} instance(s)\n")
        for o in d["objects"]:
            print(f"    {o['address']}  {o['class']}  ({o['bytes']} bytes)")
        if d["truncated"]:
            print("    … truncated")
    else:
        print(f"\n  {d['detail']}")
    print()


def _render_layout(d: Dict[str, Any]) -> None:
    print(f"\n{d['address']}")
    if d["referencesToThis"] is not None:
        print(f"  REFERENCES TO THIS: {d['referencesToThis']}")
    if d["fields"]:
        print("\n  fields")
        for f in d["fields"]:
            tgt = f"  --> {f['target']}" if f["target"] else ""
            print(f"    +{f['offset']:<4} {f['name']:<22} {f['type']}{tgt}")
    for label, rows in (("outgoing", d["outgoing"]), ("incoming", d["incoming"])):
        if rows:
            print(f"\n  {label}")
            for r in rows[:8]:
                print(f"    {r[:96]}")
    print(f"\n  {d['note']}\n")


def _render_paths(d: Dict[str, Any]) -> None:
    print(f"\n{d['address']} — {d['rootPathLines']} line(s) of root-path output\n")
    for line in d["traceTree"].splitlines()[:20]:
        print(f"  {line[:100]}")
    print(f"\n  {d['note']}\n")


def _render_diff(d: Dict[str, Any]) -> None:
    print(f"\n{len(d['newOrGrown'])} class(es) new or grown\n")
    for c in d["newOrGrown"]:
        print(f"  {c['count']:>8}  {c['bytes']:>10}  {c['class']}")
    lk = d["leaks"]
    print(f"\n  leaks diff: {lk['finding']}", end="")
    print(f"  ({lk['leakCount']} leaks)" if lk["leakCount"] is not None else "")
    print(f"\n  {d['note']}\n")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command",
                   choices=["summary", "classes", "objects", "layout", "paths", "diff"])
    p.add_argument("graph", type=Path)
    p.add_argument("target", nargs="?", help="class pattern, address, or after-graph")
    p.add_argument("--match", help="classes: substring filter")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    try:
        if args.command == "summary":
            result, render = summary(args.graph), _render_summary
        elif args.command == "classes":
            result, render = classes(args.graph, args.match, args.limit), _render_classes
        elif args.command == "objects":
            if not args.target:
                p.error("objects requires a class pattern")
            result, render = objects(args.graph, args.target, args.limit), _render_objects
        elif args.command == "layout":
            if not args.target:
                p.error("layout requires an address")
            result, render = layout(args.graph, args.target), _render_layout
        elif args.command == "paths":
            if not args.target:
                p.error("paths requires an address")
            result, render = paths(args.graph, args.target), _render_paths
        else:
            if not args.target:
                p.error("diff requires an after-graph")
            result, render = diff(args.graph, Path(args.target)), _render_diff
    except ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        render(result)

    if args.command == "objects" and result["status"] != "ok":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
