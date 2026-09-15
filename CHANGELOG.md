# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

For skills, versioning is interpreted as:

- **MAJOR** — a skill is removed or renamed, or its evidence contract changes incompatibly.
- **MINOR** — a skill is added, or a capability, script, or reference is added.
- **PATCH** — corrections, clarifications, or fixes that do not change the contract.

## [Unreleased]

### Added
- **Cline routing rules (`clinerules/`).** Eight standing rules that tell Cline
  which skill answers which symptom, and which raw command not to reach for
  instead. They exist because skill selection depends on the user's phrasing
  matching a skill `description`: asked why a button is untappable, an agent
  with a debugger attached reaches for `po someView`, which returns a one-line
  description and cannot answer the question. A rule sits in context before that
  choice is made.

  Each file carries a `paths:` glob — the only frontmatter key Cline supports —
  restricting it to iOS sources, so a project with no Swift, Objective-C or
  Xcode files never loads them. `install.sh` copies them to
  `~/Documents/Cline/Rules/`, or to a project's `.clinerules/` under
  `--project`; `--agent` naming anything but `cline` skips them. `uninstall.sh`
  removes only files still carrying the provenance marker, so a rule someone has
  rewritten is reported and left alone. Covered end to end by a new CI step.

- **`ios-build-engineer` — the produce-and-run skill.** Closes the build rows the
  roadmap has carried since v1.0.0: toolchain and lane readiness, scheme and
  destination discovery, resolved build settings and product paths, builds for
  Simulator and device, structured build diagnostics, archive and export,
  code-signing diagnosis, XCFramework packaging, artifact manifests, and the
  composite `run` action `xcodebuild` does not ship.

  Two findings from the research pass shape it. **SwiftPM cannot cross-compile to
  iOS**: `swift build --triple arm64-apple-ios17.0` is accepted, exits 0, prints
  `Build complete!` and emits macOS objects, so `package_products.py
  verify-platform` reads the Mach-O load command rather than trusting the exit
  status. And **launching is not running**: `simctl launch` and `devicectl
  process launch` both exit 0 and print a process id for an app that already
  crashed, so no run reports success without a `launchctl` liveness probe.

  Physical-device install and launch are implemented and explicitly marked
  unverified — the study machine had no hardware and no provisioning profiles.

### Changed
- **`ios-test-engineer` evidence claims tightened.** `compare` no longer
  describes itself as a complete PR gate — it is one input to one, reports
  `gateReady`, and returns `inconclusive` when either bundle is `Incomplete`.
  `matrix` cells carry an `effectiveResult`, so a run reporting `Passed` while
  carrying failed repetitions becomes `PassedWithHiddenFailures` and counts as a
  failing cell; previously it counted as green, reproducing inside `matrix` the
  hole `triage` exists to close. Cell labels gained the OS build and device id.
- Coverage `deadLines` renamed `uncoveredLines`, with the old key kept as an
  alias: the evidence is a zero hit count during one run, not proof that source
  is dead. `changed` no longer presents itself as changed-line coverage.
- Triage now requires a *correlated* infrastructure failure before a retry is
  justified, and reads the repetition mode from the run manifest rather than the
  bundle.
- README now documents all seven skills. It described five, omitting
  `ios-memory-debugger` (shipped in v1.2.0) alongside the new build skill.

### Added
- **`ios-memory-debugger` retained-size analysis.** A capability survey of the
  Darwin memory toolchain found `leaks --dominatorTree` — undocumented, named
  only inside another flag's description and absent from every man page — which
  computes the total size of each node *and everything it dominates*. That is
  retained size, the quantity both research reports declare unavailable.
  Measured at 2.4 s over a 355,948-node real iOS app, and 0.5 s over a capture
  taken with **no** `MallocStackLogging`, so it needs no instrumented relaunch.

  Six new commands: `retained` and `biggest` (dominator tree), `graph` (bulk
  edge extraction — 967,750 edges in 10.5 s versus 3.7 hours for the
  per-address walk the reports propose), `zones` (allocator capacity versus
  live payload), `history` (four `malloc_history` modes including
  high-water-mark composition), and `watch` (footprint time series via
  `footprint --sample`, no trace file or build change).

### Added
- **`ios-memory-debugger`** — investigate native iOS memory from heap snapshots:
  object layouts, retaining paths, allocation history, VM accounting. Ships
  `memory_capture.py` (resolve · probe · capture · validate) and
  `memgraph_query.py` (summary · classes · objects · layout · paths · diff) over
  Apple's own capture and readers.

  Adversarial testing of the v0.1.0 draft found the documented capture command
  could not run: `--fullStackHistory` is **fatal** without *full*
  `MallocStackLogging`, producing exit 255 and no artifact, while the same file
  recommended launching with `lite` — which `leaks` rejects by name. `capture`
  now probes the target's logging mode and omits the flag rather than losing the
  capture.

  Four further silent failures are now guarded: `heap -addresses` matches the
  **whole** class name, so a prefix returns zero at exit 0 (`objects` lists real
  class names before reporting empty); a truncated graph **aborts every Apple
  reader with SIGABRT** rather than erroring; `leaks` encodes the finding in its
  exit status for only three of six modes; and empty versus malformed input is
  indistinguishable from reader output alone, so artifacts are stat-classified
  before a reader sees them.

  Simulator capture is now qualified — the source research listed it as
  unverified. Physical-device capture remains unverified and is documented as
  such.

### Added
- **`ios-test-engineer`** — run XCTest, Swift Testing and XCUITest suites and turn
  the result bundle into trustworthy evidence. Discovers schemes (flagging any
  that are not shared), test plans and per-scheme destinations; runs with a
  watchdog and a reproducibility manifest; classifies every failure as
  deterministic, flaky, infrastructure or unclassified; **detects hidden flakes**
  — tests a run reports as passed that failed a repetition and never appear in
  `testFailures`; and reports region-aware coverage that separates dead code from
  sub-expressions which never evaluated.
- `compare_runs.py` — `compare` a candidate against a baseline (introduced
  versus resolved across test failures, build warnings and analyzer issues,
  plus tests that disappeared), `merge` bundles, and `matrix` attribution that
  distinguishes independent failures from one bug with platform reach from one
  unhealthy destination.
- `test_results.py diagnostics` — exports and reads `testmanagerd.log` and
  `scheduling.log`, so an `infrastructure` verdict rests on evidence rather than
  on the failure text alone. Confidence drops to `medium` when the text looks
  like a runner failure but the diagnostics do not corroborate it.
- `test_results.py build-results` and `attachments`.

### Changed
- `xctest_selection.py` moved from `ios-instruments-profiler` to
  `ios-test-engineer`. Proving that an `-only-testing` or `--filter` selection
  matches real tests is a test concern; the profiler only needed it because a
  wrong filter wastes a *measured* run. Its tests moved with it, and the
  profiler now resolves the script through `ios-test-engineer` with a documented
  fallback for a standalone install.
- `test_results.py` self-test (`test_selftest.py`), which enforces that the
  diagnostic signal patterns produce **zero** matches on passing runs. A healthy
  `testmanagerd.log` contains `(result:error)`, `TESTMANAGERD_SIM_SOCK` and
  `Requesting crash report collection` — loose patterns flag all three and would
  justify retrying real regressions.

### Planned
See [ROADMAP.md](ROADMAP.md) for the full plan and its rationale.

- `ios-build-engineer` and `ios-device-operator` — the two remaining skills that
  close the research baseline's capability map.
- `session.json` handoff file so target binding survives context compaction.
- Shared substrate extracted from duplicated prose across the `SKILL.md` files.
- End-to-end fixture app exercising the full build → install → drive → test → diagnose chain.

## [1.0.0] — 2026-09-12

First public release.

### Added
- **`ios-simulator-driver`** — closed observe-act-verify loop over an explicitly selected Simulator: accessibility snapshots, screenshots, taps, text entry, swipes, gestures, driver selection across AXe/idb/XcodeBuildMCP/Appium/XCUIAutomation, and recovery from stale or ambiguous state.
- **`ios-view-hierarchy-debugger`** — native UIKit tree capture with geometry, constraints, layer state, and accessibility correlation; documented limits for SwiftUI and uninstrumented apps; offline evidence analysis via `ui_evidence.py`.
- **`lldb-code-state-debugger`** — persistent LLDB session with a JSON protocol: verified breakpoints, stop tokens, stack and variable inspection, watchpoints, and bounded expression evaluation behind explicit authorization.
- **`ios-instruments-profiler`** — bounded `xctrace` recording with watchdogs and schema gates, TOC-checked export, typed reducers, XCTest metric statistics, and baseline-versus-candidate comparison.
- **Multi-runtime distribution** — Agent Skills spec conformance, Claude Code plugin and marketplace manifests, Codex plugin manifest and `agents/openai.yaml` adapters, and documented discovery paths for Cline, Cursor, Copilot/VS Code, Gemini CLI, OpenCode, and Goose.
- **`install.sh` / `uninstall.sh`** — agent detection, dependency preflight, symlink or copy install, project or user scope. Uninstall removes only installations originating from this repository.
- **`tools/doctor.py`** — capability probe reporting which skills can run and what is missing, with a machine-readable manifest (`--json`).
- **`tools/validate_skills.py`** — Agent Skills spec validator enforced in CI.
- **`/ios-doctor`** — Claude Code command wrapping the capability probe.

[Unreleased]: https://github.com/ksypinro/puppet-master/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/ksypinro/puppet-master/releases/tag/v1.0.0
