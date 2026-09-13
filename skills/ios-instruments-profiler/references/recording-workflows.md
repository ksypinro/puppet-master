# Recording workflows

## Experiment contract

Persist these fields before the first measured run:

- question, metric, unit, hypothesis, endpoint, and acceptance/comparison rule;
- bundle identifier, app/build version, commit, configuration, optimization flags, binary UUID, and dSYM UUID/path;
- Xcode version/build, `xctrace` version, and selected developer directory;
- target kind, identifier, model, OS, available storage, and relevant power/thermal state;
- scenario steps, fixture/account state, network policy, permissions, orientation, locale, and accessibility settings;
- launch class (`cold`, `warm`, or `resume`) where relevant;
- warm-up, iteration count, settle interval, template/options, time limit, expected schema and minimum rows, and retry policy;
- output directory, run ID convention, retention, and redaction policy.

Do not compare runs when a field that affects the metric changed unless the experiment explicitly studies that change.

## Preflight

Use `scripts/xctrace_doctor.py` first. It reports the `xctrace` build and its known defects, and fails when one blocks the target (Xcode 27 beta 27A5194q cannot record on any Simulator). Add `--smoke-record` with the capture mode you will use (`--smoke-attach PROCESS`, `--smoke-launch BUNDLE_ID_OR_PATH`, or neither for all processes) to prove each template and instrument set records on this target; a failing set is re-recorded one instrument at a time so the report names the one Xcode rejects. Also confirm:

- the test selection matches tests, checked with `ios-test-engineer`'s
  `scripts/xctest_selection.py` (selection is a test concern; that skill owns it); `swift test --filter` matches the identifiers `swift test list` prints (symbols such as `PackageTests.SearchTests/testQuery`), not the display names in `@Suite("…")` or `@Test("…")`, so a filter written from a display name runs nothing and exits 0;
- the app is installed and launchable on the exact target;
- a physical device is trusted, unlocked, in Developer Mode where needed, prepared by Xcode, and visible to `xctrace list devices`;
- privacy prompts have been handled before unattended `--no-prompt` recording;
- the output volume has room for the full run set and exports;
- a Release/Profile build and matching dSYM are retained;
- the requested template's recording options are inspected when needed:

```sh
xcrun xctrace record --template 'Time Profiler' --show-recording-options
```

Recording-option JSON is version-specific. Store it with the manifest and never reuse it across Xcode builds without a capability check.

## Single-run capture modes

### Launch-owned capture

Use when the trace must include process launch, or when stacks for early allocations, dyld activity or stdout/stderr are needed (an attach misses everything before it):

```sh
python3 scripts/xctrace_record.py \
  --template 'App Launch' \
  --device 'DEVICE_UDID' \
  --launch 'com.example.app' \
  --time-limit 8s \
  --run-name 'warm-launch-01' \
  --output '/absolute/run/warm-launch-01.trace'
```

Arguments for the launched target are written after a standalone `--`, because argparse reads a bare `--launch-arg -XCTest` as an option; `--launch-arg=-XCTest` also works. This is what makes an XCTest bundle profilable directly, with no scheme and no Simulator:

```sh
python3 scripts/xctrace_record.py --template 'Time Profiler' \
  --launch "$(xcode-select -p)/usr/bin/xctest" --time-limit 20s \
  --output '/absolute/run/unit-test.trace' \
  -- -XCTest MyTests.SearchTests '/absolute/path/MyTests.xctest'
```

Whether a bundle identifier or app path is accepted can differ by target and Xcode version. Use `--dry-run`, then perform one bounded smoke capture. For Simulator warm launches, terminate the app using the explicit Simulator UDID before asking `xctrace` to launch it. For a device, let XCTest or a verified device lifecycle path own termination; `simctl` is Simulator-only.

A launch-owned trace can pass every file and schema check while the target never ran. On Xcode 27 beta 27A5194q, launch-owned App Launch and Time Profiler recordings sometimes left the target asleep (2 CPU samples in 6 s), although a later App Launch recording of the same target ran normally; the Blank template with Time Profiler launched it normally in both attempts (4,870 and 3,705 samples). The helper therefore counts `time-profile` or `cpu-profile` rows in launch-owned traces and fails the run as `target-inactive` below `--min-launch-samples` (default 20; set 0 for a target that is expected to idle). When that happens, record with `--template Blank --instrument 'Time Profiler'` and add the other instruments you need.

An app normally outlives the time limit, so `xctrace` terminates it when recording ends. Xcode 27.0 beta then exits with code 54 even though it saved a complete trace. The helper accepts 54 only for `--launch` when the log shows the time limit and a saved output without a recording failure, and every post-capture gate still passes; the manifest records `exit_code_accepted` and `exit_code_note`.

The helper's start evidence is `xctrace`'s `Ctrl-C to stop the recording` line. The earlier `Starting recording with ...` line only announces the attempt. A recorder that announces but never starts ends as `start-timeout` with `recorder_announced: true`. Xcode 27 beta 27A5194q has a known bug in which `xctrace record` never starts a recording for Simulator targets (Apple 183624872, fixed in the Xcode 27 RC, which requires macOS Tahoe 26.6 or later). On that build none of 26 templates recorded on the iOS 27 Simulator: templates that need the kernel-trace service wedge before starting, and the rest stop with platform errors. The Simulator's `DTServiceHub` logs `Could not create service named com.apple.instruments.server.services.coreprofilesessiontap`; read it with `xcrun simctl spawn <UDID> log show --predicate 'process == "DTServiceHub"'`. Record on the Mac or a device, use XCTest metrics on the Simulator, or update Xcode.

### Attach-based scenario

Use for post-launch interaction:

1. Launch and settle the app at the declared initial screen.
2. Start `xctrace_record.py --attach PROCESS` with a sufficient time limit.
3. Wait for recording-start evidence; do not start UI actions immediately after process spawn.
4. Execute the same semantic action script in every measured run.
5. Verify the final UI state with fresh accessibility/screenshot evidence.
6. Allow the bounded recording to finish or explicitly stop only the owned recorder process.

The helper owns the recorder watchdog, but orchestration still needs a handshake between “recording started” and the UI driver. For production automation, listen for the Darwin notification configured by `xctrace --notify-tracing-started` when supported, or wrap the helper with an environment-specific notification listener. Terminal text and trace-directory growth are weaker fallbacks.

Attached Allocations and Leaks traces have no stacks for objects allocated before the attach (about 40% of rows in testing). Use them for growth between lifecycle points; launch the target when the question is where memory was allocated.

### All-processes capture

Use only when system context is essential, such as scheduling, storage contention, or cross-process work. Filter exports back to the intended process and time range before analysis. Never attribute total host activity to the app.

## Repeated-run policy

- Run a warm-up before the measured set. XCTest performance metrics may already add and ignore a warm-up iteration; record this behavior in the manifest.
- Start with at least 10 measured runs for an engineering signal. Use more runs for stable tail estimates; the correct count depends on variance and the decision cost.
- Prefer one trace bundle per diagnostic run. Independent artifacts make retries, provenance, validation, and deletion safer than `--append-run`.
- Use unique run IDs and preserve stdout/stderr, trace, TOC, selected exports, normalized JSON, UI verification, and manifest.
- Apply a start deadline and a completion deadline of requested duration plus grace. The recorder may wedge even when `--time-limit` is present. The helper's default grace follows each template's observed save time: 2 minutes normally, and at least 10 minutes for System Trace, 6 for File Activity and 5 for Metal GPU Counters, growing with the time limit (in testing 4 s of System Trace took about 5 minutes to save). The manifest records `completion_grace_source`; a lower `--completion-grace` produces a warning.
- Keep System Trace and File Activity windows to a few seconds around the action, or use `--window`; the helper warns above 10 s.
- Gate each run on the table that answers the question with `--expect-rows SCHEMA[:MIN]`, so a saved trace without evidence counts as invalid.
- Retry at most once after a health recheck when failure is plausibly transient. Do not retry unsupported templates/hardware, missing apps, trust/signing failures, unmatched symbols, invalid contracts, or repeated wedges.
- Exclude invalid/recovered runs according to the policy written before measurement. Never replace them with zero.

## UI-driven performance

The UI controller and profiler have separate responsibilities:

- The controller establishes and verifies semantic state.
- The recorder collects performance evidence.
- The manifest aligns action timestamps, signposts, screenshots, and trace run IDs.
- The LLM may plan a scenario and diagnose failures outside the measurement window. The measured action sequence must remain deterministic.

Prefer stable accessibility identifiers and XCTest waits. Coordinate-only actions require a fresh screenshot and postcondition check. Screenshots and accessibility trees verify state; their timestamps are not authoritative performance metrics.

## Signposts

Use `OSSignposter` intervals or `os_signpost` around stable semantic phases such as database setup, first usable content, search request, response decoding, layout, and persistence. Signpost names must remain stable across compared builds. Capture them in the same trace and use them to scope CPU, blocking, I/O, or allocation evidence; `xctrace_reduce.py` summarizes `OSSignpostIntervals` per name.

Adding signposts changes source code and must be explicitly authorized. Keep payloads free of personal data and secrets. Measure signpost overhead when emitting at high frequency.

## Simulator versus device

- Simulator is the fastest place to validate automation, recording, exports, schemas, and parsers, when the `xctrace` build can record on it.
- Physical devices are required for representative power, thermal, GPU, accelerator, storage, and end-user performance claims.
- Do not pool Simulator and device samples. Label Simulator findings as host-specific trend evidence.
- Device visibility in `devicectl` is not sufficient; the target must appear in `xctrace list devices` and pass a recording smoke test.
