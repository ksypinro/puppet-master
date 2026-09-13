# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

For skills, versioning is interpreted as:

- **MAJOR** — a skill is removed or renamed, or its evidence contract changes incompatibly.
- **MINOR** — a skill is added, or a capability, script, or reference is added.
- **PATCH** — corrections, clarifications, or fixes that do not change the contract.

## [Unreleased]

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
