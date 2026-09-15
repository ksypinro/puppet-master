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

# Use ios-instruments-profiler for performance, not ad-hoc timing

When the question is **how long, how much CPU, why the jank**, load
`ios-instruments-profiler`.

Do not measure with `Date()`, `CFAbsoluteTimeGetCurrent()` or `print`
timestamps sprinkled through the code. Do not quote Xcode's live gauges as a
measurement. Both change what they measure and neither is reproducible.

Never report summed Time Profiler or App Launch CPU samples as elapsed launch
time. Samples say where work happened; they are not a duration.

Keep the two lanes distinct. XCTest metrics answer *did this scenario regress*;
Instruments answers *where the time, allocations, I/O or energy went*. A trace
is for diagnosis, a metric is for a gate.

Simulator numbers are for trends and pipeline development only. Any claim about
real CPU, GPU, memory pressure, thermal state, energy or Neural Engine needs a
connected physical device — say so rather than implying the Simulator stands in.

Measurements taken while stack logging, leak scanning, a debugger stop or a
sanitizer is active are not baselines.

Route retention and object-graph questions to `ios-memory-debugger`; it answers
"what is holding this" at a checkpoint, which a trace does not.

<!-- installed by puppet-master · github.com/ksypinro/puppet-master · edit freely; ./uninstall.sh only removes files still carrying this line -->
