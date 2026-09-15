---
paths:
  - "**/*.swift"
  - "**/*.m"
  - "**/*.mm"
  - "**/*.h"
  - "**/*.xcodeproj/**"
  - "**/*.xcworkspace/**"
  - "**/Package.swift"
---

# Use lldb-code-state-debugger for wrong values, not print statements

When the question is **why is this value, branch or model state wrong**, load
`lldb-code-state-debugger` and use its `scripts/debugger.py` session.

Do not answer by adding `print` statements and re-running. That edits source
you were asked to diagnose, changes timing, and loses the state you were
investigating. Set a breakpoint instead.

Do not answer with a bare `po` either. `p`, `po`, breakpoint conditions,
descriptions and formatters can all **execute code in the target** and mutate
state; unwinding an expression is not a rollback. Read raw stored values first,
and treat any evaluation as a deliberate, authorised step.

Every inspection belongs to a stop token and a real thread and frame. Do not
reuse a value, frame index, pointer or child handle across a resume, step,
expression or external command — refresh status and reselect the frame.

`unavailable`, `optimized out` and `import failed` are not `nil`, `0` or a
bug in the app. Keep them in the evidence as-is.

A suspicious stack is not a root cause. Build the chain: user action → matched
breakpoint → input state → incorrect branch or write → downstream result.

Route elsewhere when the evidence needed is not code state: geometry and
constraints to `ios-view-hierarchy-debugger`, timing to
`ios-instruments-profiler`, retention to `ios-memory-debugger`.

<!-- installed by puppet-master · github.com/ksypinro/puppet-master · edit freely; ./uninstall.sh only removes files still carrying this line -->
