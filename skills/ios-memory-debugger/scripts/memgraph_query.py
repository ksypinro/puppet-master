#!/usr/bin/env python3
"""Query a captured memory graph without inventing certainty.

    summary  <graph>                  footprint, heap and scanner totals
    classes  <graph> [--match TEXT]   list real class names (find the full one)
    objects  <graph> <class>          instances, with a full-match guard
    layout   <graph> <address>        fields, offsets, incoming/outgoing edges
    paths    <graph> <address>        retaining paths toward roots
    diff     <before> <after>         what changed between two checkpoints

    retained <graph> [address]        what a node dominates -- retained size
    biggest  <graph>                  ranked by ownership, not by class total
    graph    <graph>                  the reference graph, with honest coverage
    zones    <graph>                  allocator capacity vs live payload
    history  <graph> [--mode M]       allocation provenance and peak

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
from memgraph_dominator import (  # noqa: E402
    HISTORY_MODES, biggest, graph_edges, history, retained, zones,
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


def _n(v):
    return f"{v:,}" if isinstance(v, int) else "—"


def _render_retained(d: Dict[str, Any]) -> None:
    tot = d.get("total") or {}
    print(f"\ntotal dominated: {_n(tot.get('retainedBytes'))} bytes "
          f"across {_n(tot.get('count'))} allocations\n")

    if d["address"] and not d["found"]:
        print(f"  {d['detail']}\n")
        return

    if d["address"]:
        n = d["node"]
        own = n["ownBytes"]
        amp = f"  ({n['retainedBytes']/own:,.0f}x its own size)" if own else ""
        print(f"  {n['class']}  {d['address']}")
        if n["referenceName"]:
            print(f"  referenced as: {n['referenceName']}")
        print(f"  own size     : {_n(own)} bytes")
        print(f"  DOMINATES    : {_n(n['retainedBytes'])} bytes "
              f"across {_n(n['count'])} allocations{amp}")
        if d["ownerChain"]:
            chain = " → ".join((o["vmRegion"] or o["class"] or "TOTAL")
                               for o in d["ownerChain"])
            print(f"  owned via    : {chain}")
        if d["children"]:
            print("\n  it dominates:")
            for c in d["children"][:8]:
                print(f"    {_n(c['retainedBytes']):>12}  "
                      f"{(c['class'] or c['text'])[:52]}")
    else:
        print("  top-level dominators")
        for r in d["roots"]:
            print(f"    {_n(r['retainedBytes']):>12}  "
                  f"{(r['vmRegion'] or r['class'] or r['text'])[:56]}")
    print(f"\n  {d['note']}\n")


def _render_biggest(d: Dict[str, Any]) -> None:
    print(f"\nranked by retained bytes (min {_n(d['minBytes'])})\n")
    print(f"  {'retained':>12}  {'own':>9}  {'amp':>9}  what")
    print("  " + "-" * 74)
    for n in d["nodes"]:
        amp = f"{n['amplification']:,.0f}x" if n.get("amplification") else "—"
        label = (n["class"] or n["vmRegion"] or n["text"])[:34]
        ref = f"  {n['referenceName']}" if n.get("referenceName") else ""
        print(f"  {_n(n['retainedBytes']):>12}  {_n(n['ownBytes']):>9}  "
              f"{amp:>9}  {label}{ref[:24]}")
    print(f"\n  {d['note']}\n")


def _render_graph(d: Dict[str, Any]) -> None:
    print(f"\n{_n(d['nodes'])} nodes · {_n(d['edges'])} edges · "
          f"coverage {d['coverage']*100:.0f}%\n")
    for k, v in sorted(d["byOwnership"].items(), key=lambda kv: -kv[1]):
        print(f"    {v:>9,}  {k}")
    print(f"\n    {d['interiorPointers']:>9,}  interior pointers")
    print(f"    {d['unresolvedTargets']:>9,}  unresolved targets")
    print(f"\n  {d['note']}\n")


def _render_zones(d: Dict[str, Any]) -> None:
    print()
    for z in d["zones"]:
        flag = "!" if z["utilisationPercent"] <= 25 else " "
        print(f"  {flag} {z['zone'][:40]:42s} capacity {z['capacityText']:>10}  "
              f"live {z['liveText']:>9}  {z['utilisationPercent']:>3}% used")
    print(f"\n  {d['note']}\n")


def _render_history(d: Dict[str, Any]) -> None:
    print(f"\nmode: {d['mode']}   allocation history in graph: "
          f"{'yes' if d['hasAllocationHistory'] else 'NO'}")
    if d["highWaterMark"]:
        print(f"  high water mark : {d['highWaterMark']['highWaterMark']} "
              f"(record {d['highWaterMark']['recordIndex']})")
    if d["physicalFootprintPeak"]:
        print(f"  physical peak   : {d['physicalFootprintPeak']}")
    if d["highWaterMark"] or d["physicalFootprintPeak"]:
        print(f"  {d['peakNote']}")
    if d["sample"]:
        print()
        for line in d["sample"][:18]:
            print(f"  {line[:100]}")
    if d.get("note"):
        print(f"\n  {d['note']}")
    print()


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command",
                   choices=["summary", "classes", "objects", "layout", "paths",
                            "diff", "retained", "biggest", "graph", "zones",
                            "history"])
    p.add_argument("graph", type=Path)
    p.add_argument("target", nargs="?", help="class pattern, address, or after-graph")
    p.add_argument("--match", help="classes: substring filter")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--mode", default="by-size",
                   help=f"history mode: {', '.join(HISTORY_MODES)}")
    p.add_argument("--min-bytes", type=int, default=4096,
                   help="biggest: ignore nodes retaining less than this")
    p.add_argument("--include-vm", action="store_true",
                   help="biggest: include VM regions, not only objects")
    p.add_argument("--virtual", action="store_true",
                   help="size VM regions as virtual rather than dirty+compressed")
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
        elif args.command == "diff":
            if not args.target:
                p.error("diff requires an after-graph")
            result, render = diff(args.graph, Path(args.target)), _render_diff
        elif args.command == "retained":
            result = retained(args.graph, args.target, args.virtual, args.limit)
            render = _render_retained
        elif args.command == "biggest":
            result = biggest(args.graph, args.limit, args.min_bytes,
                             args.virtual, args.include_vm)
            render = _render_biggest
        elif args.command == "graph":
            result, render = graph_edges(args.graph), _render_graph
        elif args.command == "zones":
            result, render = zones(args.graph), _render_zones
        else:
            result, render = history(args.graph, args.mode, args.limit), _render_history
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
