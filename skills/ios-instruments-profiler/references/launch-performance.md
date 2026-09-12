# Launch-performance workflow

Launch measurement requires two synchronized but distinct lanes.

## Define the launch

- **Cold launch:** behavior after reboot or a sufficiently controlled state without reusable launch caches. It is difficult to reproduce and affected by prewarming and system state.
- **Warm launch:** terminate the process and launch again without reboot. This is normally more consistent for repeated engineering measurements.
- **Resume:** bring a suspended app back. It is not a launch and belongs in a separate dataset.

Choose an endpoint:

- first rendered frame;
- responsive first frame;
- app-defined “first usable content” or extended readiness, measured with a stable signpost/telemetry interval.

Do not redefine launch to include arbitrary background work without an explicit endpoint.

## Lane A: authoritative elapsed measurement

Add a UI performance test when source changes are authorized:

```swift
final class AppLaunchPerformanceTests: XCTestCase {
    func testWarmLaunchUntilResponsive() {
        let options = XCTMeasureOptions()
        options.iterationCount = 10

        measure(
            metrics: [XCTApplicationLaunchMetric(waitUntilResponsive: true)],
            options: options
        ) {
            XCUIApplication().launch()
        }
    }
}
```

Run a previously built test on one explicit target and preserve the result bundle:

```sh
xcodebuild test-without-building \
  -xctestrun '/absolute/path/App_iphoneos.xctestrun' \
  -destination 'platform=iOS,id=DEVICE_UDID' \
  -only-testing:AppUITests/AppLaunchPerformanceTests/testWarmLaunchUntilResponsive \
  -resultBundlePath '/absolute/run/AppLaunch.xcresult'
```

Use `scripts/xcresult_metrics.py` to extract the metric's measurements and distribution. Preserve the original `.xcresult` as the authority. Do not estimate elapsed launch from video, screenshots, shell time, process creation, or summed profiler samples.

## Lane B: diagnostic traces

Capture separate App Launch traces under the same declared build, target, fixture, and launch class:

```sh
python3 scripts/xctrace_record.py \
  --template 'App Launch' \
  --device 'DEVICE_UDID' \
  --launch 'com.example.app' \
  --time-limit 8s \
  --run-name 'warm-launch-01' \
  --output '/absolute/run/traces/warm-launch-01.trace'
```

The recorder fails a launch trace as `target-inactive` when the target produced fewer CPU samples than `--min-launch-samples`. On Xcode 27 beta 27A5194q the App Launch template sometimes left launched targets asleep; when the gate fails there, record `--template Blank --instrument 'Time Profiler'` for CPU and a separate `--template Blank --instrument 'dyld Activity'` for library loading, both of which launched normally in testing.

Use the exported App Launch/Time Profiler, thread-state, lifecycle, signpost, File Activity, or allocation evidence to explain launch phases; `xctrace_reduce.py` ranks self, inclusive and first-app frames from `time-profile`. CPU-active sample weight is diagnostic even when an analyzer calls it “launch time”; rename it `cpu_active_sample_ms` or equivalent in owned output.

## Analysis

Report Lane A first: valid iteration values, median, p90, min/max, spread, target, build, and metric source. When a baseline bundle exists, compare with `xcresult_metrics.py --path CANDIDATE --baseline-path BASELINE --metric 'Launch'` and report the median delta, its bootstrap interval and the verdict. Then correlate Lane B evidence:

- recurring main-thread self/inclusive CPU paths;
- runnable, preempted, or blocked intervals;
- dynamic-loader/framework initialization;
- synchronous disk/database work;
- allocation bursts or persistent growth;
- signposted phases and their overlap with slow measured launches.

A method that appears in most slow traces is a stronger candidate than one appearing once. Association does not prove the method accounts for the full elapsed regression. Re-record after the smallest evidence-backed change and confirm with Lane A.

## When XCTest cannot be added

Use an existing app-owned signpost or field launch metric if its start/end semantics are explicit. If none exists, report that the trace can diagnose CPU/thread/I/O behavior but cannot provide authoritative elapsed launch duration. Do not manufacture the missing value.
