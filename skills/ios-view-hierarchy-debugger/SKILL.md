---
name: ios-view-hierarchy-debugger
description: Inspect and explain runtime iOS and iPadOS UI state using native view hierarchy evidence, geometry, constraints, properties, accessibility, and screenshots. Use to diagnose misplaced, clipped, overlapping, incorrectly styled, untappable, or stale views, or to understand the current screen before a UI fix. Supports Simulator and debuggable devices with explicit capability limits for SwiftUI and uninstrumented apps.
license: MIT
compatibility: Requires macOS, full Xcode, Python 3.9+, and debugger access to the target app on Simulator or a debuggable device build. Visual checks need host image inspection. Does not grant access to apps you cannot already debug.
metadata:
  author: Kazi Samin Yeaser
  version: "1.3.0"
  repository: https://github.com/ksypinro/puppet-master
  short-description: Inspect and explain runtime iOS and iPadOS UI state using native view hierarchy 
---

# iOS View Hierarchy Debugger

Explain the current UI from captured runtime facts. Locate the relevant view or authored SwiftUI component, inspect its size and position in the correct coordinate space, follow its layout and ownership relationships, and distinguish observed properties from hypotheses about the symptom.

This skill is portable Markdown plus Python helpers. An LLM needs file and command execution; live capture also needs macOS, full Xcode, and access to the target's debugger or an existing in-app inspection service. Image inspection is needed to verify appearance. The instructions do not grant access to every installed app.

## Choose the available depth

Read [references/providers.md](references/providers.md) before selecting a capture method. Reuse a healthy tool or debugger session already established for the target.

| Available access | What can be established |
|---|---|
| Screenshot and AX/XCTest only | Visible appearance and exposed semantic controls; native ownership, constraints, and most style values remain unknown |
| Existing native inspector or attachable debug app | UIKit tree, geometry, public properties, layout evidence, and backing layer state, subject to the provider's actual fields |
| Authored SwiftUI diagnostics | Registered component identity, selected app state, source location, and resolved geometry |
| Compatible private capture adapter | Additional Xcode or logical SwiftUI information, with version-specific limitations |

Treat AX, UIView, CALayer, SwiftUI, and pixels as different evidence sources. An AX child is not necessarily a native subview. A native hosting view is not the complete logical SwiftUI tree. Unavailable properties are `unknown`, never zero or false.

The bundled `scripts/lldb_ui.py` is a public UIKit capture implementation. On Simulator, `scripts/build_probe.py` can compile that collector for the observed target architecture; `ui_capture --compiled-probe` avoids LLDB's large SDK-expression compatibility problems. Read the LLDB reference before loading it: the probe temporarily runs code inside the authorized app. The `scripts/ui_evidence.py` commands are offline analysis of its JSON contract. Other providers require their own available tools and an explicit adapter; do not invent a universal `ui_diagnose`, `simctl hierarchy`, or MCP command.

## Establish one checkpoint

1. Preserve the selected UDID or device identifier, bundle ID, app build, current session, and user goal. Identify a unique target before attaching, launching, or acting. Keep artifacts in a new run directory outside the skill folder.
2. For reproduction on Simulator, use `ios-simulator-driver` if available. If it is not installed, use an existing AXe, XCTest, WDA, idb, or structured driver: observe the current screen, choose one unambiguous action, dispatch it, then verify a fresh postcondition. `simctl` alone cannot synthesize arbitrary taps or swipes.
3. Record the screen/scenario, orientation, appearance, Dynamic Type, locale, keyboard state, and relevant fixture state. Record only known values. Avoid relaunching a running app when its transient state is the subject of investigation.
4. Capture a screenshot and semantic state near the native capture. For Simulator, use an explicit target: `xcrun simctl io UDID screenshot /absolute/run/screen.png`. Inspect the image when appearance matters. A command succeeding does not establish that the expected screen was captured.
5. Use an existing native service, or read [references/lldb-capture.md](references/lldb-capture.md) in full before loading the bundled LLDB command. Capture after the intended UI has settled when the issue is static. For a transition or animation, preserve the timing and distinguish model from presentation geometry.
6. Read capture limitations, errors, node/depth limits, and coherence before interpreting the tree. A paused capture can still invoke app getters. A main-thread capture does not synchronize the external AX service, compositor, or screenshot. If evidence disagrees, take a fresh bounded checkpoint or report temporal uncertainty.

Do not force layout, dismiss overlays, scroll a suspected node into view, hide views, or call actions simply to make inspection easier: these may remove the state being diagnosed. A reproduction step can change the UI when that is part of the user's requested scenario; record it.

## Find the relevant native region

Read [references/evidence-workflow.md](references/evidence-workflow.md) for the JSON contract, actual command syntax, correlation rules, and artifacts. Resolve the skill directory from this file's location; command paths below are relative to that directory, not the app repository.

```sh
python3 scripts/ui_evidence.py summary /absolute/run/native.json --limit 30
python3 scripts/ui_evidence.py query /absolute/run/native.json --identifier checkout.total --ancestors
python3 scripts/ui_evidence.py point /absolute/run/native.json --x 210 --y 430 --limit 20
```

Start with a unique authored or accessibility identifier. Otherwise use the visible symptom's screen point, class, and nearby context. Screen-point candidates are geometric overlaps, not proof of visibility or of which view receives a touch. Inspect ancestors, siblings, owning window, and constraints before selecting the likely responsible node.

Keep pointer and node references within their capture. Re-query after navigation, reuse, layout changes, or relaunch. Duplicate identifiers require additional scope or a new authored identity; never silently choose the first match. A class name or nearest controller alone does not establish the source declaration responsible for a defect.

## Inspect size, position, and UI state

Read [references/geometry-and-properties.md](references/geometry-and-properties.md) for any geometry, layout, styling, visibility, or interaction diagnosis. It contains the property-to-question map and coordinate rules.

For the selected node, obtain the smallest useful evidence set:

- **Identity and relationships:** native class, capture ID, semantic identifier, parent, window, controller/source relationship if captured, and nearby competing nodes.
- **Geometry:** local bounds, parent-space frame, screen-space corners and enclosing rectangle, transforms, safe area, margins, scroll offsets, screen scale, and relevant presentation state.
- **Layout:** intrinsic size, hugging/compression priorities, active and affecting constraints, layout guide owners, ambiguity, and contemporaneous unsatisfiable-constraint logs when relevant.
- **Properties:** resolved colors, alpha and hidden chain, clipping/masks, typography, image/control/scroll state, first responder, accessibility, and public layer fields appropriate to the symptom.
- **Pixels and interaction:** current screenshot/crop, AX hittability if available, and targeted native hit testing only when needed and supported by the provider.

Do not turn a probable offscreen-rendering cause into a measured render pass. Do not equate a non-hidden view with a visible or tappable one. Compare final pixel color with resolved property color only after accounting for compositing and coordinate mapping.

For SwiftUI, custom drawing, web content, and remote surfaces, read [references/swiftui-and-opaque-surfaces.md](references/swiftui-and-opaque-surfaces.md). State which logical, backing, authored, or pixel facts are available.

## Explain the state and diagnose the issue

For an understanding request, stop at a useful state explanation: what the screen contains, how the selected nodes are arranged, their important properties, and the constraints or state controlling them. An issue is not required.

For a defect, name the observed symptom and rank a small number of hypotheses. Each hypothesis must identify specific nodes, property values, coordinate spaces, and supporting or conflicting evidence. Request additional capture only if it distinguishes those hypotheses.

Examples of useful conclusions:

- “The label occupies 132 screen points while its captured intrinsic width is 184. Its horizontal compression resistance is 749; the sibling button's is 751. The screenshot shows truncation. The priority relationship is a likely contributor.”
- “The control exists and is enabled, but the point query also includes an overlay. Geometry alone does not establish interception; a targeted hit test or fresh XCTest hittability check is still needed.”

Do not claim the original method's call stack or allocation site from the current event-loop stack. Do not claim a complete app state model from the properties exposed by the UI.

## Verify a requested fix

Only change app source when the user's task includes a fix or implementation. If it does, make the smallest supported change, rebuild, reproduce the same checkpoint, and capture fresh evidence. Temporary debugger mutations are experiments; they do not update source or prove a persisted fix.

```sh
python3 scripts/ui_evidence.py diff /absolute/before/native.json /absolute/after/native.json --limit 40
```

Check the intended geometry/property change, the user-visible result, and the relevant adjacent controls. Diff matches require unique durable identities; unmatched nodes are not automatically additions or removals. Treat a different device, scale, orientation, or fixture as a variant comparison with explicit context, not an unqualified regression result. Profile performance separately with `ios-instruments-profiler` when available if the user asks about hitches, hangs, or render cost.

## Deliver the evidence

Report the target and checkpoint; the selected nodes and their measured properties with units; the relationship that explains the layout or symptom; the most likely cause and confidence if diagnosing; and links to native JSON, screenshot, relevant AX/log evidence, and before/after results. State missing capture coverage explicitly. For an inaccessible third-party or system app, deliver the available semantic and pixel findings and identify the exact missing native capability.

The research foundation and provider-specific limits are in [references/research-and-limits.md](references/research-and-limits.md). Its historical comparison scores are not runtime coverage guarantees.

## Route by symptom

These six skills are one toolkit. Route on the symptom, not on the surface:

- Reaching a screen, dispatching taps, text, or gestures, or verifying a UI flow — `ios-simulator-driver`.
- Explaining what is drawn, from native view evidence — **this skill**.
- A value, branch, or model state is wrong, or you need the code path that produced it — `lldb-code-state-debugger`.
- Launch time, CPU, hangs, jank, memory growth, leaks, I/O, or power — `ios-instruments-profiler`.
- Running a suite, reading a result bundle, classifying a failure, or coverage — `ios-test-engineer`.
- Why an object is still alive, what is retaining it, or where the bytes went at a checkpoint — `ios-memory-debugger`.

Hand off when the evidence needed is not the evidence this skill produces. If a listed skill is unavailable, say what it would have established rather than substituting weaker evidence for it. Preserve the established target — UDID or device, bundle ID, PID, build identity, driver session, and run directory — across the handoff; re-deriving it invalidates element references and pointers.
