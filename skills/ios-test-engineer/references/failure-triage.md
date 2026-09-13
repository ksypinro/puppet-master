# Failure triage

Read this whenever a run is red, a test is suspected flaky, or anyone proposes a
retry. It is the most consequential reference in this skill: the difference
between a CI system that surfaces regressions and one that buries them is
entirely here.

## The rule

**Retry only an infrastructure failure.** In every other case a retry converts a
true signal into a green build.

An infrastructure failure means the assertion never ran — the runner did not
launch, the test manager never connected, the simulator was shut down, the
install failed. Retrying is correct because nothing about the product was
tested. Anything else — a failed assertion, a crash inside the app, a timeout
waiting on the app — is evidence, and retrying destroys it.

## Step 1: run triage before anything else

```sh
python3 scripts/test_results.py triage /abs/run/Run.xcresult
```

It reports two independent things, and the second is the one people miss.

### Classified failures

Each failure gets a verdict:

| Verdict | Means | Retry? |
|---|---|---|
| `deterministic` | failed every repetition | **No.** Real failure. |
| `flaky` | passed and failed within the same run | **No.** Fix or quarantine. |
| `infrastructure` | matched a runner-failure signature | Yes, after confirming with diagnostics. |
| `unclassified` | one run only, nothing to compare | Re-run under the three modes first. |

### Hidden flakes

A test that the run reports as **passed** but which failed at least one
repetition. This is not in `testFailures`, does not affect `failedTests`, and is
invisible to anything reading the summary alone.

```
1 HIDDEN FLAKE(S) — the run reports Passed, but these failed a repetition

[HIDDEN-FLAKE] testFlakyOnFirstAttemptInProcess()   [DemoAppTests]
  reported result: Passed   but 1 of 2 repetitions failed
    ✗ First Run: Failed
    ✓ Retry 1: Passed
```

If you report that run as green without mentioning this, the flake stays
invisible until it fails on someone else's branch.

## Step 2: when one run is not enough

A single run cannot distinguish a real failure from a flaky one. The three
repetition modes are the experiment, and they return **different verdicts on
identical code** — verified, not assumed:

| Mode | Behaviour | Verdict on the same flaky test |
|---|---|---|
| `--repetition retry` | re-runs in the **same process** | `TEST EXECUTE SUCCEEDED` |
| `--repetition relaunch` | **fresh process** per iteration | `TEST EXECUTE FAILED` |
| `--repetition until-failure` | stops at the first red | reproduces a rare flake |

So:

```sh
# Is the failure real, independent of process state?
python3 scripts/run_tests.py test … --repetition relaunch --iterations 3 \
    --only MyTests/FlakyCase --out /abs/run/relaunch
python3 scripts/test_results.py triage /abs/run/relaunch/Run.xcresult
```

`relaunch` is the honest mode. `retry` hides per-process state leakage — a test
polluted by a previous test in the same process passes on the second attempt and
tells you nothing. If `relaunch` fails every iteration, the failure is real.

**Whichever mode you used, name it in the report.** A verdict without its mode
is not a verdict.

## Step 3: infrastructure or product?

`triage` now does this for you: it exports the diagnostics and reads them, so an
`infrastructure` verdict is backed by evidence rather than by the failure text
alone. The confidence it reports says which:

| Confidence | Means |
|---|---|
| `high` | the text matched **and** the diagnostics corroborate it |
| `medium` | the text matched but the diagnostics show nothing — usually a product failure wearing infrastructure wording |
| `low` | no readable diagnostics; do not retry on the text alone |

To keep the exported files, or to read them yourself:

```sh
python3 scripts/test_results.py diagnostics /abs/run/Run.xcresult --out /abs/run/diag
```

The signal patterns are deliberately narrow, because a false positive here tells
you to retry a real failure. A **healthy** run's `testmanagerd.log` contains
`(result:error)` as a tuple label on successful replies, `TESTMANAGERD_SIM_SOCK`
as an environment variable name, and `Requesting crash report collection for
process names: …` as routine setup. Loose matching flags all three. The patterns
are verified to produce zero matches on passing runs — `scripts/test_selftest.py`
holds that oracle.

What to read, and what each answers:

| File | Answers |
|---|---|
| `*/testmanagerd.log` | Did the test manager connect at all? If not, nothing ran. |
| `*/scheduling.log` | Worker lifecycle, PIDs, whether parallelisation was actually on, and `cancelled: Yes/No` |
| `*/StandardOutputAndStandardError.txt` | The test process's own output |
| `*/StandardOutputAndStandardError-<bundle-id>.txt` | The **app's** output — runtime warnings, constraint conflicts, your `print` calls |

`scheduling.log` is small (hundreds of bytes) and dense:

```
06:06:19 Parallelization disabled; test execution driven by the test process
06:06:28 Finished executing tests (cancelled: No)
```

`cancelled: No` matters. A timeout-killed run and a genuinely failing run look
similar in the summary and are completely different problems.

The app's own stream is usually enormous — over a megabyte is normal — and is
where a crash or a runtime warning will be, keyed by PID. The PIDs come from the
activity tree (`test_results.py activities`).

## Step 4: decide, and say what you decided

A complete triage report names:

1. The verdict per failure and the classification behind it.
2. The repetition mode that produced it.
3. Whether a retry is justified, and for which failures specifically.
4. Hidden flakes, separately, even when the run was green.
5. What remains unknown — a bundle without diagnostics cannot confirm an
   infrastructure classification, and `triage` says so.

## Quarantine, honestly

If the user wants a known-flaky test out of the way, the supported mechanism is
the test plan's `skippedTests`, not a retry flag:

- `skippedTests` in a `.xctestplan` removes it from the run explicitly, and
  `test_doctor.py` reports which plans have entries.
- A retry flag leaves the test nominally running while guaranteeing it reports
  green. That is not quarantine; it is concealment.

Either way, a quarantined test is debt. Report the count alongside the verdict so
it stays visible. `expectedFailures` in the summary is the same kind of debt for
`XCTExpectFailure` and `withKnownIssue`.

## Signatures treated as infrastructure

Two separate pattern sets, both in `test_results.py`.

**`INFRA_PATTERNS`** matches the *failure text* from the summary — a hint that
the assertion may never have run:

- lost connection to the test or debug runner
- the runner app failed to launch or start
- `Unable to lookup in current state … Shutdown` — the simulator was shut down,
  which `xcodebuild` does after every run, so back-to-back automation hits this
- timed out waiting to launch, connect, or install
- simulator failed to boot or install
- the process died before any assertion ran
- Developer Mode disabled, or the device is locked

**`DIAG_SIGNALS`** matches the *diagnostic logs* and is the corroborating
evidence. It is deliberately much narrower, and anchored to wording that only
appears on failure:

- `(cancelled: Yes)` — the run was cancelled rather than completed
- `Lost connection to the test runner`
- `Failed to establish communication with` / `Failed to install or launch` the
  test runner
- the runner `exited with code` / `early unexpected exit`
- `Canceling tests due to timeout`
- `Test operation failure:`
- `Unable to lookup in current state: Shutdown`
- `Timed out waiting for … launch/connect/install/ready`
- `Failed to boot` / `Failed to install`

Note what is **absent** from that second list. `testmanagerd` and `error` and
`crash` all appear in a completely healthy log — as `TESTMANAGERD_SIM_SOCK`, as
the `(result:error)` tuple label on successful replies, and as
`Requesting crash report collection for process names: …`. Matching on them
flags every passing run as infrastructure failure, and would justify retrying
real regressions. `scripts/test_selftest.py` enforces zero matches on passing
runs.

If a failure matches neither set, it is product evidence until proven otherwise.
