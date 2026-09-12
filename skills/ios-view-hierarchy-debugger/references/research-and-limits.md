# Research foundation and limits

This skill distills the workspace reports `iOS-View-Hierarchy-and-UI-State-Deep-Analysis.docx` and `Xcode-View-Debugger-and-LLM-Method-Parity-Deep-Research.docx`, researched through 6 September 2026. It does not require those files to be present to run. Provider details can change; use local capabilities and tested output as the authority for a live session.

## Decisions carried into the skill

1. Xcode acquires a correlated graph and framework-specific properties, images, and diagnostics. An accessibility dump cannot substitute for that graph.
2. Public in-process UIKit inspection provides most ordinary geometry, state, and constraint facts needed to explain UIKit defects. Access to the target process remains a prerequisite.
3. Stable semantic references and small structured queries make evidence useful for an LLM. Addresses are capture-local identity, and geometry must be included in state diffs.
4. Exact logical SwiftUI information, compositor render flags, Apple's diagnostics engine, and Xcode-compatible archive generation have private or incomplete paths.
5. Final pixels, runtime properties, semantic actionability, and authored source/state metadata complement each other. Conflicting observations require a coherent recapture or an explicit uncertainty finding.

The reports' weighted coverage/operability scores are design estimates. They are not measured completion percentages of this skill, its bundled scripts, or the current app. Report actual captured domains instead.

## Relevant primary sources

- [Apple: Diagnose appearance issues in a running app](https://developer.apple.com/documentation/xcode/diagnosing-issues-in-the-appearance-of-your-running-app)
- [Apple: Pause execution and view the UI hierarchy](https://help.apple.com/xcode/mac/current/en.lproj/devea99126aa.html)
- [WWDC 2018: Advanced Debugging with Xcode and LLDB](https://developer.apple.com/videos/play/wwdc2018/412/)
- [WWDC 2019: Debugging in Xcode 11](https://developer.apple.com/videos/play/wwdc2019/412/)
- [Apple Tech Talk: Analyze and optimize app graphics with the Xcode View Debugger](https://developer.apple.com/videos/play/tech-talks/10857/)
- [Apple: UIView frame](https://developer.apple.com/documentation/uikit/uiview/frame)
- [Apple: UIView bounds](https://developer.apple.com/documentation/uikit/uiview/bounds)
- [Apple: constraintsAffectingLayout(for:)](https://developer.apple.com/documentation/uikit/uiview/constraintsaffectinglayout(for:))
- [Apple: hasAmbiguousLayout](https://developer.apple.com/documentation/uikit/uiview/hasambiguouslayout)
- [Apple: XCUIElementAttributes](https://developer.apple.com/documentation/xcuiautomation/xcuielementattributes)

## Open-source design references

| Project | Contribution to the skill | Important boundary |
|---|---|---|
| [cameroncooke/axe](https://github.com/cameroncooke/axe) and [XcodeBuildMCP](https://github.com/getsentry/XcodeBuildMCP) | Reproduction and semantic evidence | AX state does not enumerate all native views or constraints |
| [Loupe](https://github.com/heoblitz/Loupe) | Public native inspection and an evidence-driven fix/replay approach | Actual integration, injection, and device capabilities must be checked |
| [ipedro/Inspector](https://github.com/ipedro/Inspector) | Bounded queries, semantic handles, assertions, scenarios, MCP bridge | The inspected development branch's visibility/state diff was incomplete |
| [DebugSwift](https://github.com/DebugSwift/DebugSwift) | Public property inspection and a reproducible 3D hierarchy viewer | Human interface; SwiftUI reflection and isolated imagery have gaps |
| [LookinServer](https://github.com/QMUI/LookinServer) and [lookin-cli](https://github.com/shoujiaxin/lookin-cli) | Layer inspection and machine-readable access patterns | Layer hierarchy and native view hierarchy have different relationships |
| [Chisel](https://github.com/facebook/chisel) and [FLEX](https://github.com/FLEXTool/FLEX) | Debugger/in-process object inspection patterns | Command-specific private helpers or human UI may be involved |
| [ViewInspector](https://github.com/nalexn/ViewInspector) and [SwiftUI Introspect](https://github.com/siteline/swiftui-introspect) | Component-test evidence and selected UIKit bridges | Neither is a general exporter of an arbitrary running SwiftUI screen |
| [k-kohey/axe](https://github.com/k-kohey/axe) | LLDB private capture and SwiftUI logical-data exploration | A different project from cameroncooke/axe; private SDK behavior |
| [LNViewHierarchyDumper](https://github.com/LeoNatan/LNViewHierarchyDumper) | Phased private requests and `.viewhierarchy` archive generation | Optional version-pinned path, not a public CLI contract |

The private paths were inspected at LNViewHierarchyDumper commit `64d1d66ac588c5e7369d0f0945069820fdcd7434`, k-kohey/axe `f016a90a651480c86f7ec6d6317fc71159e4fa57`, Inspector development commit `bb220e49adbee9cfdd1d386ad22f00a14b37db1e`, and DebugSwift `70885d375be5b5faef37dfe19197e0d02ae5d15` in the source report. These are historical inspection records, not installation requirements or tested compatibility promises for this skill.

## Bundle scope

This package supplies an LLDB public capture command and offline JSON analysis, plus procedures for existing providers. It does not install a UI driver, deploy an app service, implement a full SwiftUI registry, export `.viewhierarchy`, produce a 3D renderer, or reproduce Apple's private diagnostic rules. Those are optional integration choices for a task that needs them.

Use the actual helper validation results recorded at delivery. Syntax/SDK compilation and offline fixture tests do not prove that debugger expression execution succeeds in every target. A live app capture must pass the checks in `lldb-capture.md` before its data is trusted.
