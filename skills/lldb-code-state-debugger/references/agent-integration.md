# Portable agent integration

Read this when using the skill outside its original agent environment or adapting its CLI to another tool transport.

## Minimum contract

The agent needs permission to read the skill files, invoke a local shell/process tool, read JSON output, and retain session identifiers between calls. The machine—not the model—needs a compatible debugger and access to the intended target. For iOS, use the selected Xcode's Apple LLDB; Swift debugging depends on a compatible compiler/debugger pair and Apple target support. An arbitrary upstream LLDB is not automatically interchangeable. [Swift debugger requirements](https://www.swift.org/documentation/lldb/)

Copy the complete skill folder, including `scripts/` and `references/`. Do not copy only `SKILL.md`. Tell an agent that lacks skill discovery:

> Read `/absolute/path/to/lldb-code-state-debugger/SKILL.md` completely, then use its supported workflow to investigate the specified app and issue. Resolve relative references and scripts against that folder. Follow your existing execution and approval permissions.

That is a file-loading instruction, not a vendor-specific slash command. No particular model, IDE, MCP server, or cloud account is required. The skill cannot give an agent shell access, debugger entitlement, device trust, source code, symbols, or permission to change app state.

## Invoke the implementation that is actually present

Use the entry point and exact arguments in the installed `SKILL.md`; inspect its CLI help when an option is unclear. Do not translate the raw LLDB examples in [advanced-debugging.md](advanced-debugging.md) into invented helper commands. Unsupported operations remain unsupported unless an explicitly chosen alternative supplies them.

The bundled architecture uses a Python-standard-library JSON client and a persistent worker inside the selected LLDB's Python runtime. LLDB's SB objects provide structured process, frame and value access; terminal text is not the primary value schema. The surrounding shell call may finish while the worker remains alive. Preserve the worker/session identity; repeatedly starting LLDB loses breakpoints and state. [LLDB embedded Python and scripting](https://lldb.llvm.org/use/python-reference.html), [script-driven debugging](https://lldb.llvm.org/use/tutorials/script-driven-debugging.html)

Consume the JSON envelope, not a guessed success message. Preserve explicit errors, availability, truncation and limits. If transport output is truncated or not valid JSON, treat the request result as unknown; query session state before retrying any state-changing action. A client timeout is not proof that the worker stopped executing the request.

## One controller, one evidence epoch

Assign one controller to execution changes in a session. Parallel agents can inspect source or previously saved snapshots; they must not race `continue`, stepping, interrupt, frame selection, or breakpoint edits. Do not attach a second debugger to a process already controlled by Xcode or another LLDB.

Use returned stop tokens exactly as specified by the helper. Reacquire state after any resume, step, interrupt, expression, unexpected stop, exit, or external-console command; do not manufacture the next token. A token proves freshness only according to this helper's documented checks, not a transaction over arbitrary runtime activity. The underlying stop IDs distinguish ordinary stops from expression-related stops when requested. [SBProcess stop-ID semantics](https://lldb.llvm.org/python_api/lldb.SBProcess.html)

For each finding, retain the app/build identity, session and stop identity, actual thread/frame, resolved source location, selected variable path, value/error, and relevant limits. These are immutable observations. Addresses, frame indices and debugger value handles are not durable object identities across resumes or launches. Do not silently merge values from different stops into one apparent snapshot. [SBFrame variable access](https://lldb.llvm.org/python_api/lldb.SBFrame.html)

## Coordinate with a UI driver

A code-state debugger is not a simulator input driver or a native view-tree exporter. If reproduction needs taps or swipes, use an available authorized driver; for geometry, styling or hierarchy, use a separately available view-evidence workflow. Neither integration is a universal prerequisite for a source-only investigation.

Coordinate the two tools as follows:

1. While stopped, resolve and verify a narrowly relevant breakpoint; record the expected action and stop.
2. Resume, confirm running state, then submit one driver action.
3. Await the expected stop or action completion with a bounded wait. A stop at an unrelated breakpoint is a different outcome.
4. At the stop, collect source/variable evidence. Resolve or cancel a pending driver request before submitting another action.
5. Resume only when continuing the authorized experiment. A paused main thread cannot process the next tap.

Screenshots and accessibility captures taken before or after the stop are nearby observations, not automatically synchronized evidence. Record their times and intervening actions. SwiftUI's declaration tree and value semantics also do not map one-to-one to UIKit objects; a source-level stop cannot promise Xcode View Debugger parity.

## Optional MCP adapter

An MCP adapter may expose the same implemented CLI operations to an agent without direct shell access. It should pass validated argument arrays to the helper, return its JSON unchanged, preserve stop/session tokens, bound input/output, serialize state-changing calls, and apply the same target/path permissions. Do not use shell interpolation or claim a command allowlist makes arbitrary LLDB expressions safe. The adapter is transport, not a new debugger engine or a privilege grant.

Prefer named, bounded operations already implemented by the helper. If a separate raw-command tool is deliberately offered, label it distinctly: `expression`, `script`, breakpoint callbacks and imported helpers can execute target or host code. A remote adapter should not expose an unauthenticated listener merely to make a local workflow portable.

Xcode's native agent bridge is an optional alternative when Xcode owns the debug session. Discover the installed tools and permission model rather than assuming tool names from release notes. It is not required for this skill's local worker. [Apple external-agent access](https://developer.apple.com/documentation/xcode/giving-external-agents-access-to-xcode)

## Report boundaries and handoff

- **Source only:** reason about code, but do not label inferred values as runtime observations.
- **Debuggable runtime with symbols:** collect supported stops and typed values, retaining failures instead of turning unavailable values into `nil`.
- **Optimized or stripped build:** source/locals may be partial; machine-level evidence can remain useful.
- **Physical device:** pairing, OS support, signing and debugger permission are separate from Simulator success.
- **Other languages/frameworks:** the workflow is reusable, but type reconstruction, evaluation and runtime plugins are language-dependent; “any agent” does not mean “every value in any app.”

Before ending, use the documented cleanup operation and explicit target disposition. Distinguish detaching from killing and leaving a process paused from resuming it. Clean only task-owned breakpoints/resources. Record whether the process is running, stopped, exited, or unknown and whether the session remains available. A disconnected client is not verified cleanup.
