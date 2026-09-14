# Reading a result bundle

The extraction surface, and what each layer is actually good for. Everything
here is read-only.

## Ask what is in the bundle first

```sh
python3 scripts/test_results.py availability /abs/Run.xcresult
```

```
yes  test results
yes  coverage
yes  diagnostics
logs: action
```

A run recorded without `-enableCodeCoverage YES` has no coverage to recover, and
querying anyway returns something ambiguous. On a bundle whose provenance you do
not control — a CI artifact, a teammate's upload, something from six months ago
— this is the correct first call.

`logs` tells you whether build output survived. Only `action` means the run was
`test-without-building` and no compilation happened.

## The layers

| Command | Layer | Use it for |
|---|---|---|
| `get test-results summary` | verdict, counts, devices, insights | the gate |
| `get test-results tests` | normalized hierarchy | inventory, framework hint, **hidden flakes** |
| `get test-results test-details` | per-repetition runs, source location | failure forensics |
| `get test-results activities` | per-run UI-test step trees | stall candidates and attachment context |
| `get test-results insights` | Apple's own clustering | direct native query; not wrapped here |
| `get test-results metrics` | measurements with thresholds | gateability |
| `get build-results` | errors, warnings, analyzer warnings | warning budgets |
| `export diagnostics` | testmanagerd, scheduling, stdout | infra vs product |
| `export attachments` | screenshots, videos, custom attachments | failure evidence |
| `compare --baseline-path` | introduced / resolved | PR gating |
| `merge` | one bundle from many | matrix aggregation |

The other listed layers are wrapped by `test_results.py`, `compare_runs.py`, or
`coverage_report.py`.

Two are deliberately **not** wrapped:

- **`get log`** — raw build and console logs. Use `xcrun xcresulttool get log
  --path B --type build` (or `action`/`console`). This command does not accept
  `--format` on the supported toolchain.
- **`get test-results insights`** — call the native command when the summary's
  `topInsights` is insufficient.
- **`export evaluations`** — Xcode 27's model-quality results. Real, and
  genuinely test-shaped, but a different evidence contract with its own scoring
  and judge semantics. It belongs in a skill of its own rather than bolted on
  here.

## Summary: read both counts

```sh
python3 scripts/test_results.py summary /abs/Run.xcresult
```

```
test cases 12   test runs 14   ← counts differ, see statistics below

statistics
  1 test ran with dynamic parameters — 3 test runs
  4 tests collected performance metrics — 4 test runs
```

Both numbers are correct. The top level counts **test cases**; the per-device row
counts **test runs**. One parameterised Swift Testing case contributes 1 and N.

The bundle reconciles itself in `statistics` — read that rather than picking the
number you prefer. Whichever you report, say which rule it used.

Other fields worth using:

- **`osBuildNumber`** — the exact OS build, not just `27.0`. It is the axis most
  flake correlates with. Record it or you cannot correlate later.
- **`expectedFailures`** — `XCTExpectFailure` and `withKnownIssue` hits. This is
  suppression debt; rising is a signal.
- **`runtimeWarnings`** — main-thread violations and constraint conflicts, free
  on every run and almost always ignored.
- **`environmentDescription`** — carries the test plan name, so you can confirm
  the plan you meant actually ran.

## Insights: Apple already did the clustering

```
insights (computed by Xcode)
  [100% of failures] 3 runs of 1 test failed with XCTAssertGreaterThan failed: …
```

Three categories exist: common failures with an impact percentage, failure
distribution, and longest test runs. They populate only when there is something
to report, cost one field read, and are the cheapest triage ordering available.
On a build with forty failures this is the difference between forty bugs and one
bug with forty symptoms.

## Failures: the stable key and the real line

```sh
python3 scripts/test_results.py failures /abs/Run.xcresult
```

Each failure carries:

- **`testIdentifierURL`** — `test://com.apple.xcode/App/Target/Suite/method`.
  Stable across runs, machines and Xcode versions. **This is the key to store**;
  display names change when someone renames a test.
- **`failureText`** — the assertion message. Normalise it (strip numbers and
  addresses) to cluster the same failure across runs.
- **`sourceLocation`** — a real `filePath` and `lineNumber`, openable in an
  editor. Wiring this up removes the slowest manual step in a red-build loop.

A location of `/<compiler-generated>` is synthesised. `test_results.py` flags it
and never presents it as the failing line; do the same in your own reports.

## Hierarchy: six node types, and what they reveal

```
Test Plan → Unit test bundle / UI test bundle → Test Suite → Test Case
                                                   ├─ Arguments    (parameterised)
                                                   └─ Repetition   (repeated runs)
                                                        └─ Failure Message
```

```sh
python3 scripts/test_results.py tests /abs/Run.xcresult
```

Three things fall out of the shape:

1. **Framework hint.** The script guesses XCTest for conventional `testFoo()`
   names and Swift Testing otherwise. This is a name heuristic, not measured
   framework metadata; either framework can use a misleading name.
2. **`Arguments` nodes explain any count discrepancy**, and on a failure tell you
   *which input* broke. `"gull"` failing while `"kelp"` passes is a far better
   bug report than "the test failed".
3. **`Repetition` nodes are where hidden flakes live.** A `Test Case` can report
   `Passed` while carrying a `Failed` repetition. See below.

## The hidden flake

The single most valuable check in this skill.

With `-retry-tests-on-failure`, a test that fails then passes produces:

```
result: Passed        failedTests: 0        testFailures: []
```

and the only surviving evidence is inside the hierarchy:

```
Test Case    testFlakyOnFirstAttemptInProcess()    Passed
  Repetition   First Run                           Failed
    Failure Message  XCTAssertGreaterThan failed: …
  Repetition   Retry 1                             Passed
```

Anything reading the summary reports green. `test_results.py triage` walks the
hierarchy and surfaces these separately from real failures. Never report a green
run without it.

## Activities: where a UI test stalled

```sh
python3 scripts/test_results.py activities /abs/Run.xcresult --test-id <URL>
```

```
Start Test at 2026-09-12 12:06:33.911
Set Up
Open com.example.App
└─ Launch com.example.App
   ├─ Terminate com.example.App:37249
   ├─ Setting up automation session
   └─ Wait for com.example.App to idle
```

- Each failed run's final or failure-associated step is a **stall candidate**,
  not proof of cause. Stopping at *"Wait for … to idle"* means XCTest was
  waiting for quiescence; correlate timestamps, app logs, and attachments before
  deciding whether the app or harness caused it.
- Timestamps expose the cost split. When *"Setting up automation session"* takes
  seconds per launch, a 44-second test is mostly harness overhead and adding
  iterations buys precision at brutal cost.
- PIDs cross-link to the app's stream in `export diagnostics`.
- XCTAttachment screenshots hang off these nodes, anchored to the step that
  produced them.

## Metrics: gateability, not statistics

```sh
python3 scripts/test_results.py metrics /abs/Run.xcresult
```

```
metric                          n         mean     RSD   gateability
CPU Instructions Retired       10        55807    0.5%   gateable
Memory Peak Physical           10        51091    0.3%   gateable
Clock Monotonic Time           10     0.004925    8.9%   gateable
App launch (first frame)        5       4.3078   22.9%   too-noisy !
Memory Physical                10       29.491  245.7%   too-noisy !
```

Same test, same run. The noise floor decides whether a metric can carry a gate:
instructions retired is nearly deterministic because it ignores CPU frequency and
thermal state; a memory *delta* whose raw values are mostly zero with one spike
is not a measurement at all.

Thresholds travel with the data — `maxPercentRegression` and
`maxPercentRelativeStandardDeviation` come from your test plan, so `!` marks a
metric exceeding its own configured limit.

**Regression comparison, baselines and confidence intervals belong to
`ios-instruments-profiler`** (`scripts/xcresult_metrics.py`). This command only
answers whether a metric is gateable at all, which is a test-quality question.

## Comparing two runs

```sh
python3 scripts/compare_runs.py compare /abs/candidate.xcresult --base /abs/baseline.xcresult
```

Wraps `xcrun xcresulttool compare`, which emits JSON natively and — unlike
`get` — rejects a `--format` flag.

Returns `introduced` / `resolved` counts across test failures, build warnings,
analyzer issues, and tests executed. This is a comparison component, not a
complete PR gate: require `gateReady`, inspect hidden retries, and verify the two
manifests describe comparable builds, plans, configurations, and destinations.

Two things to use it for:

- **Gate on `introduced`, report `resolved`.** Enforceable on a legacy codebase
  where a zero-warning rule never will be.
- **Watch `testsExecuted.removed`.** A test that disappears — deleted, skipped,
  or lost to a scheme change — makes the suite greener while making it weaker. A
  pass/fail gate cannot see this.

Narrowing flags (`--test-failures`, `--tests`, `--build-warnings`,
`--analyzer-issues`) keep a CI comment to the category that changed.

## What no single bundle can tell you

A bundle knows about one run. Flake rates, duration trends and coverage
direction all need storage you provide, keyed on `testIdentifierURL`. Say so
rather than implying a trend from a single result.
