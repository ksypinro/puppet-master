---
paths:
  - "**/*.swift"
  - "**/*.m"
  - "**/*.mm"
  - "**/*.h"
  - "**/*.xcodeproj/**"
  - "**/*.xcworkspace/**"
  - "**/Package.swift"
---

# Use ios-test-engineer to run and read tests

Running a suite, reading a result bundle, or judging a failure goes through
`ios-test-engineer`.

Do not run `xcodebuild test` and read the tail of stdout. The result bundle
carries the evidence; the console carries a summary that omits the part that
matters.

**Never report a run green without `test_results.py triage`.** With
`-retry-tests-on-failure`, a test that fails then passes makes the run report
`result: Passed`, `failedTests: 0` and an **empty `testFailures` array**. The
only surviving evidence is a failed repetition node inside the hierarchy. A
summary-only reader calls that clean.

Never retry a failure you have not classified. Retrying is legitimate only for a
correlated infrastructure failure — where the assertion never ran. Retrying a
real or flaky failure turns a true signal into a green build.

A non-zero `xcodebuild` exit does not mean a test failed. It also covers build
failure, signing failure, a runner that never launched, and a watchdog kill.
Only the bundle distinguishes them; no readable bundle means a run failure, not
a test verdict.

Report the repetition mode with every verdict. The same code returns SUCCEEDED
under `retry` and FAILED under `relaunch`.

Do not derive uncovered lines by subtracting covered from executable. On Swift
most of that difference is autoclosures and short-circuited operands on lines
that ran — including assertion messages, which are uncovered *because the test
passed*. Use `coverage_report.py gaps`.

<!-- installed by puppet-master · github.com/ksypinro/puppet-master · edit freely; ./uninstall.sh only removes files still carrying this line -->
