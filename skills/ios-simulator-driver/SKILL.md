---
name: ios-simulator-driver
description: Drive and inspect iOS Simulator apps through a closed observe-act-verify loop. Use for simulator navigation, accessibility inspection, screenshots, taps, text entry, swipes, long presses, gestures, visual verification, UI-flow exploration, and recovery from stale or ambiguous simulator state. This skill is Simulator-specific; physical iOS devices require a signed XCTest/WebDriverAgent device workflow.
license: MIT
compatibility: Requires macOS, full Xcode with an installed iOS Simulator runtime, and Python 3.9+. Needs at least one UI driver (AXe, idb, XcodeBuildMCP, Appium/WebDriverAgent, or a source-owned XCUIAutomation runner); simctl alone cannot synthesize taps. Visual checks need host image inspection.
metadata:
  author: Kazi Samin Yeaser
  version: "1.3.0"
  repository: https://github.com/ksypinro/puppet-master
  short-description: Drive and inspect iOS Simulator apps through a closed observe-act-verify loop
---

# iOS Simulator Driver

Complete the user's UI goal on one explicitly selected iOS Simulator and prove the result with fresh evidence. Treat every input command as event dispatch—not success—until a postcondition is observed.

## Operating boundary

- Require macOS, full Xcode, and an installed iOS Simulator runtime.
- Use `xcrun simctl` for target/app lifecycle, environment setup, screenshots, video, and diagnostics. It does not provide general `tap`, `swipe`, or `type` verbs.
- Require at least one UI driver: a structured XcodeBuildMCP/agent-device session, AXe, idb, Appium/WebDriverAgent, or a source-owned XCUIAutomation runner. If none is available, capture what can be observed and report the missing capability; never invent a `simctl tap` command.
- Never install a driver, alter signing, change project code, erase a Simulator, or reset app data unless the request authorizes it.
- Use an explicit UDID for every mutation. Resolve names only during discovery; do not use an ambiguous `booted` target.
- A text-only model can reason from accessibility state but cannot honestly claim pixel-level visual inspection. Use the host's image-inspection capability on captured PNGs when visual analysis is required.

## Start or resume a session

1. Preserve any UDID, bundle ID, app path, driver session, run directory, and last snapshot already established in the conversation. Do not restart a healthy session.
2. If the target is not explicit, run the bundled read-only `scripts/simulator_doctor.py`. Choose automatically only when exactly one eligible Simulator matches the user's request; otherwise ask for the target.
3. Wait for readiness with `xcrun simctl bootstatus <UDID> -b` when the target is booting. `simctl boot` returning is not readiness, and target readiness does not prove the launched app has rendered. After launch, wait for the expected semantic root or a stable non-transient screenshot before acting.
4. Bind a run directory outside the skill folder for evidence. Record the UDID, runtime, Xcode build, selected driver, foreground bundle, and timestamps. Do not place secrets in paths, commands, or logs.
5. Before the first UI action, read [references/drivers.md](references/drivers.md) and use only the selected driver's section. Prefer an already-connected structured driver over spawning another automation stack.

## Select the driver

Use the user's requested driver when viable. Otherwise prefer, in order:

1. An existing structured MCP/runtime session that returns semantic refs, post-action state, and wait predicates.
2. `agent-device` for an agent-oriented XCTest session with actionable refs and settled diffs.
3. XcodeBuildMCP CLI for an integrated build/run/snapshot/action workflow with JSON output.
4. AXe for low-latency, standalone Simulator accessibility plus HID input.
5. idb for lower-level accessibility/HID primitives.
6. A source-owned XCUIAutomation test runner for durable, supported project automation.

Do not switch drivers mid-flow unless the current driver is unhealthy or lacks a required capability. A switch invalidates element refs; observe again.

## Closed-loop protocol

Repeat this loop until the goal is verified or a real blocker is reached.

### 1. Observe

- Read target state, orientation, foreground app, and a compact semantic snapshot.
- Keep interactive visible elements plus enough static context to identify the screen. Retain identifier, role/type, label, value, enabled/selected/focused state, frame, and available actions.
- Capture and inspect a screenshot initially, at the final state, whenever visual appearance is part of the task, whenever using coordinates, and whenever semantic state is empty, suspicious, or contradicts the result.
- Treat a bare application node, zero-size root, or empty child list as `AX_UNREADY`, not as proof of a blank screen.

### 2. Plan one verifiable transition

Before acting, state internally:

- the immediate action;
- the target and why it is unique;
- the snapshot/ref/hash or visual state used to choose it;
- the expected postcondition;
- whether repeating the action would be safe.

Target precedence: stable accessibility identifier → unique scoped semantic selector → current snapshot ref → guarded coordinate derived from current evidence → vision-only coordinate as last resort. Multiple plausible matches are an error, not permission to choose the first.

### 3. Act

- Use the smallest action that advances the goal: tap/press, fill, type, key, scroll/swipe, long press, drag, slider, or hardware button.
- Focus a text field before keyboard injection. Prefer a driver's verified `fill`/`set-value` operation when available; otherwise tap, clear deliberately, type, and verify.
- Derive gesture points from current element frames or the current screenshot. Keep start/end points away from system gesture regions unless the requested gesture needs them.
- Avoid batching across navigation or layout changes unless the driver refreshes selectors per step and every intermediate action is safe.

### 4. Wait and verify

- Wait on the smallest semantic predicate: element appears/disappears, value/focus/selection changes, foreground bundle changes, or layout/screen hash settles. Use a monotonic bounded deadline.
- Always fetch fresh post-action semantic state. Inspect a fresh screenshot when the action was coordinate-based, the visual result matters, the semantic result is inconclusive, or the action failed.
- If the immediate semantic state and screenshot disagree, take no further action. Fetch a bounded fresh pair and require them to converge or classify the state as uncertain; either source may lag during transitions.
- Verify the intended outcome, not merely that the command exited successfully. For secure fields, verify focus, masked-entry state, or the enabled next action without exposing the secret.
- Invalidate old refs after navigation, scrolling, rotation, relaunch, driver restart, or material layout change.

### 5. Decide the next action

- If the postcondition holds, continue from the fresh state.
- If the state changed differently, re-plan from evidence; do not force the old plan.
- If nothing changed, classify the failure before retrying: stale selector, not hittable, overlay, keyboard/focus, animation/idleness, app crash, AX unavailable, driver failure, or target loss.
- Retry only when the action is idempotent and evidence shows it did not commit. Never automatically replay submit, purchase, send, delete, account, permission, or other consequential actions after an ambiguous timeout.
- Read [references/recovery-and-safety.md](references/recovery-and-safety.md) before escalating recovery or handling sensitive/destructive actions.

## Completion and handoff

Finish only when the requested state is observable. Report:

- what was achieved;
- the selected Simulator and app;
- the semantic or visual postcondition that proved completion;
- paths to the final screenshot and relevant run artifacts;
- any limitation or unverified visual claim.

If blocked, provide the last trustworthy state, the failure class, evidence paths, and the smallest user action or missing dependency needed. Do not present a dispatched gesture as completion.

## Implementing a reusable controller

When the task is to build an MCP server, CLI facade, or AXe-like controller rather than drive one session, read [references/controller-contract.md](references/controller-contract.md). Keep lifecycle, observer, driver, synchronizer, verifier, artifact, lease, and recovery components replaceable behind a versioned structured contract.

## Route by symptom

These six skills are one toolkit. Route on the symptom, not on the surface:

- Reaching a screen, dispatching input, or verifying a UI flow — **this skill**.
- A view is misplaced, clipped, overlapping, mis-styled, or untappable, or you need the native tree, geometry, or constraints — `ios-view-hierarchy-debugger`.
- A value, branch, or model state is wrong, or you need the code path that produced it — `lldb-code-state-debugger`.
- Launch time, CPU, hangs, jank, memory growth, leaks, I/O, or power — `ios-instruments-profiler`.
- Running a suite, reading a result bundle, classifying a failure, or coverage — `ios-test-engineer`.
- Why an object is still alive, what is retaining it, or where the bytes went at a checkpoint — `ios-memory-debugger`.

Hand off when the evidence needed is not the evidence this skill produces. If a listed skill is unavailable, say what it would have established rather than substituting weaker evidence for it. Preserve the established target — UDID or device, bundle ID, PID, build identity, driver session, and run directory — across the handoff; re-deriving it invalidates element references and pointers.
