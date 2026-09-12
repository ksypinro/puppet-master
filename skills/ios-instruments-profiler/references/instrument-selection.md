# Instrument selection and target fidelity

Choose the evidence that answers the question, then verify the installed template and exported schemas on the actual worker. Template names and schemas change across Xcode versions; the list below is a routing guide, not a static support promise.

## Question-to-evidence map

| Question | Primary evidence | Supporting evidence | Important caveat |
|---|---|---|---|
| How long does the app launch? | `XCTApplicationLaunchMetric` or deliberate field telemetry | App-owned readiness signpost | Time Profiler sample totals are not elapsed launch time |
| Why is launch slow? | App Launch, Thread State, symbolized call stacks | File Activity, Allocations, signposts | Diagnose separately from the launch benchmark |
| Which code consumes CPU? | Time Profiler or CPU Profiler | CPU Counters on supported hardware | Samples estimate CPU work, not wall-clock responsiveness |
| Why is the main UI unresponsive? | Hangs, Thread State, System Trace | Main-thread signposts and UI timestamps | High CPU alone is insufficient; Hangs evaluates app processes |
| Is memory growing? | Allocations and VM Tracker over repeated fixed scenarios | XCTest memory metrics | Compare equivalent lifecycle points; export through track details |
| Is there a leak? | Leaks plus allocation/backtrace evidence over a lifecycle | Memory Graph imported separately | One run or snapshot is not proof; launch the target when stacks matter |
| Why does scrolling stutter? | Animation Hitches/Hitches | SwiftUI, Time Profiler, frame instruments | Use deterministic gestures; average FPS hides tails |
| Which network request is slow? | Network/HTTP Traffic and HAR when exportable | Signposts from request to rendered result | HTTP Traffic can miss command-line clients; redact data |
| Is startup I/O excessive? | File Activity scoped to the launch window | Data Persistence and signposts | Filter unrelated processes; very slow to save |
| Is Swift concurrency involved? | Swift Concurrency | Time Profiler, Thread State, signposts | Requires supported runtime instrumentation |
| Is SwiftUI recomputing excessively? | SwiftUI | Hitches and Time Profiler | Instrument names changed in newer Xcode versions; smoke-test first |
| Is power use acceptable? | Power Profiler on a physical device | Thermal state and field/MetricKit data | iPhone and iPad only; Simulator power values are not representative |
| Is GPU/Metal/ML work efficient? | Relevant Metal, GPU, Core ML, Neural Engine template | CPU and signpost context | Hardware, OS, workload, and permissions gate availability |

## Fidelity tiers

1. **Simulator:** good for toolchain smoke tests, app logic, automation, schema/parser development, and same-host trend signals. Do not generalize its CPU, GPU, memory pressure, storage, network stack, thermal, energy, or accelerator behavior to an iPhone or iPad.
2. **Physical development device:** appropriate for engineering conclusions when device model, OS, thermal state, battery/power conditions, build, and fixture are controlled.
3. **Field telemetry:** needed when the question concerns population behavior, rare tails, diverse devices, or real-world networks. Instruments explains sampled laboratory runs; it is not production population evidence.

## Common templates and their practical constraints

- **App Launch:** phase, thread-state, and CPU diagnosis. Pair it with XCTest for elapsed duration.
- **Time Profiler:** general CPU call-tree analysis. Require symbols and correct process/time scope.
- **System Trace:** scheduler, scheduling, system calls, and contention. High volume; narrow the window to a few seconds.
- **Hangs:** responsiveness failures. Reproduce the exact interaction and keep main-thread evidence.
- **Allocations / VM Tracker / Leaks:** memory allocation, virtual-memory, and leak investigations. Use a lifecycle long enough to expose the issue; export with `xctrace_export.py table --track ... --detail ...`.
- **Animation Hitches:** dropped/hitched frames during interaction. Prefer a physical device and fixed gestures.
- **SwiftUI / Swift Concurrency:** framework-specific activity. Confirm runtime and export support first.
- **File Activity / Data Persistence:** storage and persistence behavior. Correlate with signposted phases.
- **Network:** URLSession/HTTP activity; HAR availability is trace-dependent and sensitive.
- **Power Profiler:** energy/thermal/resource indicators on real hardware under controlled conditions.
- **CPU Counters / CPU Profiler / Processor Trace:** hardware-dependent and potentially high volume. Smoke-test every target.
- **Metal System Trace / Game Performance / Core ML / Foundation Models / RealityKit:** workload- and hardware-specific. Do not run them simply because the template is installed.

## Instrument conditions observed in testing

Recorded on 11 September 2026 on an M1 MacBook Pro (macOS 26.5.1) with Xcode 27 beta 27A5194q, against purpose-built workloads: a command-line tool, a small SwiftUI app, and XCTest on the iOS 27 Simulator. Other builds and devices may differ; re-check with `xctrace_doctor.py --smoke-record` and a row gate.

| Instrument or template | Condition | Evidence |
|---|---|---|
| Hangs | Evaluates app processes | A command-line tool blocking its main run loop for 120–1,500 ms: 0 potential hangs. A SwiftUI app blocking its main thread for 300 ms every 3 s: 2 potential hangs in 7 s. |
| Allocations, Leaks | Stacks only for allocations made while recording | Attached: 41% of live allocations and 40% of leaks had `<Call stack limit reached>`. Launched by `xctrace`: 1.6% and 0%. The responsible frame is often the Swift allocator. |
| Allocations, Leaks, VM Tracker | Data lives in track details, not schema tables | Details `Allocations / Statistics`, `Allocations / Allocations List`, `Leaks / Leaks`, `VM Tracker / Regions Map`; the schema tables in these traces held no memory data. |
| VM Tracker | Regions Map was empty in unattended recordings | 0 rows in every Allocations trace; it records snapshots on demand. |
| dyld Activity, stdout/stderr | Need a launch-owned trace | Attached after loading: 0 dyld intervals. Launched: 1,436 dyld intervals, and 97 stdout/stderr lines. |
| HTTP Traffic | Can miss command-line URLSession clients | 0 HTTP tasks while Network Connections recorded 52 connections. Network Connections is not available in the Simulator. |
| SwiftUI | Recorded no data on this setup | "Trace file had no SwiftUI data", attached and launched, while Hangs in the same trace worked. |
| Foundation Models | Model loading only | 1 model-loading row attached and 25 launched; 0 requests and inferences for three prompts. |
| Core ML, Neural Engine | No Core ML events from a command-line tool; a small model did not use the Neural Engine | 0 Core ML signposts and 0 Neural Engine intervals, while GPU work was recorded (4,009 intervals). |
| GCD Performance | Flagged nothing | 400-block bursts and 5,000 synchronous dispatches produced 0 events. |
| Core Animation FPS | Not on macOS; one rejected instrument fails the whole recording | With it the recording failed; Core Animation Commits and Frame Lifetimes alone recorded 572 commits. |
| Animation Hitches | An empty `hitches` table means no hitch | 396 frames and 0 hitches for on-time animation; the Display tables stayed empty for a macOS app. |
| System Trace, File Activity | Very slow to save | 4 s of recording took about 5 minutes (System Trace) and 3 minutes (File Activity) to save; the recorder's default grace allows for it. |
| Processor Trace | M4 or A18 hardware, iOS 18.4 / macOS 15.4 or later | Xcode refused the M1 Mac. |
| Power Profiler | iPhone and iPad only | Xcode refused macOS. |
| RealityKit Trace | Not on macOS; RealityKit Metrics not in the Simulator | Xcode refused both. |
| App Launch, Time Profiler templates with `--launch` (27A5194q) | Launched target sometimes stays asleep | One App Launch recording got 2 CPU samples in 6 s and one Time Profiler recording got 1; a later App Launch recording ran normally (192). Blank + Time Profiler launched normally both times (4,870 and 3,705). The recorder fails asleep traces as `target-inactive`. |
| Any template on the Simulator (27A5194q) | Recording never starts | 0 of 26 templates recorded; XCTest metrics worked. The doctor flags this build. |

## Capability decision

Treat support as three separate gates:

- **Invocable:** `xctrace list templates` or `list instruments` reports the name.
- **Recordable:** the selected target/mode starts and finalizes a bounded smoke recording. `xctrace_doctor.py --smoke-record` tests this per template and per instrument set, and names instruments Xcode rejects.
- **Analyzable:** TOC export succeeds and exposes a recognized table or track detail that has rows from the target and answers the question. Use `xctrace_record.py --expect-rows` to gate on it.

Only "analyzable" supports a performance conclusion. If the desired GUI track is absent from the TOC, report it as unavailable and choose a different evidence source rather than reverse-engineering private Xcode frameworks.
