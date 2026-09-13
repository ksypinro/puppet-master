# Capabilities and evidence boundaries

## Scope and qualification

This design is based on the September 13, 2026 report, Xcode Memory Graph and CLI Snapshot Analysis, especially chapters 4–5 and 11–14. The report qualified an isolated Objective-C Foundation process on macOS 26.5.1 using Xcode 27 beta 27A5194q. It did not capture Sparrow, an iOS Simulator process, or a connected device. The new skill itself is a playbook, with no bundled native collector, parser service, or MCP server.

The report demonstrated capture, offline summaries, two-snapshot differences, allocation stacks, named strong fields and incoming references. Its deliberate cycle contained four leaked allocations totaling 82,032 bytes. This is a fixture oracle, not an app benchmark or universal compatibility claim.

For each operation record both its implementation route and its qualification on the actual host/target/artifact. Use `qualified`, `available_untested`, `documented`, `unavailable`, or `unknown`; attach evidence and versions. “Tool exists” only establishes availability.

| Question | Necessary evidence | Boundary |
|---|---|---|
| How much memory is in use | Footprint and VM accounting | Heap payload is not physical footprint |
| Which allocations are large | Heap inventory and allocation sizes | Includes raw buffers; type recognition may be partial |
| Why is an object alive | Current incoming edges and root paths | Conservative references are not proven owners |
| Is there a retain cycle | Scanner finding and owning-edge evidence | A bounded detector cannot establish exhaustiveness |
| Should it have died | Expected lifetime plus survival evidence | Reachability alone does not establish a bug |
| Where was it allocated | Recorded stack plus matching symbols | Logging cannot reconstruct earlier uncaptured events |
| Who wrote this reference | Recorded writer event or debugger reproduction | Allocation stack does not answer it |
| What was the peak | Interval recording or appropriate recorded history | End snapshot misses transient peaks |
| Exact bytes freed by removing an owner | Complete domain graph, roots and dominators | Not available from a display tree or this draft |
| What is in every field | Captured layouts/content or live debugger | Swift metadata, computed state and protections limit visibility |

## Capture lanes

**Imported native graph.** Analyze a supplied `.memgraph` with compatible Apple readers. No live attachment required. Verify provenance, readability, included history, and content policy. It represents a past checkpoint even if the app is currently open.

**Local host process.** Use permitted `leaks --outputGraph` capture. The report qualified this lane only on its owned macOS fixture. Validate access and outputs for the selected process.

**Simulator app as a host process.** Resolve the exact Simulator installation and host PID. The local capture approach is an integration recipe until qualified on that runtime. Do not pass an arbitrary `pgrep` result. Do not use `booted` when multiple targets might exist.

**Physical device under controlled XCTest.** An existing memory performance test can request diagnostics through `xcodebuild`, with graphs exported from the result bundle when supported. Extra diagnostic iterations may repeat effects. Historical Xcode 13 documentation excludes simulated-device memory-graph collection; discover actual current behavior rather than promise this as a Simulator fallback. This skill has not qualified a signed device run.

**Arbitrary existing device state.** No general native `.memgraph` export was found in the inspected public `devicectl` surface. Imported Xcode graphs are useful but may require a human-assisted step. `xcdebug` opens an Xcode-backed session; it is not a verified headless graph-export command. Private-service engineering is outside this playbook.

**Protected or third-party app.** Require whatever capture access the platform actually provides. Do not bypass protections or infer that pairing, developer tools, or source access makes every process inspectable. Offer permitted telemetry or a user-supplied artifact where useful.

## Runtime and information boundaries

- Objective-C and supported Swift metadata can expose types, fields and ownership labels. Pure Swift, generics, closures, async runtime objects, custom allocators and stripped binaries need per-case coverage evidence.
- A native graph does not replace a WebKit/JavaScript heap snapshot or Unity managed snapshot. Join domains by process/time/semantic markers; do not invent cross-runtime identity mappings.
- Debugger memory reads expose bytes, not a complete ownership graph. `po` may execute code and keep objects alive. A memory graph does not provide arbitrary method evaluation.
- `referenceTree` chooses a display parent when a node has multiple references. Its subtree is not an exact dominator set. Root/edge omissions invalidate exact retained-size claims.
- A typed weak or unowned reference is nonowning. A raw pointer-shaped value remains conservative/unknown unless independently typed. Scanner reference count is not ARC retain count.
- Without lifetime events, address reuse prevents definitive individual-object identity in snapshot differences. Across launches compare types, normalized stacks and scenario phases.
- Missing history, symbols or application lifetime intent are information gaps; more agent reasoning does not recover them.

## Repository ideas to reuse

Use memorydetective's separation of Apple command wrappers and bounded tool operations as a starting concept, but harden error recognition, parser completeness and retainer coverage. Its parser-level empty/error-to-zero behavior must not survive into this design.

Use FBRetainCycleDetector's typed traversal and candidate search concepts for an optional source-owned probe; keep Swift opt-in and traversal bounds explicit. FBAllocationTracker's generations and MLeaksFinder's expected-lifetime checks inspire scenarios, not universal whole-heap coverage.

FLEX and HeapInspector demonstrate live heap inspection but have safety, perturbation, age and licensing constraints. A retained diagnostic handle can itself change lifetime. Do not copy legacy hooks into an app as a routine skill step.

The Unity memgraph-analyzer suggests a staged offline pipeline, not an independent universal graph decoder. pymobiledevice3 exposes telemetry and a separate WebKit heap domain, not demonstrated arbitrary native device graph capture. Source incorporation requires a license review, including FBMemoryProfiler's root license and FLEX's additional restriction.
