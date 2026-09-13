# Integration with coding agents

## Portable execution model

An agent needs file reading, a permitted local command runner, and access to the selected evidence. Read SKILL.md and route to the relevant reference. No proprietary model SDK or conversation state is required. The skill package contains instructions, not an executable memory service; current commands run on the Mac with the Apple toolchain.

A host with skill discovery can load the folder through its own supported mechanism. An agent without that mechanism can be told to read the entrypoint by absolute path and resolve the linked references relative to it. A cloud or chat-only LLM needs a local executor or a human-provided validated export. Installing this draft into a particular agent's global configuration is a separate deployment choice, not a prerequisite for reviewing or manually using it.

An example handoff prompt is: “Read the ios-memory-debugger SKILL.md at the supplied path. Investigate why this selected feature's objects remain after dismissal. Use the established target/session and supplied artifacts. Do not relaunch, change source or expose raw contents. Return observed owners, uncertainties and the next discriminating check.” Replace the feature with the user's actual scope; do not prefill imaginary app types.

## Responsibility boundaries

| Component | Owns | Must hand back |
|---|---|---|
| Simulator driver | Navigation and semantic/visual verification | Target, foreground process context, action/checkpoint IDs and fresh UI evidence |
| Memory skill | Snapshot questions, native readers and ownership reasoning | Capture/query evidence, accounting definitions, supported findings and gaps |
| LLDB skill | Stopped variables, writer breakpoints, watchpoints and invalid access | Stop epoch, actual frame/stack, expression side effects and final process state |
| Instruments skill | Allocation timelines, peaks, churn and performance | Validated trace exports, interval/units, quality and instrumentation conditions |
| Test engineer | Test selection and result-bundle validity | Executed test IDs, outcome and actual exported diagnostics |
| View hierarchy skill | Native UI geometry and view relationships | Capture epoch, view identity and supported UI properties |

Resolve the actual installed sibling skill paths; do not assume they are always adjacent. If a skill or driver is missing, report the evidence it would supply and use an authorized available equivalent where possible. Missing UI automation should not block offline analysis of a supplied graph.

The memory skill owns point-in-time ownership questions; the profiler owns interval allocation behavior. Existing toolkit descriptions may mention memory under profiling. This is complementary routing, not a reason to run both stacks for every query. This draft does not modify the existing five skills or their discovery settings.

## Shared session and capture barrier

Carry a shared record containing target/build identity, launch identity, controller owner, debugger owner, app running/stopped state, scenario step, artifact directory and last trustworthy observation. Use a single target lease in an implemented controller; without one, serialize operations explicitly through the agent's session record.

The normal sequence is running and observed → verified checkpoint → capture barrier → validated artifact and final state check → running and reobserved. During the barrier, no gestures or dependent debugger actions should be dispatched. A separate intentional debugger stop is not equivalent to a capture-owned pause and cannot be resumed without its owner's authority.

After relaunch, invalidate memory addresses and live handles, refresh process identity and observe the UI again. After debugger evaluation, refresh the stop token and preserve pre-evaluation evidence separately. An imported graph stays associated with its original epoch and never becomes live state through a handoff.

## A complete Sparrow investigation design

Select one reversible flow, such as opening and dismissing an item editor, and verify the actual app state. Confirm that the question concerns the main app; an App Intent investigation first resolves its execution host. Use discovered types from artifacts/source, not assumed Sparrow class names.

The driver establishes a warmed baseline and emits checkpoint C0. The memory lane captures S0 after verifying identity. The driver executes one open-close cycle and proves the editor disappeared; a declared completion condition establishes C1. The memory lane captures S1. Repeat within the same launch for the agreed cycle count, preserving any deviations.

The memory agent compares type/byte trends, selects unexpected post-cleanup candidates, queries layouts and root paths, and recovers available allocation stacks. If the graph identifies a long-lived owner but not the writer, the next experiment hands that exact question to LLDB. If counts normalize but footprint remains elevated, it routes to VM/allocator analysis rather than declaring cleanup failed. If an interval spike is the symptom, it asks the profiler for a separate aligned trace.

The final result combines scenario verification, memory facts, explanation, competing hypotheses and limitations. Only an authorized fix triggers source edits and a repeat. This is an end-to-end design, not a Sparrow live test already performed.

## Optional CLI and MCP backend design

For repeated unattended use, implement the logical operations in the evidence contract as one deterministic local engine, then expose them over CLI JSON or MCP. Avoid separate business logic per agent. Capability discovery, artifact validation, parsers, evidence storage and bounded queries belong in the engine; hypothesis selection and explanation belong in the agent.

Use operation-specific inputs rather than arbitrary shell text. Bind every object query to an immutable snapshot hash. Stream output locally, preserve stderr, enforce limits, and return recognized/partial/unrecognized parsing separately from process execution. A future whole-graph index must record root/edge completeness before advertising dominators or exact retained bytes.

The protocol should support cancellation and a capture lease, but neither implies the target was restored. Return verified cleanup disposition or unknown. An MCP connection must not grant more process or content access than the local executor already permits.

Build this in stages: offline graph inspection with error fixtures; controlled Simulator capture and driver coordination; signed device test diagnostics; then narrowly justified lifecycle probes or deeper extraction. This package does not implement those service stages.

## Acceptance tests for the design and future implementation

First test decisions using real command outputs or deliberately invalid inputs. A failed capture with a pre-existing file must not become a fresh success. Empty/error text must not become zero leaks. Recognized totals with unknown detail grammar must remain partial. A valid footprint result with stderr warnings must retain them.

Test identity and scope: same address after restart, address reuse within one launch, an App Intent in an unidentified process, active work mistaken for a leak, unrelated debugger ownership, and ten fresh launches used to answer an accumulation question. Each must trigger the right narrower claim or next experiment.

Test information limits: no allocation history, mismatched symbols, conservative-only cycles, unknown Swift fields, and exact retained size requested from a projected tree. The correct outcome may be a useful partial answer, not an exception or fabricated completeness.

Then qualify live fixtures separately: known clean and cyclic Objective-C graphs; reachable abandoned cache; normal lifecycle cleanup; Swift weak/unowned and closures; async tasks; large buffers; false pointers; address reuse; and a graph with shared descendants. Measure pause, disk and instrumentation overhead. Compare selected object queries against Xcode on the same artifact/build when possible.

Finally test Simulator driver-to-capture coordination and a real signed device result bundle. Record qualification by toolchain/runtime/operation. A passing Markdown/frontmatter validator or an offline reasoning exercise does not certify live capture or universal application support.
