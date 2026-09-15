---
paths:
  - "**/*.swift"
  - "**/*.m"
  - "**/*.mm"
  - "**/*.h"
  - "**/*.xcodeproj/**"
  - "**/*.xcworkspace/**"
  - "**/Package.swift"
  - "**/*.xctestplan"
---

# iOS toolkit routing

Seven skills cover iOS work. Route on the symptom, then read that skill's
`SKILL.md` before running anything.

| Symptom | Skill |
|---|---|
| Build, sign, archive, export, install, launch | `ios-build-engineer` |
| Reach a screen, tap, type, swipe, verify a flow | `ios-simulator-driver` |
| A view is misplaced, clipped, mis-styled, untappable | `ios-view-hierarchy-debugger` |
| A value, branch or model state is wrong | `lldb-code-state-debugger` |
| Slow launch, jank, hitches, CPU, I/O, power | `ios-instruments-profiler` |
| Run a suite, read a result bundle, is this failure real | `ios-test-engineer` |
| Why is this object alive, what retains it, where did the bytes go | `ios-memory-debugger` |

Each skill ships scripts. Use them instead of hand-composing the underlying
`xcrun` command — they carry the failure modes the raw tools do not report.

A dispatched action is not a completed action. A command exiting 0 is not a
correct result. Report what was observed separately from what it implies, and
say `unknown` rather than `0` for anything not captured.

<!-- installed by puppet-master · github.com/ksypinro/puppet-master · edit freely; ./uninstall.sh only removes files still carrying this line -->
