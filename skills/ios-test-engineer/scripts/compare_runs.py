#!/usr/bin/env python3
"""Compare result bundles, and aggregate a matrix of them.

    compare  <candidate> --base <baseline>   introduced / resolved deltas
    merge    <bundle> [<bundle> ...] --out   one bundle from many
    matrix   <bundle> [<bundle> ...]         per-cell verdicts + correlation hypotheses

Add --json for machine-readable output. `--fail-on-introduced` exits non-zero
when a comparison introduces anything or its bundle evidence is not gate-ready.

WHY EACH EXISTS

`compare` is one input to a PR gate. Gate on `introduced`, report `resolved`,
and separately establish run completeness and comparable build provenance. It
also surfaces `testsExecuted.removed` --
a test that disappears (deleted, skipped, or lost to a scheme change) makes the
suite greener while making it weaker, and a plain pass/fail gate cannot see it.

`matrix` answers the question a naive count cannot. "4 of 40 failed" is three
different situations needing three different responses:

    4 different tests in 4 cells   -> four independent failures, triage each
    1 test failing in 4 cells      -> one bug with platform reach, fix once
    4 tests failing in 1 cell      -> that destination is unhealthy, fix the cell

It groups by testIdentifierURL across cells and by destination, and says which
pattern it found.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from xcresult_util import (  # noqa: E402
    TIMEOUTS, ToolError, resolve_bundle, xcresulttool,
)
from test_results import hidden_flakes  # noqa: E402

DEFAULT_TIMEOUT = TIMEOUTS["compare"]


# --------------------------------------------------------------------------
# compare
# --------------------------------------------------------------------------

def compare(candidate: Path, baseline: Path) -> Dict[str, Any]:
    # `compare` emits JSON natively and rejects --format, unlike `get`.
    raw = json.loads(xcresulttool([
        "compare", str(candidate), "--baseline-path", str(baseline),
        "--summary", "--test-failures"]))

    summary = raw.get("summary", {}) or {}
    introduced = {}
    resolved = {}
    for key in ("testFailures", "buildWarnings", "analyzerIssues"):
        block = summary.get(key, {}) or {}
        introduced[key] = block.get("introduced", 0)
        resolved[key] = block.get("resolved", 0)

    executed = summary.get("testsExecuted", {}) or {}
    total_introduced = sum(introduced.values())

    candidate_cell = _cell(candidate)
    baseline_cell = _cell(baseline)
    comparable_results = (candidate_cell["effectiveResult"] != "Incomplete" and
                          baseline_cell["effectiveResult"] != "Incomplete")
    warnings = (
        ["Tests disappeared between runs. A suite that shrinks looks greener "
         "while covering less -- confirm this was intentional."]
        if executed.get("removed") else [])
    if not comparable_results:
        warnings.append("At least one bundle is incomplete or contains zero tests; "
                        "the comparison cannot support a gate.")
    if candidate_cell["hiddenFlakeCount"]:
        warnings.append("The candidate reports Passed while one or more failed "
                        "repetitions remain in its hierarchy; it is not clean.")

    verdict = "inconclusive" if not comparable_results else (
        "regressed" if total_introduced else
        "improved" if sum(resolved.values()) else "unchanged")

    return {
        "candidate": str(candidate),
        "baseline": str(baseline),
        "introduced": introduced,
        "resolved": resolved,
        "totalIntroduced": total_introduced,
        "testsExecuted": {
            "added": executed.get("added", 0),
            "removed": executed.get("removed", 0),
            "inBaseline": executed.get("itemsInBaseline", 0),
            "inCurrent": executed.get("itemsInCurrent", 0),
        },
        "detail": raw.get("testFailures"),
        "verdict": verdict,
        "candidateRun": candidate_cell,
        "baselineRun": baseline_cell,
        "gateReady": (comparable_results and not executed.get("removed") and
                      candidate_cell["effectiveResult"] == "Passed"),
        "requiredExternalCheck": ("Compare manifest build identity, scheme, plan, "
                                  "configuration and destination before treating "
                                  "these deltas as causal."),
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# merge
# --------------------------------------------------------------------------

def merge(bundles: List[Path], out: Path) -> Dict[str, Any]:
    if len(bundles) < 2:
        raise ToolError("merge needs at least two bundles")
    out = out.expanduser().resolve()
    if out.exists():
        raise ToolError(f"{out} already exists; choose a new --out")
    xcresulttool(["merge"] + [str(b) for b in bundles] +
                 ["--output-path", str(out)], timeout=TIMEOUTS["merge"])
    return {
        "merged": [str(b) for b in bundles],
        "output": str(out),
        "note": ("Keep the per-cell bundles. The merged bundle answers 'did the "
                 "suite pass'; only the individual ones answer 'which cell "
                 "failed', which is the point of a matrix."),
    }


# --------------------------------------------------------------------------
# matrix
# --------------------------------------------------------------------------

def _cell(bundle: Path) -> Dict[str, Any]:
    raw = json.loads(xcresulttool(
        ["get", "test-results", "summary", "--path", str(bundle),
         "--format", "json"]))
    devices = []
    for dc in raw.get("devicesAndConfigurations", []) or []:
        dev = dc.get("device", {}) or {}
        devices.append({
            "name": dev.get("deviceName"),
            "platform": dev.get("platform"),
            "os": dev.get("osVersion"),
            "osBuild": dev.get("osBuildNumber"),
            "deviceId": dev.get("deviceId"),
            "configuration": (dc.get("testPlanConfiguration") or {}).get(
                "configurationName"),
        })
    label = "unknown"
    if devices:
        d = devices[0]
        label = (f"{d['name']} {d['os']} ({d['osBuild']}) "
                 f"[{d['deviceId']}] / {d['configuration']}")
    recorded = raw.get("result")
    total = raw.get("totalTestCount", 0)
    hidden = hidden_flakes(bundle) if total else []
    effective = ("Incomplete" if not total or recorded not in ("Passed", "Failed")
                 else "PassedWithHiddenFailures"
                 if recorded == "Passed" and hidden else recorded)
    hidden_failures = [
        {"identifier": h.get("identifier"), "url": None,
         "text": "failed a repetition before the reported pass",
         "hiddenRetryFailure": True}
        for h in hidden
    ]
    return {
        "bundle": str(bundle),
        "cellKey": str(bundle),
        "label": label,
        "result": recorded,
        "effectiveResult": effective,
        "devices": devices,
        "totalTestCount": raw.get("totalTestCount", 0),
        "failedTests": raw.get("failedTests", 0),
        "hiddenFlakeCount": len(hidden),
        "failures": [
            {"identifier": f.get("testIdentifierString"),
             "url": f.get("testIdentifierURL"),
             "text": (f.get("failureText") or "").strip()}
            for f in raw.get("testFailures", []) or []
        ] + hidden_failures,
    }


def matrix(bundles: List[Path]) -> Dict[str, Any]:
    cells = [_cell(b) for b in bundles]

    by_test: Dict[str, List[str]] = defaultdict(list)
    by_cell: Dict[str, List[str]] = defaultdict(list)
    labels = {c["cellKey"]: c["label"] for c in cells}
    for c in cells:
        for f in c["failures"]:
            key = f["url"] or f["identifier"] or "?"
            by_test[key].append(c["cellKey"])
            by_cell[c["cellKey"]].append(key)

    total_failures = sum(len(c["failures"]) for c in cells)
    failing_cells = [c for c in cells if c["effectiveResult"] != "Passed"]

    # Correlation hypotheses, not root-cause attribution.
    patterns = []
    cross_platform = {t: sorted(set(cs)) for t, cs in by_test.items()
                      if len(set(cs)) > 1}
    if cross_platform:
        patterns.append({
            "pattern": "same-test-many-cells",
            "confidence": "hypothesis",
            "detail": [{"test": t,
                        "cells": [{"key": key, "label": labels[key]} for key in cs]}
                       for t, cs in cross_platform.items()],
            "action": ("The same test failed in several cells. Compare failure "
                       "text, source location and diagnostics before deciding "
                       "whether it is one shared product defect."),
        })
    for cell_key, tests_failed in by_cell.items():
        distinct = set(tests_failed)
        if len(distinct) >= 3:
            patterns.append({
                "pattern": "unhealthy-cell",
                "confidence": "hypothesis",
                "detail": {"cellKey": cell_key, "cell": labels[cell_key],
                           "distinctFailures": len(distinct)},
                "action": ("Several distinct tests failed in one cell. That makes "
                           "the destination a useful hypothesis; correlate its "
                           "diagnostics before assigning cause."),
            })
    independent = [t for t, cs in by_test.items() if len(set(cs)) == 1]
    if independent and not patterns:
        patterns.append({
            "pattern": "independent-failures",
            "detail": {"count": len(independent)},
            "action": "Failures appear unrelated. Triage each on its own.",
        })

    return {
        "cellCount": len(cells),
        "cells": cells,
        "passedCells": len(cells) - len(failing_cells),
        "failingCells": [c["label"] for c in failing_cells],
        "totalFailures": total_failures,
        "distinctFailingTests": len(by_test),
        "hypotheses": patterns,
        # Compatibility alias for v1 consumers. These are hypotheses, not
        # established attribution.
        "attribution": patterns,
        "note": ("Cells that were never run do not appear here. State skipped "
                 "or invalid combinations explicitly -- a matrix with unstated "
                 "gaps reads as more coverage than it is."),
    }


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _render_compare(d: Dict[str, Any]) -> None:
    print(f"\n{d['verdict'].upper()}\n")
    print(f"  {'category':18s} {'introduced':>11s} {'resolved':>9s}")
    for key in d["introduced"]:
        intro, res = d["introduced"][key], d["resolved"][key]
        mark = "  <-- blocks" if intro else ""
        print(f"  {key:18s} {intro:>11d} {res:>9d}{mark}")
    e = d["testsExecuted"]
    print(f"\n  tests executed: {e['inBaseline']} -> {e['inCurrent']}"
          f"   added {e['added']}   removed {e['removed']}")
    for w in d["warnings"]:
        print(f"\n  ! {w}")
    print(f"\n  gate ready: {'yes' if d['gateReady'] else 'no'}")
    print(f"  {d['requiredExternalCheck']}")
    print()


def _render_matrix(d: Dict[str, Any]) -> None:
    print(f"\n{d['passedCells']}/{d['cellCount']} cells passed   "
          f"{d['totalFailures']} failure(s) across "
          f"{d['distinctFailingTests']} distinct test(s)\n")
    for c in d["cells"]:
        mark = "✓" if c["effectiveResult"] == "Passed" else "✗"
        print(f"  {mark} {c['label'][:48]:50s} {c['effectiveResult']:24s} "
              f"{c['totalTestCount']:3d} tests, {c['failedTests']} failed")
    if d["attribution"]:
        print("\n  correlation hypotheses")
        for p in d["attribution"]:
            print(f"    [{p['pattern']}]")
            print(f"      {p['action']}")
            if p["pattern"] == "same-test-many-cells":
                for item in p["detail"]:
                    short = (item["test"] or "").rsplit("/", 1)[-1]
                    print(f"        {short} — {len(item['cells'])} cells")
    print(f"\n  {d['note']}\n")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["compare", "merge", "matrix"])
    p.add_argument("bundles", nargs="+", type=Path)
    p.add_argument("--base", type=Path, help="baseline bundle (compare)")
    p.add_argument("--out", type=Path, help="output bundle (merge)")
    p.add_argument("--fail-on-introduced", action="store_true",
                   help="compare: exit 1 when anything is introduced")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    try:
        bundles = [resolve_bundle(b) for b in args.bundles]
        if args.command == "compare":
            if not args.base:
                p.error("compare requires --base")
            result = compare(bundles[0], resolve_bundle(args.base))
            render = _render_compare
        elif args.command == "merge":
            if not args.out:
                p.error("merge requires --out")
            result = merge(bundles, args.out)
            render = lambda d: print(f"\nmerged {len(d['merged'])} bundles -> "
                                     f"{d['output']}\n\n  {d['note']}\n")
        else:
            result = matrix(bundles)
            render = _render_matrix
    except (ToolError, subprocess.TimeoutExpired) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        render(result)

    if args.command == "compare" and args.fail_on_introduced:
        return 1 if result["totalIntroduced"] or not result["gateReady"] else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
