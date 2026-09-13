# Achievable memory investigation scenarios

These scenarios specify what an agent can establish when the required evidence is available. They are not claims that this skill has live-tested every route. Native Apple reader operations have report-level macOS fixture evidence; Simulator, device and application-specific coverage still require qualification. Scenario outputs should follow the evidence contract.

## Scenario index

U01 footprint; U02 largest allocations; U03 owner paths; U04 cycles; U05 dismissed screens; U06 caches; U07 closures; U08 async tasks; U09 timers and observers; U10 backing stores; U11 allocation provenance; U12 reference writers; U13 historical frees; U14 peaks and churn; U15 autorelease; U16 fragmentation; U17 duplicate strings; U18 Swift metadata; U19 App Intents and extensions; U20 devices; U21 managed runtimes; U22 invalid access; U23 regression testing; U24 exact retained size and exhaustive queries.

## U01 Explain current memory usage

User question: “Why is this app using so much memory on this screen?”

Requirements: a validated graph or authorized target, a verified screen/checkpoint, and an explicit metric. Begin with physical footprint, VM categories and heap allocation totals; preserve each metric's accounting definition.

Agent procedure: establish the app process, capture or open the graph, inspect vmmap and footprint summaries, then rank heap bytes. Separate app buffers, mapped files, images, stacks, allocator regions and diagnostic-tool storage where the reader identifies them. If the concern is an increase, request or capture a comparable warmed baseline instead of inventing one.

Achievable answer: identify the dominant reported categories and explain which changes are supported by the evidence. Provide bytes, checkpoint and reader provenance. If footprint output has permission warnings, retain the available values while marking collection partial.

Limit: heap bytes are not the whole physical footprint. A Simulator measurement describes the local process, not a device memory budget. A single large value does not prove a leak, regression or impending jetsam.

Example agent prompt: “Use the memory skill to explain the current checkpoint by category. Do not relaunch or edit the app. State any missing baseline.”

## U02 Find the largest objects and raw buffers

User question: “Which objects are responsible for most allocated memory?”

Requirements: a readable native heap inventory. Type metadata improves attribution but is not required to discover large anonymous allocations.

Agent procedure: rank heap types by total bytes, distinguish count from per-instance size, then inspect representative addresses and large malloc blocks. Record logical instance bytes separately from allocation bytes. Follow relevant owner references to connect a large buffer with a small data/image/container object when evidence permits.

Achievable answer: a ranked list of types or allocation groups, selected instances, known backing stores and recorded allocation sites. Include unknown-type buckets rather than dropping allocations the runtime cannot name.

Limit: the largest object shell may not own the largest payload; shared backing storage cannot be charged fully to every owner. Allocation-derived image attribution is not automatically a class-definition image. This ranking does not establish exclusive retained size.

Example agent prompt: “List the largest allocation groups and inspect the top unexplained group, including non-object buffers. Keep shared storage separate.”

## U03 Explain why a particular object is still alive

User question: “What keeps this view model alive after I leave the screen?”

Requirements: a verified post-dismissal checkpoint, a discoverable instance or semantic identity, and captured reference metadata. Source knowledge is needed to decide which owners are intentional.

Agent procedure: locate candidates by type, inspect selected layouts and incoming edges, then obtain bounded paths toward roots. Inspect more than one path when available. Relate named fields to the matching source revision; use UI evidence only to establish that dismissal occurred.

Achievable answer: “This captured instance has these observed incoming references and root paths; this owner conflicts with the stated lifetime contract.” If no lifetime contract exists, report retention facts and competing explanations, not a bug verdict.

Limit: a shortest path is a convenient explanation, not necessarily the incorrect owner. The reader may omit or conservatively infer references. No root path may indicate an unreachable cycle, incomplete metadata, filtering or failure; the rest of the evidence determines which.

Example agent prompt: “Inspect why the selected model remains alive. Show observed owners, alternative paths and what is still unknown before recommending a change.”

## U04 Diagnose a retain cycle

User question: “Find and explain the ownership cycle causing this leak.”

Requirements: a recognized scanner result or a graph with qualified owning-edge information. A source-owned bounded cycle probe is an optional, separately authorized route.

Agent procedure: preserve scanner totals, select a cycle, inspect every edge used in the explanation, and classify it as strong, weak, unowned, conservative or unknown. Identify owned storage associated with the cycle without counting shared descendants repeatedly. Look up matching ownership declarations and the expected cleanup behavior.

Achievable answer: a closed path of verified owning relationships and a plausible correction point grounded in the lifetime contract. A scanner-detected leaked-byte total can be reported with its original semantics. A raw-pointer loop is only a candidate cycle until ownership is established.

Limit: bounded depth-first search is not exhaustive. Weak/unowned edges cannot establish an ARC owning cycle. Replacing a reference with weak without understanding ownership can create premature deallocation.

Example agent prompt: “Explain one confirmed cycle and its payload. Do not modify source; identify the narrowest ownership decision to review.”

## U05 Detect accumulation after repeated navigation

User question: “Open and close this editor ten times and check whether memory returns.”

Requirements: a safe repeatable flow, one process launch, a warmed baseline, expected cleanup conditions and a permitted driver. Discover actual app types; do not invent class names from the screen title.

Agent procedure: verify the baseline screen, capture baseline, then repeat open, verify, close, verify and wait for the declared completion condition. Capture after each cycle or a predefined subset when capture cost is excessive. Track counts and bytes by type; inspect unexpected post-cleanup instances and their roots. Record failed or altered cycles separately.

Achievable answer: per-cycle count/byte deltas, evidence of accumulation and a supported retention hypothesis. Plot survivors or type counts separately from leaked bytes and footprint. If individual identity is not established, label counts as counts rather than “the same objects survived.”

Limit: ten fresh launches do not test in-process accumulation. Address reuse, asynchronous cleanup, caches and instrumentation can confound the result. A warmed plateau may be intentional.

Example agent prompt: “Repeat this reversible editor flow ten times in one launch. Verify each dismissal, compare with the warmed baseline, and explain retained candidates without changing source.”

## U06 Distinguish an intentional cache from abandoned memory

User question: “Leaks reports zero, but the app keeps growing. Is the cache broken?”

Requirements: comparable checkpoints, cache or feature lifetime expectations, and access to reference paths or suitable source. A cache eviction policy must be known or explicitly treated as unknown.

Agent procedure: show the recognized zero-leak result only as scanner evidence, then inspect class/byte growth. Trace reachable candidates toward cache/singleton roots. Compare growth against the actual policy: bounded entries, count/cost limit, expiry, explicit invalidation or expected reuse. Reproduce a normal eviction trigger only if it is within the authorized scenario.

Achievable answer: identify reachable retained populations and whether their observed behavior violates a stated policy. A plateau or reuse may support normal caching; repeated unbounded growth beyond a verified bound supports a defect hypothesis.

Limit: being named “Cache” does not establish intent, and being reachable does not establish health. Do not flush caches or inject memory warnings as a default diagnostic shortcut. Freed allocations may not immediately reduce footprint.

Example agent prompt: “Check whether growth matches the cache's intended limit. Distinguish scanner leaks, reachable abandoned objects and allocator retention.”

## U07 Investigate closure or block captures

User question: “Does this callback retain its owner?”

Requirements: supported block/closure metadata or a debug build with source and a permitted targeted inspection route. Capture semantics may be less visible for pure Swift closures or optimized code.

Agent procedure: inspect the owning object, stored callback and supported capture references. Check matching source capture lists and callback lifetime. Look for a complete owning loop such as owner to callback storage to capture to owner, rather than identifying any closure as a leak.

Achievable answer: name observed capture relationships, distinguish verified ownership from untyped pointer candidates, and connect the retention to callback completion or storage cleanup. If metadata is incomplete, propose a narrowly targeted debugger or lifecycle reproduction to discriminate between alternatives.

Limit: absence of named captures does not prove no capture. Source syntax alone may not reveal all runtime storage. Diagnostic code that stores closure/object handles can itself extend lifetime.

Example agent prompt: “Determine whether the stored completion handler retains this owner beyond its expected lifetime. Preserve uncertainty where closure layout is unavailable.”

## U08 Distinguish active asynchronous work from a leaked task

User question: “Why is this screen's model still alive while a task runs?”

Requirements: a declared task-completion/cancellation condition, aligned UI checkpoints and supported runtime/source evidence. A long-running task may legitimately retain state.

Agent procedure: compare the model while work is active and after completion or cancellation. Inspect candidate task/closure ownership paths when available. Use authorized lifecycle markers, existing logs or debugger task state for the missing semantic fact. Record whether cancellation was merely requested or actual completion was observed.

Achievable answer: distinguish retention during intended work from retention after the expected terminal condition. Identify a supported owner chain or explain why the runtime graph is insufficient to name one.

Limit: task object presence does not establish a leak, and a cancel request does not guarantee immediate deallocation. Do not infer a task's lifecycle solely from a dismissed screen or use debugger pauses as performance evidence.

Example agent prompt: “Check retention before and after this task really finishes. Do not label an active task as leaked merely because its screen disappeared.”

## U09 Investigate timers observers and subscriptions

User question: “Is an observer or timer keeping this controller alive?”

Requirements: selected survivor instances, reference evidence and matching registration/cleanup source where available.

Agent procedure: inspect incoming paths, identify any observed timer, observer token, callback or subscription container, and check its owner. Compare a checkpoint before registration with a post-dismissal checkpoint. If the registration or cleanup event is unknown, use an authorized breakpoint on the relevant app boundary during a new reproduction.

Achievable answer: establish whether a specific retained registration path persists beyond the stated lifetime and which cleanup responsibility is implicated. Distinguish multiple owners; removing one registration may leave another path.

Limit: not all observer APIs have the same ownership semantics. A name-based heuristic or a framework frame is not sufficient proof. Do not automatically unregister, invalidate or mutate subscriptions while diagnosing an existing live state.

Example agent prompt: “Inspect the actual path retaining the dismissed controller and verify the registration's expected cleanup. Recommend a fix only after showing evidence.”

## U10 Explain image data and collection backing storage

User question: “Only a few objects remain. Why do they account for so much memory?”

Requirements: heap and VM evidence, address-specific layouts/references, and type-specific attribution when available.

Agent procedure: compare object-shell sizes with separately allocated storage, capacities and VM regions. Follow observed payload pointers, inspect allocation stacks and identify sharing. For images, distinguish encoded data from decoded buffers only where evidence supports that interpretation; for collections distinguish count, capacity and owned element allocations.

Achievable answer: a storage breakdown with clearly named accounting quantities and evidence linking small owners to larger allocations. The report's fixture illustrates the issue: two 32-byte nodes participated in a scanner leak totaling 82,032 bytes when the data object and backing storage were included.

Limit: the fixture numbers are not measurements of the user's app. Requested data length, allocation capacity and physical footprint can differ. A native heap inventory may not fully attribute GPU, surface or external allocator storage.

Example agent prompt: “Explain the backing storage retained by these small objects. Do not report only instance size or double-count shared buffers.”

## U11 Recover allocation provenance

User question: “Which code created this allocation?”

Requirements: the target allocation's recorded stack and symbols matching the captured executable. If the relevant allocation predates logging, preserve the current graph and state the gap.

Agent procedure: query malloc_history for the selected snapshot address, inspect the recorded stack and resolve app frames against image UUIDs and dSYMs. Report the strongest supported location: symbol, file/line, or unresolved address. If needed and authorized, repeat the flow with an explicit qualified logging mode and test that new allocations receive stacks.

Achievable answer: an allocation origin with provenance and symbolication quality. It may narrow the candidate feature or factory even when exact source lines are unavailable.

Limit: allocation provenance is not the writer of a retaining field, the time an object became unnecessary, or a complete event history. Environment-variable presence does not prove stacks were actually captured.

Example agent prompt: “Find the recorded allocation origin of this buffer. Give a source line only when matching symbols support it; otherwise state the strongest available frame.”

## U12 Find the code that installed an unwanted reference

User question: “Which line put this model into the long-lived owner?”

Requirements: a graph identifying the suspicious field/container plus a debuggable matching build and a repeatable path, unless a relevant writer event was already recorded.

Agent procedure: use the graph to identify the precise ownership question, then hand off to the LLDB skill. Set a relevant setter/registration breakpoint or a verified storage watchpoint; reproduce one action while respecting debugger stops. Inspect the stopped stack and arguments. Link the observed write to the later retention checkpoint.

Achievable answer: a reproduced writer location and code-state transition supporting a causal explanation. Compare an alternative path or cleanup event to test the hypothesis.

Limit: a graph captured today cannot identify an unrecorded write yesterday. Computed properties may have no stable watchable storage. Addresses expire after process changes; expression evaluation can alter state. This is a new debugger experiment, not retrospective reconstruction.

Example agent prompt: “Use the observed owner path to find the writer in a new reproduction. Do not invent the writer from the allocation stack or change source.”

## U13 Investigate allocation and free history

User question: “Was this address freed and later reused?”

Requirements: relevant allocation/deallocation events recorded in a supported full-history mode, with artifact and process identity. Lite/current-allocation data may not answer the question.

Agent procedure: establish the effective recording mode and event interval, query the address history and preserve event order. Distinguish a storage location from the successive allocations that occupied it. Where compaction or missing intervals could remove evidence, state that coverage limit.

Achievable answer: a recorded sequence of allocations/frees within the available history, or a precise explanation of why it cannot be recovered. Use this evidence to strengthen or invalidate snapshot-survivor joins.

Limit: no events returned does not prove an address was never freed. Missing logs cannot be reconstructed from one current graph. Full/no-compact logging can add substantial memory and disk overhead and requires a separate authorized reproduction.

Example agent prompt: “Determine whether address reuse can explain this apparent survivor. If history was not recorded, keep individual identity uncertain and compare aggregate counts instead.”

## U14 Diagnose transient peaks and allocation churn

User question: “Memory spikes while importing, then drops before I can capture it. Why?”

Requirements: a repeatable interval and a qualified Allocations/VM or telemetry recording. A graph at the end of the import is insufficient.

Agent procedure: use the profiler skill to discover supported templates, record a smoke trace, validate target data and export actual available tables/details. Align a fixed import flow with start/end markers. Rank allocation size/count/stack activity around the spike. Capture a separate graph at a meaningful checkpoint if ownership evidence is also needed.

Achievable answer: an interval-based peak or churn explanation with units, timestamp ranges and allocation provenance. A recorded malloc_history high-water query may complement this but must retain its heap-plus-VM semantics.

Limit: sampled peaks can miss short spikes. Summed allocation volume is not simultaneous live memory or physical footprint. Logging storage and pause overhead can alter the result; keep diagnostic recordings separate from baseline performance measurements.

Example agent prompt: “Profile the import interval, identify the allocation burst and distinguish churn from persistent retention. Do not infer the peak from the final snapshot.”

## U15 Investigate autorelease lifetime

User question: “Why do temporary objects persist until this batch finishes?”

Requirements: a supported autorelease-pool query, a known batch boundary and source/runtime context. The feature may involve Objective-C bridging even in a Swift app.

Agent procedure: inspect pool evidence and temporary allocation groups during the batch and after a verified boundary. Compare type counts and bytes with the warmed baseline. If a narrower pool scope is a plausible remedy, describe a controlled source experiment only when fixes are authorized.

Achievable answer: evidence consistent with delayed release at a pool boundary versus retention that persists afterward. Recorded allocation stacks can identify the producing loop.

Limit: not every delayed deallocation is autorelease behavior. Do not force a pool drain or invoke arbitrary cleanup methods on an existing state as an inspection shortcut. A shorter lifetime may lower peak usage without changing the end-state heap.

Example agent prompt: “Check whether these temporaries are waiting on an autorelease boundary. Compare during and after the real batch completion before calling them leaks.”

## U16 Separate allocator retention from object retention

User question: “Object counts drop, but footprint stays high. Did cleanup fail?”

Requirements: compatible heap inventories and VM/footprint summaries before and after cleanup. A single object count or process gauge is insufficient.

Agent procedure: verify that logical cleanup occurred, compare live allocation payload with dirty/resident allocator regions and mapped storage, and inspect size distributions when available. Look for retained objects as one hypothesis and allocator-region reuse/fragmentation as another. Compare subsequent equivalent work to see whether existing regions are reused.

Achievable answer: show which layer remains large and why dropping object counts alone does not guarantee an immediate footprint drop. Identify fragmentation or allocator retention as supported hypotheses, not automatically proven mechanisms.

Limit: no general skill command can force an app's memory back to an exact number or infer all allocator internals. OS accounting and instrumentation affect the observations. Do not kill/relaunch the app to make a cleanup graph look better.

Example agent prompt: “Explain the divergence between live heap payload and footprint after cleanup. Keep allocator behavior separate from an owning-reference leak.”

## U17 Identify duplicate strings without exposing user content

User question: “Are repeated strings wasting memory?”

Requirements: a suitable content-bearing artifact and authorization for local content inspection. A noContent capture may deliberately lack the evidence.

Agent procedure: inspect installed stringdups capabilities, analyze locally, and summarize duplicate counts, lengths and estimated storage under the tool's semantics. Prefer aggregate or redacted groups; quote actual values only when relevant and authorized. Preserve limits from truncation, encoding or content omissions.

Achievable answer: identify repeated captured string populations and candidate deduplication opportunities. Correlate allocations with creation stacks if available.

Limit: duplicate values can be legitimate, and estimated duplicate storage is not guaranteed reclaimable memory. Redacted graphs do not provide omitted text retroactively. Memory content can include credentials and personal data; a string analysis request is not blanket permission to upload an entire graph.

Example agent prompt: “Analyze duplicate-string overhead locally and return counts and lengths, not raw user text. Report if the capture lacks required content.”

## U18 Inspect Swift objects with incomplete metadata

User question: “Show every stored property and owner of this Swift object.”

Requirements: a compatible artifact/runtime and available type metadata. A matching debug build and LLDB may provide a complementary live route.

Agent procedure: inspect the native type/layout and mark which fields and ownership labels are actually exposed. Preserve unknown generic payloads, closure storage and conservative references. If a live stored value is needed, coordinate a single LLDB owner and inspect raw state first. Use a source-owned semantic probe only for a demonstrated missing fact and with authorization.

Achievable answer: the supported fields, sizes, offsets and relationships, with an explicit coverage inventory. The agent can explain how a missing field could be investigated instead of filling it from source assumptions.

Limit: no promise of every Swift property, private runtime detail, computed value or optimized-out state. A declaration in source does not prove the corresponding captured runtime value. A live debugger observation belongs to its own stop epoch, not the earlier graph.

Example agent prompt: “Inspect what this capture actually exposes for the Swift object. Separate captured values, source declarations and unavailable runtime state.”

## U19 Investigate Sparrow App Intents and extension memory

User question: “Run this Sparrow Shortcut repeatedly and explain its memory growth.”

Requirements: a chosen safely repeatable intent, verified invocation evidence and identification of the executing process. The intent may execute in the app, an extension or another host; the main app must not be assumed.

Agent procedure: use the appropriate UI/test driver to invoke the selected Shortcut, correlate process creation/activity with the invocation, and bind each relevant capture to that process launch. Define whether the question concerns repeated work within one long-lived host or repeated short-lived executions. Capture supported checkpoints and compare like-for-like phases.

Achievable answer: scoped memory findings for the actual identified process or processes, with invocation and checkpoint links. If the host exits before capture, report that limitation and consider a controlled diagnostic test or interval recording.

Limit: this is a proposed Sparrow scenario; no Sparrow memory qualification is supplied by this skill. Main-app graphs do not establish extension coverage. Multiple process footprints can share pages, so blindly summing them is not a reliable device-total measurement.

Example agent prompt: “Investigate this selected Sparrow intent ten times. First prove where it executes; do not report main-app memory as coverage of an unidentified intent host.”

## U20 Analyze memory on a connected device

User question: “Can you collect and analyze memory graphs on my iPhone?”

Requirements: an authorized device and supported route: supplied Xcode graphs, or an existing safely repeatable signed XCTest memory performance test with working diagnostics.

Agent procedure: prefer supplied artifacts when adequate. Otherwise verify test selection, pairing/developer prerequisites and scope; request performance diagnostics, export result attachments/diagnostics, identify the measured process and validate actual pre/post graphs. Preserve evidence of additional diagnostic iterations and any repeated effects.

Achievable answer: offline graph analysis from actual collected device artifacts, or a documented route with its unresolved prerequisite. Validate a real run before calling the route qualified.

Limit: the inspected public device CLI did not offer arbitrary native graph capture at any existing pause point. Test diagnostics do not preserve an irreproducible current state. A physical-device PID is not valid input to Mac host leaks. Protected apps may not be inspectable.

Example agent prompt: “Analyze the supplied iPhone graph, or use this existing memory performance test if permitted. Do not claim arbitrary live-device capture or alter signing.”

## U21 Separate native JavaScript and managed memory

User question: “Does the WebView or Unity layer account for this growth?”

Requirements: process/domain identification, native VM/heap evidence and, when needed, a compatible authorized JS or managed-runtime snapshot/trace.

Agent procedure: identify app and helper processes, capture available evidence per domain, and align build, time and semantic checkpoints. Native buffers may reveal growth without exposing JS reachability; a JS snapshot may reveal script owners without explaining all native backing resources. Keep each domain's IDs and accounting units separate.

Achievable answer: attribute observations to the domain that supports them and identify missing cross-domain edges. A synchronized lifecycle marker or source-owned bridge ID can improve correlation if explicitly instrumented and validated.

Limit: pymobiledevice3's WebKit heap conversion is not a native iOS graph collector; native memgraph analysis does not replace Unity's managed snapshot. Coincident timestamps or similar addresses do not prove cross-runtime object identity. Shared resources can make totals overlap.

Example agent prompt: “Determine which runtime owns the unexplained growth. Keep native, WebContent and managed evidence separate and state what cannot yet be joined.”

## U22 Diagnose invalid access and memory corruption

User question: “Can the memory graph explain this use-after-free crash?”

Requirements: the crash/stop evidence and a suitable debugger, sanitizer or recorded allocation history route. A current reachability graph alone usually cannot establish the invalid write/read sequence.

Agent procedure: preserve crash registers, stack, address and build identity; use the LLDB skill to inspect the stopped state or reproduce with targeted breakpoints/watchpoints. When authorized, a diagnostic build with the relevant sanitizer or allocation history may reveal the event. Use any graph as supporting ownership context, not the decisive access-history proof.

Achievable answer: identify the strongest recorded failing access, allocation/free provenance or reproduced writer, with gaps clearly stated. Separate storage lifetime from object ownership and source fixes from temporary debugger expressions.

Limit: sanitizers require compatible builds and may change behavior. A reused address can describe a different object by the time a snapshot is taken. A clean leak scan neither confirms nor excludes memory corruption.

Example agent prompt: “Route this suspected use-after-free to the appropriate debugger/history evidence. Do not diagnose it solely from a leak graph.”

## U23 Validate a memory regression or authorized fix

User question: “Did this patch fix the leak, and can we guard it in CI?”

Requirements: a defined scenario and lifetime/metric contract, comparable builds and target conditions, valid baselines and permission to run the chosen tests. Source modification is only in scope when requested.

Agent procedure: repeat the same warm-up, flow, cleanup and checkpoint policy before/after the patch. Keep individual values, missing runs and logging settings. Compare type counts, scanner findings, owner paths and footprint separately. Across launches/builds join semantic phases and normalized types/stacks rather than addresses. Use targeted XCTest or a qualified capture pipeline for automation.

Achievable answer: whether the intended lifetime violation disappeared under the tested conditions, what metrics changed and what remains untested. CI gates should distinguish invalid evidence from a passing threshold and retain actionable failure artifacts.

Limit: zero leaks in one run is not whole-app proof. A simulator regression threshold is not a physical-device memory guarantee. Do not compare instrumented and uninstrumented footprints as an uncontaminated app regression. CI graph collection and parsers require their own qualification.

Example agent prompt: “Re-run the original scenario after this authorized patch. Report valid and invalid runs and keep functional, retention and footprint conclusions separate.”

## U24 Handle exact retained size and exhaustive requests honestly

User question: “Tell me everything in memory and exactly how many bytes removing this object will free.”

Requirements: first decompose the request into quantities and runtime domains. Exact exclusive retained bytes require a complete graph and root model for the relevant domain, reliable owning relationships and correct shared-descendant/dominator handling.

Agent procedure: inventory what the artifact actually contains, return useful summaries and selected object queries, and state which exact/exhaustive claims are unavailable. Do not sum a referenceTree subtree and rename it retained size. Offer an explicitly labeled available quantity such as allocation bytes or scanner-reported leaked bytes. If complete-graph extraction is necessary, propose it as separately validated engineering work.

Achievable answer: a broad, bounded memory inventory and a precise capability-gap explanation. A useful answer can say “allocation size is known; exact reclaimable bytes are not established” without discarding the known facts.

Limit: unrecorded history, protected processes, omitted metadata, unknown runtime domains and application intent cannot be solved by a larger prompt. “Everything” is not a valid completeness promise for this skill.

Example agent prompt: “Answer as much as the evidence supports. Explicitly separate known allocation sizes from unavailable exact retained size and list the next capability needed.”
