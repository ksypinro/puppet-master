# CLI capture and query workflows

## Read this before commands

These are real Apple command recipes, not new commands provided by this skill. Resolve placeholders from current evidence and inspect installed help before a version-sensitive operation. Use argument arrays in a controller, never interpolate an app label, address or path into an arbitrary shell program. Validate addresses as hexadecimal values selected from the current artifact. Exact class matches require regex escaping, since `heap -addresses` accepts patterns.

For every operation keep stdout and stderr in separate owned files, exit status, start/end times and the complete argument array. Drain both streams concurrently; a service must enforce time, output and disk limits without deadlocking. A diagnostic exit code and a finding are separate facts. Stop only tool children owned by the operation, not the target app or every process with the tool's name.

The following commands are inventory, not permission-changing operations:

```sh
xcode-select -p
xcodebuild -version
xcrun simctl list devices available -j
xcrun simctl help launch
leaks --help
heap --help
malloc_history --help
vmmap --help
footprint --help
```

Help grammar and exit conventions can vary. Preserve the executable path and help/man provenance. For stack logging, inspect the selected runtime documentation; the report's malloc manual came from the selected Xcode macOS SDK, not proof for every Simulator runtime.

## A Bind and capture a local target

Obtain the app container with `xcrun simctl get_app_container <UDID> <BUNDLE_ID> app` where applicable. Correlate it with the already-established session's launch evidence and host process inventory. Inspect candidate PID start time, full command and executable identity; a first `pgrep` match is not resolution. Record enough evidence to distinguish another Simulator, an extension, a stale PID and a fresh launch. Do not launch merely to discover an already-running PID.

Before capture ensure the output path is absent and its parent is writable, with a configured disk/pause budget. Coordinate with any debugger owner.

Prefer the bundled script, which probes the target's logging mode and picks flags accordingly:

```sh
python3 scripts/memory_capture.py probe   --pid <VERIFIED_HOST_PID>
python3 scripts/memory_capture.py capture --pid <VERIFIED_HOST_PID> --out <NEW_RUN_DIR>
```

By hand, the baseline capture is:

```sh
leaks --noContent --outputGraph=<NEW_ABSOLUTE_GRAPH> <VERIFIED_HOST_PID>
```

**Add `--fullStackHistory` only after confirming the target ran with *full* `MallocStackLogging`.** It is not a best-effort flag. Measured on a real Simulator app:

| target's logging mode | `leaks --fullStackHistory --outputGraph=…` |
|---|---|
| none (every default launch) | `[fatal] MallocStackLogging was not enabled` — exit 255, **no artifact** |
| `lite` | `[fatal] … ran with MallocStackLogging lite mode` — exit 255, **no artifact** |
| `full` | succeeds |

The failure is fatal and writes nothing, so an unconditional `--fullStackHistory` loses the capture entirely on any app you did not deliberately relaunch. `lite` is rejected by name — see §B.

Two further behaviours worth knowing by hand:

- `--outputGraph=<path>` **appends `.memgraph`** when the path lacks it, so the file written may not be the path you named. Check the real path, not the requested one.
- A capture produces `MEMGRAPH` magic with `--fullStackHistory` and a bare `bplist00` binary plist without it. Both are valid graphs. A validator demanding the documented `MEMGRAPH` signature rejects every ordinary capture.

`--noContent` minimizes descriptions but is not anonymization: `--debug=contents` on a `--noContent` capture still returns field names, offsets, bitfields, allocation stacks with symbols, library paths and process identity. Content-heavy reader modes need separate review even for a minimized graph.

The report observed capture exit 0 with leaks present, followed by offline analysis exit 1 for detected leaks. Interpret the particular mode's documented status. Errors must not produce zero leak totals. After completion verify nonempty artifact, timestamps and provenance, hash, reader success and embedded process/build information where available. Report missing embedded identity as unknown and retain independently collected identity evidence. Reject unexplained identity conflicts. Verify final process state; a timeout can leave state uncertain.

## B Request history for a new reproduction

If relaunch is authorized and current evidence has been preserved, the Simulator environment bridge can request logging:

```sh
SIMCTL_CHILD_MallocStackLogging=lite xcrun simctl launch <UDID> <BUNDLE_ID>
```

`lite` records stacks for current allocations without history. It is the cheaper choice, but note the consequence: **a `lite` launch cannot be captured with `--fullStackHistory`** — `leaks` rejects it by name. If you intend to use that flag, launch with `full` instead:

```sh
SIMCTL_CHILD_MallocStackLogging=full xcrun simctl launch <UDID> <BUNDLE_ID>
```

The inspected Xcode 27 SDK manual defines `1` as lite, so do not silently use old recipes expecting full history from `1`. Environment-variable presence does not prove useful stacks; test a known allocation from that launch, or run `memory_capture.py probe`, which reports the effective mode.

`MallocStackLoggingNoCompact` and full history can be expensive. A logging directory must exist and be writable inside the target's effective environment. Do not assume a controller's host path is valid in an app sandbox. Changing diagnostics/relaunch requires authority; it may destroy the irreproducible state being investigated. Record logging overhead and keep these runs separate from production footprint/timing benchmarks.

## C Summarize a graph

Start with these readers; use a new JSON output path:

```sh
vmmap -summary <GRAPH>
footprint -f bytes -j <NEW_FOOTPRINT_JSON> <GRAPH>
heap -sortBySize <GRAPH>
leaks --fullStacks <GRAPH>
```

Use bytes internally and preserve original units. Heap payload, dirty/resident regions, virtual size, physical footprint and scanner leaked bytes overlap or measure different things; never sum them into one total. A valid footprint JSON with exit 0 can coexist with stderr permission warnings; report partial operational coverage even if its JSON warning array is empty.

Require a recognized leak summary before reading a zero as a finding — and note that `leaks` only encodes the finding in its exit status for some modes. Measured on one graph containing four leaks:

| invocation | exit with 4 leaks | exit with 0 leaks |
|---|---|---|
| `leaks` | 1 | 0 |
| `leaks --fullStacks` | 1 | 0 |
| `leaks --groupByType` | 1 | 0 |
| `leaks --referenceTree` | **0** | 0 |
| `leaks --autoreleasePools` | **0** | 0 |
| `leaks --debug=…` | **0** | 0 |
| `heap`, `vmmap` | 0 | 0 |

Inferring "exit 0 means clean" is correct for three modes and wrong for three others on identical evidence. `scripts/memgraph_query.py` routes every `leaks` call through a helper that reports operation and finding separately and answers `unknown` rather than guessing.

If the summary is understood but node grammar is not, expose summary facts and mark node detail partial/unsupported. Without a qualified parser, inspect a bounded raw section, attach its line offsets and state the limits. Do not manufacture parser confidence.

## D Inspect an allocation and its references

Prefer the bundled script, which guards the class-pattern trap described below:

```sh
python3 scripts/memgraph_query.py classes <GRAPH> --match <TEXT>
python3 scripts/memgraph_query.py objects <GRAPH> <EXACT_CLASS>
python3 scripts/memgraph_query.py layout  <GRAPH> <ADDRESS>
python3 scripts/memgraph_query.py paths   <GRAPH> <ADDRESS>
```

**`heap -addresses` matches the WHOLE class name, not a substring.** Verified against a class that exists, agreeing with `re.fullmatch` on 8 of 8 patterns:

| pattern | matches |
|---|---|
| `MemoryResearchNode` | 2 |
| `MemoryResearch` (prefix) | **0**, exit 0 |
| `Node` (suffix) | **0**, exit 0 |
| `.*Node`, `Memory.*`, `.*Research.*` | 2 |
| `^MemoryResearchNode$` | invalid — dumps help, exit 255 |

A partial class name returns zero matches at exit 0, which is indistinguishable from "no such class". Escaping still matters for `.`, `[`, `+` in Swift symbols, but the dominant risk is under-matching, not over-matching. Guard by requiring the `Active blocks in all zones that match pattern` header and, on an empty result, listing real class names before concluding the objects are absent.

By hand, discover addresses in the selected snapshot, then inspect a representative instance:

```sh
heap -addresses '<ESCAPED_CLASS_PATTERN>' <GRAPH>
heap -addresses 'malloc[500k+]' <GRAPH>
heap --layouts=<CLASS_PATTERN> <GRAPH>
leaks --debug=layout --debug=<ADDRESS> <GRAPH>
leaks --trace=<ADDRESS> <GRAPH>
leaks --traceTree=<ADDRESS> <GRAPH>
malloc_history <GRAPH> -fullStacks <ADDRESS>
```

Qualify the installed `--debug` grammar before use. The report's address-selected layout query exposed named fields, offsets, outgoing pointers, `REFERENCES TO THIS`, allocation size, instance size and stack. Other types may expose less. No field output does not prove no fields or no owners.

`leaks --debug=references` on the inspected version selected allocations with more than one reference. It is not a reliable substitute for a single-address incoming-edge query. `--debug=contents` is a separate, potentially sensitive inspection mode; use only when the needed contents and disclosure are authorized.

Zero root paths can be expected for an unreachable cycle. Distinguish it from an incomplete/filtered graph or a failed reader. Inspect multiple incoming paths when a proposed fix depends on removing an owner. Large allocations can be backing stores owned by small objects; keep object logical size, allocated bytes and associated payload separately named.

For broad structural discovery only:

```sh
leaks --referenceTree --groupByType --noContent <GRAPH>
```

This is a parent-selected display projection, not complete adjacency. Do not run exact retained-size/dominator analysis on it. Enumerating per-address layouts into a complete graph is future backend work, not implemented here.

## E Compare checkpoints or inspect recorded history

```sh
heap -diffFrom <BEFORE_GRAPH> <AFTER_GRAPH>
leaks --diffFrom=<BEFORE_GRAPH> <AFTER_GRAPH>
malloc_history <GRAPH> -allBySize
malloc_history <GRAPH> -callTree
malloc_history <GRAPH> -highWaterMark -callTree
leaks --autoreleasePools <GRAPH>
```

Compare compatible same-process checkpoints for accumulation and supplement tool differences with class-count/byte deltas in both directions. Do not assert address-based survival without addressing reuse. Across independent launches use type/stack distributions and aligned phases, not pointer joins.

History queries require relevant recorded events. A recorded heap-plus-VM high-water mark is not peak physical footprint and may include logging storage. For transient timeline questions route to `ios-instruments-profiler`, discover templates and verify exported data from the actual target. Do not issue an assumed universal `xctrace` schema.

Duplicate-string analysis uses `stringdups` only after checking its installed help and obtaining an appropriate content-bearing artifact. Do not recover or expose sensitive strings merely to count duplicates. Prefer local aggregate counts and lengths where possible.

## F Physical device test diagnostics

For an existing, selected, safely repeatable memory performance test on an authorized signed device:

```sh
xcodebuild test -project <PROJECT> -scheme <SCHEME> \
  -destination 'platform=iOS,id=<DEVICE_UDID>' \
  -only-testing:<TEST_TARGET>/<TEST_CLASS>/<TEST_METHOD> \
  -enablePerformanceTestsDiagnostics YES \
  -resultBundlePath <NEW_RESULT_BUNDLE>
xcrun xcresulttool export attachments \
  --path <RESULT_BUNDLE> --output-path <NEW_ATTACHMENT_DIR>
xcrun xcresulttool export diagnostics \
  --path <RESULT_BUNDLE> --output-path <NEW_DIAGNOSTIC_DIR>
```

Use `-workspace` instead of `-project` when the verified build requires it. Confirm test selection with the test-engineer skill or installed test enumeration before running. Do not create tests or change signing unless authorized. Extra diagnostic execution can repeat actions.

Inspect actual result records and exported artifacts. Require the intended test to have run, identify app versus test-runner process, and validate pre/post graphs and their intervals. Passing tests, successful export or an existing result bundle do not prove graph collection. Archive/container contents require safe extraction to owned directories without following untrusted paths.

This route is not arbitrary live-state capture and is not a guaranteed Simulator fallback. If blocked, report the exact prerequisite and offer a supplied Xcode graph or permitted telemetry; do not use the device's PID with host `leaks`.
