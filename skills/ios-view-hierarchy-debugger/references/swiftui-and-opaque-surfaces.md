# SwiftUI and opaque surfaces

Read this reference for SwiftUI, custom drawing, WebKit, Metal/video, remote views, or source attribution that a native UIView capture does not resolve.

## Identify the evidence layer

| Evidence | Reliable use | What it cannot establish alone |
|---|---|---|
| SwiftUI AX/XCTest tree | Labels, values, actionable semantics, exposed geometry | Every modifier, decorative layout node, state wrapper, or view value |
| Public UIView/CALayer backing capture | Hosting geometry and actual bridged UIKit controls/layers | Complete SwiftUI logical composition or one source view per native node |
| Authored component registry | Chosen component identity, safe scalar state, source location, and resolved anchors | Framework internals or unregistered descendants |
| ViewInspector component tests | Inspectable known SwiftUI values/modifiers and testable actions | An arbitrary already-running screen or final compositor output |
| SwiftUI Introspect | Selected UIKit/AppKit objects bridged by explicitly instrumented SwiftUI code | A general logical SwiftUI hierarchy exporter |
| Compatible private debug capture | Additional logical nodes, reflected attributes, and resolved geometry | Stable public contracts, guaranteed source mapping, or future compatibility |

The public LLDB helper may encounter `_UIHostingView` and other framework-private class names through ordinary public traversal. Seeing the class name is not proof that the object's SwiftUI internals are exposed.

## Authored diagnostics for source-owned SwiftUI

When native geometry cannot identify the relevant logical component and app instrumentation is within the requested work, add a small debug-only registry. Keep it scoped to the relevant screen or component. It should record:

- A stable component ID shared with its accessibility identifier when that mapping is appropriate. Include a stable model identifier for repeated rows; do not use only a reused index or pointer.
- An authored parent ID and source `#fileID`/`#line` captured at the modifier call site. Read these as registered source attribution, not compiler-generated proof of every descendant.
- Selected safe scalar state that explains the UI, such as expanded/selected/loading, and relevant environment values such as size category, appearance, or layout direction.
- Resolved bounds through anchor preferences or a background geometry observer in a named ancestor coordinate space. Preserve that space's ID and its mapping to the window/screen.
- Capture generation and lifecycle removal, so disappeared/reused components do not remain as stale registry entries.

Use `anchorPreference`/an ancestor preference consumer or an appropriate public geometry observation API supported by the target SDK. Avoid a layout-affecting top-level `GeometryReader` if it would change the layout being diagnosed. Do not mutate observable state repeatedly during layout to update the diagnostic registry; use a deliberate snapshot mechanism or a bounded non-layout-affecting update.

SwiftUI `.global` geometry is not automatically interchangeable with `UIScreen` coordinates in a multiwindow app. Register the hosting/window conversion. Anchor bounds describe a resolved geometry relation, not necessarily an exact clip or hit region after every effect.

Keep the registry out of release configurations and expose only allowlisted state; reflecting the whole application model is unnecessary for layout debugging. An LLM should not generate new instrumentation for a request that only asks to explain an existing artifact.

## Private SwiftUI capture

The researched `k-kohey/axe` route uses LLDB, `libViewDebuggerSupport.dylib`, and a separate private SwiftUI path. Its researched environment flag and method names are recorded in `research-and-limits.md`. Use the installed project's documented interface and verify its version; do not call guessed private selectors based on this description.

A launch flag requires a new launch. If the requested defect is a transient existing state, preserve public evidence first and disclose that the private run reproduces the scenario rather than capturing the original moment. Retain raw data and mark unknown fields/schema changes. Do not label private `_ViewDebug.Data` as a supported SwiftUI reflection API.

## Other opaque surfaces

- **WKWebView:** native hierarchy explains the container, scroll view, frame, and surrounding clipping. DOM/CSS layout requires an authorized, enabled web inspection channel and its own coordinate mapping. Accessibility text is not a full DOM; a native web container does not expose computed CSS colors.
- **Metal, SceneKit, SpriteKit, video, camera, and custom drawing:** native evidence can establish the owning surface and geometry. Individual rendered objects require a framework/app diagnostic adapter or pixel evidence. Never infer an internal UIView for every drawn object.
- **Remote/system surfaces:** keyboard, remote controllers, and protected content can belong to other processes. App capture may provide only a proxy or container. Compare a screenshot and semantic evidence; report the ownership boundary.
- **Blur, vibrancy, masks, and transparency:** isolated layer rendering may be blank or differ from the composited screen. Prefer a full screenshot plus a correctly mapped crop for visible appearance. Preserve the fact that the crop includes whatever covers the region.

For any missing domain, explain what is known at its boundary, what remains unknown inside, and which available provider could answer the actual question. Do not claim that screenshots alone identify source ownership or exact internal state.
