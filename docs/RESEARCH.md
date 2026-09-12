# Research

Each skill in this repository is the distillation of a deep-research pass over the actual tooling: what the Apple toolchain exposes from the command line, what the open-source ecosystem has already solved, and — most usefully — where the published claims do not survive contact with a real device.

**The reports are attached to the [v1.0.0 release](https://github.com/ksypinro/puppet-master/releases/tag/v1.0.0)**, not committed to the repository. They are ~90 MB of `.docx` and would otherwise dominate the clone size of a repository whose product is under a megabyte of Markdown and Python — so they are downloadable without being in everyone's `git clone`.

The findings that matter are already in the skills: every `references/` file is the operational residue of one of these passes, and `ios-view-hierarchy-debugger/references/research-and-limits.md` states its capability limits directly. Read the reports when you want the reasoning behind a limit, not the limit itself.

## What was researched

| Report | Became |
|---|---|
| LLM-Driven iOS Simulator and Device Control | `ios-simulator-driver` |
| iOS View Hierarchy and UI State — Deep Analysis | `ios-view-hierarchy-debugger` |
| Xcode View Debugger and LLM Method Parity | `ios-view-hierarchy-debugger` capability limits |
| Xcode LLDB Debugging and LLM Root-Cause Analysis | `lldb-code-state-debugger` |
| iOS Instruments CLI and LLM Performance Research | `ios-instruments-profiler` |
| iOS Developer CLI — Deep Analysis | the shared toolchain boundaries in every skill |

A second pass audited the existing ecosystem rather than the toolchain — XcodeBuildMCP, LLVM's LLDB-DAP and MCP work, CodeLLDB, three independent LLDB MCP servers, Chisel, and AXe — to establish what was already solved, what was claimed but unverified, and what had to be built. That audit is why `ios-simulator-driver` selects among existing drivers instead of shipping another one.

## Why the limits sections exist

The consistent finding across every pass was that the gap between *documented* and *actual* capability is wide, and it is where agent tooling breaks:

- An installed Instruments template is not proof it records or exports useful data on a given Simulator, device, OS, or workload.
- The Xcode View Debugger's SwiftUI fidelity is not reachable through public API, and tools that imply otherwise are reporting the UIKit shadow of a SwiftUI tree.
- Accessibility trees and native view hierarchies disagree in ways that matter for exactly the bugs people ask about.
- A great deal of published LLDB automation breaks on Swift targets because of Python binding mismatches between system Python and LLDB's embedded interpreter.

Each of those is now a documented limit in the relevant skill rather than a surprise at run time. That is the main thing the research bought.

## Downloading the reports

All fifteen documents are attached to the [v1.0.0 release](https://github.com/ksypinro/puppet-master/releases/tag/v1.0.0). The raw evidence, fixtures, and trace artifacts behind them stay in the author's local workspace — if a specific negative result would save you a rediscovery, open an issue and ask.
