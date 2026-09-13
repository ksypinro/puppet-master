# Running tests

Composing a run. Read before anything beyond a single `run_tests.py test`.

## Discover first, always

```sh
python3 scripts/test_doctor.py --path /abs/project --destinations
```

Guessing a scheme name costs a failed build; guessing a destination costs a
confusing one. The discovery output settles both, plus the toolchain and the
shared-scheme question below.

### The shared-scheme trap

Schemes live in two places:

```
<project>.xcodeproj/xcshareddata/xcschemes/            committed
<project>.xcodeproj/xcuserdata/<you>.xcuserdatad/xcschemes/   yours alone
```

`xcodebuild -list` shows both on your machine. On CI or a fresh clone the second
set does not exist, so targets silently drop out of the run and it still reports
green. `test_doctor.py` reads the filesystem to tell them apart — `-list`
cannot — and warns when any scheme is unshared.

## Container precedence

A workspace wins over a project when both exist, because that is what resolves
package and pod dependencies. `test_doctor.py` picks correctly; if you compose a
command by hand, use `-workspace` whenever one is present.

## Test plans

Plans are the right place to encode configuration — repetitions, localisation,
diagnostics, environment, and which tests to skip — instead of multiplying
schemes.

- `-testPlan <name>` works with `-scheme`. It does **not** work with
  `-xctestrun`; the plan is already baked into the generated file.
- `test_doctor.py` reports each plan's target count, whether coverage is on, and
  whether it carries `skippedTests` entries.
- Plan settings propagate into the `.xctestrun`: execution ordering, default and
  maximum test time allowances, language and region as
  `CommandLineArguments`, and `ClangProfileDataDirectoryPath` only when coverage
  is enabled.
- The plan name appears in the bundle as `environmentDescription`, e.g.
  `"Fast · Built with macOS 26.5.1"`. Use it to confirm the plan you meant
  actually ran.

## Build once, run many

For anything repeated — repetition modes, several destinations, sharding —
separate compilation from execution:

```sh
python3 scripts/run_tests.py build --project /abs/App.xcodeproj --scheme App \
    --destination-id <UDID> --out /abs/run

python3 scripts/run_tests.py test \
    --xctestrun /abs/run/DerivedData/Build/Products/App_Fast_*.xctestrun \
    --destination-id <UDID> --out /abs/run/fast
```

`build-for-testing` emits **one `.xctestrun` per test plan**. The transportable
`.xctestproducts` bundle (`--test-products`) is preferable to copying arbitrary
DerivedData when moving a build between machines. Build and execute with the same
Xcode.

## Selection

```
--only  Target/Class/method       repeatable
--skip  Target/Class/method       repeatable
```

Enumerate without running to prove a filter matches:

```sh
xcodebuild -enumerate-tests -test-enumeration-format json \
    -test-enumeration-style hierarchical \
    -test-enumeration-output-path /abs/run/enumerated.json …
```

A filter that matches nothing **exits clean**. Without enumeration you cannot
distinguish "all selected tests passed" from "no tests were selected".

## SwiftPM

For a Swift package, `swift test` is a much faster loop than `xcodebuild`:

```sh
swift test                                # XCTest and Swift Testing together
swift test list                           # enumerate both frameworks
swift test --filter 'HeavyWorkloadTests'  # regex
swift test --skip-build --filter 'Traits'
swift test --parallel --num-workers 4
swift test --enable-code-coverage
swift test --show-codecov-path
swift build --build-tests                 # build without running
```

Three traps, all verified:

- **`--filter` matches symbol names, not display names.** `swift test list`
  prints `CoreKitTests.HeavyWorkloadTests/linearSearchIsSlow()`. Filtering on a
  `@Suite` display name like `'HeavyDemo'` silently matches nothing and reports
  *"No matching test cases were run"* with a zero exit. Always `list` first.
- **`--xunit-output` is asymmetric.** It writes `<name>-swift-testing.xml`
  always, but `<name>.xml` for XCTest **only when `--parallel` is passed**.
- **SwiftPM produces no `.xcresult`.** Performance results print to stdout.
  Everything in `test_results.py` and `coverage_report.py` needs a bundle, so
  use `xcodebuild` when you need structured evidence.

Coverage for a package comes from the profdata SwiftPM writes:

```sh
xcrun llvm-cov report \
    .build/debug/<Name>Tests.xctest/Contents/MacOS/<Name>Tests \
    -instr-profile .build/debug/codecov/default.profdata
```

## XCTest and Swift Testing coexist

Both run from one bundle and one command. They differ in ways that matter when
reading results:

| | XCTest | Swift Testing |
|---|---|---|
| Naming | `testFoo()` | prose display names |
| Parameterisation | none | `Arguments` nodes per case |
| Parallelism | process-level | **in-process by default** |
| Performance API | `measure`, `XCTMetric` | none |
| UI automation | XCUIAutomation | none — still XCTest |

`test_results.py tests` infers the framework from naming and reports the split,
which is how you measure migration progress from the bundle alone.

Swift Testing's default in-process parallelism is worth knowing: three
one-second tests complete in about one second. `.serialized` changes that, and
changes timing-sensitive behaviour with it.

## Repetition and parallelism

Repetition modes are covered in [failure-triage.md](failure-triage.md) — they
are a triage tool, not a throughput tool.

Parallel testing **clones the device**. Results are attributed to
`Clone 1 of iPhone 17 Pro`, and each worker starts a fresh process, so a test
that depends on state left by an earlier test in the same process will fail on a
clone while passing serially. That is a real bug the clone exposed, not a
parallelism artefact.

`-parallelize-tests-among-destinations` distributes classes across destinations
rather than cloning the suite. It is explicitly **not a stable sharding
contract**. For deterministic ownership, compute shards yourself and pass
explicit `-only-testing` lists.

## Coverage must be decided before the run

`-enableCodeCoverage YES` (or `--coverage`) cannot be added to a bundle
afterwards. If coverage might be asked for, enable it up front.

## Device lanes

Simulator lanes are fully supported by this skill and exercised by its fixtures.
Physical device execution additionally requires:

- signing for both the app and the test target, plus a runner app for UI tests;
- Developer Mode enabled, the device unlocked and paired;
- an exclusive lease — two jobs contending over install or XCTest on one device
  is a common source of false failures.

A device that launches the app by hand can still fail UI-test setup on signing,
runner entitlements or test-manager connectivity. Those failures are
*infrastructure*, and the diagnostics in [failure-triage.md](failure-triage.md)
are how you prove it.

**This skill's device lane is unverified.** Report device results as such rather
than implying the same confidence as Simulator results.

## After the run, always

```sh
python3 scripts/test_results.py triage /abs/run/Run.xcresult
```

A non-zero `xcodebuild` exit does not mean a test failed — it also covers build
failure, signing failure, a runner that never launched, and a watchdog kill.
Only the bundle tells them apart, and if there is no readable bundle that is a
run failure, not a test failure.
