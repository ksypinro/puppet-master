# Selecting a capture provider

Use this reference before a live capture. The choice depends on access, not just whether a command is installed.

## Preflight

Read the tools already connected to the session and preserve existing target context. On a local Mac, `xcode-select -p` and `xcodebuild -version` identify the selected installation. `xcrun simctl list devices --json` inventories Simulator targets. Use the simulator-driver doctor if that skill is available. For devices, inspect the available Xcode/device connection tools and their help; a device process is not an ordinary local host PID.

Establish the app bundle ID and PID from the existing launch result, debugger, or target-scoped process inspection. If several processes match, resolve the ambiguity before attaching. `xcrun simctl launch` changes launch state; do not use it solely to discover the PID of a transient screen already under investigation.

Choose a read-only inspection route already supported by the app or current debugger. A new debugger attachment pauses the process and can alter timing. Existing debugger ownership takes precedence; use its console instead of attempting a second attachment.

## Provider routes

| Route | Setup and usable result | Limits that affect reasoning |
|---|---|---|
| Bundled LLDB public capture | Import `scripts/lldb_ui.py` in an attached debug session; `ui_capture` writes structured native evidence on the host. Simulator can use `scripts/build_probe.py` and `--compiled-probe` to avoid large-expression SDK import failures | Requires execution in a suitable paused main-thread frame. Compiled mode was live-tested on Sparrow/arm64/iOS Simulator 27; it does not imply device support or the full Xcode model |
| Existing in-app public probe | Query the app's debug service on the main actor; inspect its returned capabilities/schema | Must be present or integrated into an authorized debug build; field and capture semantics vary |
| Loupe | Native UIKit inspection plus targeted reports in the inspected project | Use the actual installed interface and source revision; injection and device support are environment dependent |
| ipedro/Inspector MCP bridge | Query/resolve/subtree/inspect/state operations in a debug integration | Research inspected a development branch; `assertVisible` then meant non-hidden and state diffs omitted geometry |
| LookinServer plus lookin-cli | Layer-oriented capture and selected properties, screenshots, and measurements | CALayer display graph differs from UIView containment; client/server revisions must agree |
| Chisel or FLEX | Existing LLDB commands or embedded inspection UI | Inspect command implementation and scope; some Chisel helpers use private methods; FLEX is primarily a human interface |
| k-kohey/axe | LLDB-based private native and optional SwiftUI capture | Distinct from cameroncooke/axe; normalized fields are a subset; private symbols and SwiftUI mode are version dependent |
| LNViewHierarchyDumper | Private phased capture with Xcode-compatible `.viewhierarchy` artifacts | Requires a compatible target-side integration or injection and Xcode support; no universal supported headless export |
| Xcode View Debugger GUI | Human inspection and exported hierarchy where available | Appropriate escalation for unsupported fields; do not pretend GUI-only data is already in a CLI result |
| AXe / XCTest / XcodeBuildMCP / WDA / idb | Semantic hierarchy, actions, screenshots, and UI reproduction | Does not expose every native view, CALayer, constraint, color, or logical SwiftUI node |

Discover command names and arguments from the installed tool's help or tool schema. This skill supplies no adapters for third-party wire formats. Preserve a raw capture and explicitly transform known fields into the bundled JSON contract if using the offline analysis commands. Keep provider provenance when adding AX or authored SwiftUI evidence.

## Simulator versus device

On Simulator, the app runs as a host process, but debugger permissions and app signing still matter. Reuse the PID returned by a known app launch or selected debugger session. Full Xcode is needed for UIKit-aware expressions.

On a physical device, use a developer-authorized debug build and an established device debugging connection, or a signed debug inspection component. Device trust, Developer Mode, signing entitlements, and preparation must be satisfied by the existing development workflow. A bare `lldb --attach-pid` on the Mac does not attach to an arbitrary device process.

On an App Store, third-party, or system app without native debug access, continue with its accessible semantics and screenshots. The skill cannot bypass the process boundary to inspect arbitrary private application objects.

## Private capture is conditional

Use private capture when the requested fact needs it and the user has placed that debugging approach in scope. Record the exact Xcode build, runtime, architecture, provider revision, raw response, and normalization status. Verify a small capture on that combination before relying on it. Never infer compatibility from the research's version alone.

`k-kohey/axe`'s researched SwiftUI mode needs an app launch configuration involving `SWIFTUI_VIEW_DEBUG=287` and private `_viewDebugData()`. Adding the environment switch requires relaunch and can destroy the state being studied. The switch is an implementation detail, not a supported Apple interface.

A private provider failure should leave screenshot, AX, and public native analysis usable. Keep private code out of release configurations. Exact compositor flags, Xcode's issue engine, logical SwiftUI internals, and `.viewhierarchy` compatibility must remain explicitly provider/version dependent.
