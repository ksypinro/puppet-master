---
name: ios-instruments-profiler
description: Plan, record, validate, export, reduce, compare, and explain iOS or iPadOS app performance with XCTest and Xcode Instruments from the command line. Use for launch time, CPU, hangs, memory, leaks, I/O, networking, rendering, SwiftUI, concurrency, power, or analysis of existing .trace and .xcresult artifacts on Simulator or connected Apple devices. Do not use for ordinary functional UI testing when no performance evidence is requested.
license: MIT
compatibility: Requires macOS and full Xcode: xctrace does not ship with the standalone Command Line Tools. Python 3.9+. Claims about real CPU, GPU, memory pressure, thermal, energy, or power require a connected physical Apple device.
metadata:
  author: Kazi Samin Yeaser
  version: "1.0.0"
  repository: https://github.com/ksypinro/puppet-master
  short-description: Plan, record, validate, export, reduce, compare, and explain iOS or iPadOS app p
---

# iOS Instruments Profiler

Produce a reproducible performance result, not merely a successful `xctrace` invocation. Separate authoritative measurements from diagnostic samples, preserve raw artifacts, and give the LLM bounded evidence with explicit quality and confidence.

## Non-negotiable boundaries

- Require macOS and full Xcode. `xctrace` does not come from the standalone Command Line Tools package.
- Discover the selected Xcode, target, templates, and instruments at run time. An installed name is not proof that it records or exports useful data on a particular Simulator, device, OS, mode, or workload.
- Use Simulator for pipeline development and repeatable local trends. Use one identified physical device for claims about real CPU, GPU, memory pressure, I/O, thermal, energy, Neural Engine, or user-facing device performance.
- Keep measurement and profiling distinct. XCTest metrics or deliberately defined signpost/field telemetry measure elapsed outcomes; Time Profiler and most Instruments tables diagnose where sampled work occurred.
- Never report summed Time Profiler or App Launch CPU samples as elapsed launch time.
- Prefer a Release/Profile build without a debugger, code coverage, sanitizers, or unrelated diagnostics. Record the build, binary UUID, dSYM, target, OS, Xcode build, fixture state, and scenario.
- Prefer one focused template per hypothesis. A broad trace is for discovery; confirm a suspected cause with a narrower trace.
- Do not feed raw, unbounded XML, HAR, logs, or multi-gigabyte traces into the model. Export, redact, normalize, bound, and summarize them with deterministic code first.
- Do not edit app source, add signposts, install dependencies, alter signing, erase a Simulator, reset app data, or change a device unless the user authorized that action.

## Select the investigation mode

Before recording, turn the request into a metric and an observable scenario. Read only the references needed for that mode:

- For template choice, target fidelity, common questions, and the conditions each instrument needs, read [references/instrument-selection.md](references/instrument-selection.md).
- For new recordings, repeated runs, UI-driven scenarios, Simulator/device handling, or signposts, read [references/recording-workflows.md](references/recording-workflows.md).
- For app launch timing or launch diagnosis, also read [references/launch-performance.md](references/launch-performance.md).
- For existing traces, export, reducers, comparison, statistics, quality gates, privacy, or the final report, read [references/analysis-contract.md](references/analysis-contract.md).

Use these evidence modes:

1. **Launch measurement:** XCTest `XCTApplicationLaunchMetric`; App Launch traces are a separate diagnostic lane.
2. **CPU or slow operation:** Time Profiler or CPU Profiler, scoped to the app, thread, signposted phase, and fixed action sequence.
3. **Hang or responsiveness:** Hangs plus Thread State/System Trace evidence; high CPU alone does not prove a hang. Hangs evaluates app processes, not command-line tools.
4. **Memory growth or leaks:** repeated Allocations/VM Tracker measurements and lifecycle-aware Leaks runs; one snapshot is not proof of a leak. Launch the target when allocation or leak stacks matter: an attached recording has no stack for anything allocated before it attached. These instruments export through track details, not schema tables.
5. **Scrolling or rendering:** Animation Hitches/Hitches, with a deterministic gesture script and frame/UI context; average FPS alone is insufficient.
6. **I/O, persistence, or networking:** File Activity/Data Persistence/Network plus app signposts. Redact exported paths, URLs, headers, bodies, logs, and user content before model use.
7. **Power, GPU, ML, Metal, or hardware counters:** require an appropriate physical device and a capability smoke test.
8. **Existing artifacts:** do not re-record unless the supplied trace lacks the evidence needed for the question.

## Bundled scripts

| Script | Role |
|---|---|
| `scripts/xctrace_doctor.py` | Toolchain, inventory, device, disk, and known-defect checks; optional smoke recordings |
| `scripts/xctrace_record.py` | One bounded recording with watchdogs, TOC export, schema and row gates, and a manifest |
| `scripts/xctrace_export.py` | TOC inventory (tables and track details), TOC-checked table/detail export, HAR, preview |
| `scripts/xctrace_reduce.py` | Typed, bounded summaries of exported tables and track details |
| `scripts/xcresult_metrics.py` | XCTest metric statistics and baseline-versus-candidate comparison |
| `scripts/xctest_selection.py` | Prove a test filter or `-only-testing` selection matches tests before a measured run |

## Closed experiment loop

### 1. Define the contract

State the app/bundle, build, target and OS, metric and unit, scenario, launch state if relevant, endpoint, fixture/account/network state, iteration count, warm-up policy, template, expected schemas, output directory, and acceptance or comparison rule. If a missing choice would materially change the result, ask before recording; otherwise choose a conservative default and disclose it.

### 2. Run capability checks

Use the bundled doctor before a new capture:

```sh
python3 scripts/xctrace_doctor.py \
  --template 'Time Profiler' \
  --device 'DEVICE_NAME_OR_UDID' \
  --output-dir '/absolute/path/to/run' \
  --smoke-record --smoke-attach 'ProcessName'
```

For an installed Simulator app, add `--simulator-udid` and `--bundle-id`. The doctor returns structured JSON and exits nonzero when a requested prerequisite fails. It reports known defects of the installed `xctrace` build and fails when one blocks the target: Xcode 27 beta 27A5194q cannot record on any Simulator. `--smoke-record` records each requested template, and the requested instrument set on Blank, for two seconds (use `--smoke-launch` instead of `--smoke-attach` for launch-owned captures, or neither for all processes), then records each instrument alone if the set fails, so it names the instrument Xcode rejects. Preserve the report with the run manifest.

Do not start a multi-run experiment until one smoke trace finalizes, exports a TOC, contains the expected run/schema, and has rows from the target.

### 3. Establish deterministic state

- Reuse an explicit target identifier throughout the run set.
- Prove the test selection before measuring with it. A wrong `swift test --filter` or `-only-testing` runs nothing and still exits 0, which looks like a passing run with no measurements:

```sh
python3 scripts/xctest_selection.py swiftpm --package-path '/absolute/package' --filter 'SearchTests'
python3 scripts/xctest_selection.py xcodebuild --xctestrun '/absolute/App_Plan_….xctestrun' \
  --destination 'platform=iOS Simulator,id=DEVICE_UDID' --only-testing AppTests/SearchTests
```

  It exits 3 when a selector matches nothing, and names the identifier you probably meant.
- Stabilize reproducible UI state with XCTest or an available semantic UI driver. Use the existing `ios-simulator-driver` skill when available for Simulator interaction; otherwise use a deterministic XCUIAutomation, AXe, idb, Appium/WebDriverAgent, or equivalent workflow.
- The LLM may plan the fixed action script and recover before a run. It must not improvise during a measured iteration. Mark any run that required recovery as non-comparable unless the experiment contract explicitly allows it.
- For post-launch work, launch and settle the app first, start an attach-based trace, wait for recording-start evidence, run the fixed actions, verify the semantic endpoint, and stop the capture.

### 4. Record one bounded artifact

Use one `.trace` per diagnostic iteration. The helper builds an argument array, applies start/completion watchdogs, stops only its own process group, exports the TOC, checks expected schemas and row counts, and writes a manifest:

```sh
python3 scripts/xctrace_record.py \
  --template 'Time Profiler' \
  --device 'DEVICE_UDID' \
  --attach 'ProcessName' \
  --time-limit 15s \
  --run-name 'search-01' \
  --expect-rows time-profile:100 \
  --output '/absolute/path/to/search-01.trace'
```

Use `--launch BUNDLE_ID_OR_APP_PATH` for a launch-owned trace or `--all-processes` only when system-wide context is required. Arguments for a launched target go after a standalone `--` (or in `--launch-arg=-flag` form when they start with a dash), which is how a test bundle is profiled without Xcode:

```sh
python3 scripts/xctrace_record.py \
  --template 'Time Profiler' \
  --launch "$(xcode-select -p)/usr/bin/xctest" \
  --time-limit 20s --expect-rows time-profile:100 \
  --output '/absolute/path/to/unit-test.trace' \
  -- -XCTest MyTests.SearchTests '/absolute/path/to/MyTests.xctest'
```
 Run with `--dry-run` first when target syntax or launch arguments are uncertain. Do not automatically retry more than once, and never retry an unsupported target/template, missing app, unmatched dSYM, or invalid experiment contract.

Gates beyond "the file saved":

- `--expect-rows SCHEMA[:MIN]` fails the run as `expected-rows-missing` when the table has fewer rows; use it for the table that answers the question.
- With `--launch`, a trace whose `time-profile` or `cpu-profile` has fewer than `--min-launch-samples` (default 20) rows fails as `target-inactive`: the target probably never ran. Attached traces only warn, because an idle target is legitimate.
- The completion grace defaults to the template's observed save cost (System Trace 10 min, File Activity 6 min, Metal GPU Counters 5 min, otherwise 2 min) and grows with the time limit. Keep kernel-event templates to a few seconds.
- `recorder_errors` in the manifest lists what Xcode rejected, such as an instrument unsupported on the platform.

### 5. Validate, symbolicate, and export

- Preserve the original trace. Symbolicate a copy using matching dSYMs when app frames are unresolved.
- Treat a trace as invalid if it never finalized, contains only run-issue boilerplate, cannot export a TOC, lacks the expected run/table, or contains no relevant rows.
- Inventory before selecting a table. The summary lists schema tables and track details:

```sh
python3 scripts/xctrace_export.py toc \
  --trace '/absolute/path/to/run.trace' \
  --output '/absolute/path/to/run.toc.xml'
```

- Export only what the TOC lists: `table --schema time-profile` for a schema table, or `table --track Allocations --detail Statistics` for a track detail (Allocations, Leaks and VM Tracker have no schema tables). The helper checks the name against the TOC, counts the exported rows, and warns on zero. Use `har` or `preview` as described in [references/analysis-contract.md](references/analysis-contract.md). A generic preview supports discovery, not semantic conclusions.

### 6. Reduce and aggregate deterministically

- Reduce each export with the bundled analyzer instead of reading XML:

```sh
python3 scripts/xctrace_reduce.py \
  --input '/absolute/path/run.time-profile.xml' \
  --process 'MyApp' --top 15
```

  It recognizes `time-profile`/`cpu-profile` (self, inclusive and first-app-frame rankings), `potential-hangs`, `OSSignpostIntervals`, `os-signpost`, `hitches*`, `core-data-*`, and the Allocations Statistics, Allocations List and Leaks details; anything else gets a generic column summary that infers no meaning. `--thread`, `--start-ms` and `--end-ms` filter rows, which matters because some `xctrace` builds ignore export time windows. An `"empty"` status means not captured, not zero.
- Resolve `id`/`ref` values, detect missing references, establish stack order, normalize declared units, and filter by process/run/thread/time range before aggregation. The reducer does this for the tables it knows; write a template-specific analyzer for any other table a conclusion depends on.
- For XCTest result bundles, extract performance metrics, and compare against a baseline bundle when there is one:

```sh
python3 scripts/xcresult_metrics.py \
  --path '/absolute/path/Candidate.xcresult' \
  --baseline-path '/absolute/path/Baseline.xcresult' \
  --metric 'Application Launch'
```

- Keep elapsed measurements separate from diagnostic CPU weights. Across comparable runs, report valid values, median, p90, min/max, MAD or IQR, invalid count, and conditions. Treat small-sample p90 as directional. A comparison verdict (`regression`, `improvement`, `no-clear-change`, `insufficient-data`) comes from a bootstrap interval of the median difference; it only holds for runs with the same device, build configuration, and scenario.
- For diagnostic traces, aggregate stable symbols/phases by self and inclusive weight, presence rate, thread state, signpost overlap, and their association with slower measured runs. Correlation proposes a cause; it does not prove it.

### 7. Decide whether another trace is justified

Request a narrower follow-up only when it can confirm or reject a named hypothesis. Examples: File Activity after repeated database I/O appears in App Launch; Allocations after persistent growth appears; System Trace after main-thread blocking appears. Stop when the evidence answers the request, the next capture would not discriminate between hypotheses, or a prerequisite needs user action.

## Evidence and reporting rules

Every final result must include:

- **Measurement:** metric, unit, all valid iteration values or a linked artifact, median/p90/spread, target, build, and measurement source.
- **Quality:** valid/invalid runs, trace and TOC status, expected-schema and row presence, target activity, symbolication coverage, warnings, and recovery contamination.
- **Diagnosis:** repeated hotspots, blocked/runnable intervals, allocations/I/O/network/frame/signpost evidence tied to run IDs and phases.
- **Confidence:** `high`, `directional`, or `inconclusive`, with the reason.
- **Recommendation:** the smallest change supported by the evidence; do not promise its impact before remeasurement.
- **Next experiment:** only if current evidence cannot decide the leading hypothesis.
- **Artifacts:** absolute paths to traces, result bundles, manifests, selected exports, normalized summaries, and relevant UI evidence.

Use `unknown`, `not captured`, `not exportable`, or `invalid` instead of numeric zero when evidence is absent. An instrument that recorded no rows has not shown absence unless [references/instrument-selection.md](references/instrument-selection.md) shows it captures that kind of target. Never claim GUI parity: `xctrace export --toc` is the authority for what a particular trace exposes.

## Failure and safety behavior

- A recording command returning success is not enough; require the post-capture gates.
- A timeout must target only the process created for this capture. Never kill every `xctrace` process on the host.
- Preserve raw logs and partial artifacts, classify the failure, and exclude invalid runs from statistics.
- Do not silently mix Simulator and device runs, cold/warm/resume launches, different app builds, changed fixtures, different templates/options, or recovered and clean runs.
- Treat network and logging exports as sensitive. Redact before quoting or sending to an LLM; do not expose credentials, tokens, personal data, request bodies, or private paths.
- If device trust, unlock, Developer Mode, privacy prompts, signing, or Xcode preparation requires user interaction, stop with the exact missing prerequisite rather than looping.

## Route by symptom

These four skills are one toolkit. Route on the symptom, not on the surface:

- Reaching a screen, dispatching taps, text, or gestures, or verifying a UI flow — `ios-simulator-driver`.
- A view is misplaced, clipped, overlapping, mis-styled, or untappable, or you need the native tree, geometry, or constraints — `ios-view-hierarchy-debugger`.
- A value, branch, or model state is wrong, or you need the code path that produced it — `lldb-code-state-debugger`.
- Measuring or diagnosing performance — **this skill**.

Hand off when the evidence needed is not the evidence this skill produces. If a listed skill is unavailable, say what it would have established rather than substituting weaker evidence for it. Preserve the established target — UDID or device, bundle ID, PID, build identity, driver session, and run directory — across the handoff; re-deriving it invalidates element references and pointers.
