#!/usr/bin/env python3
"""Extract XCTest performance metrics from an xcresult, compute robust summaries, and compare with a baseline."""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


# Below this many values per side a comparison reports deltas but no verdict.
MIN_COMPARE_SAMPLES = 5


def quantile_type7(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("quantile requires at least one value")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def stats(values: Iterable[float]) -> dict[str, Any]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return {"count": 0}
    median = statistics.median(clean)
    absolute_deviations = [abs(value - median) for value in clean]
    result: dict[str, Any] = {
        "count": len(clean),
        "values": clean,
        "min": min(clean),
        "max": max(clean),
        "mean": statistics.fmean(clean),
        "median": median,
        "p90_type7": quantile_type7(clean, 0.90),
        "mad": statistics.median(absolute_deviations),
        "q1_type7": quantile_type7(clean, 0.25),
        "q3_type7": quantile_type7(clean, 0.75),
    }
    result["iqr"] = result["q3_type7"] - result["q1_type7"]
    if len(clean) > 1:
        result["sample_standard_deviation"] = statistics.stdev(clean)
    else:
        result["sample_standard_deviation"] = None
    result["tail_confidence"] = "directional" if len(clean) < 20 else "more-stable"
    return result


def bootstrap_median_delta(baseline: list[float], candidate: list[float], resamples: int, seed: int) -> tuple[float, float]:
    """95% percentile-bootstrap interval for median(candidate) - median(baseline), with a fixed seed."""
    rng = random.Random(seed)
    deltas = []
    for _ in range(resamples):
        resampled_baseline = [rng.choice(baseline) for _ in baseline]
        resampled_candidate = [rng.choice(candidate) for _ in candidate]
        deltas.append(statistics.median(resampled_candidate) - statistics.median(resampled_baseline))
    return quantile_type7(deltas, 0.025), quantile_type7(deltas, 0.975)


def compare_values(baseline: list[float], candidate: list[float], polarity: str | None,
                   resamples: int = 2000, seed: int = 0) -> dict[str, Any]:
    before, after = stats(baseline), stats(candidate)
    if not before["count"] or not after["count"]:
        return {"verdict": "missing-data", "baseline_count": before["count"], "candidate_count": after["count"]}
    delta = after["median"] - before["median"]
    result: dict[str, Any] = {
        "baseline": {key: before[key] for key in ("count", "median", "p90_type7", "mad")},
        "candidate": {key: after[key] for key in ("count", "median", "p90_type7", "mad")},
        "median_delta": delta,
        "median_delta_percent": delta / before["median"] * 100 if before["median"] else None,
        "p90_delta": after["p90_type7"] - before["p90_type7"],
        "hodges_lehmann_delta": statistics.median([after_value - before_value for before_value in baseline for after_value in candidate]),
        "polarity": polarity,
    }
    if min(before["count"], after["count"]) < MIN_COMPARE_SAMPLES:
        result["verdict"] = "insufficient-data"
        return result
    low, high = bootstrap_median_delta(before["values"], after["values"], resamples, seed)
    result["bootstrap_ci95_median_delta"] = [low, high]
    if low <= 0 <= high:
        result["verdict"] = "no-clear-change"
    else:
        higher = low > 0
        if polarity == "prefers smaller":
            result["verdict"] = "regression" if higher else "improvement"
        elif polarity == "prefers larger":
            result["verdict"] = "improvement" if higher else "regression"
        else:
            result["verdict"] = "higher" if higher else "lower"
    return result


def load_xcresult(path: Path, test_id: str | None, timeout: float) -> dict[str, Any]:
    bundle = path.expanduser().resolve()
    if not bundle.exists():
        raise RuntimeError(f"xcresult does not exist: {bundle}")
    argv = [
        "xcrun",
        "xcresulttool",
        "get",
        "test-results",
        "metrics",
        "--path",
        str(bundle),
        "--compact",
    ]
    if test_id:
        argv.extend(["--test-id", test_id])
    try:
        completed = subprocess.run(
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
        raise RuntimeError(f"xcresulttool timed out after {timeout}s") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"xcresulttool failed ({completed.returncode}): {completed.stdout.strip()}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"xcresulttool returned invalid JSON: {exc}") from exc


def collect_metrics(value: Any, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    context = dict(context or {})
    results: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if isinstance(value.get("testIdentifier"), str):
            context["test_identifier"] = value["testIdentifier"]
        if isinstance(value.get("testIdentifierURL"), str):
            context["test_identifier_url"] = value["testIdentifierURL"]
        if isinstance(value.get("device"), dict):
            context["device"] = value["device"]
        if isinstance(value.get("testPlanConfiguration"), dict):
            context["test_plan_configuration"] = value["testPlanConfiguration"]

        required = {"displayName", "unitOfMeasurement", "measurements"}
        if required.issubset(value) and isinstance(value["measurements"], list):
            numeric = [
                float(item)
                for item in value["measurements"]
                if isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(float(item))
            ]
            metric = {
                **context,
                "display_name": value["displayName"],
                "identifier": value.get("identifier"),
                "unit": value["unitOfMeasurement"],
                "measurements": numeric,
                "baseline": {
                    key: value[key]
                    for key in (
                        "baselineName",
                        "baselineAverage",
                        "maxRegression",
                        "maxPercentRegression",
                        "maxStandardDeviation",
                        "maxPercentRelativeStandardDeviation",
                        "polarity",
                    )
                    if key in value
                },
            }
            results.append(metric)
            return results
        for child in value.values():
            results.extend(collect_metrics(child, context))
    elif isinstance(value, list):
        for child in value:
            results.extend(collect_metrics(child, context))
    return results


def group_metrics(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for metric in metrics:
        device = metric.get("device") or {}
        configuration = metric.get("test_plan_configuration") or {}
        key = (
            metric.get("test_identifier") or "",
            metric.get("display_name") or "",
            metric.get("unit") or "",
            device.get("deviceId") or device.get("deviceName") or "",
            configuration.get("configurationId") or configuration.get("configurationName") or "",
        )
        groups[key].append(metric)

    output: list[dict[str, Any]] = []
    for key, items in sorted(groups.items()):
        measurements = [value for item in items for value in item["measurements"]]
        representative = items[0]
        output.append(
            {
                "test_identifier": key[0] or None,
                "display_name": key[1],
                "identifier": representative.get("identifier"),
                "unit": key[2],
                "device": representative.get("device"),
                "test_plan_configuration": representative.get("test_plan_configuration"),
                "baseline": representative.get("baseline"),
                "statistics": stats(measurements),
            }
        )
    return output


def match_key(group: dict[str, Any], match: str, include_device: bool) -> tuple[str, ...]:
    key = [group["display_name"], group["unit"]]
    if match == "test-and-metric":
        key.insert(0, group.get("test_identifier") or "")
    if include_device:
        device = group.get("device") or {}
        key.append(device.get("deviceId") or device.get("deviceName") or "")
    return tuple(key)


def compare_groups(baseline_groups: list[dict[str, Any]], candidate_groups: list[dict[str, Any]], match: str,
                   include_device: bool, resamples: int) -> dict[str, Any]:
    """Pair metric groups from two sources and compare each pair; ambiguous or unmatched groups are listed."""
    before: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    after: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for group in baseline_groups:
        before[match_key(group, match, include_device)].append(group)
    for group in candidate_groups:
        after[match_key(group, match, include_device)].append(group)
    pairs, ambiguous = [], []
    for key in sorted(set(before) & set(after)):
        if len(before[key]) > 1 or len(after[key]) > 1:
            ambiguous.append(" / ".join(key))
            continue
        old, new = before[key][0], after[key][0]
        polarity = (new.get("baseline") or {}).get("polarity") or (old.get("baseline") or {}).get("polarity")
        pairs.append({
            "display_name": new["display_name"],
            "unit": new["unit"],
            "test_identifier": {"baseline": old.get("test_identifier"), "candidate": new.get("test_identifier")},
            "device": {"baseline": old.get("device"), "candidate": new.get("device")},
            **compare_values(old["statistics"].get("values", []), new["statistics"].get("values", []), polarity, resamples),
        })
    return {
        "match": match,
        "same_device_required": include_device,
        "pairs": pairs,
        "ambiguous": ambiguous,
        "unmatched_baseline": [" / ".join(key) for key in sorted(set(before) - set(after))],
        "unmatched_candidate": [" / ".join(key) for key in sorted(set(after) - set(before))],
    }


def filter_metrics(metrics: list[dict[str, Any]], test_id: str | None, metric: str | None) -> list[dict[str, Any]]:
    if test_id:
        needle = test_id.casefold()
        metrics = [item for item in metrics if needle in (item.get("test_identifier") or "").casefold()]
    if metric:
        needle = metric.casefold()
        metrics = [
            item
            for item in metrics
            if needle in (item.get("display_name") or "").casefold()
            or needle in (item.get("identifier") or "").casefold()
        ]
    return metrics


def load_source(path: Path | None, json_path: Path | None, test_id: str | None, timeout: float) -> tuple[Any, str]:
    if path:
        return load_xcresult(path, test_id, timeout), str(path.expanduser().resolve())
    assert json_path is not None
    resolved = json_path.expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8")), str(resolved)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--path", type=Path, help="XCResult bundle")
    source.add_argument("--input-json", type=Path, help="Previously exported xcresult metrics JSON")
    baseline = parser.add_mutually_exclusive_group()
    baseline.add_argument("--baseline-path", type=Path, help="Baseline XCResult bundle to compare against")
    baseline.add_argument("--baseline-json", type=Path, help="Baseline xcresult metrics JSON to compare against")
    parser.add_argument("--match", choices=("test-and-metric", "metric"), default="test-and-metric",
                        help="Pair groups by test and metric (default), or by metric name and unit only")
    parser.add_argument("--allow-cross-device", action="store_true", help="Pair groups recorded on different devices")
    parser.add_argument("--resamples", type=int, default=2000, help="Bootstrap resamples for the comparison interval")
    parser.add_argument("--fail-on-regression", action="store_true", help="Exit 5 when any pair is a regression")
    parser.add_argument("--test-id", help="Pass through to xcresulttool and/or filter test identifiers")
    parser.add_argument("--metric", help="Case-insensitive display-name or metric-identifier substring")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--save", type=Path)
    args = parser.parse_args()

    try:
        raw, source_label = load_source(args.path, args.input_json, args.test_id, args.timeout)
        baseline_raw, baseline_label = (None, None)
        if args.baseline_path or args.baseline_json:
            baseline_raw, baseline_label = load_source(args.baseline_path, args.baseline_json, args.test_id, args.timeout)
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2

    metrics = filter_metrics(collect_metrics(raw), args.test_id, args.metric)
    report: dict[str, Any] = {
        "schema_version": "ios.xcresult.metrics.v1",
        "source": source_label,
        "metric_group_count": 0,
        "groups": group_metrics(metrics),
        "notes": [
            "Units are preserved exactly as exported; groups with different units are never combined.",
            "p90 uses the Hyndman-Fan type-7 linear estimator and is labeled directional below 20 values.",
            "These XCTest metrics are measurements; Instruments CPU sample weights remain separate diagnostics.",
        ],
    }
    report["metric_group_count"] = len(report["groups"])
    regression = False
    if baseline_raw is not None:
        baseline_groups = group_metrics(filter_metrics(collect_metrics(baseline_raw), args.test_id, args.metric))
        comparison = compare_groups(baseline_groups, report["groups"], args.match, not args.allow_cross_device, args.resamples)
        comparison["baseline_source"] = baseline_label
        report["comparison"] = comparison
        report["notes"].append(
            f"Comparisons give candidate minus baseline, a Hodges-Lehmann shift, and a {args.resamples}-resample percentile "
            f"bootstrap 95% interval (seed 0) for the difference in medians. A verdict needs {MIN_COMPARE_SAMPLES}+ values per "
            "side and an interval that excludes zero; polarity comes from the XCTest metric. Compare only runs with the same "
            "device, build configuration, scenario and launch class."
        )
        regression = any(pair.get("verdict") == "regression" for pair in comparison["pairs"])
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.save:
        destination = args.save.expanduser().resolve()
        if destination.exists():
            print(json.dumps({"status": "error", "error": f"refusing to overwrite {destination}"}), file=sys.stderr)
            return 2
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered + "\n", encoding="utf-8")
    if not report["groups"]:
        return 3
    return 5 if args.fail_on_regression and regression else 0


if __name__ == "__main__":
    sys.exit(main())
