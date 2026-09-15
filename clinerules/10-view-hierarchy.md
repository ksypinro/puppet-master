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

# Use ios-view-hierarchy-debugger, not raw LLDB, for UI appearance

When the question is **why the UI looks wrong** — misplaced, clipped,
overlapping, wrong colour or font, untappable, stale — load
`ios-view-hierarchy-debugger` and use its `scripts/ui_evidence.py`.

Do not answer this class of question with raw `po`, `p` or `expr` in LLDB.

`po someView` returns a one-line description. The question needs the frame in
the right coordinate space, the screen-space rectangle, active constraints,
hugging and compression priorities, layer state, effective alpha, ancestor
clipping and the owning controller. The skill captures all of that in one
structured pass; `po` gives you a string you then guess from.

Three specific traps raw inspection walks into:

- **An accessibility node is not a native view.** Reading the AX tree and
  calling it the view hierarchy is wrong — an AX child need not be a subview.
- **`po` on a SwiftUI hosting view tells you nothing about the SwiftUI tree.**
  You get the UIKit shadow. The skill documents exactly which SwiftUI
  information is and is not recoverable.
- **A property that cannot be read is `unknown`, never `0` or `false`.**
  `po` on an unavailable value returns something; that something is not
  evidence.

If a debugger session is already attached and owned, reuse it — the skill's
LLDB capture runs through the existing owner rather than attaching a second
debugger.

Escalate to `lldb-code-state-debugger` only when the geometry is correct and
the question has become *which code wrote this value*.

<!-- installed by puppet-master · github.com/ksypinro/puppet-master · edit freely; ./uninstall.sh only removes files still carrying this line -->
