# Research lineage and qualification ledger

The skill synthesizes the supplied `Xcode-LLDB-Debugging-and-LLM-Root-Cause-Analysis.docx` and the eight repository deep dives completed September 2026. It is an original small SB-API controller, not a redistribution of those wrappers or a claim to reproduce their entire codebases. Copying the folder does not install Xcode, a UI driver or MCP.

| Research input | Design carried into this skill | Deliberate boundary |
|---|---|---|
| [XcodeBuildMCP persistent debugger manager](https://github.com/getsentry/XcodeBuildMCP/blob/e6ef59b49b44012c824f0a0de261c96142e37390/src/utils/debugger/debugger-manager.ts#L25) | Persistent session, selected Xcode, Simulator identity and debugger-aware UI workflow | No second debugger owner; no claim to implement its build/test/UI tools |
| [LLVM LLDB breakpoint verification](https://github.com/llvm/llvm-project/blob/dbeea4508e52856497e4080b1d3b265975044795/lldb/tools/lldb-dap/Breakpoint.cpp#L60) | Preserve resolved locations and typed state, not text-only success | Uses Apple LLDB SB API directly, not a DAP or native-MCP implementation |
| [CodeLLDB event listener](https://github.com/vadimcn/codelldb/blob/62def434dc22c1d77d4837c4d99cddef7ac3338f/src/codelldb/src/debug_event_listener.rs#L29) | Own event consumer, short-lived handles and explicit event loss | No editor-refresh events mistaken for business stops; no mature-adapter parity claim |
| [stass transport](https://github.com/stass/lldb-mcp/blob/a610f2d0d3835739c41762352442ba2a13958b38/lldb_mcp.py#L28) | Transparent expert console plus small command taxonomy | JSON framing does not use the literal LLDB prompt as a delimiter |
| [FYTJ session engine](https://github.com/FYTJ/lldb-mcp-server/blob/c9757dea2537c4a71af62c5c0485f65547d7c6c8/src/lldb_mcp_server/session/manager.py#L17) | Structured SB values, memory and watchpoint access | Continue is asynchronous; native evaluation remains synchronous and can wedge |
| [Rust debugger backend contract](https://github.com/danweinerdev/lldb-debug-mcp/blob/a032c18f2f52c9f2b5a3c43f22917cef9e6264dc/crates/debugger-core/src/backend.rs) | Separate transport, worker state and bounded presentation; persistent stop observation | No claim to implement its DAP backend; client wait cancellation does not cancel native work |
| Chisel runtime-inspection research | Reviewed expressions/probes can connect code state with UIKit geometry | Runtime captures execute code; use the separately available view-hierarchy skill, not an invented Xcode-equivalent graph |
| [AXe implementation](https://github.com/cameroncooke/AXe/blob/30f4bfa9bc81817906a60fadedbc913d7314b7e1/Package.swift#L1) | Delegate accessibility/HID reproduction to a qualified driver | This skill adds no HID driver; physical-device input and private Simulator APIs need separate qualification |

## Live qualification on September 12, 2026

Toolchain: selected Xcode-beta, Apple LLDB 2103.0.23.6, Apple Swift 6.4; arm64 macOS host and iOS 27.0 Simulator. These are environment-scoped observations, not universal support badges. The external validation report holds per-request evidence and final regression results.

- C: conditional source stop, symbol resolution/pending status, raw arguments/global values, child paging, source/instruction steps, watchpoint writer, memory/register/disassembly, expression result, errors, token invalidation and cleanup.
- Swift: an independent agent followed this skill to identify the third-debit sign defect and prove `po` mutation. A corrected module-linked build additionally passed a Swift conditional stop and typed getter evaluation. Before the build correction, expression compilation failed even though raw variables were readable.
- C++: a handled throw was stopped, its caller's error code inspected, then allowed to complete. A handled throw was not labeled an app crash.
- Expert lane: auto-continuing logpoint, stack-style core save and offline stack inspection. These do not establish full heap/core coverage or reverse execution.
- Sparrow: verified installed Simulator executable/PID, attach, bounded stacks/variables/registers/disassembly/modules, pause/resume, wait timeout without cancellation, detach alive. Its source folder was inaccessible; no Sparrow source-line root-cause diagnosis is claimed.
- UI integration: XCTest fallback built successfully but the new Simulator app could not launch due to execution-security-policy refusal. The guard refused to activate a non-running fixture. A complete tap → breakpoint → code-state → resumed UI chain remains **blocked/unproven** in this validation.
- Not qualified: physical device transport/input; Xcode-owned bridge; Swift async actor/task diagnosis; optimized/stripped-state recovery; arbitrary managed languages; combined native-view capture; hostile remote operation or independent interruption of a wedged native call.

## Boundaries that must survive adaptation

Do not promote documented raw recipes or an operation's presence in `capabilities` into a tested claim. Default client wait is intentionally short; cold debugger compiler/module work may exceed it. Reconcile and wait again within the investigation's budget without replaying the operation. Cold latency is not app execution time or proof of a hang.

The custom fixture link initially omitted Swift module discovery metadata. The build script now adds its module path at the Darwin link step. This is a fixture build correction, not a target-security bypass; future toolchains can change module tracking. Consult [Swift's module-tracking explanation](https://www.swift.org/blog/module-tracking-in-debug-info/) and the selected compiler/debugger rather than applying a link flag indiscriminately to a user's project.

The controller's opt-in fields are trusted-agent decision markers. They are not an adversarial security policy. Raw scripting can execute arbitrary host code. Do not expose this local interface to untrusted clients, and never use raw commands to evade an attachment or execution-security refusal.
