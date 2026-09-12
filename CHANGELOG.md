# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

For skills, versioning is interpreted as:

- **MAJOR** — a skill is removed or renamed, or its evidence contract changes incompatibly.
- **MINOR** — a skill is added, or a capability, script, or reference is added.
- **PATCH** — corrections, clarifications, or fixes that do not change the contract.

## [Unreleased]

### Planned
See [ROADMAP.md](ROADMAP.md) for the full plan and its rationale.

- `ios-test-engineer`, `ios-build-engineer`, and `ios-device-operator` — the three skills that close the remaining rows of the research baseline's capability map.
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
