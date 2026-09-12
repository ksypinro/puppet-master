# Native UIKit evidence through LLDB

Use this route when the user has authorized debugging the app and you can access its debug process. It reads actual UIKit instances and each view's backing Core Animation layer using public APIs. It works independently of the accessibility tree, so decorative, hidden, overlapping and non-accessible UIView instances can appear. It requires a compatible LLDB/Xcode SDK and a debuggable app. It does not make an arbitrary App Store app attachable and does not expose the logical SwiftUI tree.

The bundled `scripts/lldb_ui.py` installs `ui_capture`. Live Sparrow testing on 10 September 2026 with Xcode 27.0 build 27A5194q, iOS Simulator 27.0 build 24A5355p, and arm64 completed three validated 90-view captures, including a fresh LLDB session without SDK imports. All three recorded buffer release and successful `dlclose`; offline summary, query, point, and diff validation succeeded. The screenshots surrounding capture were identical below the status bar. This validates compiled Simulator capture on that combination, not device or universal SwiftUI support. The test also exposed expression-import, loader, cleanup-result, and sentinel-geometry issues that SDK compilation alone did not catch.

For Simulator, start with [compiled probe mode](#compiled-probe-fallback-for-simulator). It does not need the SDK-import setup used by expression mode below. Verify the first runtime capture for every new Xcode/iOS combination; a successful import or compile does not establish live capture coverage.

## Capture an existing authorized debugging session

1. Reproduce the UI state using the simulator-driver workflow, save its screenshot and record the app PID, simulator UDID, orientation, scenario and time. Avoid UI actions once the app is stopped. Screenshots and hierarchy are separate observations; record that time gap.
2. In the existing LLDB session, pause the app if needed. Inspect `process status`, `thread list` and `thread backtrace`. Select the main thread using its actual listed index, then a valid frame. Do not assume thread index 1 is always the main thread. The helper checks `[NSThread isMainThread]` and refuses other threads.
3. For expression mode only, check the target SDK and import SDK modules as persistent LLDB declarations before using the helper. A directly attached simulator process can have no `target.sdk-path`, even while its architecture correctly says `arm64-apple-ios-simulator`. Obtain the SDK with `xcrun --sdk iphonesimulator --show-sdk-path` on the host. For a new LLDB target, configure that path before target creation/attach when possible. For an existing target, inspect its current setting and use the correct observed SDK if it is missing or wrong; do not substitute a Simulator SDK for a device target. Keep the prior value in the session record if you change it.

```text
(lldb) settings show target.sdk-path
(lldb) settings set target.sdk-path <OBSERVED_MATCHING_SDK_PATH>
(lldb) expression -l objc++ -- @import UIKit
(lldb) expression -l objc++ -- @import QuartzCore
(lldb) expression -l objc++ -- @import Darwin
```

Set the SDK only when needed. Each import must succeed; a compiler module-cache permission failure is an environment issue, not an empty app hierarchy. The helper deliberately does not silently alter target settings. Do not place `#import <UIKit/UIKit.h>` or `@import UIKit` in `SBExpressionOptions.SetPrefix`: that wrapper can lack the module/header search context even after a normal persistent import succeeds. The bundled `PREFIX` constant is only for standalone clang validation. The capture uses an empty runtime prefix and the imported declarations. Explicit types for dictionary values avoid depending on LLDB's runtime lookup of methods on an untyped `id`.

4. Import the helper and capture into a new absolute host file. Quote paths containing spaces. The parent directory must already exist.

```text
(lldb) process status
(lldb) thread list
(lldb) thread select <observed-main-thread-index>
(lldb) frame select 0
(lldb) command script import "/absolute/skill/scripts/lldb_ui.py"
(lldb) ui_capture "/absolute/evidence/before.json" --max-nodes 2000 --max-depth 40 --timeout 15
```

`ui_capture --help` describes the arguments. Defaults: 2,000 views, depth 40, 16 MiB JSON, 15-second expression timeout and 128 constraints per list. Hard configurable ceilings are 10,000 views, depth 100, 32 MiB and 60 seconds. Start smaller when the app is large or unstable. A target expression timeout is a best effort debugger limit, not a guarantee that arbitrary overridden getters can safely finish or unwind.

The helper evaluates Objective-C++ on the selected main-thread frame, asks LLDB to stop other threads, refuses thread fallback and leaves the process stopped. It never attaches, launches, resumes, dispatches synchronously, calls `layoutIfNeeded`, synthesizes interaction or calls `hitTest`. Objective-C property getters can still execute application code; a getter blocked on a lock held by another stopped thread can fail. On a failure, inspect the debugger state and call stack before retrying. Do not automatically continue a session that was already paused by the user.

It returns a malloc-owned UTF-8 JSON buffer, reads it with `ReadCStringFromMemory`, decodes and checks its shape, then attempts target cleanup in `finally`. It subsequently writes the data and cleanup results to a new mode-0600 host file and re-reads the JSON. It does not parse `po` or `GetObjectDescription`. A cleanup failure reports the buffer address. Inspect the stopped process before deciding whether another expression is safe; do not blindly retry. In a failed or interrupted expression, the debugger may be unable to recover all temporary allocations or changes caused by custom getters.

## Start a new simulator debugging session

Use a user-authorized debug build already installed on a selected simulator. Discover the CLI options from the installed version before launch. Expression mode requires the SDK/module setup above; compiled mode needs only the matching built probe and an authorized stopped main-thread frame. A typical controlled fresh launch is:

```sh
xcrun simctl launch --terminate-running-process --wait-for-debugger <SIMULATOR_UDID> <BUNDLE_ID>
```

`--terminate-running-process` discards the app's running state; use it for an explicitly requested fresh reproduction, not an already reproduced issue. Capture the reported PID, then start `xcrun lldb` and attach to that exact observed PID:

```text
(lldb) process attach --pid <OBSERVED_PID>
(lldb) continue
```

Resume here only because this is your newly launched, intentionally waiting app. Reproduce the issue through the simulator driver, take a screenshot, interrupt this debugging session, select the main-thread frame and run the capture command above. If Xcode or another debugger already owns the process, use that session instead of a second attach.

After capture, leave an existing user's debugging session in its original stopped/running state only when that restoration is authorized and understood. For your own temporary attach, `process detach` ends debugging and normally allows the app to run; consult `help process detach` for the installed LLDB's keep-stopped option when needed. Do not use `quit` or kill commands without checking their process disposition. On a device, use Xcode's supported device debugging connection and the same imported capture command; host `process attach --pid` is not a device connection recipe.

## Compiled probe fallback for Simulator

If the public expression cannot compile inside LLDB despite the correct SDK and persistent imports, use the explicit compiled probe mode. During the Sparrow test, Xcode 27 beta LLDB could import UIKit and check the main thread, but failed when interpreting framework geometry types (`CGRect` reported a deleted destructor) and local variables in its scratch expression context. Normal SDK compilation accepts the same public capture body. These diagnostics do not mean the app's geometry is invalid.

Build a new probe directory on the host, outside the skill. Obtain the architecture from the actual LLDB target triple; choose `arm64` or `x86_64` explicitly. The output directory must not exist, and its parent must already exist.

```sh
python3 /absolute/skill/scripts/build_probe.py \
  --output-dir /absolute/run/probe \
  --arch arm64
```

The builder creates `PuppetUIProbe.mm`, `PuppetUIProbe.dylib`, and `build.json`. It uses the installed Simulator SDK, links public frameworks, signs only the new dylib ad hoc, verifies its signature and exported functions, and records commands, SDK/compiler versions, target architecture, source/binary hashes, and build failures. It never attaches, loads code, launches an app, or modifies an app project. It refuses to replace an existing output directory. Each build/sign command has a configurable 1–60 second timeout. Failed artifacts remain available for diagnosis; use a new directory for the next attempt.

In an authorized stopped Simulator debugging session with its main thread selected:

```text
(lldb) command script import "/absolute/skill/scripts/lldb_ui.py"
(lldb) ui_capture "/absolute/run/native.json" --compiled-probe "/absolute/run/probe/PuppetUIProbe.dylib" --timeout 30
```

This mode loads the explicitly supplied dylib through a bounded primitive C `dlopen` expression and keeps the returned handle. Sparrow's live session exposed a failure in LLDB's `SBProcess.LoadImage` wrapper; the direct C call succeeded. The helper resolves three exported functions from the loaded module and calls them through primitive C signatures: `PuppetUIIsMainThread`, `PuppetUICapture`, and `PuppetUIFree`. No UIKit types or framework imports are needed in those LLDB call expressions. The compiled capture checks the main thread again before reading UIKit; capture ID/time are fresh arguments for every invocation. Node/depth/byte limits remain enforced both by the command and the exported function. The normal JSON schema and public-API capture limitations remain unchanged.

The helper rejects this option unless the target triple identifies an iOS Simulator. Match the dylib architecture and minimum supported OS to the target. This workflow does not compile, sign, transfer, or inject a probe into a physical device automatically. A source-integrated debug service or an existing supported device debugger remains the device route.

The command frees the returned buffer and releases its own `dlopen` reference with a bounded primitive C `dlclose` expression in `finally`, including host read/JSON failures. `PuppetUIFree` returns integer `1` after freeing; the host requires both a successful debugger result and this explicit acknowledgement. Sparrow's LLDB returned an ambiguous error for void-valued expressions, including `(void)0`, so a void expression alone cannot reliably report cleanup success on this version. A failed result remains a reported uncertainty; do not retry a free blindly.

The helper avoids closing a probe while a captured stack still executes its code, when the process is no longer stopped, or when stack inspection is incomplete. Missing/invalid frames or a thread exceeding the 200-frame inspection bound prevent closing. Read `capture.executionMode` and `capture.cleanup` in the saved evidence: compiled mode reports `compiled-simulator-probe`, with explicit outcomes for `targetBuffer` and `probeImage`. A successful `dlclose` returning zero releases this command's reference; it does not guarantee that dyld physically unmaps the image. Inspect the debugger's module list separately if removal from the address space matters. Cleanup failure warnings contain the retained buffer address or library handle. A timed-out target call is still subject to debugger unwind limitations; inspect process/thread state before further calls.

Loading a probe temporarily changes the process's loaded-image state and allocates diagnostic objects. It does not change source, navigation, view properties, or app data intentionally. Preserve the screenshot/checkpoint before capture and verify app responsiveness after detaching your own session. Keep the compiled dylib and its provenance with the evidence so the exact implementation can be reviewed and rebuilt.

## What the JSON actually contains

Top level uses `schemaVersion: "ios-ui-evidence/v1"`, `capture`, `target` and `nodes`. `capture` includes an ID/time, provider `lldb-public-uikit` or `lldb-public-uikit-compiled-probe`, execution mode and cleanup outcomes, coherence description, limitations, limits, truncation flags and a `windows` list. Target metadata includes bundle ID, process ID/name and OS version. No app content text, accessibility label, accessibility value, text-field value or text-view value is read. Secure text fields and text views are identified while their contents remain omitted. Identifiers and class/font names are still metadata; inspect them before sharing artifacts outside the task.

| Field | Meaning and limitation |
| --- | --- |
| `id`, `parentId`, `windowId` | Capture-local pointer IDs. Do not reuse across capture, restart or process. Constraints may reference objects outside the captured set. |
| `accessibilityIdentifier` | Optional top-level identifier; `accessibilityIdentifierUniqueInCapture` reports only observed uniqueness. A truncated capture cannot prove global uniqueness. No `semanticId` is fabricated. |
| `geometry.frame`, `bounds`, `center` | Raw model geometry: frame/center in the superview, bounds in the view's own coordinates. `frameReliable` is false when the UIView affine transform is nonidentity. A nonidentity layer transform and ancestors also require checking screen conversion and screenshot. |
| `geometry.screenFrame`, `screenQuad` | Bounds converted with public `convertRect/convertPoint:toCoordinateSpace:` to the window screen's points. Quad order is top-left, top-right, bottom-right, bottom-left in local bounds, transformed into screen coordinates. Screen rectangle is an enclosing box, not a clipping or occlusion result. An unusable/sentinel screen rectangle produces unknown quad coordinates and unknown screen intersection. |
| `capture.windows` | Window IDs, screen bounds/scale/native scale, interface orientation (raw SDK enum), scene activation, key-window state and window level. Multi-screen captures need per-window matching. |
| `properties` | Visibility flags, alpha, interaction/first-responder state, colors resolved for traits, accessibility flags/traits, style/layout direction/content-size category. Labels expose typography and line settings; controls state; text inputs non-content settings; scroll views offset, size, insets and scrolling state. |
| `layout` | Ambiguity, intrinsic size, priorities, safe area/margins, autoresizing-mask translation and affecting-constraint lists per axis. Intrinsic `-1` means UIView's no-intrinsic-metric sentinel; it is not a negative measured size. |
| `constraints` | Constraints owned by the view, with raw item identities, layout-guide owning view/frame, attributes, relation, multiplier, constant, priority, active state and identifier. Inspect ancestors' owned constraints too. Numeric enums follow the installed SDK. No private conflict diagnosis is claimed. |
| `layer` | Common properties of the view's model backing layer: geometry, transform matrix, opacity, clipping, corners/border/shadow, mask presence, rasterization and animation-key metadata. Sublayer count is recorded, but standalone sublayers, masks, animation values and presentation layers are not recursively captured. |
| `visibility` | Self/ancestor UIView hidden flags, multiplied UIView alpha, screen intersection and positive bounds. Occlusion is explicitly unknown; ancestor clipping and hit testing are not performed. This is insufficient to prove a control is visible or tappable. |

`capture.truncated` becomes true for a node, depth, per-list constraint or byte limit. A byte overflow reduces the node array until JSON fits and reports the number removed. Breadth-first traversal retains captured parents before their children. Counts, child truncation and constraint truncation remain explicit. Do not infer that missing nodes/constraints do not exist. The constraint lists include only what the live view APIs return; inactive or uninstalled constraints held elsewhere in application state may be absent. Nonfinite geometry/numeric values become JSON `null`; rectangle `finite` flags retain validity information.

Core Graphics also has sentinel rectangles whose components can be extremely large but individually finite. Live Sparrow evidence exposed this for a hidden `_UISplitViewControllerAdaptiveColumnSeparatorView`: screen conversion returned `CGRectInfinite`, not a meaningful enormous frame. The collector recognizes `CGRectInfinite`/`CGRectNull`, stores null rectangle components with `finite: false` and `specialValue`, and gives the four `screenQuad` points null coordinates when screen conversion is unusable. `visibility.intersectsScreen` is then null/unknown. Preserve the sentinel evidence and omit those nodes from ordinary geometric overlap calculations; do not clamp their coordinates into a plausible screen position or diagnose the sentinel as a visible layout defect.

The expression reads all UIKit windows in connected scenes, with a public deprecated application-windows fallback for legacy apps. Empty results can mean the wrong process, a scene/window lifecycle transition, a non-UIKit app surface or an early launch pause. They do not prove the visible app has no views. The helper does not inspect other processes, keyboard/system overlays, web DOMs, draw calls, view-controller containment, SwiftUI modifiers or source locations.

## From capture to a defensible diagnosis

Use the offline evidence helper to select a bounded subtree and properties. Correlate screen points with screenshot pixels using the correct window's bounds, scale and orientation. Inspect a candidate's ancestors and siblings as well as its own geometry: clipping, stacking order, scroll offset and a parent's constraint can explain a child's symptom. Compare before/after captures using a unique authored identifier and compatible targets; pointer equality does not establish identity.

For a touch issue, a separately authorized, targeted main-thread LLDB expression may call the appropriate window's public `hitTest:withEvent:` at a known point in that window's coordinates. That executes app hit-test overrides and answers current model hit routing only. It does not establish accessibility hit testing, gesture-recognizer outcomes, system interception or actual rendered visibility. Keep this deliberate query separate from baseline collection.

A SwiftUI app typically yields UIKit hosting/container/bridged views. Obtain authored SwiftUI geometry/state instrumentation or an explicitly selected private provider when the missing logical component matters. Report missing information as unknown; never describe the hosting view tree as the complete SwiftUI source hierarchy.

## Reproduce the SDK-only validation

Python syntax validation can use `compile(source, path, 'exec')` without generating cache files. The generated expression can be compiled by importing the module outside LLDB (its import tolerates missing `lldb`), combining `PREFIX` with `unsigned long long check(void) { return <expression()>; }`, and passing that string to:

```sh
xcrun --sdk iphonesimulator clang -x objective-c++ -fblocks -fsyntax-only \
  -Wno-deprecated-declarations -isysroot <OBSERVED_SIMULATOR_SDK_PATH> \
  -target arm64-apple-ios17.0-simulator -
```

The source is supplied on standard input. Use `xcrun --sdk iphonesimulator --show-sdk-path` to obtain the SDK path. This proves that the chosen public declarations compile for that SDK; module import, entitlements, expression execution, snapshots and target-buffer cleanup still need a real authorized debug session.
