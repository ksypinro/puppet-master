# Roadmap

Where this toolkit stands against a complete CLI-first iOS development system, what is missing, and the order in which the gaps are worth closing.

The baseline is the *iOS Developer Command-Line Tools — Deep Technical Analysis* research pass (2 September 2026, verified against Xcode 27.0 beta 27A5194q), attached to the [v1.0.0 release](https://github.com/ksypinro/puppet-master/releases/tag/v1.0.0). Its capability map is the yardstick used throughout this document. See [docs/RESEARCH.md](docs/RESEARCH.md).

This is a statement of direction, not a schedule. Nothing here has a date.

## Where the toolkit stands

Measured against the fifteen requirements in the report's capability map: **thirteen fully covered, one partial, one absent** as of v1.4.0. `ios-test-engineer` closed the two test rows in v1.1.0; `ios-memory-debugger` closed the memory row in v1.2.0–1.3.0; `ios-build-engineer` closed both build rows in v1.4.0 and reaches device install/launch behind an unverified marker.

| Requirement | Status | Skill |
|---|---|---|
| Install and launch on Simulator | ✅ | `ios-simulator-driver` |
| Screenshot / video, Simulator | ✅ | `ios-simulator-driver` |
| Tap / type / swipe / button | ✅ | `ios-simulator-driver` |
| Accessibility hierarchy | ✅ | `ios-simulator-driver` |
| Full view hierarchy | ✅ | `ios-view-hierarchy-debugger` |
| Call stacks and variables | ✅ | `lldb-code-state-debugger` |
| Instruments recording | ✅ | `ios-instruments-profiler` |
| Instruments analysis | ✅ | `ios-instruments-profiler` |
| Unit and UI tests | ✅ | `ios-test-engineer` |
| Structured test analysis | ✅ | `ios-test-engineer` |
| Memory graph | ✅ | `ios-memory-debugger` — reference graph, dominator tree, retained size |
| Build for Simulator | ✅ | `ios-build-engineer` |
| Build for physical iOS | ✅ | `ios-build-engineer` — compiles with no credentials |
| Install and launch on device | ⚠️ | `ios-build-engineer` — implemented, **unverified** without hardware |
| Screenshot / video, device | ❌ | — |

One result runs the other way. The report concluded that the full render tree "remains Xcode View Debugger territory or requires a project-owned Debug introspection layer." `ios-view-hierarchy-debugger` ships a public-API UIKit capture driven through an LLDB probe, which is more than the research expected to be reachable headlessly.

## The shape of the gap

```
  PRODUCE          DEPLOY           EXERCISE         DIAGNOSE          MEASURE
  build / sign ✅   Simulator ✅      UI driving ✅     view tree ✅       Instruments ✅
  package ✅        device ⚠️         tests ✅          LLDB ✅
  run + verify ✅                                     memory ✅
                                                     crash ❌
```

The original four skills owned **"why is this wrong"** completely and **"how do I produce and ship this"** not at all. `ios-test-engineer` and `ios-memory-debugger` closed the test and memory rows; `ios-build-engineer` has now closed the produce-and-run gap, so the toolkit no longer opens by assuming a built, installed application already exists.

What remains is physical hardware: device install and launch are implemented but unverified, device capture is absent, and crash triage still needs its own research pass.

## Planned skills

Each candidate below is judged by the separation test in [ARCHITECTURE.md](ARCHITECTURE.md#why-one-repository-one-plugin): a skill earns its own directory by having a distinct failure taxonomy, a distinct authority boundary, and a distinct evidence artifact. Anything failing that test belongs in an existing skill's `references/` instead.

### 5. `ios-test-engineer` — **shipped in v1.1.0**

**Covers** report §5–6: `xcodebuild test`, `build-for-testing` / `test-without-building`, `.xctestproducts`, test plans, selection and sharding, `xcresulttool`, `xccov`, attachment export.

**Evidence**: `.xcresult` bundles — a versioned structured artifact with its own schema, activities, attachments, and coverage archives. Nothing else in the toolkit reads them except through the narrow performance-metric door.

**Failure taxonomy**: flaky versus real failure versus infrastructure failure. This distinction is the whole job, and getting it wrong is worse than not running the tests — the report is explicit that blind retrying hides flakiness, and that retries must be confined to identified infrastructure failures with the original failure preserved as evidence.

Built from a live empirical study rather than documentation: a purpose-built SwiftPM package and Xcode project, run under every repetition mode, with the resulting bundles kept as fixtures.

The study turned up the finding the skill is built around. Under `-retry-tests-on-failure`, a test that fails then passes makes the run report `result: Passed`, `failedTests: 0` and an **empty `testFailures` array** — the failure survives only as a `Repetition` node inside the hierarchy. Anything reading the summary reports green. `test_results.py triage` walks the hierarchy and surfaces these as **hidden flakes**.

Still unverified: physical-device test execution. The study machine had no device attached, so that lane is documented as unverified rather than implied to work.

### 6. `ios-build-engineer` — **shipped in v1.4.0**

**Covers** report §1–2: toolchain pinning and `DEVELOPER_DIR`, scheme and destination discovery, JSON build settings, locating the product without guessing, `archive` and `exportArchive`, signing and provisioning diagnosis.

**Evidence**: build settings JSON, build logs, artifact manifests with binary and dSYM UUIDs, `codesign` and provisioning output.

**Failure taxonomy**: signing, provisioning, scheme and destination mismatch, first-launch state, package resolution. Shares no vocabulary with anything in v1.0.0 — a provisioning profile mismatch has nothing in common with a stale element reference.

**Authority**: the sharpest of the five. The report flags automatic signing mutation as a risk requiring pre-provisioned, scoped identities and explicit approval, because a careless build invocation can change Developer Portal state. This skill must read signing configuration freely and change it only on request.

The precondition every other skill quietly assumes, and now shipped.

Built from a live study rather than documentation: a hand-authored `.xcodeproj` and SwiftPM package driven through the whole lifecycle, plus a read of twenty-one open-source build and device tools.

Two findings shaped the skill. **`swift build --triple arm64-apple-ios17.0` exits 0, prints `Build complete!` and emits macOS objects** — SwiftPM cannot cross-compile to iOS, and nothing in the exit status says so, which is why `package_products.py verify-platform` exists. And **both `simctl launch` and `devicectl process launch` exit 0 and print a process id for an app that already crashed**, which is why no run reports success without a `launchctl` liveness probe.

The device lane is implemented and marked unverified: the study machine had no hardware and zero provisioning profiles. Device capture stays with `ios-device-operator`.

### 7. `ios-device-operator`

**Covers** report §3–4 for physical hardware: `devicectl` install, launch, process enumeration, diagnostics, and the Xcode 27 `device capture` screenshot and recording surface.

**Evidence**: `devicectl --json-output` files. The report is emphatic that stdout is for humans and is not a stable contract; the JSON file is the scripting interface.

**Failure taxonomy**: pairing, trust, Developer Mode, device lock, CoreDevice service failure, device contention.

**Authority**: physical hardware belongs to a person. Installing, launching, terminating, and capturing within a leased target is expected; erasing, re-pairing, or registering a device is not, and must never happen automatically.

Third because it upgrades the whole toolkit rather than only adding to it: `ios-simulator-driver` is Simulator-only by design, and the other three degrade to Simulator today. This skill is what makes device-fidelity claims — the ones `ios-instruments-profiler` already refuses to make from Simulator data — actually reachable.

### 8. `ios-memory-debugger` — **shipped in v1.2.0, extended in v1.3.0**

**Covers** report §10 and more than it anticipated: `.memgraph` capture and reopening, `vmmap`, `heap`, `leaks`, `malloc_history`, `footprint`, stack-logging modes, and the documented escalation to Xcode's GUI Memory Graph on physical devices.

**Evidence**: the live object reference graph, and — via `leaks --dominatorTree` — retained size.

**What the research got wrong.** Both memory reports state that exact retained size requires a complete graph that cannot be built, and that whole-graph extraction is future backend work. Neither survived testing. `leaks --dominatorTree` is undocumented — named only inside the description of `--groupByType`, absent from every man page — and computes the total size of each node and everything it dominates. Measured at 2.4 s over a 355,948-node real iOS app, and 0.5 s over a capture taken with **no** `MallocStackLogging`, so it needs no instrumented relaunch. Bulk edge extraction yields 967,750 edges in 10.5 s against the 3.7 hours the reports' per-address approach would take.

**Authority**: a `.memgraph` can contain heap-resident credentials, tokens and customer data, and `--noContent` is minimisation rather than anonymisation — the readers still expose field names, offsets, allocation stacks with symbols and process identity. It needs access control and expiry that trace handling does not.

**Still unverified**: physical-device live capture. No `devicectl` subcommand exports a graph; the only CLI route is XCTest performance diagnostics, which needs a repeatable test rather than an arbitrary checkpoint.

### 9. `ios-crash-triage` — optional, needs research first

**Covers**: `.ips` crash report symbolication, `sysdiagnose`, MetricKit payloads, and the sanitizer configurations the report mentions in passing.

**Evidence**: symbolicated crash reports matched to a binary and dSYM UUID.

**Failure taxonomy**: post-mortem. No live process, no reproduction, and frequently no matching build still on disk — which makes it genuinely different from `lldb-code-state-debugger`, whose entire method depends on stopping a running target.

**This one is not ready to build.** The baseline report covers crash triage least, touching it only across §10 and §14. It needs its own research pass before it becomes a skill, on the same standard as the other five: what the tooling actually exposes, and where the documented and actual capability diverge.

## Not planned

Stated so the boundaries are explicit rather than implied:

- **A skill router or dispatcher.** The reasoning is in [ARCHITECTURE.md](ARCHITECTURE.md#why-there-is-no-skill-router) and does not change at nine skills: routing already happens at zero tool-call cost from descriptions the agent has loaded, and nine descriptions cost roughly 900 tokens. Adding build, test, and device support arguably *reduces* the disambiguation risk, because "signing failed", "tests are flaky", and "install on my iPhone" collide with nothing already present.
- **More than nine skills.** Past nine, further additions subdivide existing skills rather than adding capability, and each marginal skill starts competing for triggers with one already there.
- **A replacement for Xcode's build system.** The report's decision table is unambiguous: reimplementing `xcodebuild` semantics is the wrong foundation. `ios-build-engineer` orchestrates `xcodebuild`; it does not model it.
- **Private-framework or reverse-engineered transports as a primary path.** `pymobiledevice3`, `go-ios`, and idb's private `CoreSimulator` use stay behind replaceable adapters, selected only when the supported CoreDevice path cannot do the job. The supported path must always remain sufficient on its own.
- **Claims the research did not support.** No hidden first-party UI-input API, no stable headless View Debugger export contract, no headless physical Memory Graph capture, no universal `xctrace` analytics schema. If Apple ships any of these, that is a research pass, not an assumption.

## Architectural work that has to land alongside

Two items from [ARCHITECTURE.md § Known gaps](ARCHITECTURE.md#known-gaps) were tolerable at four skills and blocking at nine. At six they are overdue, not hypothetical.

### Durable session state

Target binding currently lives in conversation context. Every `SKILL.md` instructs the agent to preserve the UDID or device, bundle ID, PID, build identity, driver session, and run directory across steps — and that instruction is the first thing lost to context compaction.

A build → install → test → diagnose chain carries far more state than the original four ever did: build artifact path, binary and dSYM UUIDs, `.xctestproducts` path, test selection, `.xcresult` path, device lease, source revision. Threading that through prose across nine skills will not survive a long session.

The fix is a `session.json` written into the run directory by whichever skill establishes each fact and read by the rest, matching Layer 5 of the report's recommended architecture. It is roughly a hundred lines, and it is what decides whether nine skills compose or merely coexist.

### Routing that survives its own growth

The `## Route by symptom` block added in v1.0.0 is now six rows maintained by hand in six files, and has already been edited by script twice to stay consistent. Nine rows in nine files will drift within a month.

Two workable answers: generate the blocks from one source of truth, or replace the per-skill table with a lifecycle tier map — produce, deploy, exercise, diagnose, measure — which stays five entries long no matter how many skills exist. The second is preferable; it reads better and it is what a person would reach for anyway.

### Shared substrate

Target binding, run-directory conventions, capability probing, and redaction rules are restated as prose in every `SKILL.md`. At four skills that was duplication. At six it is drift with a guaranteed arrival date.

The *code* half of this is done. `ios-memory-debugger` keeps its shared behaviour in `memgraph_util.py`, and `ios-test-engineer` now does the same in `xcresult_util.py` — three copies of bundle validation and five separate `ToolError` classes collapsed to one each, with a self-test that fails if a copy creeps back. What remains is the *prose* half: the same invariants restated in six `SKILL.md` files, which no import can deduplicate and which a shared `references/` file would have to serve without breaking standalone skill installs. Extract to plugin-level helpers reachable through `${CLAUDE_PLUGIN_ROOT}` once there is a second consumer of each rule.

### Verification

`tools/validate_skills.py` enforces the specification and CI exercises a real install on macOS, but no fixture app exercises the skills end to end. A build → install → drive → test → diagnose chain across one fixture would catch composition breakage that per-skill validation cannot see — and that chain only becomes expressible once skills 5 through 7 exist.

## Summary

| | Skills | Result |
|---|---|---|
| v1.0.0 | 4 | Diagnosis complete; production and shipping absent |
| v1.1.0 | 5 | Test execution and result analysis closed |
| **v1.3.0** | **6** | **Memory closed, including retained size** |
| Next | 8 | Closes every row of the report's capability map |
| Full | 9 | Complete development lifecycle, including crash triage |

Remaining order: `ios-build-engineer`, then `ios-device-operator`. Crash triage after, if at all — and it needs its own research pass first.

`ios-build-engineer` is the one that matters most. All six shipped skills still open by assuming a built, installed application exists.

## Contributing to the roadmap

Building one of these is welcome — read [CONTRIBUTING.md](CONTRIBUTING.md) first, particularly the evidence discipline, which is the part most likely to send a pull request back.

Proposing a skill that is not listed here is also welcome. The bar is the separation test: name the distinct evidence artifact, the distinct failure taxonomy, and the distinct authority boundary. If a proposal shares all three with an existing skill, it is a `references/` file in that skill, and that is a good outcome rather than a rejection.
