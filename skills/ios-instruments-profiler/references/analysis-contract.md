# Trace analysis and evidence contract

## Validity gates

| Gate | Pass condition | Failure classification |
|---|---|---|
| Toolchain | intended Xcode selected; `xctrace` responds; no blocking known defect for the target | infrastructure failure |
| Target | visible to `xctrace`; app ready; permissions satisfied | target-readiness failure |
| Start | recording-start marker (not the `Starting recording` announcement) before deadline | never-started wedge |
| Completion | owned recorder exits within time limit plus grace | finalization wedge |
| Bundle | contains real run data, not only run issues | partial/empty trace |
| TOC | `xctrace export --toc` succeeds | invalid/incompatible trace |
| Schema | expected table exists | unsupported analysis |
| Rows | expected table has at least the declared rows (`--expect-rows`) | `expected-rows-missing` |
| Activity | a launched target produced CPU samples (`--min-launch-samples`) | `target-inactive` |
| Symbols | app binary and dSYM UUIDs match; useful frames resolve | degraded symbolication |
| Measurement | authoritative metric contains valid values | missing measurement |
| Comparability | declared build/target/scenario/state match; no contamination | non-comparable run |

Failed gates produce `invalid`, `unknown`, `not captured`, or `not exportable`—never zero.

## Export workflow

Inventory a trace. The inventory lists schema tables and, under `tracks`, the track details that legacy instruments use:

```sh
python3 scripts/xctrace_export.py toc \
  --trace '/absolute/run.trace' \
  --output '/absolute/run.toc.xml'
```

Export a table proved by the TOC:

```sh
python3 scripts/xctrace_export.py table \
  --trace '/absolute/run.trace' \
  --schema time-profile \
  --output '/absolute/run.time-profile.xml'
```

Export a track detail. Allocations, Leaks and VM Tracker expose their data only this way:

```sh
python3 scripts/xctrace_export.py table \
  --trace '/absolute/run.trace' \
  --track 'Allocations' --detail 'Statistics' \
  --output '/absolute/run.allocations-statistics.xml'
```

Other details: `Allocations / Allocations List`, `Leaks / Leaks`, `VM Tracker / Regions Map`. `--schema` and `--track` check the name against the TOC first and list what exists when it is missing; `--xpath` still accepts any selection, and `--run` picks a run other than 1. Every table export reports its row count and warns when it is zero.

Xcode 27 adds `--time-start`, `--time-end`, and `--duration` to `xctrace export`; they do not appear in `xctrace help export`. The helper passes them through for `table` exports and also counts the rows of an unbounded export. If the counts match, it exits 3 with `time_window.effect: "no-change"`: the window either spans the whole table or was ignored. Xcode 27 beta 27A5194q parses these options but ignores them, so filter by time with `xctrace_reduce.py --start-ms/--end-ms` on that build.

Export HTTP traffic with `xctrace_export.py har --output DIR`. The helper first checks the TOC for `external-format[@format="har"]` and stops if the trace declares no HAR data. It then exports into a new or empty directory, because `xctrace` requires a directory and writes one `<source-schema>_run_<n>.har` file per run, and it reports each file's entry count. Zero entries means no HTTP transactions were captured, not that none happened: an attached Network recording of a command-line client on this Mac recorded no CFNetwork rows although all of its requests reached the server.

Inspect an unfamiliar export without loading it into the model:

```sh
python3 scripts/xctrace_export.py preview \
  --input '/absolute/run.time-profile.xml' \
  --max-rows 20 \
  --max-nodes-per-row 80
```

The preview is structural discovery. It deliberately does not infer units, stack orientation, or performance meaning.

## Reducing exports

`scripts/xctrace_reduce.py` turns one export into a bounded JSON summary:

```sh
python3 scripts/xctrace_reduce.py --input '/absolute/run.time-profile.xml' --process 'MyApp' --top 15
```

| Export | Analyzer | Summary |
|---|---|---|
| `time-profile`, `cpu-profile` | `profile` | samples and weight (ms or cycles), threads, processes, thread states, top self (leaf), top inclusive, top first-app frames, leaf symbolication |
| `potential-hangs` | `hangs` | count, duration distribution, types, threads, longest hangs |
| `OSSignpostIntervals` | `signpost-intervals` | per name/category/subsystem counts and duration distribution |
| `os-signpost` | `signpost-events` | event counts per name and event type |
| `hitches`, `hitches-*` | `frames` | count and durations, processes, potential issues, frame colors; `--seconds` gives hitch time per second |
| `core-data-fetch`, `-save`, `-fault` | `core-data` | durations, entities, objects returned, first app caller |
| Allocations / Statistics | `allocation-statistics` | live and allocated totals, top live categories |
| Allocations / Allocations List | `allocation-list` | count and bytes, categories, share without a stack, responsible callers |
| Leaks / Leaks | `leaks` | leaked objects and bytes by type, share without a stack, responsible frames |
| anything else | `generic-table` / `generic-detail` | column or attribute coverage and common values only |

Filters: `--process`, `--thread`, `--start-ms`, `--end-ms` (table rows only). `--binary NAME` attributes stacks to the first frame in that binary instead of the first non-system frame. `--analyzer` forces an analyzer. `"status": "empty"` means no row matched: report "not captured". Home-directory paths are redacted in the output.

## Parser requirements

The bundled reducer meets these for the tables above. Any other analyzer a conclusion depends on must:

- stream large XML and enforce file, row, nesting, text, and output limits;
- resolve `id`/`ref` dictionaries with missing-reference detection (ids are unique within an export; refs can point into earlier rows and into nested elements);
- use schema metadata for units and column meanings, not fixed positions;
- determine whether stacks are leaf-first or root-first before self/inclusive aggregation (xctrace writes them leaf-first);
- filter the intended run, process, thread, state, and time/signpost interval;
- treat sentinel/invalid values as unknown;
- preserve raw symbol, module, address, binary UUID, and symbolication quality;
- version outputs by parser version, Xcode build, template/options, and schema fingerprint;
- keep fixture traces/exports from every supported Xcode family.

Other candidate implementations include `apple-instruments-mcp` for recorder/quality gates and focused parsers, `XcodeTraceMCP` for typed bounded analyzers, `xtrace-skill` for bounded CPU presentation, and `xcodeinstrumentmcp` for persistent evidence packs. Verify versions and behavior before adopting them; none is a universal authority for every template.

## Normalized per-run record

```json
{
  "schema_version": "ios.performance.v1",
  "run_id": "search-01",
  "question": "Why is search slow?",
  "conditions": {
    "app_bundle_id": "com.example.app",
    "app_build": "...",
    "binary_uuid": "...",
    "xcode_build": "...",
    "target_kind": "physical-device",
    "target_id": "...",
    "target_os": "...",
    "scenario": "fixed-search-query"
  },
  "measurement": {
    "name": "search-to-results",
    "source": "app-signpost",
    "unit": "ms",
    "value": null
  },
  "trace_quality": {
    "status": "valid",
    "toc_exported": true,
    "schemas": ["time-profile", "os-signpost"],
    "row_counts": {"time-profile": 5395},
    "target_activity": "active",
    "symbolication": "complete",
    "warnings": []
  },
  "diagnostics": {
    "top_self_cpu": [],
    "top_inclusive_cpu": [],
    "main_thread_states": [],
    "signpost_intervals": [],
    "allocation_findings": [],
    "io_findings": [],
    "network_findings": [],
    "frame_findings": []
  },
  "artifacts": {
    "trace": "/absolute/run.trace",
    "toc": "/absolute/run.toc.xml",
    "exports": []
  }
}
```

Leave `measurement.value` null unless a measurement source defines elapsed semantics. Never populate it from a sum of CPU samples.

## Multi-run statistics

- Preserve every valid value and invalid-run reason.
- Report count, min, max, median, p90, MAD and/or IQR. Mean and standard deviation may supplement but not replace robust measures.
- State the p90 estimator and call small-sample tails directional.
- For baseline/candidate work, use the same device and conditions, preferably paired or interleaved ordering. Report absolute and percentage differences and a confidence interval when sample size permits:

```sh
python3 scripts/xcresult_metrics.py \
  --path '/absolute/Candidate.xcresult' \
  --baseline-path '/absolute/Baseline.xcresult' \
  --metric 'Application Launch'
```

  Each pair reports median, p90 and Hodges-Lehmann deltas, a seeded bootstrap 95% interval for the median difference, and a verdict: `regression` or `improvement` (interval excludes zero, direction judged by the metric's polarity), `no-clear-change`, or `insufficient-data` (fewer than 5 values on a side). Groups pair by test and metric on the same device; `--match metric` pairs renamed tests, `--allow-cross-device` pairs different devices (only for deliberate device comparisons), and `--fail-on-regression` exits 5 for CI.
- Aggregate diagnostic symbols separately from elapsed metrics: median self/inclusive weight, run presence rate, stable versus sporadic paths, main-thread state, and signpost overlap.
- Do not infer causation solely from correlation or a single hot stack.

## Privacy and bounding

- HAR, network, logging, stdout/stderr, signpost payloads, file paths, screenshots, and accessibility trees may contain credentials or personal content.
- Redact headers, query values, bodies, tokens, cookies, identifiers, local home paths, and user-entered data before model use.
- Keep the full artifact locally with access controls and retention limits. Give the LLM bounded summaries and stable evidence IDs/paths.
- When evidence is too large, narrow by run, process, thread, schema, time range, signpost phase, and top-N—not by silently truncating without noting it.

## Final report shape

1. **Answer:** direct performance conclusion and target/build scope.
2. **Measurement:** metric source, values, median/p90/spread, and comparison delta.
3. **Quality:** valid/invalid runs, schema/row/activity/symbol status, warnings, and contamination.
4. **Explanation:** repeated evidence linked to runs, phases, symbols, thread states, or resources.
5. **Confidence:** high, directional, or inconclusive with rationale.
6. **Recommendations:** smallest evidence-backed changes, ordered by likely impact and verification cost.
7. **Next experiment:** a focused capture that can confirm or reject the leading unresolved hypothesis.
8. **Artifacts:** trace/result/manifest/export paths.

Use calibrated language: “consistent evidence,” “likely contributor,” “associated with,” or “inconclusive.” Do not claim a full expected speedup before remeasurement.
