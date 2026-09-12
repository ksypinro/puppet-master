# Advanced LLDB recipes and capability boundaries

These are **raw LLDB commands**, not claims about the bundled helper's implemented API. Use a recipe only through an explicitly supported command route or a separately authorized LLDB console. Do not start a competing debugger while the helper or Xcode owns the process. All sample filenames, lines, IDs and addresses are illustrative: replace them with verified current evidence.

## Discover before executing

Inspect the selected toolchain without attaching to an app:

```sh
xcrun --find lldb
xcrun lldb --version
xcrun lldb --no-lldbinit --batch -o 'help breakpoint set' -o 'help expression' -o 'help language swift task'
```

Availability and option spelling vary by Xcode/LLDB release. Start without user initialization for reproducibility, then load only reviewed helpers needed by the task. Python imports, callbacks and formatters execute host code; some formatting also evaluates target code. The LLDB command interpreter provides command-specific `help` and `apropos` discovery. [LLDB Python integration](https://lldb.llvm.org/use/python-reference.html), [command structure](https://lldb.llvm.org/use/tutorial.html#command-structure)

## Conditional stops, logpoints and exceptions

Resolve a current source location before setting a condition:

```text
breakpoint set --file NoteStore.swift --line 120 --condition 'noteID == expectedID'
breakpoint list --verbose
breakpoint modify --ignore-count 4 1
breakpoint modify --one-shot true 1
```

The numeric ID above is an example. Inspect the returned logical breakpoint and every relevant resolved location: zero locations means pending; one source line may resolve to several closures or inline instances. A condition is evaluated in the stop's context and may call code. Prefer cheap stored-state comparisons over getters or description calls. A SwiftUI `Button` construction breakpoint does not prove its action fired; resolve a line inside the action body. [LLDB breakpoint semantics](https://lldb.llvm.org/use/tutorial.html#setting-breakpoints), [Apple breakpoint-placement demonstration](https://developer.apple.com/videos/play/wwdc2024/10198/?time=447)

For bounded repeated observations, a task-owned auto-continuing breakpoint can act as a logpoint:

```text
breakpoint set --file NoteStore.swift --line 120 --command 'frame variable --raw-output --dynamic-type no-run-target --depth 1 noteID state' --command 'thread backtrace --count 8' --auto-continue true
```

Capture the console output through the chosen transport and limit run duration/hit volume. This is a real debugger stop with overhead, not a performance-neutral probe. Do not install actions on a user's existing breakpoint: replacing actions can destroy its behavior. [Apple high-frequency breakpoint discussion](https://developer.apple.com/videos/play/wwdc2024/10198/?time=965)

Discover exception options with `help breakpoint set`:

```text
breakpoint set --language-exception swift
breakpoint set --language-exception objc
breakpoint set --language-exception c++ --on-throw true --on-catch false
breakpoint set --name UIViewAlertForUnsatisfiableConstraints
```

Where the installed debugger supports it, `--exception-typename 'MyApp.StorageError'` narrows a Swift error breakpoint. Expected handled errors can hit; classify using the source and subsequent handling. The layout diagnostic symbol is for unsatisfiable constraints, not all visual defects. Runtime-issue breakpoints require the corresponding checker/instrumentation. [Apple breakpoint guidance](https://developer.apple.com/documentation/xcode/setting-breakpoints-to-pause-your-running-app)

## Find a writer; avoid fabricating logical watchpoints

```text
help watchpoint set variable
help watchpoint set expression
watchpoint set variable --watch write trackedCount
watchpoint list --verbose
```

For an address watchpoint, supply a verified live address and byte size using the discovered syntax. Confirm actual target support and the returned watchpoint status; hardware slots are limited. Choose `write` when same-value stores matter, rather than assuming the default `modify` semantics. A computed Swift property, property-wrapper facade or copy-on-write collection has no universal fixed storage address. Revalidate after replacement, scope exit or relaunch. A setter breakpoint is often a better logical-state probe. [LLDB watchpoint commands](https://lldb.llvm.org/use/map.html#watchpoint-commands)

## Expressions and Swift health

First inspect raw stored state at a verified stop and frame. Use a targeted expression only when needed and authorized:

```text
frame variable --raw-output --dynamic-type no-run-target --depth 2 self
expression --language swift --timeout 1000000 --all-threads false --ignore-breakpoints true --unwind-on-error true -- noteID == expectedID
```

Current help specifies microseconds for that expression timeout. Disabling all-thread retry avoids one escalation path; it does not guarantee a safe evaluation. Unwinding an error is not rollback of heap, file or network changes. Compiler work or debugger failure also needs an outer timeout/recovery policy. Refresh helper state after any console evaluation. [SBExpressionOptions](https://lldb.llvm.org/python_api/lldb.SBExpressionOptions.html)

Modern `p`/`po` use `dwim-print`; a simple path can avoid the expression compiler, but complex input and object descriptions can still execute target code. Do not treat `po` as categorically read-only. `swift-healthcheck`, when available, diagnoses Swift expression-environment failures; missing modules, SDK paths or bridging-header context are debugger-environment evidence, not proof of an app defect. Variables may be readable even when expression compilation fails. [Swift 5.9 debugging changes](https://www.swift.org/blog/whats-new-swift-debugging-5.9/), [Apple Swift debugger diagnosis](https://developer.apple.com/videos/play/wwdc2022/110370/)

## Async tasks and suspected hangs

Discover the installed `language swift task` subtree. Where supported:

```text
language swift task info
language swift task list
language swift task tree --max-frames 8
thread backtrace --count 25 all
```

Task backtrace/selection commands take an actual discovered task address; inspect their help before use. Tree/list coverage is **discovered tasks**, not necessarily all tasks: disconnected unstructured tasks can be absent. Bound threads as well as frames and total output. Async work can move between OS threads, so correlate task/request identity and values around `await`, not only a thread index. [Apple Swift concurrency debugging improvements](https://developer.apple.com/videos/play/wwdc2025/245/), [Xcode release notes](https://developer.apple.com/documentation/xcode-release-notes/xcode-27-release-notes)

A waiting main run loop or `mach_msg` frame can be normal. Establish an expected progress deadline, inspect all relevant threads/tasks and awaited resource ownership, then compare separated observations or a time profile. A single stack does not prove deadlock or a past race. Pausing the main thread also prevents a UI driver from completing normal app interactions.

## Missing symbols, source mismatch and optimization

```text
image list
image lookup --verbose --address $pc
image lookup --file NoteStore.swift --line 120
target symbols add /absolute/artifacts/MyApp.app.dSYM
settings list target.source-map
settings set target.source-map /BUILDROOT /absolute/current-checkout
```

The last two mutating commands are diagnostic examples, not defaults. Confirm the binary/dSYM UUID for the relevant architecture using `xcrun dwarfdump --uuid` on each artifact. Frameworks and extensions may need their own symbols. Source mapping repairs path prefixes, not incorrect source revisions. `ENABLE_DEBUG_DYLIB` may place app implementation in a separate debug dylib; inspect actual loaded modules rather than filtering only the launcher. [Apple symbol matching](https://developer.apple.com/documentation/xcode/locating-a-missing-debug-symbol-file), [LLDB source troubleshooting](https://lldb.llvm.org/use/troubleshooting.html), [Apple build settings](https://developer.apple.com/documentation/xcode/build-settings-reference)

Optimization can remove locals, inline functions and change source stepping. Report unavailable values with their actual errors; do not convert them into `nil` or claim a line never ran merely because its breakpoint did not resolve. A diagnostic `-Onone`/`-O0` build can help but can hide a release-only issue: preserve the original baseline and label the rebuild as another experiment. [LLVM source-level debugging](https://llvm.org/docs/SourceLevelDebugging.html)

## Simulator, physical device and Xcode-owned sessions

**Simulator:** the app is a host process, but its PID must be tied to the intended Simulator and bundle. Use the skill's verified-target attach workflow. Do not choose the first process with a familiar name or run an iOS binary as a generic macOS executable. A successful Simulator attach does not validate physical-device transport or signing.

**Physical device:** discover `xcrun devicectl help device process launch` and, inside the selected Apple LLDB, `help device`. The supported native path uses LLDB's device selection and attachment, not a device PID supplied to host `process attach`:

```text
device list
device select VERIFIED_DEVICE_ID
device process list
device process attach --pid VERIFIED_DEVICE_PID
```

These are templates, not executable identifiers. For an already-running app, do not relaunch it. For an explicitly requested startup experiment, `devicectl device process launch` can use `--start-stopped` and a new absolute `--json-output` artifact; configure stops before continuing. Do not add `--terminate-existing` or `--continue` by habit. `devicectl --console` is app I/O, not LLDB; its signal forwarding means a timeout/interrupt may affect the app. The selected tool's help is authoritative for its exact version. [Apple command-line tool reference](https://developer.apple.com/documentation/xcode/xcode-command-line-tool-reference)

Device trust/pairing, Developer Mode, supported OS/Xcode versions and debugger-authorized signing are prerequisites. This skill cannot grant `get-task-allow`, bypass a denied attachment, or inspect every App Store app just because symbols are available. [Apple Developer Mode](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device), [Apple entitlement troubleshooting](https://developer.apple.com/library/archive/technotes/tn2415/_index.html)

**Xcode owns the debugger:** use its LLDB console or an installed, permissioned native agent bridge. Do not second-attach with the worker. `xcdebug` starts an Xcode debugging session; it is not itself a breakpoint/variable API. Its `--pid` selects an **Xcode process**, not the app. Scheme mode supplies the iOS destination; process mode is for a host command. Discover native MCP tools on that installation; release notes do not establish an exact available schema. [Apple CLI reference](https://developer.apple.com/documentation/xcode/xcode-command-line-tool-reference), [external-agent access](https://developer.apple.com/documentation/xcode/giving-external-agents-access-to-xcode)

## Core files, memory and performance are different evidence

- **Memory reads:** use verified live addresses and bounded counts. Bytes do not establish Swift object lifetime, ownership or semantic type. Memory writes are a separate state-changing experiment, not diagnosis by default. [LLDB memory commands](https://lldb.llvm.org/use/map.html#memory-commands)
- **Core files:** discover `help process save-core` and `help target create`. Saving/loading support varies by process plugin and platform; a saved core is not a guaranteed whole-device or complete heap capture. A core cannot resume or execute arbitrary expressions in its dead target. Matching images/symbols remain necessary. [LLDB core loading](https://lldb.llvm.org/man/lldb.html), [SBProcess core API](https://lldb.llvm.org/python_api/lldb.SBProcess.html)
- **Memory graph:** raw pointers and stacks are not Xcode's ownership graph, leak diagnosis or a UIKit/SwiftUI view capture. Use the corresponding capture tool and label its coverage.
- **Sanitizers:** require a supported, appropriately instrumented build/run configuration. Attaching LLDB to an existing binary does not retroactively enable Address Sanitizer or Thread Sanitizer. [Apple diagnosing memory/thread bugs](https://developer.apple.com/documentation/xcode/diagnosing-memory-thread-and-crash-issues-early)
- **Profiling:** use Instruments/xctrace or appropriate runtime metrics for launch, hangs, hitches and allocations. Breakpoints, expression execution and paused intervals perturb timing; collect a separate minimally perturbed performance run. A stack snapshot is explanatory context, not a launch-time measurement. [Apple Instruments](https://developer.apple.com/documentation/xcode/improving-your-app-s-performance)

Record the boundary honestly: captured stored value, evaluated result, sampled stack, UI evidence and inferred cause are distinct evidence classes.
