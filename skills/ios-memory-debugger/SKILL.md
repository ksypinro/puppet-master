---
name: ios-memory-debugger
description: Investigate native iOS app memory using heap snapshots, object layouts, retaining paths, allocation history, VM accounting, and repeatable lifecycle scenarios. Use for leaks, unexpected survivors, memory growth, large allocations, and analysis of supplied memgraphs. Route timeline, live code, and managed-runtime questions to their appropriate evidence sources; do not promise unrestricted access to every app or device.
compatibility: Requires macOS, full Xcode and Python 3.9+, plus permission to inspect the target process. Simulator and local macOS capture are qualified; physical-device capture is not and must go through XCTest performance diagnostics. Allocation history requires the target to have launched with full MallocStackLogging.
license: MIT
metadata:
  author: Kazi Samin Yeaser
  version: "1.3.0"
  repository: https://github.com/ksypinro/puppet-master
  short-description: Investigate native iOS app memory from heap snapshots
---

# iOS Memory Debugger

Answer a specific memory question with the strongest available evidence, identify what remains unknown, and choose the next discriminating query. This skill orchestrates Apple's own capture and readers; it is not a universal heap-access service.

Apple native capture and readers require compatible macOS/Xcode tools and target permissions. Other hosts can reason over validated exports. Device capture, recorded history and runtime metadata are capability dependent.

## Bundled scripts

Python 3.9+, standard library only. Resolve `SKILL_DIR` to this file's directory.

| Script | Role |
|---|---|
| `scripts/memory_capture.py` | `resolve` a process unambiguously, `probe` what it can give, `capture` with the right flags, `validate` the artifact |
| `scripts/memgraph_query.py` | `summary` `classes` `objects` `layout` `paths` `diff` **`retained`** **`biggest`** `graph` `zones` `history` |
| `scripts/memgraph_dominator.py` | dominator-tree, whole-graph and allocator analysis |
| `scripts/memgraph_util.py` | shared classification and `leaks` exit-status interpretation |
| `scripts/test_selftest.py` | offline self-test; no Xcode or graph needed |

Use them rather than raw commands where they cover the operation. Each exists because a hand-run command fails silently in a specific, measured way:

- **`--fullStackHistory` is fatal without *full* `MallocStackLogging`** — exit 255 and no artifact at all. `capture` probes the mode and omits the flag rather than losing the capture.
- **`heap -addresses` matches the whole class name**, so a prefix returns zero at exit 0. `objects` lists real class names before reporting an empty result.
- **`leaks` encodes the finding in its exit status for only some modes.** Every call is interpreted, never inferred from the exit code.
- **A truncated graph aborts every Apple reader with SIGABRT**, not a clean error. Artifacts are classified before a reader sees them.

## Retained size is available

`leaks --dominatorTree` is undocumented — it appears only inside another flag's
description, and in no man page — but it computes what every "how much would
freeing this release" question needs. Measured: 2.4 s over a 355,948-node real
iOS app, 0.5 s over a capture taken with **no** `MallocStackLogging`, so it needs
no instrumented relaunch.

```sh
python3 "$SKILL_DIR/scripts/memgraph_query.py" retained /abs/Run.memgraph 0x1030a19a0
python3 "$SKILL_DIR/scripts/memgraph_query.py" biggest  /abs/Run.memgraph
```

```
NSMutableArray  0x1030a19a0
referenced as: retainedCache
own size     : 48 bytes
DOMINATES    : 163,840 bytes across 4 allocations  (3,413x its own size)
```

`biggest` ranks by what each node retains rather than by class total, which is
the difference between "NSMutableDictionary is numerous" and "this dictionary is
holding 890 KB". Amplification — retained ÷ own size — finds the small object
sitting on a large backing store.

It remains a conservative scanner's view. Say **"N bytes dominated by this node
in this capture"**, never "freeing this frees N bytes".

## Choose the evidence

Before a first investigation on a target, read [capabilities](references/capabilities.md). Then load only the relevant references:

- Capture or query an Apple memory graph: [CLI workflows](references/cli-workflows.md).
- Record findings, compare snapshots, or consume tool output: [evidence contract](references/evidence-contract.md).
- Plan a concrete investigation: the matching scenario in [use cases](references/use-cases.md). Search by U01–U24 or symptom.
- Coordinate UI reproduction, LLDB, Instruments, tests, or another coding agent: [agent integration](references/agent-integration.md).

Reuse an existing artifact when it answers the question. Live capture is not necessary merely because the application is still running. A question about peak memory needs interval evidence; a question about why an object is alive needs reference evidence; a question about a past retaining write needs recorded events or a new debugger reproduction.

Fifteen of the eighteen questions this skill answers need **no** `MallocStackLogging` at all — including retained size. Only allocation provenance, the free/alloc event stream and high-water-mark composition require it, and enabling it costs a relaunch that destroys the state under investigation. Capture structurally first, always.

For "does memory grow while I repeat this action", `memory_capture.py watch` samples physical footprint at sub-second resolution with no trace file and no build change. Route allocation *churn* within an interval to `ios-instruments-profiler`; footprint drift over a scenario does not need it.

## Establish the investigation

1. State the question, expected lifetime or metric, relevant process/domain, checkpoint, and what observation would settle it. For example: do editor-model counts return to the warmed baseline after repeated open-close cycles in one launch?
2. Preserve the existing session. Bind target UDID/device, bundle, executable, PID plus launch identity, build UUIDs, source revision if known, driver/debugger owner, and artifact directory. If more than one process matches, resolve it before capture. App Intents, extensions and WebContent may run elsewhere.
3. Establish which operations the request allows: inspection, UI reproduction, capture pauses, instrumented relaunch, test reruns, source changes, and content disclosure. Diagnosis does not itself authorize a fix, restart, data reset, dependency installation, or diagnostic injection.
4. Discover installed tool versions/help, capture access, artifact readability, runtime metadata and effective stack history. Report each capability as qualified, available but untested, documented, unavailable, or unknown. Prior macOS fixture proof is not live Simulator/device qualification.
5. Use a new task-owned output path for every capture. Keep artifacts local by default. `--noContent` reduces descriptions, not all sensitive information. Obtain authorization before exposing raw artifacts or sensitive contents to an external service/model.

## Observe and capture

For UI-dependent investigations, use the available `ios-simulator-driver` or an authorized equivalent to establish and verify the checkpoint. It must supply fresh semantic/screenshot evidence, not just successful input dispatch.

- Use warmed baseline → action → cleanup condition → post-cleanup capture for retention. Repeat in the same process lifetime to investigate accumulation. Independent launches answer a different question.
- Record semantic cleanup conditions such as dismissal, task completion, or an app-specific lifecycle marker. A fixed delay is only a declared fallback, not proof of cleanup.
- Revalidate process identity immediately before capture. Stop UI dispatch during capture or debugger stops. Respect an existing intentional LLDB/Xcode stop; do not attach a competing debugger or resume someone else's stop.
- Use the target-specific route in CLI workflows. A physical-device PID is never a host PID. Missing allocation history cannot be repaired by a capture flag; preserve useful current evidence before requesting an instrumented reproduction.
- Save raw outputs, stderr, exit status, capture interval and final process disposition. Validate the artifact independently. A file already at the output path or a command returning zero does not establish a fresh, complete capture.

## Query from broad to narrow

1. Establish VM/footprint categories, heap class counts/bytes and scanner leak totals. Name the metric and unit; do not add overlapping accounting domains.
2. Rank unexplained changes or expected-lifetime violations. Select a small number of relevant allocations, using addresses from the selected snapshot only.
3. Inspect allocation size versus logical instance size, layouts, named fields, incoming/outgoing references, and multiple paths to roots where available. Preserve original labels and distinguish strong, weak, unowned, conservative and unknown edges.
4. Recover recorded allocation stacks when present. Match build/symbol UUIDs before assigning source lines. An allocation site is not the historical writer of the retaining field.
5. Test competing explanations: intended cache, pending task, autorelease delay, backing storage, allocator retention, unknown scanner coverage, or an unintended owning path. Zero scanner leaks does not rule out reachable abandoned memory.
6. When the missing fact belongs elsewhere, hand off: Instruments for interval peaks/churn, LLDB for the writer or invalid access, lifecycle instrumentation for semantic identities, managed-runtime tools for JS/Unity state. Preserve identity and checkpoint links.

Use bounded extracts for reasoning. When a custom parser is absent, report reviewed raw evidence conservatively rather than inventing structured success. Empty, malformed, permission-denied, truncated, and valid-zero inputs must remain distinguishable. Every limit/filter should remain visible in the answer.

## Explain and finish

Return a direct answer followed by: observed facts with artifact/query IDs; the supported explanation and alternatives; coverage/history/symbol/selection limits; and the smallest next experiment if necessary. Values not captured are unknown, not zero. Useful clean wording is “no scanner-detected leaks in this validated capture,” not “the app has no memory issues.”

Do not call a raw-pointer cycle a verified owning cycle. Do not compute exact retained bytes from `referenceTree` or a partial graph. Do not equate the same address with the same object across launches or ignore reuse within a launch. Explain which fact is inferred and what would validate it.

If fixing is authorized, make the smallest evidence-supported source change and repeat the same experiment with matched conditions. Compare object counts, leaked bytes, and footprint separately; preserve failed runs and individual values. Do not recommend replacing every strong reference with weak.

Release only owned capture resources, verify the intended final process state, and report any unresolved stop or failed cleanup. Preserve artifacts unless the user authorizes their removal.

Simulator capture and offline analysis are qualified against live processes on this toolchain. Physical-device capture is not: route it through the XCTest performance-diagnostics path in [CLI workflows](references/cli-workflows.md) and report it as unverified.

## Route by symptom

These six skills are one toolkit. Route on the symptom, not on the surface:

- Reaching a screen, dispatching taps, text, or gestures, or verifying a UI flow — `ios-simulator-driver`.
- A view is misplaced, clipped, overlapping, mis-styled, or untappable, or you need the native tree, geometry, or constraints — `ios-view-hierarchy-debugger`.
- A value, branch, or model state is wrong, or you need the code path that produced it — `lldb-code-state-debugger`.
- Launch time, CPU, hangs, jank, or an interval's allocation churn — `ios-instruments-profiler`.
- Running a suite, reading a result bundle, classifying a failure, or coverage — `ios-test-engineer`.
- Why an object is still alive, what is retaining it, or where the bytes went at a checkpoint — **this skill**.

Hand off when the evidence needed is not the evidence this skill produces. A memory graph answers reachability at one instant; `ios-instruments-profiler` answers what happened over an interval, and `lldb-code-state-debugger` answers which code wrote the retaining field. Preserve the established target — UDID or device, bundle ID, PID and launch identity, build UUIDs, run directory — across the handoff.
