---
name: lldb-code-state-debugger
description: Debug live native application code state with LLDB. Use to reproduce an issue, set source or symbolic breakpoints, inspect stopped variables and stacks, step, evaluate p/po expressions, find memory writers, and build evidence-backed root-cause explanations. Integrates with an authorized iOS Simulator driver and view-hierarchy debugger. Requires a debuggable target and compatible symbols/toolchain; does not bypass app protections or promise every runtime's state.
license: MIT
metadata:
  author: Kazi Samin Yeaser
  version: "1.4.0"
  repository: https://github.com/ksypinro/puppet-master
  short-description: Debug live native application code state with LLDB
---

# LLDB code-state debugger

Use this skill to connect an observed symptom to the first incorrect code-state transition. A suspicious stack alone is not a root cause. This folder is portable: any agent that can read files and run local commands can follow it. Read [agent integration](references/agent-integration.md) when adapting to another agent or transport.

Read [research lineage and qualification](references/research-and-capabilities.md) before promising a particular capability. The core has live fixture and Sparrow evidence; the full Simulator tap-to-breakpoint chain and physical-device workflows are not yet qualified. For maintenance, run `python3 scripts/test_protocol.py`; opt-in live C validation is `python3 scripts/validate_native.py --fixture-dir /absolute/built-fixtures --output-dir /absolute/new-evidence --allow-fixture-execution` after reading the fixture contract.

## Safety and scope

- Establish authority for the exact app and experiment. Diagnosis permits relevant attachment/stops and inspection, not source edits, deleting data, sending real transactions, memory writes, or killing an existing app. Use source-owned fixtures for mutation experiments.
- One controller and one debugger own a process. Do not compete with Xcode, another LLDB, or another agent. If Xcode owns it, use its existing console/permissioned bridge instead. The helper's PID lock is only advisory among its workers.
- Bind UDID/device, bundle, executable, current PID, architecture, binary/dSYM UUID and source revision. A PID or process name alone is insufficient. Re-resolve on relaunch. Simulator processes use host attachment; physical-device PIDs do not.
- Every inspection belongs to a stop token and actual thread/frame. Never reuse values, frame indices, pointer addresses or child handles after resume, step, evaluation, external command or exit. Refresh status and select the frame again.
- Raw stored-variable reads first. `p`, `po`, conditions, descriptions, formatters and expressions can execute code. Evaluation can mutate state; unwind is not rollback. Opt-in flags document authority, not enforce a security sandbox.
- Do not interpret unavailable/optimized-out/import-failed values as `nil`, zero or app defects. Keep errors and truncation in evidence.
- Breakpoints perturb timing. Use a separate Instruments run for performance. Memory bytes are not an ownership graph; logical SwiftUI state and Xcode View Debugger parity are not guaranteed.

## 1. Discover and bind

Resolve `SKILL_ROOT` to this folder. Use Python 3 and the selected Xcode's Apple LLDB for Swift/iOS. The client uses only the Python standard library; the worker runs inside LLDB's matching embedded Python, avoiding system-Python binding mismatches.

```sh
python3 "$SKILL_ROOT/scripts/debugger.py" doctor
python3 "$SKILL_ROOT/scripts/debugger.py" start /absolute/task-artifacts/new-session
python3 "$SKILL_ROOT/scripts/debugger.py" status /absolute/task-artifacts/new-session
```

`start` requires a new session directory, creates private connection metadata, and leaves a persistent local worker. Read [the protocol](references/protocol.md) completely before its first target operation. Run `call SESSION '{"op":"capabilities"}'`; implemented operations are not automatically qualified on every target. Help discovery is not a live test.

For a host executable, create a target, add verified breakpoints, then launch. For an existing Simulator app, use `simctl` to resolve the installed bundle path and verify the PID's executable against that exact Simulator installation; then attach by executable and current host PID. Do not launch an iOS binary as a macOS program. Prefer an already-running app; startup experiments require a deliberate start-stopped launch and matching symbols.

If attachment or runtime support is denied, retain the exact error and stop that route. Do not change signing, trust, security settings or restart the app by assumption. See [advanced debugging](references/advanced-debugging.md) for devices, symbol repair, Swift runtime diagnostics and Xcode-owned alternatives.

## 2. Form a discriminating experiment

1. Record symptom, expected result, reproduction steps and competing hypotheses.
2. Locate the smallest relevant action/model/render boundary in the current source.
3. Set a source, symbol or regex breakpoint. Record requested and actual resolved locations, module UUID and condition. Zero locations means pending, not success; loaded modules may resolve it later.
4. Prefer cheap conditions over noisy global stops. Use a setter breakpoint or verified storage watchpoint to find a writer. Do not invent a storage address for a computed property.
5. Describe what observation would confirm or refute each hypothesis before running the experiment.

## 3. Reproduce → stop → inspect

For UI reproduction, load the available `ios-simulator-driver` skill and its selected-provider instructions. This skill supplies no HID or accessibility engine itself.

1. Observe current UI while running, verify a selector, and record screenshot/AX evidence and time.
2. Arm the relevant breakpoint. Resume using the current token and confirm the process is running.
3. Dispatch **one** UI action. Concurrently or immediately afterward, use the debugger's bounded `wait` for the expected breakpoint. Action dispatch is not UI completion.
4. If stopped, do not wait for main-thread UI idleness, retap, or issue dependent input. Inspect the actual stop reason and thread. Unexpected stops require analysis, not blind continue.
5. Save `stack`, targeted `variables`/`children`, and necessary memory/register evidence. Read the caller if the top frame is runtime glue. Inspect arguments, stored state and the decision immediately before the mutation.
6. If raw values cannot answer the question, explicitly authorize one bounded `evaluate` or expert `raw` command. Reacquire the stop token even when evaluation fails. Preserve pre-evaluation evidence separately.
7. Step or resume only as the experiment requires. Once running, observe the next UI state. A screen captured while paused before `render()` is not proof of a rendering bug.

Use the view-hierarchy skill when native geometry, constraints or styling are relevant. Reuse this LLDB owner through the expert command route for reviewed capture helpers; do not attach another debugger. Such probes execute target code and require their own cleanup. AX nodes are not native views, and pointers are only meaningful for the capture's process/epoch.

## 4. Explain and verify the cause

Build a short chain: user action → matched breakpoint → input/stored state → incorrect branch/write → downstream UI result. Name observed values separately from inference. Compare a repeat or a controlled alternative that distinguishes the remaining hypotheses. Do not edit app source unless fixing was requested. If an authorized fix is made, repeat the original scenario and relevant tests; do not call an expression-based patch a persistent fix.

For exceptions, Swift tasks, logpoints, disassembly, core files and source mapping, read [advanced debugging](references/advanced-debugging.md). Those recipes are capability-dependent expert operations, not all live-certified features.

## 5. Cleanup and handoff

Remove only owned probes. For an existing app, normally `detach` with `keep_stopped:false` and verify its PID still exists; for a disposable owned fixture, explicit `terminate` is allowed. Then `shutdown`. Client disconnect/timeout is not cleanup. If a native expression or raw command wedges, the single worker cannot service `pause` while that call is blocked: do not claim cancellation or kill an attached app to clear a timeout. Report state unknown and seek a deliberate recovery decision.

Save a task-owned evidence report containing: target/build identity; action and stop timeline; source/module/line; raw values/errors; evaluated results and side effects; supported hypothesis and alternatives; cleanup disposition; tested, failed, unsupported and untested capabilities. Session connection tokens and app secrets must not be published. See [validation fixtures](assets/fixtures/validation.md) for deterministic test oracles; build success and prior research are not live proof of this implementation.

## Route by symptom

These six skills are one toolkit. Route on the symptom, not on the surface:

- Reaching a screen, dispatching taps, text, or gestures, or verifying a UI flow — `ios-simulator-driver`.
- A view is misplaced, clipped, overlapping, mis-styled, or untappable, or you need the native tree, geometry, or constraints — `ios-view-hierarchy-debugger`.
- Explaining why a value, branch, or model state is wrong — **this skill**.
- Launch time, CPU, hangs, jank, memory growth, leaks, I/O, or power — `ios-instruments-profiler`.
- Running a suite, reading a result bundle, classifying a failure, or coverage — `ios-test-engineer`.
- Why an object is still alive, what is retaining it, or where the bytes went at a checkpoint — `ios-memory-debugger`.

Hand off when the evidence needed is not the evidence this skill produces. If a listed skill is unavailable, say what it would have established rather than substituting weaker evidence for it. Preserve the established target — UDID or device, bundle ID, PID, build identity, driver session, and run directory — across the handoff; re-deriving it invalidates element references and pointers.
