#!/usr/bin/env python3
"""Read one .xcresult bundle and report bounded, honest test evidence.

Every subcommand is read-only. Nothing here runs tests, mutates a bundle, or
retries anything -- it reports what a run actually recorded so the caller can
decide what to do next.

    summary      <bundle>              verdict, both counting rules, timing
    failures     <bundle>              each failure with its source location
    tests        <bundle>              hierarchy, frameworks, duration profile
    triage       <bundle>              flake / infrastructure classification
    activities   <bundle> --test-id X  UI-test step tree
    metrics      <bundle>              which metrics exist and whether they can gate
    availability <bundle>              what the bundle actually contains

Add --json to any subcommand for machine-readable output.

Design notes that matter:

* Result bundles carry TWO test counts that disagree legitimately. The top level
  counts test cases; the per-device row counts test runs, so one parameterised
  case contributes 1 and N respectively. Both are reported, always, with the
  reconciliation from the bundle's own `statistics` field.

* `testIdentifierURL` is the stable key across runs, machines and Xcode
  versions. Display names are not -- they change when someone renames a test.

* A source location of `/<compiler-generated>` is synthesised. It is reported as
  such and never presented as a failing line.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_TESTED = "0.4.0"
DEFAULT_TIMEOUT = 180

# A source location pointing here is compiler-synthesised, not real source.
SYNTHETIC_PATH = "/<compiler-generated>"

# Relative standard deviation above which a metric cannot support a gate.
# Derived from the bundle's own maxPercentRelativeStandardDeviation default.
RSD_USABLE = 10.0
RSD_MARGINAL = 15.0


# --------------------------------------------------------------------------
# tool plumbing
# --------------------------------------------------------------------------

class ToolError(RuntimeError):
    pass


def xcresulttool(args: List[str], timeout: int = DEFAULT_TIMEOUT) -> str:
    if not shutil.which("xcrun"):
        raise ToolError("xcrun not found. These skills require macOS with full Xcode.")
    argv = ["xcrun", "xcresulttool"] + args
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise ToolError(f"xcresulttool timed out after {timeout}s: {' '.join(args[:3])}")
    if proc.returncode != 0:
        raise ToolError(f"xcresulttool failed ({proc.returncode}): "
                        f"{(proc.stderr or proc.stdout).strip()[:400]}")
    return proc.stdout


def get_json(bundle: Path, *parts: str, timeout: int = DEFAULT_TIMEOUT) -> Any:
    out = xcresulttool(list(parts) + ["--path", str(bundle), "--format", "json"],
                       timeout=timeout)
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise ToolError(f"xcresulttool returned invalid JSON for "
                        f"{' '.join(parts)}: {exc}")


def resolve_bundle(path: Path) -> Path:
    bundle = path.expanduser().resolve()
    if not bundle.exists():
        raise ToolError(f"no such bundle: {bundle}")
    if not (bundle / "Info.plist").exists():
        raise ToolError(f"not an .xcresult bundle (no Info.plist): {bundle}")
    return bundle


# --------------------------------------------------------------------------
# availability -- always the first question about an unfamiliar bundle
# --------------------------------------------------------------------------

def availability(bundle: Path) -> Dict[str, Any]:
    try:
        data = get_json(bundle, "get", "content-availability", timeout=60)
    except ToolError as exc:
        return {"error": str(exc)}
    return {
        "hasTestResults": bool(data.get("hasTestResults")),
        "hasCoverage": bool(data.get("hasCoverage")),
        "hasDiagnostics": bool(data.get("hasDiagnostics")),
        "logs": data.get("logs", []),
    }


# --------------------------------------------------------------------------
# summary
# --------------------------------------------------------------------------

def summary(bundle: Path) -> Dict[str, Any]:
    raw = get_json(bundle, "get", "test-results", "summary")

    devices = []
    run_total = 0
    for dc in raw.get("devicesAndConfigurations", []):
        dev = dc.get("device", {})
        passed = dc.get("passedTests", 0)
        failed = dc.get("failedTests", 0)
        skipped = dc.get("skippedTests", 0)
        run_total += passed + failed + skipped
        devices.append({
            "name": dev.get("deviceName"),
            "platform": dev.get("platform"),
            "os": dev.get("osVersion"),
            # The OS *build* is the axis most flake correlates with. Keep it.
            "osBuild": dev.get("osBuildNumber"),
            "architecture": dev.get("architecture"),
            "deviceId": dev.get("deviceId"),
            "configuration": (dc.get("testPlanConfiguration") or {}).get("configurationName"),
            "passed": passed, "failed": failed, "skipped": skipped,
            "expectedFailures": dc.get("expectedFailures", 0),
        })

    case_total = raw.get("totalTestCount", 0)
    start, finish = raw.get("startTime"), raw.get("finishTime")

    return {
        "title": raw.get("title"),
        "result": raw.get("result"),
        "environment": raw.get("environmentDescription"),
        "durationSeconds": round(finish - start, 3) if (start and finish) else None,
        "counts": {
            # Both rules, always. See the module docstring.
            "testCases": case_total,
            "testRuns": run_total,
            "passed": raw.get("passedTests", 0),
            "failed": raw.get("failedTests", 0),
            "skipped": raw.get("skippedTests", 0),
            "expectedFailures": raw.get("expectedFailures", 0),
            "reconciled": case_total == run_total,
        },
        # The bundle explains its own count discrepancy here.
        "statistics": [
            {"title": s.get("title"), "detail": s.get("subtitle")}
            for s in raw.get("statistics", [])
        ],
        "devices": devices,
        "failureCount": len(raw.get("testFailures", [])),
        "insights": [
            {"category": i.get("category"), "impact": i.get("impact"), "text": i.get("text")}
            for i in raw.get("topInsights", [])
        ],
        "runtimeWarnings": raw.get("runtimeWarnings", []),
    }


# --------------------------------------------------------------------------
# failures
# --------------------------------------------------------------------------

def _walk(node: Dict[str, Any]):
    yield node
    for child in node.get("children", []) or []:
        for item in _walk(child):
            yield item


def _source_location(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    loc = node.get("sourceLocation")
    if not loc or not loc.get("filePath"):
        return None
    path = loc["filePath"]
    return {
        "file": path,
        "line": loc.get("lineNumber"),
        # Never present a synthesised location as the failing line.
        "synthetic": path == SYNTHETIC_PATH or path.startswith("/<"),
    }


def failures(bundle: Path, with_detail: bool = True) -> Dict[str, Any]:
    raw = get_json(bundle, "get", "test-results", "summary")
    insights = raw.get("topInsights", [])

    items: List[Dict[str, Any]] = []
    for f in raw.get("testFailures", []):
        item: Dict[str, Any] = {
            "testName": f.get("testName"),
            "target": f.get("targetName"),
            "identifier": f.get("testIdentifierString"),
            # The stable key. Use this, not the display name.
            "identifierURL": f.get("testIdentifierURL"),
            "failureText": (f.get("failureText") or "").strip(),
            "sourceLocation": None,
            "repetitions": [],
        }
        if with_detail and item["identifierURL"]:
            item.update(_failure_detail(bundle, item["identifierURL"]))
        items.append(item)

    return {
        "count": len(items),
        "failures": items,
        # Apple already clustered these. Read them before writing your own.
        "insights": [
            {"category": i.get("category"), "impact": i.get("impact"), "text": i.get("text")}
            for i in insights
        ],
    }


def _failure_detail(bundle: Path, test_url: str) -> Dict[str, Any]:
    try:
        raw = get_json(bundle, "get", "test-results", "test-details",
                       "--test-id", test_url)
    except ToolError as exc:
        return {"detailError": str(exc)}

    location = None
    repetitions = []
    for run in raw.get("testRuns", []) or []:
        rep = {
            "name": run.get("name"),
            "result": run.get("result"),
            "durationSeconds": run.get("durationInSeconds"),
            "messages": [],
        }
        for node in _walk(run):
            if node is run:
                continue
            if node.get("nodeType") == "Test Case Run" and node.get("result") == "Failed":
                rep["messages"].append(node.get("name"))
                loc = _source_location(node)
                if loc and not loc["synthetic"] and location is None:
                    location = loc
        repetitions.append(rep)

    return {
        "sourceLocation": location,
        "repetitions": repetitions,
        "hasMediaAttachments": raw.get("hasMediaAttachments"),
        "hasPerformanceMetrics": raw.get("hasPerformanceMetrics"),
        "averageDurationSeconds": raw.get("durationInSeconds"),
    }


# --------------------------------------------------------------------------
# tests -- hierarchy, framework detection, duration profile
# --------------------------------------------------------------------------

XCTEST_NAME = re.compile(r"^test[A-Z0-9_].*\(\)$")


def _framework_of(name: str) -> str:
    """XCTest names are `testFoo()`; Swift Testing @Test names are prose."""
    if not name:
        return "unknown"
    return "XCTest" if XCTEST_NAME.match(name) else "Swift Testing"


def tests(bundle: Path) -> Dict[str, Any]:
    raw = get_json(bundle, "get", "test-results", "tests")

    cases: List[Dict[str, Any]] = []
    bundles: Dict[str, str] = {}

    def visit(node, bundle_name=None, suite=None):
        ntype = node.get("nodeType")
        name = node.get("name", "")
        if ntype in ("Unit test bundle", "UI test bundle"):
            bundle_name = name
            bundles[name] = ntype
        elif ntype == "Test Suite":
            suite = name
        elif ntype == "Test Case":
            children = node.get("children", []) or []
            args = [c for c in children if c.get("nodeType") == "Arguments"]
            # Repetitions appear here when -test-iterations or
            # -retry-tests-on-failure was used. A Test Case can report Passed
            # while carrying a Failed repetition -- see hidden_flakes().
            reps = [c for c in children if c.get("nodeType") == "Repetition"]
            cases.append({
                "name": name,
                "suite": suite,
                "bundle": bundle_name,
                "kind": bundles.get(bundle_name or "", "unknown"),
                "framework": _framework_of(name),
                "result": node.get("result"),
                "duration": node.get("duration"),
                "durationSeconds": _parse_duration(node.get("duration")),
                "identifier": node.get("nodeIdentifier"),
                "argumentSets": len(args),
                "arguments": [a.get("name") for a in args],
                "repetitions": [
                    {
                        "name": r.get("name"),
                        "result": r.get("result"),
                        "durationSeconds": _parse_duration(r.get("duration")),
                        "messages": [m.get("name") for m in (r.get("children") or [])
                                     if m.get("nodeType") == "Failure Message"],
                    }
                    for r in reps
                ],
            })
            return  # Arguments and Repetitions are folded into their case
        for child in node.get("children", []) or []:
            visit(child, bundle_name, suite)

    for root in raw.get("testNodes", []):
        visit(root)

    by_fw: Dict[str, int] = {}
    for c in cases:
        by_fw[c["framework"]] = by_fw.get(c["framework"], 0) + 1

    timed = [c for c in cases if c["durationSeconds"] is not None]
    timed.sort(key=lambda c: c["durationSeconds"], reverse=True)
    total_time = sum(c["durationSeconds"] for c in timed)

    ui_time = sum(c["durationSeconds"] for c in timed if c["kind"] == "UI test bundle")
    parameterised = [c for c in cases if c["argumentSets"] > 0]

    return {
        "caseCount": len(cases),
        "runCount": sum(max(1, c["argumentSets"]) for c in cases),
        "byFramework": by_fw,
        "bundles": bundles,
        "parameterised": [
            {"name": c["name"], "argumentSets": c["argumentSets"], "arguments": c["arguments"]}
            for c in parameterised
        ],
        "durationProfile": {
            "totalSeconds": round(total_time, 3),
            "uiTestSeconds": round(ui_time, 3),
            "uiTestShare": round(ui_time / total_time, 4) if total_time else None,
            "slowest": [
                {"name": c["name"], "bundle": c["bundle"],
                 "seconds": c["durationSeconds"], "result": c["result"]}
                for c in timed[:10]
            ],
        },
        "cases": cases,
    }


_DUR = re.compile(r"^([\d.]+)\s*(ms|s|m)?$")


def _parse_duration(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    m = _DUR.match(value.strip())
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2) or "s"
    return n / 1000 if unit == "ms" else n * 60 if unit == "m" else n


# --------------------------------------------------------------------------
# triage -- the classification that decides whether a retry is honest
# --------------------------------------------------------------------------

# Signatures that mean the runner failed, not the product. A failure matching
# one of these is an infrastructure failure and is the ONLY kind a retry may
# legitimately paper over.
INFRA_PATTERNS = [
    (r"Lost connection to the (test|debug)", "runner connection lost"),
    (r"failed to (launch|start).*(test runner|runner app)", "runner app would not launch"),
    (r"Unable to (lookup|find) in current state.*Shutdown", "simulator was shut down"),
    (r"testmanagerd", "test manager error"),
    (r"Timed out (waiting|while) .*(launch|connect|install)", "timed out before the test ran"),
    (r"Simulator device failed to (boot|install)", "simulator lifecycle failure"),
    (r"(Unable|Failed) to install", "install failure"),
    (r"early unexpected exit|crashed before the test", "process died before assertion"),
    (r"Developer Mode disabled|device is locked", "device not ready"),
]


def _infra_match(text: str) -> Optional[str]:
    for pattern, label in INFRA_PATTERNS:
        if re.search(pattern, text, re.I):
            return label
    return None


def build_results(bundle: Path) -> Dict[str, Any]:
    """Build errors, warnings and analyzer warnings recorded alongside the tests.

    `status: notRequested` means no build happened in this run -- typical of
    `test-without-building`. That is not the same as "no warnings", and is
    reported as such rather than as a clean build.
    """
    try:
        raw = get_json(bundle, "get", "build-results")
    except ToolError as exc:
        return {"error": str(exc)}

    status = raw.get("status")
    return {
        "status": status,
        "buildRan": status not in (None, "notRequested"),
        "errorCount": raw.get("errorCount", 0),
        "warningCount": raw.get("warningCount", 0),
        "analyzerWarningCount": raw.get("analyzerWarningCount", 0),
        "errors": [_issue(i) for i in raw.get("errors", []) or []],
        "warnings": [_issue(i) for i in raw.get("warnings", []) or []],
        "analyzerWarnings": [_issue(i) for i in raw.get("analyzerWarnings", []) or []],
        "destination": raw.get("destination"),
        "note": ("status 'notRequested' means no compilation happened in this "
                 "run (test-without-building). Zero warnings here does not mean "
                 "the build is clean -- it means nothing was built."
                 if status == "notRequested" else None),
    }


def _issue(item: Dict[str, Any]) -> Dict[str, Any]:
    loc = item.get("sourceURL") or item.get("location") or {}
    if isinstance(loc, str):
        loc = {"path": loc}
    return {
        "message": item.get("message") or item.get("title"),
        "target": item.get("targetName"),
        "file": loc.get("path") or loc.get("filePath"),
        "line": loc.get("lineNumber"),
        "issueType": item.get("issueType"),
    }


# Diagnostics files that decide infrastructure-versus-product, and what each
# is evidence of. Read in this order.
DIAGNOSTIC_FILES = (
    ("testmanagerd.log", "did the test manager connect at all"),
    ("scheduling.log", "worker lifecycle, PIDs, parallelisation, cancellation"),
    ("StandardOutputAndStandardError.txt", "the test process's own output"),
)

# Lines in diagnostics that indicate the RUNNER, not the product, failed.
#
# These are deliberately narrow. A healthy run's testmanagerd.log legitimately
# contains the string `(result:error)` -- it is a tuple label on a SUCCESSFUL
# reply -- along with `TESTMANAGERD_SIM_SOCK` and
# `Requesting crash report collection for process names: …` as routine setup.
# Loose patterns match all three and would tell the caller to retry a real
# failure, which is the exact mistake this skill exists to prevent.
#
# The oracle: these must produce ZERO matches on a fully passing run.
DIAG_SIGNALS = [
    (r"\(cancelled:\s*Yes\)",
     "the run was cancelled rather than completed"),
    (r"Lost connection to the test (runner|manager)",
     "connection to the test runner was lost"),
    (r"Failed to (establish communication with|install or launch) the test runner",
     "the test runner never started"),
    (r"(test runner|Test runner) exited (with code|unexpectedly)|early unexpected exit",
     "the runner process died before the tests finished"),
    (r"Canceling tests due to timeout",
     "the run was cancelled by a timeout"),
    (r"Test operation failure:",
     "xcodebuild reported a test operation failure"),
    (r"Unable to lookup in current state:\s*Shutdown",
     "the simulator was shut down mid-operation"),
    (r"Timed out (waiting|while waiting) for .*(launch|connect|install|ready)",
     "timed out before the tests could run"),
    (r"Failed to (boot|install)\b",
     "the simulator or app could not be prepared"),
]


def diagnostics(bundle: Path, out_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Export and read the diagnostics that settle infrastructure vs product.

    Pattern-matching a failure message is a hint. This is the evidence.
    """
    avail = availability(bundle)
    if not avail.get("hasDiagnostics"):
        return {"available": False,
                "note": ("This bundle has no diagnostics, so an infrastructure "
                         "classification cannot be confirmed from it.")}

    import tempfile
    target = out_dir.expanduser().resolve() if out_dir else Path(
        tempfile.mkdtemp(prefix="xcresult-diag-"))
    target.mkdir(parents=True, exist_ok=True)

    try:
        xcresulttool(["export", "diagnostics", "--path", str(bundle),
                      "--output-path", str(target)], timeout=300)
    except ToolError as exc:
        return {"available": True, "error": str(exc)}

    files, signals = [], []
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        size = path.stat().st_size
        rel = str(path.relative_to(target))
        entry = {"path": rel, "absolute": str(path), "bytes": size}

        # Only scan the small control-plane logs. The app's own stream is
        # routinely over a megabyte and is not where runner failures appear.
        if path.name in {n for n, _ in DIAGNOSTIC_FILES} and size < 2_000_000:
            text = path.read_text(errors="replace")
            entry["role"] = next(d for n, d in DIAGNOSTIC_FILES if n == path.name)
            for pattern, meaning in DIAG_SIGNALS:
                for m in re.finditer(pattern, text, re.I):
                    line = text[max(0, m.start() - 90):m.end() + 90].strip()
                    signals.append({"file": rel, "meaning": meaning,
                                    "excerpt": " ".join(line.split())[:190]})
        files.append(entry)

    app_streams = [f for f in files
                   if f["path"].split("/")[-1].startswith(
                       "StandardOutputAndStandardError-")]

    return {
        "available": True,
        "exportedTo": str(target),
        "temporary": out_dir is None,
        "fileCount": len(files),
        "files": files,
        "infrastructureSignals": signals,
        "appLogStreams": [{"path": f["path"], "bytes": f["bytes"]}
                          for f in app_streams],
        "verdict": ("runner-failure-evidence-found" if signals
                    else "no-runner-failure-evidence"),
        "note": ("No infrastructure signal here means the runner worked and any "
                 "failure is product evidence. The app's own stream is where "
                 "crashes and runtime warnings appear -- read it by PID from "
                 "the activity tree."
                 if not signals else
                 "Infrastructure signals found. A retry may be legitimate; "
                 "confirm the specific failure matches one of these."),
    }


def attachments(bundle: Path, out_dir: Path,
                only_failures: bool = True) -> Dict[str, Any]:
    """Export XCTAttachments -- screenshots, videos and custom payloads."""
    target = out_dir.expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    args = ["export", "attachments", "--path", str(bundle),
            "--output-path", str(target)]
    if only_failures:
        args.append("--only-failures")
    try:
        xcresulttool(args, timeout=600)
    except ToolError as exc:
        return {"error": str(exc), "exportedTo": str(target)}

    manifest_path = target / "manifest.json"
    entries: List[Any] = []
    if manifest_path.exists():
        try:
            entries = json.loads(manifest_path.read_text())
        except json.JSONDecodeError:
            entries = []

    files = [p for p in sorted(target.rglob("*"))
             if p.is_file() and p.name != "manifest.json"]
    return {
        "exportedTo": str(target),
        "onlyFailures": only_failures,
        "manifestEntries": len(entries) if isinstance(entries, list) else 0,
        "fileCount": len(files),
        "files": [{"name": p.name, "bytes": p.stat().st_size} for p in files[:50]],
        "note": ("Empty is normal when the suite records no XCTAttachments. "
                 "Screenshots are attached per activity step, so a UI test that "
                 "takes none produces none."
                 if not files else None),
    }


def hidden_flakes(bundle: Path) -> List[Dict[str, Any]]:
    """Find tests that PASSED overall but failed at least one repetition.

    This is the highest-value check in the whole script. With
    `-retry-tests-on-failure`, a test that fails then passes makes the run
    report `result: Passed`, `failedTests: 0` and an EMPTY `testFailures` array.
    The only surviving evidence is a Failed `Repetition` node inside the test
    hierarchy. A CI system that reads the summary alone reports green and the
    flake stays invisible until it fails on someone else's branch.
    """
    found = []
    for case in tests(bundle)["cases"]:
        reps = case.get("repetitions") or []
        if not reps or case.get("result") == "Failed":
            continue
        failed = [r for r in reps if r.get("result") == "Failed"]
        if not failed:
            continue
        found.append({
            "test": case["name"],
            "suite": case.get("suite"),
            "target": case.get("bundle"),
            "identifier": case.get("identifier"),
            "reportedResult": case.get("result"),
            "repetitions": reps,
            "failedRepetitions": len(failed),
            "totalRepetitions": len(reps),
            "messages": [m for r in failed for m in (r.get("messages") or [])],
        })
    return found


def triage(bundle: Path, read_diagnostics: bool = True) -> Dict[str, Any]:
    """Classify each failure and state what a retry would and would not prove.

    When diagnostics are available they are exported and read, so an
    `infrastructure` verdict rests on evidence from testmanagerd/scheduling
    rather than on pattern-matching the failure text alone.
    """
    data = failures(bundle)
    avail = availability(bundle)
    hidden = hidden_flakes(bundle)

    diag: Dict[str, Any] = {"available": False}
    if read_diagnostics and avail.get("hasDiagnostics"):
        try:
            diag = diagnostics(bundle)
        except ToolError as exc:
            diag = {"available": True, "error": str(exc)}
    diag_signals = diag.get("infrastructureSignals") or []

    classified = []
    for f in data["failures"]:
        reps = f.get("repetitions") or []
        results = [r.get("result") for r in reps]
        passed = results.count("Passed")
        failed = results.count("Failed")

        infra = _infra_match(f.get("failureText", ""))

        if infra:
            verdict = "infrastructure"
            # The text matched a runner signature. Diagnostics either corroborate
            # that or leave it a hint -- say which.
            if diag_signals:
                confidence = "high"
                action = ("Retry is legitimate. The assertion never ran, and the "
                          "diagnostics corroborate a runner failure.")
            elif diag.get("available") and not diag.get("error"):
                confidence = "medium"
                action = ("The failure text looks like a runner failure, but the "
                          "diagnostics show no corroborating signal. Read them "
                          "before retrying -- this may be a product failure "
                          "wearing infrastructure wording.")
            else:
                confidence = "low"
                action = ("Matched a runner signature, but this bundle has no "
                          "readable diagnostics to confirm it. Do not retry on "
                          "the text alone.")
        elif len(reps) <= 1:
            verdict, confidence = "unclassified", "low"
            action = ("Single run: nothing here distinguishes a real failure from a "
                      "flaky one. Re-run under the three repetition modes "
                      "(see references/failure-triage.md) before deciding.")
        elif failed and passed:
            verdict, confidence = "flaky", "high"
            action = ("Passed and failed within the same run. Do NOT report green. "
                      "Name the repetition mode alongside the verdict.")
        elif failed == len(reps):
            verdict, confidence = "deterministic", "high"
            action = "Failed every repetition. Real failure -- do not retry."
        else:
            verdict, confidence = "unclassified", "low"
            action = "Repetition results were inconclusive; inspect manually."

        classified.append({
            "test": f.get("identifier"),
            "identifierURL": f.get("identifierURL"),
            "target": f.get("target"),
            "verdict": verdict,
            "confidence": confidence,
            "infrastructureSignal": infra,
            "repetitions": {"total": len(reps), "passed": passed, "failed": failed},
            "sourceLocation": f.get("sourceLocation"),
            "failureText": f.get("failureText")[:400],
            "action": action,
        })

    counts: Dict[str, int] = {}
    for c in classified:
        counts[c["verdict"]] = counts.get(c["verdict"], 0) + 1

    for h in hidden:
        counts["hidden-flake"] = counts.get("hidden-flake", 0) + 1

    return {
        "failureCount": len(classified),
        "byVerdict": counts,
        "classified": classified,
        # Reported separately because these do NOT appear in testFailures and
        # the run's own verdict is Passed.
        "hiddenFlakes": hidden,
        "cleanGreen": not classified and not hidden,
        "diagnosticsAvailable": avail.get("hasDiagnostics", False),
        "diagnostics": {
            "read": bool(diag.get("available") and not diag.get("error")),
            "verdict": diag.get("verdict"),
            "signals": diag_signals,
            "exportedTo": diag.get("exportedTo"),
            "appLogStreams": diag.get("appLogStreams", []),
        },
        "retryPolicy": (
            "Retry ONLY failures classified `infrastructure`. Retrying a "
            "deterministic or flaky failure converts a real signal into a green "
            "build and is how regressions reach production."
        ),
    }


# --------------------------------------------------------------------------
# activities -- UI-test step tree
# --------------------------------------------------------------------------

def activities(bundle: Path, test_id: str) -> Dict[str, Any]:
    raw = get_json(bundle, "get", "test-results", "activities", "--test-id", test_id)

    steps: List[Dict[str, Any]] = []

    def visit(node, depth=0):
        title = node.get("title") or node.get("name") or ""
        steps.append({
            "depth": depth,
            "title": title,
            "start": node.get("startTime"),
            "type": node.get("activityType"),
            "attachments": len(node.get("attachments", []) or []),
        })
        for child in node.get("childActivities", []) or []:
            visit(child, depth + 1)

    for run in raw.get("testRuns", []) or []:
        for act in run.get("activities", []) or []:
            visit(act)

    return {
        "testId": test_id,
        "stepCount": len(steps),
        "steps": steps,
        # A hung UI test's last step names the stall.
        "lastStep": steps[-1]["title"] if steps else None,
        "attachmentCount": sum(s["attachments"] for s in steps),
    }


# --------------------------------------------------------------------------
# metrics -- presence and gateability only; statistics belong to the profiler
# --------------------------------------------------------------------------

def _rsd(values: List[float]) -> Optional[float]:
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    if mean == 0:
        return None
    var = sum((v - mean) ** 2 for v in values) / n
    return (var ** 0.5) / abs(mean) * 100


def metrics(bundle: Path) -> Dict[str, Any]:
    """Report which metrics exist and whether their noise floor can carry a gate.

    Deliberately NOT a statistics engine. Regression comparison, baselines and
    confidence intervals belong to `ios-instruments-profiler`'s
    xcresult_metrics.py -- this only answers "is this metric gateable at all",
    which is a test-quality question.
    """
    try:
        raw = json.loads(xcresulttool(
            ["get", "test-results", "metrics", "--path", str(bundle), "--compact"]))
    except ToolError as exc:
        return {"error": str(exc), "groups": []}

    groups = []
    for entry in raw if isinstance(raw, list) else []:
        for run in entry.get("testRuns", []) or []:
            for m in run.get("metrics", []) or []:
                values = [float(v) for v in m.get("measurements", []) or []]
                rsd = _rsd(values)
                threshold = m.get("maxPercentRelativeStandardDeviation")
                if rsd is None:
                    gate = "unknown"
                elif rsd <= RSD_USABLE:
                    gate = "gateable"
                elif rsd <= RSD_MARGINAL:
                    gate = "marginal"
                else:
                    gate = "too-noisy"
                groups.append({
                    "test": entry.get("testIdentifier"),
                    "metric": m.get("displayName"),
                    "identifier": m.get("identifier"),
                    "unit": m.get("unitOfMeasurement"),
                    "polarity": m.get("polarity"),
                    "n": len(values),
                    "mean": round(sum(values) / len(values), 6) if values else None,
                    "rsdPercent": round(rsd, 1) if rsd is not None else None,
                    "thresholdPercent": threshold,
                    "gateability": gate,
                    "exceedsOwnThreshold": (
                        bool(rsd is not None and threshold and rsd > threshold)),
                })

    return {
        "groupCount": len(groups),
        "groups": groups,
        "handoff": ("For regression comparison, baselines and confidence "
                    "intervals use ios-instruments-profiler's "
                    "scripts/xcresult_metrics.py -- it owns that analysis."),
    }


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _render_summary(d: Dict[str, Any]) -> None:
    c = d["counts"]
    print(f"\n{d['title'] or 'Test run'} — {d['result']}")
    if d.get("environment"):
        print(f"  {d['environment']}")
    if d.get("durationSeconds") is not None:
        print(f"  duration {d['durationSeconds']}s")

    print(f"\n  test cases {c['testCases']}   test runs {c['testRuns']}", end="")
    print("" if c["reconciled"] else "   ← counts differ, see statistics below")
    print(f"  passed {c['passed']}   failed {c['failed']}   "
          f"skipped {c['skipped']}   expected failures {c['expectedFailures']}")

    if d["statistics"]:
        print("\n  statistics")
        for s in d["statistics"]:
            print(f"    {s['title']} — {s['detail']}")

    for dev in d["devices"]:
        print(f"\n  {dev['name']}  {dev['platform']} {dev['os']} "
              f"(build {dev['osBuild']}, {dev['architecture']})")
        print(f"    configuration {dev['configuration']}   "
              f"passed {dev['passed']} failed {dev['failed']} skipped {dev['skipped']}")

    if d["insights"]:
        print("\n  insights (computed by Xcode)")
        for i in d["insights"]:
            print(f"    [{i['impact']}] {i['text']}")

    if d["runtimeWarnings"]:
        print(f"\n  runtime warnings: {len(d['runtimeWarnings'])}")
    print()


def _render_failures(d: Dict[str, Any]) -> None:
    if not d["count"]:
        print("\nNo failures recorded.\n")
        return
    print(f"\n{d['count']} failure(s)\n")
    for f in d["failures"]:
        print(f"  {f['identifier']}   [{f['target']}]")
        loc = f.get("sourceLocation")
        if loc:
            print(f"    at {loc['file']}:{loc['line']}")
        elif f.get("repetitions"):
            print("    no real source location (synthesised only)")
        for line in (f["failureText"] or "").splitlines():
            print(f"    {line.strip()}")
        reps = f.get("repetitions") or []
        if len(reps) > 1:
            states = "  ".join(f"{r['name']}:{r['result']}" for r in reps)
            print(f"    repetitions: {states}")
        print(f"    key: {f['identifierURL']}")
        print()
    if d["insights"]:
        print("  insights")
        for i in d["insights"]:
            print(f"    [{i['impact']}] {i['text']}")
        print()


def _render_tests(d: Dict[str, Any]) -> None:
    print(f"\n{d['caseCount']} test cases, {d['runCount']} runs")
    print("  frameworks: " + ", ".join(f"{k} {v}" for k, v in sorted(d["byFramework"].items())))
    if d["parameterised"]:
        print("\n  parameterised cases (these explain any count discrepancy)")
        for p in d["parameterised"]:
            print(f"    {p['name']} — {p['argumentSets']} argument sets")

    dp = d["durationProfile"]
    print(f"\n  total {dp['totalSeconds']}s", end="")
    if dp["uiTestShare"] is not None:
        print(f"   UI tests {dp['uiTestSeconds']}s "
              f"({dp['uiTestShare']*100:.0f}% of the time)")
    else:
        print()
    print("\n  slowest")
    for s in dp["slowest"]:
        print(f"    {s['seconds']:8.3f}s  {s['name'][:52]:54s} {s['result']}")
    print()


def _render_hidden(hidden: List[Dict[str, Any]]) -> None:
    print(f"\n  {len(hidden)} HIDDEN FLAKE(S) — the run reports Passed, "
          f"but these failed a repetition\n")
    for h in hidden:
        print(f"  [HIDDEN-FLAKE] {h['test']}   [{h['target']}]")
        print(f"    reported result: {h['reportedResult']}   "
              f"but {h['failedRepetitions']} of {h['totalRepetitions']} "
              f"repetitions failed")
        for r in h["repetitions"]:
            mark = "✗" if r["result"] == "Failed" else "✓"
            print(f"      {mark} {r['name']}: {r['result']}")
        for m in h["messages"][:2]:
            print(f"    {(m or '').strip()[:110]}")
        print("    → Do NOT report this as green. It passed only because a retry "
              "was allowed.")
        print("      This test does not appear in `testFailures` and is invisible "
              "to a summary-only reader.")
        print()


def _render_triage(d: Dict[str, Any]) -> None:
    if d.get("cleanGreen"):
        print("\nNo failures, and no test passed only on retry.\n")
        return

    if d.get("hiddenFlakes"):
        _render_hidden(d["hiddenFlakes"])

    if not d["failureCount"]:
        if not d.get("hiddenFlakes"):
            print("\nNo failures to triage.\n")
        return
    print(f"\n{d['failureCount']} failure(s) classified")
    print("  " + "  ".join(f"{k}={v}" for k, v in sorted(d["byVerdict"].items())))
    print()
    for c in d["classified"]:
        print(f"  [{c['verdict'].upper()}] {c['test']}   confidence {c['confidence']}")
        if c["infrastructureSignal"]:
            print(f"    infrastructure signal: {c['infrastructureSignal']}")
        r = c["repetitions"]
        if r["total"] > 1:
            print(f"    repetitions: {r['passed']} passed / {r['failed']} failed "
                  f"of {r['total']}")
        loc = c.get("sourceLocation")
        if loc:
            print(f"    at {loc['file']}:{loc['line']}")
        print(f"    → {c['action']}")
        print()
    print(f"  {d['retryPolicy']}")
    if not d["diagnosticsAvailable"]:
        print("  NOTE: this bundle has no diagnostics, so an infrastructure "
              "classification cannot be confirmed.")
    print()


def _render_metrics(d: Dict[str, Any]) -> None:
    if d.get("error"):
        print(f"\n{d['error']}\n")
        return
    if not d["groupCount"]:
        print("\nNo performance metrics in this bundle.\n")
        return
    print(f"\n{d['groupCount']} metric group(s)\n")
    print(f"  {'metric':40s} {'n':>3s} {'mean':>16s} {'RSD':>7s}  gateability")
    print("  " + "-" * 82)
    for g in d["groups"]:
        rsd = f"{g['rsdPercent']}%" if g["rsdPercent"] is not None else "—"
        mean = f"{g['mean']:.5g}" if g["mean"] is not None else "—"
        flag = " !" if g["exceedsOwnThreshold"] else ""
        print(f"  {(g['metric'] or '')[:40]:40s} {g['n']:3d} {mean:>16s} "
              f"{rsd:>7s}  {g['gateability']}{flag}")
    print(f"\n  ! exceeds the bundle's own maxPercentRelativeStandardDeviation")
    print(f"  {d['handoff']}\n")


def _render_activities(d: Dict[str, Any]) -> None:
    print(f"\n{d['stepCount']} steps for {d['testId']}")
    if d["attachmentCount"]:
        print(f"  {d['attachmentCount']} attachment(s)")
    print()
    for s in d["steps"]:
        mark = f"  [{s['attachments']}]" if s["attachments"] else ""
        print("    " + "  " * s["depth"] + s["title"][:90] + mark)
    if d["lastStep"]:
        print(f"\n  last step: {d['lastStep']}")
        print("  (for a hung or timed-out test, this names where it stalled)")
    print()


def _render_availability(d: Dict[str, Any]) -> None:
    if d.get("error"):
        print(f"\n{d['error']}\n")
        return
    print("\nBundle contents")
    for key, label in (("hasTestResults", "test results"),
                       ("hasCoverage", "coverage"),
                       ("hasDiagnostics", "diagnostics")):
        print(f"  {'yes' if d[key] else 'no ':4s} {label}")
    print(f"  logs: {', '.join(d['logs']) if d['logs'] else 'none'}")
    if not d["hasCoverage"]:
        print("\n  No coverage: this run was recorded without -enableCodeCoverage YES.")
        print("  It cannot be recovered from this bundle; re-run to collect it.")
    print()


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def _render_build(d: Dict[str, Any]) -> None:
    if d.get("error"):
        print(f"\n{d['error']}\n")
        return
    print(f"\nBuild results — status {d['status']}")
    print(f"  errors {d['errorCount']}   warnings {d['warningCount']}   "
          f"analyzer warnings {d['analyzerWarningCount']}")
    for label, key in (("errors", "errors"), ("warnings", "warnings"),
                       ("analyzer", "analyzerWarnings")):
        for i in d.get(key, [])[:20]:
            loc = f"{i['file']}:{i['line']}" if i.get("file") else "(no location)"
            print(f"    [{label}] {loc}")
            print(f"      {(i.get('message') or '')[:110]}")
    if d.get("note"):
        print(f"\n  ! {d['note']}")
    print()


def _render_diagnostics(d: Dict[str, Any]) -> None:
    if not d.get("available"):
        print(f"\n{d.get('note')}\n")
        return
    if d.get("error"):
        print(f"\n{d['error']}\n")
        return
    print(f"\n{d['fileCount']} diagnostic file(s) → {d['exportedTo']}")
    if d["temporary"]:
        print("  (temporary directory; pass --out to keep them)")
    print(f"\n  verdict: {d['verdict']}")
    if d["infrastructureSignals"]:
        print("\n  infrastructure signals")
        for s in d["infrastructureSignals"][:12]:
            print(f"    [{s['meaning']}]  {s['file']}")
            print(f"      …{s['excerpt']}…")
    if d["appLogStreams"]:
        print("\n  app log streams (crashes and runtime warnings live here)")
        for a in d["appLogStreams"]:
            print(f"    {a['bytes']:>10,d} bytes  {a['path'].split('/')[-1]}")
    print(f"\n  {d['note']}\n")


def _render_attachments(d: Dict[str, Any]) -> None:
    if d.get("error"):
        print(f"\n{d['error']}\n")
        return
    print(f"\n{d['fileCount']} attachment(s) → {d['exportedTo']}"
          f"{'  (failures only)' if d['onlyFailures'] else ''}")
    for f in d["files"]:
        print(f"    {f['bytes']:>10,d} bytes  {f['name']}")
    if d.get("note"):
        print(f"\n  {d['note']}")
    print()


COMMANDS = {
    "summary": (summary, _render_summary),
    "failures": (failures, _render_failures),
    "tests": (tests, _render_tests),
    "triage": (triage, _render_triage),
    "metrics": (metrics, _render_metrics),
    "availability": (availability, _render_availability),
    "build-results": (build_results, _render_build),
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command",
                        choices=list(COMMANDS) + ["activities", "diagnostics",
                                                  "attachments"])
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--test-id", help="testIdentifierURL (required for activities)")
    parser.add_argument("--out", type=Path,
                        help="where to write exported diagnostics or attachments")
    parser.add_argument("--all", action="store_true",
                        help="attachments: export all, not only failures")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--no-detail", action="store_true",
                        help="failures: skip the per-failure test-details lookup")
    parser.add_argument("--no-diagnostics", action="store_true",
                        help="triage: classify from failure text only, do not "
                             "export and read diagnostics")
    args = parser.parse_args()

    try:
        bundle = resolve_bundle(args.bundle)

        if args.command == "activities":
            if not args.test_id:
                parser.error("activities requires --test-id")
            result = activities(bundle, args.test_id)
            renderer = _render_activities
        elif args.command == "failures":
            result = failures(bundle, with_detail=not args.no_detail)
            renderer = _render_failures
        elif args.command == "diagnostics":
            result = diagnostics(bundle, args.out)
            renderer = _render_diagnostics
        elif args.command == "attachments":
            if not args.out:
                parser.error("attachments requires --out")
            result = attachments(bundle, args.out, only_failures=not args.all)
            renderer = _render_attachments
        elif args.command == "triage":
            result = triage(bundle, read_diagnostics=not args.no_diagnostics)
            renderer = _render_triage
        else:
            fn, renderer = COMMANDS[args.command]
            result = fn(bundle)

    except ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        renderer(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
