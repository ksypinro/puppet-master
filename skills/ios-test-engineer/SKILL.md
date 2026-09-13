---
name: ios-test-engineer
description: Run iOS and Swift tests from the command line and turn the result bundle into trustworthy evidence. Use to execute XCTest, Swift Testing or XCUITest suites, select tests or test plans, read verdicts and failure source locations, classify a failure as deterministic, flaky or infrastructure, detect a test that passed only because a retry was allowed, and report region-aware code coverage. Also use to interpret an existing .xcresult bundle without re-running anything. Do not use for performance regression statistics, which belong to ios-instruments-profiler, or for driving app UI, which belongs to ios-simulator-driver.
license: MIT
compatibility: Requires macOS, full Xcode, and Python 3.9+. Simulator lanes are fully supported; physical-device test execution additionally needs signing, Developer Mode and a paired device, and is not verified by this skill's fixtures. Coverage requires the run to have been recorded with -enableCodeCoverage YES.
metadata:
  author: Kazi Samin Yeaser
  version: "1.3.0"
  repository: https://github.com/ksypinro/puppet-master
  short-description: Run iOS tests and read the result bundle honestly
---

# iOS Test Engineer

Produce a verdict the user can act on, not a green checkmark. A passing run is
not the same as a working suite, and a failing run is not the same as a broken
product. Separate what the bundle recorded from what it implies, and say which
is which.

## Non-negotiable boundaries

- **A green run is not proof the suite passed.** With `-retry-tests-on-failure`,
  a test that fails then passes makes the run report `result: Passed`,
  `failedTests: 0` and an **empty `testFailures` array**. The only surviving
  evidence is a `Failed` repetition node inside the test hierarchy. Never report
  green without running `test_results.py triage`, which finds these.
- **Never retry a failure you have not classified.** Retrying is legitimate for
  an infrastructure failure, where the assertion never ran. Retrying a real or
  flaky failure converts a true signal into a green build. Classify first.
- **Report which repetition mode produced the verdict.** The same code returns
  `SUCCEEDED` under `-retry-tests-on-failure` and `FAILED` under
  `-test-repetition-relaunch-enabled YES`. A verdict without its mode is not a
  verdict.
- **Two test counts disagree legitimately.** The top-level count counts test
  cases; the per-device row counts test runs. One parameterised Swift Testing
  case contributes 1 and N. Report both, and use the bundle's own `statistics`
  field to reconcile them rather than picking the flattering one.
- **Do not derive "uncovered lines" by subtracting covered from executable.** On
  Swift, most of that difference is autoclosures and short-circuited operands on
  lines that did run — including assertion failure messages, which are uncovered
  precisely *because the test passed*. Use `coverage_report.py gaps`, which
  separates dead code from never-evaluated sub-expressions.
- **A non-zero `xcodebuild` status does not mean a test failed.** It also covers
  build failure, signing failure, a runner that never launched, and a watchdog
  kill. Only the bundle distinguishes them; if there is no bundle, that is a run
  failure, not a test failure.
- **Use an explicit UDID for every run.** `booted` and bare device names can
  resolve to a different device between runs, which silently invalidates any
  comparison.
- **Do not edit tests, change signing, erase a Simulator, or reset app data**
  unless the user asked for that specific action. Diagnosis is not permission to
  modify the suite.

## Bundled scripts

All are read-only except `run_tests.py`. Python 3.9+, standard library only.
Resolve `SKILL_DIR` to this file's directory; paths below are relative to it.

| Script | Role |
|---|---|
| `scripts/test_doctor.py` | Discover schemes, which are **shared**, test plans, destinations, toolchain |
| `scripts/run_tests.py` | Bounded execution with a watchdog and a reproducibility manifest |
| `scripts/test_results.py` | Read one bundle: `summary` `failures` `tests` **`triage`** `activities` `metrics` `diagnostics` `attachments` `build-results` `availability` |
| `scripts/coverage_report.py` | `report` `gaps` `changed` `hot` — region-aware, so a gate never fires on an autoclosure |
| `scripts/compare_runs.py` | `compare` a candidate to a baseline, `merge` bundles, `matrix` attribution across cells |
| `scripts/xctest_selection.py` | Prove an `-only-testing` or `--filter` selection matches real tests **before** running |
| `scripts/xcresult_util.py` | Shared bundle validation, tool invocation and error type |
| `scripts/test_selftest.py` | Self-test for the classification logic; runs offline, no Xcode needed |

## The loop

### 1. Discover before running anything

```sh
python3 "$SKILL_DIR/scripts/test_doctor.py" --path /abs/project --destinations
```

Never guess a scheme, plan or destination. This reports the toolchain, the
container (workspace beats project), every scheme with whether it is **shared**,
each scheme's test plans and their coverage settings, and the destinations each
scheme actually supports.

Act on the shared-scheme warning. A scheme under `xcuserdata/` is not in version
control: CI and teammates will not see it, targets vanish from the run, and the
suite still reports green. On a multi-target project this is the most common
reason "all tests pass" means less than it appears to.

### 2. Choose the shape of the run

- **One suite, once:** `run_tests.py test --scheme … --plan … --destination-id …`
- **Repeated or matrix runs:** `run_tests.py build` once, then
  `run_tests.py test --xctestrun …` per destination. Building once avoids
  recompiling shared dependencies per cell.
- **Narrowing:** `--only Target/Class/method`, `--skip …`. **Verify the
  selection first** — a filter that matches nothing exits 0 and is
  indistinguishable from a pass:

  ```sh
  python3 "$SKILL_DIR/scripts/xctest_selection.py" xcodebuild \
      --xctestrun /abs/App_Fast_….xctestrun --only-testing AppTests/SearchTests
  python3 "$SKILL_DIR/scripts/xctest_selection.py" swiftpm \
      --package-path /abs/package --filter 'SearchTests'
  ```

  Exit 3 means a selector matched nothing. This catches the Swift Testing trap
  where a `@Suite("…")` display name is used as a filter: `--filter` matches
  the *symbol* identifiers `swift test list` prints, so the display name runs
  nothing and reports success.
- **Coverage must be decided up front.** It cannot be added to a bundle
  afterwards. Pass `--coverage` if coverage might be asked for.

Read [references/running-tests.md](references/running-tests.md) before composing
anything beyond the above: it covers test plans, SwiftPM, selection semantics
(including the Swift Testing `--filter` trap that silently matches nothing),
parallelism and device lanes.

### 3. Run it

```sh
python3 "$SKILL_DIR/scripts/run_tests.py" test \
  --project /abs/App.xcodeproj --scheme App --plan Fast \
  --destination-id <UDID> --coverage --out /abs/run/fast
```

Use `plan` instead of `test` to print the exact command without running it.
Every run writes `manifest.json` with the toolchain, argv, destination, timings
and exit status — enough to reproduce it, or to explain why two runs are not
comparable.

### 4. Read the result honestly

```sh
python3 "$SKILL_DIR/scripts/test_results.py" summary  /abs/run/fast/Run.xcresult
python3 "$SKILL_DIR/scripts/test_results.py" triage   /abs/run/fast/Run.xcresult
python3 "$SKILL_DIR/scripts/test_results.py" failures /abs/run/fast/Run.xcresult
```

`triage` is the one that must always run. It classifies every failure as
`deterministic`, `flaky`, `infrastructure` or `unclassified`, states what a retry
would and would not prove, and separately reports **hidden flakes** — tests the
run calls passed that failed a repetition.

It also exports and reads the diagnostics, so an `infrastructure` verdict rests
on evidence from `testmanagerd.log` and `scheduling.log` rather than on the
failure text alone. Confidence drops to `medium` when the text looks like a
runner failure but the diagnostics do not corroborate it — that combination is
usually a product failure wearing infrastructure wording.

For an unfamiliar bundle, start with `availability`: a run recorded without
coverage cannot produce coverage, and knowing that up front avoids an ambiguous
empty result.

Other layers, when the question calls for them:

```sh
test_results.py build-results  BUNDLE     # errors, warnings, analyzer warnings
test_results.py diagnostics    BUNDLE     # runner evidence; --out to keep it
test_results.py attachments    BUNDLE --out DIR   # failure screenshots and payloads
test_results.py activities     BUNDLE --test-id URL
```

`build-results` reports `status: notRequested` when the run did no compilation
(`test-without-building`). That is not a clean build — it means nothing was
built, and the script says so rather than reporting zero warnings.

Read [references/result-analysis.md](references/result-analysis.md) for the full
extraction surface and what each layer is good for.

### 5. Classify a failure before acting on it

Read [references/failure-triage.md](references/failure-triage.md) whenever a run
is red, a test is suspected flaky, or someone proposes a retry. It carries the
three-mode protocol, the infrastructure-versus-product decision, and the
diagnostics evidence that settles it.

The short version: a single run cannot distinguish a real failure from a flaky
one. Re-run under `--repetition relaunch` to decide.

### 6. Coverage, if asked

```sh
python3 "$SKILL_DIR/scripts/coverage_report.py" report /abs/run/fast/Run.xcresult
python3 "$SKILL_DIR/scripts/coverage_report.py" gaps   /abs/run/fast/Run.xcresult
```

`report` excludes test bundles by default — they measure tests testing
themselves and inflate the headline. `gaps` separates genuinely dead code from
sub-expressions that never evaluated, and explains each one. Only the dead-code
count belongs in a gate.

Read [references/coverage.md](references/coverage.md) before building any
coverage gate or reporting a percentage to a user.

### 7. Compare, or aggregate a matrix

```sh
python3 "$SKILL_DIR/scripts/compare_runs.py" compare /abs/pr.xcresult --base /abs/main.xcresult
python3 "$SKILL_DIR/scripts/compare_runs.py" matrix  /abs/run/*/Run.xcresult
python3 "$SKILL_DIR/scripts/compare_runs.py" merge   /abs/run/*/Run.xcresult --out /abs/run/all.xcresult
```

`compare` gives `introduced` versus `resolved` across test failures, build
warnings and analyzer issues — a complete PR gate with no history database.
Gate on `introduced`; also watch `testsExecuted.removed`, because a suite that
shrinks looks greener while covering less.

`matrix` answers what a failure count cannot: whether you are looking at
independent failures, one bug with platform reach, or one unhealthy destination.
Those need three different responses.

### 8. Report

State, in this order:

1. **The verdict**, with the repetition mode that produced it and the
   destination it ran on.
2. **Hidden flakes**, if any. These are the finding most likely to be new to the
   user.
3. **Each failure**: the test, the assertion, and the real source location. Say
   when a location is `/<compiler-generated>` and therefore not a real line.
4. **The classification** per failure, and explicitly whether a retry is
   justified.
5. **Coverage**, if asked, as real gaps rather than a line-count difference.
6. **What was not established.** Untested platforms, a partial run killed by the
   watchdog, a bundle with no diagnostics, absent coverage.

Keep raw artifacts. Link the bundle, the log and the manifest rather than
pasting them.

## Three ways a test result lies

Each is reproduced by this skill's own checks, not asserted.

1. **A retried pass looks like a pass.** `result: Passed`, `testFailures: []`,
   and a `Failed` repetition buried in the hierarchy. `triage` surfaces it.
2. **"Uncovered lines" are usually not code.** `?? []` fallbacks that never
   fired, short-circuited `||` operands, and assertion messages uncovered
   because the assertion passed. `coverage_report.py gaps` explains each.
3. **A metric's noise floor decides whether it can gate.** On one real run, CPU
   Instructions Retired had 0.5% relative standard deviation while Memory
   Physical had 245.7% — same test, same run. `test_results.py metrics` reports
   gateability per metric. The statistics themselves belong to
   `ios-instruments-profiler`.

## Scale and matrices

For more than one scheme or destination — the case where discovery, build
amplification, result aggregation and device contention start to dominate — read
[references/matrix-and-scale.md](references/matrix-and-scale.md) before running
anything. A naive matrix recompiles shared dependencies per cell and produces N
unaggregated verdicts.

## Route by symptom

These skills are one toolkit. Route on the symptom, not on the surface:

- Reaching a screen, dispatching taps, text, or gestures, or verifying a UI flow — `ios-simulator-driver`.
- A view is misplaced, clipped, overlapping, mis-styled, or untappable, or you need the native tree, geometry, or constraints — `ios-view-hierarchy-debugger`.
- A value, branch, or model state is wrong, or you need the code path that produced it — `lldb-code-state-debugger`.
- Launch time, CPU, hangs, jank, memory growth, leaks, I/O, or power — `ios-instruments-profiler`.
- Running a suite, reading a result bundle, classifying a failure, or coverage — **this skill**.
- Why an object is still alive, what is retaining it, or where the bytes went at a checkpoint — `ios-memory-debugger`.

Hand off when the evidence needed is not the evidence this skill produces. A
failing test tells you *that* something is wrong; `lldb-code-state-debugger`
tells you *why*. If a listed skill is unavailable, say what it would have
established rather than substituting weaker evidence for it. Preserve the
established target — UDID or device, bundle ID, build identity, run directory,
and result bundle path — across the handoff.
