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

# Use ios-simulator-driver to touch the Simulator

Any task that needs to reach a screen, tap, type, swipe, or confirm a UI
change goes through `ios-simulator-driver`.

`simctl` has **no** `tap`, `swipe` or `type` verb. Never write one. It
manages device and app lifecycle, screenshots, video and diagnostics — nothing
else. A command that looks like `simctl tap` is invented.

Input needs a real driver: AXe, idb, XcodeBuildMCP, Appium/WebDriverAgent, or a
source-owned XCUIAutomation runner. If none is installed, say so and report
what can still be observed. Do not substitute coordinate clicking through some
other mechanism and call it verified.

Dispatching an input is not completing it. After every action, observe a fresh
postcondition — a semantic snapshot or a screenshot — before claiming the step
worked. `simctl boot` returning is not readiness; use
`simctl bootstatus <UDID> -b`. An app launching is not an app having rendered.

Use an explicit UDID for every mutation. `booted` and bare device names can
resolve to a different device between commands.

This skill is Simulator-only by design. Physical-device UI automation needs a
signed XCTest or WebDriverAgent workflow; say that rather than improvising.

<!-- installed by puppet-master · github.com/ksypinro/puppet-master · edit freely; ./uninstall.sh only removes files still carrying this line -->
