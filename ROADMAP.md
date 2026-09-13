# Roadmap

Where this toolkit stands against a complete CLI-first iOS development system, what is missing, and the order in which the gaps are worth closing.

The baseline is the *iOS Developer Command-Line Tools — Deep Technical Analysis* research pass (2 September 2026, verified against Xcode 27.0 beta 27A5194q), attached to the [v1.0.0 release](https://github.com/ksypinro/puppet-master/releases/tag/v1.0.0). Its capability map is the yardstick used throughout this document. See [docs/RESEARCH.md](docs/RESEARCH.md).

This is a statement of direction, not a schedule. Nothing here has a date.

## Where the toolkit stands

Measured against the fifteen requirements in the report's capability map: **ten fully covered, one partial, four absent** as of v1.1.0, when `ios-test-engineer` closed the two test rows.

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
| Memory graph | ◐ | Allocations and Leaks only; no reference graph |
| Build for Simulator | ❌ | — |
| Build for physical iOS | ❌ | — |
| Install and launch on device | ❌ | — |
| Screenshot / video, device | ❌ | — |

One result runs the other way. The report concluded that the full render tree "remains Xcode View Debugger territory or requires a project-owned Debug introspection layer." `ios-view-hierarchy-debugger` ships a public-API UIKit capture driven through an LLDB probe, which is more than the research expected to be reachable headlessly.

## The shape of the gap

```
  PRODUCE          DEPLOY           EXERCISE         DIAGNOSE          MEASURE
  build / sign     Simulator ✅      UI driving ✅     view tree ✅       Instruments ✅
      ❌           device ❌         tests ✅          LLDB ✅
                                                     memory ◐
                                                     crash ❌
```

The original four skills owned **"why is this wrong"** completely and **"how do I produce and ship this"** not at all. `ios-test-engineer` now closes the test rows, but every skill still opens by assuming a built, installed application already exists — which held while they were driven by hand against apps already built in Xcode, and stops holding the moment an agent is expected to work end to end.

Closing that is the roadmap.

## Planned skills

Each candidate below is judged by the separation test in [ARCHITECTURE.md](ARCHITECTURE.md#why-one-repository-one-plugin): a skill earns its own directory by having a distinct failure taxonomy, a distinct authority boundary, and a distinct evidence artifact. Anything failing that test belongs in an existing skill's `references/` instead.

### 5. `ios-test-engineer` — **shipped in v1.1.0**

**Covers** report §5–6: `xcodebuild test`, `build-for-testing` / `test-without-building`, `.xctestproducts`, test plans, selection and sharding, `xcresulttool`, `xccov`, attachment export.

**Evidence**: `.xcresult` bundles — a versioned structured artifact with its own schema, activities, attachments, and coverage archives. Nothing else in the toolkit reads them except through the narrow performance-metric door.

**Failure taxonomy**: flaky versus real failure versus infrastructure failure. This distinction is the whole job, and getting it wrong is worse than not running the tests — the report is explicit that blind retrying hides flakiness, and that retries must be confined to identified infrastructure failures with the original failure preserved as evidence.

Built from a live empirical study rather than documentation: a purpose-built SwiftPM package and Xcode project, run under every repetition mode, with the resulting bundles kept as fixtures.

The study turned up the finding the skill is built around. Under `-retry-tests-on-failure`, a test that fails then passes makes the run report `result: Passed`, `failedTests: 0` and an **empty `testFailures` array** — the failure survives only as a `Repetition` node inside the hierarchy. Anything reading the summary reports green. `test_results.py triage` walks the hierarchy and surfaces these as **hidden flakes**.

Still unverified: physical-device test execution. The study machine had no device attached, so that lane is documented as unverified rather than implied to work.

### 6. `ios-build-engineer` — next

**Covers** report §1–2: toolchain pinning and `DEVELOPER_DIR`, scheme and destination discovery, JSON build settings, locating the product without guessing, `archive` and `exportArchive`, signing and provisioning diagnosis.

**Evidence**: build settings JSON, build logs, artifact manifests with binary and dSYM UUIDs, `codesign` and provisioning output.

**Failure taxonomy**: signing, provisioning, scheme and destination mismatch, first-launch state, package resolution. Shares no vocabulary with anything in v1.0.0 — a provisioning profile mismatch has nothing in common with a stale element reference.

**Authority**: the sharpest of the five. The report flags automatic signing mutation as a risk requiring pre-provisioned, scoped identities and explicit approval, because a careless build invocation can change Developer Portal state. This skill must read signing configuration freely and change it only on request.

Now first in line, and the precondition every other skill quietly assumes. It also unblocks serious matrix support: scheme and destination discovery is build-engineer territory, and `ios-test-engineer` currently carries a minimal version of it in `test_doctor.py`.

### 7. `ios-device-operator`

**Covers** report §3–4 for physical hardware: `devicectl` install, launch, process enumeration, diagnostics, and the Xcode 27 `device capture` screenshot and recording surface.

**Evidence**: `devicectl --json-output` files. The report is emphatic that stdout is for humans and is not a stable contract; the JSON file is the scripting interface.

**Failure taxonomy**: pairing, trust, Developer Mode, device lock, CoreDevice service failure, device contention.

**Authority**: physical hardware belongs to a person. Installing, launching, terminating, and capturing within a leased target is expected; erasing, re-pairing, or registering a device is not, and must never happen automatically.

Third because it upgrades the whole toolkit rather than only adding to it: `ios-simulator-driver` is Simulator-only by design, and the other three degrade to Simulator today. This skill is what makes device-fidelity claims — the ones `ios-instruments-profiler` already refuses to make from Simulator data — actually reachable.

### 8. `ios-memory-debugger` — **shipped in v1.2.0**

**Covers** report §10: `.memgraph` capture and reopening, `vmmap`, `heap`, `leaks`, `malloc_history`, `MallocStackLogging`, and the documented escalation to Xcode's GUI Memory Graph on physical devices.

**Evidence**: the live object reference graph.

**Rationale, and the argument against**: the report separates three memory questions — current footprint, allocation behaviour over time, and the reference graph — and states that no single artifact answers all three. `ios-instruments-profiler` already owns the middle one. Only the reference graph is genuinely unserved, and it needs Darwin host-process tools on Simulator plus a GUI escalation on device, which is a different toolchain from `xctrace`.

That is a real separation, but a narrow one. **Folding this into `ios-instruments-profiler` as a third mode is a defensible call** and gets the system to eight skills. It is listed separately because the authority boundary differs: a `.memgraph` can contain heap-resident credentials, tokens, and customer data, and needs encryption, access control, and expiry that trace handling does not.

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

Two items from [ARCHITECTURE.md § Known gaps](ARCHITECTURE.md#known-gaps) are tolerable at four skills and blocking at nine. Neither is optional once skill 5 exists.

### Durable session state

Target binding currently lives in conversation context. Every `SKILL.md` instructs the agent to preserve the UDID or device, bundle ID, PID, build identity, driver session, and run directory across steps — and that instruction is the first thing lost to context compaction.

A build → install → test → diagnose chain carries far more state than the current four ever did: build artifact path, binary and dSYM UUIDs, `.xctestproducts` path, test selection, `.xcresult` path, device lease, source revision. Threading that through prose across nine skills will not survive a long session.

The fix is a `session.json` written into the run directory by whichever skill establishes each fact and read by the rest, matching Layer 5 of the report's recommended architecture. It is roughly a hundred lines, and it is what decides whether nine skills compose or merely coexist.

### Routing that survives its own growth

The `## Route by symptom` block added in v1.0.0 is four rows maintained by hand in four files. Nine rows in nine files will drift within a month.

Two workable answers: generate the blocks from one source of truth, or replace the per-skill table with a lifecycle tier map — produce, deploy, exercise, diagnose, measure — which stays five entries long no matter how many skills exist. The second is preferable; it reads better and it is what a person would reach for anyway.

### Shared substrate

Target binding, run-directory conventions, capability probing, and redaction rules are restated as prose in every `SKILL.md`. At four skills that is duplication. At nine it is drift with a guaranteed arrival date. Extract to plugin-level helpers reachable through `${CLAUDE_PLUGIN_ROOT}` once there is a second consumer of each rule.

### Verification

`tools/validate_skills.py` enforces the specification and CI exercises a real install on macOS, but no fixture app exercises the skills end to end. A build → install → drive → test → diagnose chain across one fixture would catch composition breakage that per-skill validation cannot see — and that chain only becomes expressible once skills 5 through 7 exist.

## Summary

| | Skills | Result |
|---|---|---|
| v1.0.0 | 4 | Diagnosis complete; production and shipping absent |
| **v1.1.0** | **5** | **Test execution and result analysis closed** |
| Next | 7 | Closes every row of the report's capability map |
| Full | 9 | Complete development lifecycle, including memory graphs and crash triage |

Remaining order: `ios-build-engineer`, then `ios-device-operator`. Memory and crash after, if at all.

## Contributing to the roadmap

Building one of these is welcome — read [CONTRIBUTING.md](CONTRIBUTING.md) first, particularly the evidence discipline, which is the part most likely to send a pull request back.

Proposing a skill that is not listed here is also welcome. The bar is the separation test: name the distinct evidence artifact, the distinct failure taxonomy, and the distinct authority boundary. If a proposal shares all three with an existing skill, it is a `references/` file in that skill, and that is a good outcome rather than a rejection.
