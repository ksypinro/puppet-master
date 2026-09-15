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

# Use ios-memory-debugger for retention, not guesswork

When the question is **why is this object still alive, what retains it, or
where did the bytes go**, load `ios-memory-debugger`.

Do not answer by reading Xcode's memory gauge, or by `po`-ing objects and
reasoning about what probably holds them. Capture a graph and query it.

Capture with `scripts/memory_capture.py`, not a hand-written `leaks` line.
`--fullStackHistory` is **fatal** without full `MallocStackLogging` — exit 255
and no artifact at all — and a default-launched app has none. The script probes
the mode and picks flags accordingly.

For "how much would freeing this release", use `memgraph_query.py retained`.
It reads Apple's dominator tree, which gives the total for a node and everything
it dominates. Do not sum a `referenceTree` subtree and call it retained size —
that projection shows roughly half the nodes.

Say **"N bytes dominated by this node in this capture"**, never "freeing this
frees N bytes". The scanner is conservative: no detected leak is a narrower
claim than no memory bug, and reachable memory can still be abandoned.

Keep the accounting domains apart. Heap payload, resident and dirty pages,
virtual size, physical footprint and scanner-leaked bytes measure different
things and must never be summed.

A `.memgraph` can contain credentials, tokens and customer data. `--noContent`
is minimisation, not anonymisation — field names, offsets, allocation stacks
and process identity survive it. Keep artifacts local unless told otherwise.

Route interval and churn questions to `ios-instruments-profiler`; a graph is one
instant.

<!-- installed by puppet-master · github.com/ksypinro/puppet-master · edit freely; ./uninstall.sh only removes files still carrying this line -->
