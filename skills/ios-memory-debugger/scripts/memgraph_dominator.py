#!/usr/bin/env python3
"""Dominator-tree, whole-graph and allocator analysis over a captured memgraph.

Imported by memgraph_query.py; not a command on its own.

WHAT A DOMINATOR TREE GIVES YOU

`leaks --dominatorTree` is not listed in `leaks --help` -- it appears only inside
the description of `--groupByType` -- and it is in no man page. It works, and it
computes the quantity the research corpus declares unavailable.

From the tool's own output header:

    In a dominator tree a node(X) can be a descendant of node(Y) only if all
    paths of owning references from root nodes to node(X) go through node(Y).
    Each line shows:
      1. The total count of allocations for this node and all descendants.
      2. The total size of allocations for this node and all descendants.

Line 2 is retained size. Measured: 2.4 s over a 355,948-node real iOS app graph,
and 0.5 s over a 71,234-node capture taken with NO MallocStackLogging -- so it
needs no instrumented relaunch.

It is still a conservative scanner's view. Report "N bytes dominated by this node
in this capture", never "freeing this frees N bytes".
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from memgraph_util import ToolError, human_bytes, require_graph, run  # noqa: E402

# `   + ! 3 (160K) retainedCache --> <NSMutableArray 0x…> [48]`
# The indent carries the nesting and MUST NOT be stripped: `+ ! ` and `+ !   `
# are different depths distinguished only by trailing spaces.
DOM_LINE = re.compile(
    r"^(?P<indent>[ +!]*?)(?P<count>\d+) \((?P<size>[\d.]+\s*(?:bytes?|[KMG]B?))\)\s*(?P<rest>.*)$")
SIZE = re.compile(r"^([\d.]+)\s*(bytes?|KB?|MB?|GB?)$", re.I)
NODE = re.compile(r"<(?P<class>.+?) (?P<addr>0x[0-9a-f]+)>(?:\s*\[(?P<bytes>\d+)\])?")
REF = re.compile(r"^(?P<ref>.+?)\s+-->\s+")
VM_ROW = re.compile(r"^VM:\s+(?P<region>\S+)")

_MULT = {"byte": 1, "bytes": 1, "k": 1024, "kb": 1024,
         "m": 1024**2, "mb": 1024**2, "g": 1024**3, "gb": 1024**3}


def parse_size(text: str) -> Optional[int]:
    m = SIZE.match(text.strip())
    if not m:
        return None
    unit = m.group(2).lower()
    return int(float(m.group(1)) * _MULT.get(unit, 1))


def _dominator_rows(graph: Path, virtual: bool = False) -> List[Dict[str, Any]]:
    argv = ["leaks", "--dominatorTree"]
    if virtual:
        # Sizes VM regions as virtual rather than dirty+compressed. On one
        # fixture this moved the total from 978 K to 72.3 M -- a different
        # accounting domain, not a more accurate number.
        argv.append("--virtual")
    result = run(argv + [str(graph)], timeout=900)
    if result["exit"] not in (0, 1):
        raise ToolError(f"leaks --dominatorTree failed ({result['exit']}): "
                        f"{(result['stderr'] or '')[:300]}")

    body = result["stdout"]
    start = body.find("<< TOTAL >>")
    if start < 0:
        raise ToolError("no dominator tree in output; the graph may be unreadable")
    body = body[body.rfind("\n", 0, start) + 1:]

    rows: List[Dict[str, Any]] = []
    stack: List[tuple] = []          # (indent_width, row_index)
    for line in body.splitlines():
        m = DOM_LINE.match(line)
        if not m:
            continue
        width = len(m.group("indent"))
        rest = m.group("rest")

        while stack and stack[-1][0] >= width:
            stack.pop()
        parent = stack[-1][1] if stack else None

        node = NODE.search(rest)
        ref = REF.match(rest)
        vm = VM_ROW.match(rest)

        rows.append({
            "index": len(rows),
            "depth": len(stack),
            "parent": parent,
            "count": int(m.group("count")),
            "retainedBytes": parse_size(m.group("size")),
            "referenceName": ref.group("ref").strip() if ref else None,
            "class": node.group("class") if node else None,
            "address": node.group("addr") if node else None,
            "ownBytes": int(node.group("bytes")) if (node and node.group("bytes")) else None,
            "vmRegion": vm.group("region") if vm else None,
            "isTotal": "<< TOTAL >>" in rest,
            "text": rest.strip(),
        })
        stack.append((width, len(rows) - 1))
    return rows


# --------------------------------------------------------------------------
# retained
# --------------------------------------------------------------------------

def retained(graph: Path, address: Optional[str] = None,
             virtual: bool = False, limit: int = 25) -> Dict[str, Any]:
    """How much does a node dominate -- i.e. what would freeing it release?"""
    require_graph(graph)
    rows = _dominator_rows(graph, virtual)
    total = next((r for r in rows if r["isTotal"]), None)

    if address:
        hits = [r for r in rows if r["address"] == address]
        if not hits:
            return {"address": address, "found": False, "total": total,
                    "detail": (f"{address} is not a dominator-tree node. It may be "
                               f"dominated by something else and therefore appear "
                               f"only as a descendant, or it may not be in this "
                               f"capture. Use `paths` to find what retains it.")}
        best = max(hits, key=lambda r: r["retainedBytes"] or 0)
        children = [r for r in rows if r["parent"] == best["index"]]
        chain, cur = [], best
        while cur["parent"] is not None:
            cur = rows[cur["parent"]]
            chain.append(cur)
        return {
            "address": address, "found": True, "node": best,
            "children": sorted(children, key=lambda r: r["retainedBytes"] or 0,
                               reverse=True)[:limit],
            "ownerChain": list(reversed(chain)),
            "total": total,
            "note": ("`retainedBytes` is the total for this node and everything it "
                     "dominates, from a conservative scanner. Report it as "
                     "'dominated in this capture', not as guaranteed reclaimable."),
        }

    roots = [r for r in rows if r["depth"] == 1]
    return {
        "address": None, "found": True, "total": total,
        "roots": sorted(roots, key=lambda r: r["retainedBytes"] or 0,
                        reverse=True)[:limit],
        "rowCount": len(rows),
        "note": "Top-level dominators, ranked by what each retains.",
    }


# --------------------------------------------------------------------------
# biggest -- ownership-ranked, not class-ranked
# --------------------------------------------------------------------------

def biggest(graph: Path, limit: int = 25, min_bytes: int = 4096,
            virtual: bool = False, include_vm: bool = False) -> Dict[str, Any]:
    """Rank nodes by what they retain, skipping pure pass-through links.

    `heap -sortBySize` ranks by class total, which answers "what type is
    numerous". This answers "which single object is holding the memory", which
    is the actionable question when something is too big.
    """
    require_graph(graph)
    rows = _dominator_rows(graph, virtual)
    total = next((r for r in rows if r["isTotal"]), None)

    children_of: Dict[Optional[int], List[Dict[str, Any]]] = {}
    for r in rows:
        children_of.setdefault(r["parent"], []).append(r)

    ranked = []
    for r in rows:
        if r["isTotal"] or (r["retainedBytes"] or 0) < min_bytes:
            continue
        # VM regions are containers, not owners anyone can act on. At real-app
        # scale they dominate the ranking and bury the objects, so they are
        # excluded unless asked for.
        if r["vmRegion"] and not include_vm:
            continue
        # Ownership chains look like array -> storage -> data -> bytes, every
        # link retaining the same total. The informative node is the TOP of the
        # chain -- the one a developer can act on -- so drop a node whose parent
        # retains exactly the same bytes, keeping the highest link.
        parent = rows[r["parent"]] if r["parent"] is not None else None
        if (parent and not parent["isTotal"]
                and parent["retainedBytes"] == r["retainedBytes"]):
            continue
        own = r["ownBytes"] or 0
        ranked.append({**r, "amplification": (
            round((r["retainedBytes"] or 0) / own, 1) if own else None),
            "childCount": len(children_of.get(r["index"], []))})

    ranked.sort(key=lambda r: r["retainedBytes"] or 0, reverse=True)
    return {
        "total": total,
        "nodes": ranked[:limit],
        "consideredRows": len(rows),
        "minBytes": min_bytes,
        "includesVMRegions": include_vm,
        "note": ("Ranked by retained bytes, not by class total. `amplification` "
                 "is retained / own size -- a small object with high "
                 "amplification is holding a large backing store."),
    }


# --------------------------------------------------------------------------
# graph -- bulk edge extraction with honest coverage
# --------------------------------------------------------------------------

EDGE = re.compile(r"-->")
OWNERSHIP = re.compile(r"__(strong|weak|unsafe_unretained)")
SCANNING = re.compile(r"^SCANNING <(?P<class>.+?) (?P<addr>0x[0-9a-f]+)> \[(?P<bytes>\d+)\]")


def graph_edges(graph: Path, limit: int = 0) -> Dict[str, Any]:
    """Extract the reference graph, and report how much of it is unknown.

    One unfiltered `leaks --debug=layout` yields the whole thing: measured at
    967,750 edges in 10.5 s over a 355,948-node app. The per-address walk the
    research corpus proposes would take 3.7 hours for the same graph.
    """
    require_graph(graph)
    result = run(["leaks", "--debug=layout", str(graph)], timeout=1800)
    if result["exit"] not in (0, 1):
        raise ToolError(f"bulk layout dump failed ({result['exit']})")

    out = result["stdout"]
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []
    interior = unresolved = 0
    current: Optional[str] = None

    for line in out.splitlines():
        s = SCANNING.match(line)
        if s:
            current = s.group("addr")
            nodes.setdefault(current, {"class": s.group("class"),
                                       "bytes": int(s.group("bytes"))})
            continue
        if not current or "-->" not in line:
            continue
        lhs, rhs = line.split("-->", 1)
        target = NODE.search(rhs)
        if not target:
            unresolved += 1
            continue
        if "bytes into" in rhs:
            interior += 1
        own = OWNERSHIP.search(lhs)
        off = re.search(r"\+?(\d+):", lhs)
        field = re.search(r"(\b_\w+(?:\.\w+)*)\s*$", lhs.strip())
        edges.append({
            "from": current, "to": target.group("addr"),
            "offset": int(off.group(1)) if off else None,
            "ownership": own.group(0) if own else None,
            "field": field.group(1) if field else None,
        })

    with_out = {e["from"] for e in edges}
    by_own: Dict[str, int] = {}
    for e in edges:
        by_own[e["ownership"] or "(unnamed offset)"] = \
            by_own.get(e["ownership"] or "(unnamed offset)", 0) + 1

    coverage = len(with_out) / len(nodes) if nodes else 0
    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "nodesWithKnownOutgoing": len(with_out),
        "coverage": round(coverage, 4),
        "byOwnership": by_own,
        "interiorPointers": interior,
        "unresolvedTargets": unresolved,
        "edgeSample": edges[:limit] if limit else [],
        "note": (f"{len(nodes) - len(with_out)} node(s) show no outgoing edges. "
                 f"A node with no layout and a node with no pointers are "
                 f"INDISTINGUISHABLE here, so this graph is a lower bound. Do "
                 f"not compute dominators or exact retained size from it -- use "
                 f"`retained`, which uses the scanner's own dominator tree."),
    }


# --------------------------------------------------------------------------
# zones -- fragmentation versus retention
# --------------------------------------------------------------------------

ZONE = re.compile(r"^Zone (?P<zone>\S+): Overall size: (?P<cap>[\d.]+\w*); "
                  r"(?P<nodes>\d+) nodes malloced for (?P<live>[\d.]+\w*) "
                  r"\((?P<pct>\d+)% of capacity\)")


def zones(graph: Path) -> Dict[str, Any]:
    """Allocator capacity versus live payload.

    A zone at a few percent utilisation is a fragmentation signal, not a
    retained-object problem -- reaching for the reference graph there wastes
    the investigation.
    """
    require_graph(graph)
    result = run(["heap", "-z", str(graph)], timeout=600)
    found = []
    for line in result["stdout"].splitlines():
        m = ZONE.match(line.strip())
        if m:
            found.append({
                "zone": m.group("zone"),
                "capacity": parse_size(m.group("cap").replace("KB", " KB")
                                       .replace("MB", " MB")) or m.group("cap"),
                "capacityText": m.group("cap"),
                "nodes": int(m.group("nodes")),
                "liveText": m.group("live"),
                "utilisationPercent": int(m.group("pct")),
            })
    low = [z for z in found if z["utilisationPercent"] <= 25]
    return {
        "zones": found,
        "lowUtilisation": low,
        "note": ("Low utilisation means the allocator holds pages the program is "
                 "not using. That is fragmentation or churn, and no amount of "
                 "reference-graph analysis will explain it."
                 if low else
                 "No zone is unusually under-utilised in this capture."),
    }


# --------------------------------------------------------------------------
# history
# --------------------------------------------------------------------------

HISTORY_MODES = {
    "by-size": ["-allBySize"],
    "by-count": ["-allByCount"],
    "events": ["-allEvents"],
    "call-tree": ["-callTree"],
    "peak": ["-highWaterMark", "-callTree"],
}


def history(graph: Path, mode: str = "by-size", limit: int = 30) -> Dict[str, Any]:
    """Allocation provenance. Requires the target to have run with logging.

    `peak` additionally requires FULL MallocStackLogging -- lite records current
    allocations only, with no history to find a high-water mark in.
    """
    info = require_graph(graph)
    if mode not in HISTORY_MODES:
        raise ToolError(f"mode must be one of: {', '.join(HISTORY_MODES)}")

    result = run(["malloc_history", str(graph)] + HISTORY_MODES[mode], timeout=900)
    out = result["stdout"]

    peak = None
    m = re.search(r"High water mark of allocated heap \+ VM memory:\s*(.+?)\s*"
                  r"at malloc stack log record index\s*(\d+)", out)
    if m:
        peak = {"highWaterMark": m.group(1).strip(), "recordIndex": int(m.group(2))}
    fp = re.search(r"Physical footprint \(peak\):\s*(\S+)", out)

    body = [l for l in out.splitlines() if l.strip()]
    header_end = next((i for i, l in enumerate(body)
                       if l.startswith("----")), 12)

    return {
        "mode": mode,
        "exit": result["exit"],
        "hasAllocationHistory": info.get("fullStackHistory", False),
        "lines": len(body),
        "highWaterMark": peak,
        "physicalFootprintPeak": fp.group(1) if fp else None,
        "sample": body[header_end:header_end + limit],
        "note": (None if info.get("fullStackHistory") else
                 "This graph was captured WITHOUT --fullStackHistory, so it "
                 "carries no allocation history. Provenance and peak queries "
                 "will be empty -- that is a capture limitation, not a finding."),
        "peakNote": ("Physical footprint peak and heap+VM high-water mark are "
                     "different quantities measured differently. Never "
                     "substitute one for the other."),
    }
