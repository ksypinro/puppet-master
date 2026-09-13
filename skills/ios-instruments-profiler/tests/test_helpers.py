from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve postponed annotations through sys.modules
    spec.loader.exec_module(module)
    return module


doctor = load_module("xctrace_doctor", ROOT / "scripts" / "xctrace_doctor.py")
exporter = load_module("xctrace_export", ROOT / "scripts" / "xctrace_export.py")
metrics = load_module("xcresult_metrics", ROOT / "scripts" / "xcresult_metrics.py")
recorder = load_module("xctrace_record", ROOT / "scripts" / "xctrace_record.py")
reducer = load_module("xctrace_reduce", ROOT / "scripts" / "xctrace_reduce.py")

# Shapes below are trimmed from real Xcode 27 beta exports: ids are defined once and later rows use refs,
# a thread nests the process that the next column refers to, and stacks are leaf-first.
TIME_PROFILE_XML = """<?xml version="1.0"?>
<trace-query-result>
<node xpath='//trace-toc[1]/run[1]/data[1]/table[14]'><schema name="time-profile"><col><mnemonic>time</mnemonic><name>Sample Time</name><engineering-type>sample-time</engineering-type></col><col><mnemonic>thread</mnemonic><name>Thread</name><engineering-type>thread</engineering-type></col><col><mnemonic>process</mnemonic><name>Process</name><engineering-type>process</engineering-type></col><col><mnemonic>weight</mnemonic><name>Weight</name><engineering-type>weight</engineering-type></col><col><mnemonic>stack</mnemonic><name>Backtrace</name><engineering-type>tagged-backtrace</engineering-type></col></schema>
<row><sample-time id="1" fmt="00:00.100.000">100000000</sample-time><thread id="2" fmt="Main Thread (0x1) (App, pid: 7)"><tid id="3" fmt="0x1">1</tid><process id="4" fmt="App (7)"><pid id="5" fmt="7">7</pid></process></thread><process ref="4"/><weight id="6" fmt="1.00 ms">1000000</weight><tagged-backtrace id="7"><frame id="8" name="memcpy" addr="0x1"><binary id="9" name="libsystem_platform.dylib" path="/usr/lib/system/libsystem_platform.dylib"/></frame><frame id="10" name="parse()" addr="0x2"><binary id="11" name="App" path="/Users/alice/App.app/App"/></frame><frame id="12" name="main" addr="0x3"><binary ref="11"/></frame></tagged-backtrace></row>
<row><sample-time id="13" fmt="00:00.101.000">101000000</sample-time><thread ref="2"/><process ref="4"/><weight ref="6"/><tagged-backtrace ref="7"/></row>
<row><sample-time id="14" fmt="00:00.200.000">200000000</sample-time><thread id="15" fmt="worker (0x2) (App, pid: 7)"><tid id="16" fmt="0x2">2</tid><process ref="4"/></thread><process ref="4"/><weight ref="6"/><tagged-backtrace id="17"><frame ref="12"/></tagged-backtrace></row>
</node></trace-query-result>"""

POTENTIAL_HANGS_XML = """<?xml version="1.0"?>
<trace-query-result>
<node xpath='//trace-toc[1]/run[1]/data[1]/table[10]'><schema name="potential-hangs"><col><mnemonic>start</mnemonic><name>Start</name><engineering-type>start-time</engineering-type></col><col><mnemonic>duration</mnemonic><name>Duration</name><engineering-type>duration</engineering-type></col><col><mnemonic>hang-type</mnemonic><name>Hang Type</name><engineering-type>hang-type</engineering-type></col><col><mnemonic>thread</mnemonic><name>Thread</name><engineering-type>thread</engineering-type></col><col><mnemonic>process</mnemonic><name>Process</name><engineering-type>process</engineering-type></col></schema><row><start-time id="1" fmt="00:02.223.897">2223897125</start-time><duration id="2" fmt="300.04 ms">300043333</duration><hang-type id="3" fmt="Microhang">Microhang</hang-type><thread id="4" fmt="Main Thread (0x149cf37) (LabUI, pid: 12249)"><tid id="5" fmt="0x149cf37">21614391</tid><process id="6" fmt="LabUI (12249)"><pid id="7" fmt="12249">12249</pid></process></thread><process ref="6"/></row>
<row><start-time id="9" fmt="00:05.223.901">5223901250</start-time><duration id="10" fmt="300.04 ms">300037375</duration><hang-type ref="3"/><thread ref="4"/><process ref="6"/></row>
</node></trace-query-result>"""

LEAKS_XML = """<?xml version="1.0"?>
<trace-query-result>
<node xpath='//trace-toc[1]/run[1]/tracks[1]/track[2]/details[1]/detail[1]'><row leaked-object="Parent" size="32" responsible-frame="&lt;Call stack limit reached&gt;" count="1" responsible-library="" address="0x1"/>
<row leaked-object="Child" size="32" responsible-frame="swift_slowAlloc" count="1" responsible-library="libswiftCore.dylib" address="0x2"/>
<row leaked-object="Malloc 4.00 KiB" size="4096" responsible-frame="swift::swift_slowAllocTyped(unsigned long, unsigned long, unsigned long long)" count="1" responsible-library="libswiftCore.dylib" address="0x3"/>
</node></trace-query-result>"""

ALLOCATION_STATISTICS_XML = """<?xml version="1.0"?>
<trace-query-result>
<node xpath='//trace-toc[1]/run[1]/tracks[1]/track[1]/details[1]/detail[1]'><row category="All Heap &amp; Anonymous VM" persistent-bytes="55445520" count-persistent="122702" total-bytes="506604112" transient-bytes="451158592" count-events="1420553" count-transient="648337" count-total="771039"/>
<row category="All Heap Allocations" persistent-bytes="55445520" count-persistent="122702" total-bytes="506128976" transient-bytes="450683456" count-events="1420543" count-transient="648332" count-total="771034"/>
<row category="_ContiguousArrayStorage&lt;UInt8&gt;" persistent-bytes="31267584" count-persistent="36000" total-bytes="313065216" transient-bytes="281797632" count-events="684000" count-transient="324000" count-total="360000"/>
<row category="Malloc 1.25 KiB" persistent-bytes="7522560" count-persistent="5877" total-bytes="7522560" transient-bytes="0" count-events="5877" count-transient="0" count-total="5877"/>
</node></trace-query-result>"""

EMPTY_HITCHES_XML = """<?xml version="1.0"?>
<trace-query-result>
<node xpath='//trace-toc[1]/run[1]/data[1]/table[66]'><schema name="hitches"><col><mnemonic>start</mnemonic><name>Start</name><engineering-type>start-time</engineering-type></col><col><mnemonic>duration</mnemonic><name>Duration</name><engineering-type>duration</engineering-type></col></schema></node></trace-query-result>"""

TOC_WITH_TRACKS = """<?xml version="1.0"?>
<trace-toc><run number="1"><data><table schema="time-profile"/></data>
<tracks><track name="Allocations"><details><detail kind="table" name="Statistics"/><detail kind="table" name="Allocations List"/></details></track>
<track name="Leaks"><details><detail kind="table" name="Leaks"/></details></track></tracks></run></trace-toc>"""


def write_temp(directory: str, name: str, text: str) -> Path:
    path = Path(directory) / name
    path.write_text(text, encoding="utf-8")
    return path


class HelperTests(unittest.TestCase):
    def test_inventory_parser_removes_headers(self):
        self.assertEqual(
            doctor.inventory_lines("== Standard Templates ==\nTime Profiler\n\nApp Launch\n"),
            ["Time Profiler", "App Launch"],
        )

    def test_xcresult_metric_collection_and_robust_statistics(self):
        payload = {
            "testIdentifier": "AppUITests/testLaunch",
            "testRuns": [
                {
                    "device": {"deviceId": "D1", "deviceName": "iPhone"},
                    "testPlanConfiguration": {"configurationId": "C1", "configurationName": "Default"},
                    "metrics": [
                        {
                            "displayName": "Application Launch",
                            "identifier": "com.apple.XCTPerformanceMetric_ApplicationLaunch",
                            "unitOfMeasurement": "s",
                            "measurements": [1.0, 1.1, 0.9, 1.2],
                        }
                    ],
                }
            ],
        }
        collected = metrics.collect_metrics(payload)
        grouped = metrics.group_metrics(collected)
        self.assertEqual(len(grouped), 1)
        summary = grouped[0]["statistics"]
        self.assertEqual(summary["count"], 4)
        self.assertAlmostEqual(summary["median"], 1.05)
        self.assertEqual(summary["tail_confidence"], "directional")

    def test_recorder_dry_command_is_argument_based_and_redacts_environment(self):
        namespace = argparse.Namespace(
            template="App Launch",
            instrument=[],
            device="D1",
            time_limit="5s",
            window=None,
            run_name="launch-01",
            recording_options=None,
            env=["API_TOKEN=secret"],
            no_prompt=True,
            output=Path("/tmp/launch-01.trace"),
            launch="com.example.app",
            launch_arg=["--perf"],
            attach=None,
            all_processes=False,
        )
        command = recorder.build_command(namespace)
        self.assertEqual(command[:3], ["xcrun", "xctrace", "record"])
        self.assertIn("com.example.app", command)
        rendered = recorder.safe_command_text(command)
        self.assertIn("API_TOKEN=<redacted>", rendered)
        self.assertNotIn("secret", rendered)

    def test_start_evidence_is_recording_marker_not_announcement(self):
        # Lines from xctrace 27.0 beta; a wedged Simulator recorder printed only the first.
        self.assertFalse(recorder.is_start_evidence(
            "Starting recording with the App Launch template. Launching process: com.sparrow.fieldnotes. Time limit: 8.0 s"))
        self.assertTrue(recorder.is_start_evidence("Ctrl-C to stop the recording"))

    def test_exit_54_accepted_only_after_launch_time_limit_save(self):
        saved = (
            "Starting recording with the Time Profiler template. Launching process: sleep. Time limit: 6.0 s\n"
            "Ctrl-C to stop the recording\n"
            "Reached specified time limit, ending recording...\n"
            "Recording completed. Saving output file...\n"
            "Output file saved as: raw.trace\n"
        )
        self.assertTrue(recorder.recorder_exit_accepted(54, True, saved))
        self.assertFalse(recorder.recorder_exit_accepted(54, False, saved))
        self.assertFalse(recorder.recorder_exit_accepted(54, True, saved.replace("Reached specified time limit", "Stopped")))
        self.assertFalse(recorder.recorder_exit_accepted(54, True, saved + "Recording failed with errors. Saving output file...\n"))
        self.assertFalse(recorder.recorder_exit_accepted(2, True, saved))
        self.assertTrue(recorder.recorder_exit_accepted(0, False, ""))

    def test_launch_arguments_may_start_with_a_dash(self):
        # `--launch-arg -XCTest` is rejected by argparse, so arguments after a standalone `--` are passed through.
        own, trailing = recorder.split_trailing_args(
            ["--template", "Time Profiler", "--launch", "/usr/bin/xctest", "--", "-XCTest", "Suite/test", "/tmp/T.xctest"])
        self.assertEqual(own, ["--template", "Time Profiler", "--launch", "/usr/bin/xctest"])
        self.assertEqual(trailing, ["-XCTest", "Suite/test", "/tmp/T.xctest"])
        self.assertEqual(recorder.split_trailing_args(["--template", "Blank"]), (["--template", "Blank"], []))
        namespace = argparse.Namespace(
            template="Time Profiler", instrument=[], device=None, time_limit="20s", window=None, run_name=None,
            recording_options=None, env=[], no_prompt=True, output=Path("/tmp/unit.trace"), launch="/usr/bin/xctest",
            launch_arg=["-XCTest", "Suite/test", "/tmp/T.xctest"], attach=None, all_processes=False,
        )
        self.assertEqual(recorder.build_command(namespace)[-5:],
                         ["--", "/usr/bin/xctest", "-XCTest", "Suite/test", "/tmp/T.xctest"])

    def test_completion_grace_follows_observed_save_times(self):
        # System Trace needed about 315 s and File Activity about 180 s to save 4 s of recording.
        self.assertEqual(recorder.default_completion_grace("Time Profiler", [], 5.0), 120.0)
        self.assertEqual(recorder.default_completion_grace("System Trace", [], 4.0), 600.0)
        self.assertEqual(recorder.default_completion_grace("System Trace", [], 10.0), 1200.0)
        self.assertEqual(recorder.default_completion_grace("File Activity", [], 4.0), 360.0)
        self.assertEqual(recorder.default_completion_grace("Blank", ["Metal GPU Counters"], 4.0), 300.0)
        self.assertEqual(recorder.default_completion_grace("Blank", ["Thread State Trace"], 4.0), 600.0)

    def test_row_gates(self):
        self.assertEqual(recorder.parse_expect_rows("time-profile:50"), ("time-profile", 50))
        self.assertEqual(recorder.parse_expect_rows("potential-hangs"), ("potential-hangs", 1))
        # UC-02: App Launch left the launched target asleep (2 samples in 6 s); UC-02b: Blank + Time Profiler ran.
        self.assertEqual(recorder.launch_activity(2, 6.0, 20)["verdict"], "inactive")
        active = recorder.launch_activity(4870, 5.0, 20)
        self.assertEqual((active["verdict"], active["samples_per_second"]), ("active", 974.0))
        self.assertEqual(recorder.launch_activity(None, 5.0, 20)["verdict"], "unknown")
        log = ("* [Error] Core Animation FPS: Disabled because macOS does not have an FPS metric for Core Animation.\n"
               "Recording failed with errors. Saving output file...\n")
        self.assertEqual(recorder.recorder_errors(log), [log.splitlines()[0]])

    def test_doctor_ignores_devices_listed_offline(self):
        text = (
            "== Devices ==\nStudio Mac (MAC-UDID)\n\n"
            "== Devices Offline ==\nOld iPhone (18.0) (00008101-OFFLINE)\n\n"
            "== Simulators ==\niPhone 17 Pro Simulator (27.0) (SIM-UDID)\n"
        )
        sections = doctor.device_sections(text)
        self.assertEqual(sorted(sections), ["Devices", "Devices Offline", "Simulators"])
        visible, detail = doctor.device_visibility("00008101-OFFLINE", sections)
        self.assertFalse(visible)
        self.assertEqual(detail["reason"], "listed only under an offline section")
        self.assertTrue(doctor.device_visibility("SIM-UDID", sections)[0])
        self.assertTrue(doctor.device_visibility("iPhone 17 Pro", sections)[0])
        self.assertEqual(doctor.device_kind("SIM-UDID", sections), "simulator")
        self.assertEqual(doctor.device_kind("MAC-UDID", sections), "device")
        self.assertIsNone(doctor.device_kind("00008101-OFFLINE", sections))

    def test_doctor_flags_known_bad_toolchain_for_simulators_only(self):
        build = doctor.xctrace_build("xctrace version 16.0 (27A5194q)")
        self.assertEqual(build, "27A5194q")
        on_simulator = {issue["id"]: issue for issue in doctor.known_issues(build, "simulator")}
        self.assertTrue(on_simulator["simulator-recording-never-starts"]["applies_now"])
        self.assertTrue(on_simulator["simulator-recording-never-starts"]["blocking"])
        on_mac = {issue["id"]: issue for issue in doctor.known_issues(build, "device")}
        self.assertFalse(on_mac["simulator-recording-never-starts"]["applies_now"])
        self.assertEqual(doctor.known_issues("99Z999", "simulator"), [])
        plans = doctor.smoke_plans(["Time Profiler"], ["Core Animation Commits", "Core Animation FPS"])
        self.assertEqual([plan["template"] for plan in plans], ["Time Profiler", "Blank"])

    def test_har_availability_comes_from_toc_external_format(self):
        with tempfile.TemporaryDirectory() as directory:
            with_har = Path(directory) / "with-har.xml"
            with_har.write_text(
                "<trace-toc><run number='1'><data><table schema='com-apple-cfnetwork-harlogging-schema'/>"
                "<external-format format='har' source-schema='com-apple-cfnetwork-harlogging-schema'/>"
                "</data></run></trace-toc>",
                encoding="utf-8",
            )
            without_har = Path(directory) / "without-har.xml"
            without_har.write_text("<trace-toc><run number='1'><data><table schema='time-profile'/></data></run></trace-toc>",
                                   encoding="utf-8")
            self.assertEqual([f["format"] for f in exporter.toc_external_formats(with_har)], ["har"])
            self.assertEqual(exporter.toc_external_formats(without_har), [])

    def test_toc_lists_track_details_and_selections_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory = exporter.summarize_toc(write_temp(directory, "toc.xml", TOC_WITH_TRACKS))
        self.assertEqual(inventory["tracks"][0], {
            "run": "1", "track": "Allocations",
            "details": [{"kind": "table", "name": "Statistics"}, {"kind": "table", "name": "Allocations List"}],
        })
        self.assertEqual(inventory["tracks"][1]["details"], [{"kind": "table", "name": "Leaks"}])
        self.assertEqual(exporter.selection_xpath(None, "time-profile", None, None, 1),
                         '/trace-toc/run[@number="1"]/data/table[@schema="time-profile"]')
        self.assertEqual(exporter.selection_xpath(None, None, "Allocations", "Statistics", 1),
                         '/trace-toc/run[@number="1"]/tracks/track[@name="Allocations"]/details/detail[@name="Statistics"]')
        exporter.check_selection(inventory, None, "Leaks", "Leaks", 1)
        with self.assertRaises(RuntimeError):
            exporter.check_selection(inventory, "potential-hangs", None, None, 1)
        with self.assertRaises(RuntimeError):
            exporter.check_selection(inventory, None, "Allocations", "Leaks", 1)

    def test_time_window_must_reduce_rows_to_count_as_applied(self):
        # Xcode 27 beta 27A5194q returned byte-identical exports with and without a window.
        self.assertEqual(exporter.window_effect(1100, 3346), "applied")
        self.assertEqual(exporter.window_effect(3346, 3346), "no-change")
        self.assertEqual(exporter.window_effect(0, 0), "unknown-empty-table")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "rows.xml"
            source.write_text("<trace-query-result><node><row><a/></row><row/><row><row-ish/></row></node></trace-query-result>",
                              encoding="utf-8")
            self.assertEqual(exporter.count_rows(source), 3)

    def test_preview_is_bounded_and_redacts_home_path(self):
        xml = """<?xml version='1.0'?>
<trace-query-result><schema name='time-profile'/>
<row><binary path='/Users/alice/App.app/App'/><weight fmt='1.00 ms'>1000000</weight></row>
<row><binary path='/Users/alice/Other'/></row></trace-query-result>"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.xml"
            source.write_text(xml, encoding="utf-8")
            namespace = argparse.Namespace(
                input=source,
                max_input_bytes=1024 * 1024,
                max_rows=1,
                max_nodes_per_row=10,
                max_depth=4,
                max_text=100,
                save=None,
                force=False,
            )
            result = exporter.preview(namespace)
        self.assertEqual(result["schemas_seen"], ["time-profile"])
        self.assertEqual(result["rows_collected"], 1)
        self.assertTrue(result["truncated"])
        self.assertNotIn("alice", json.dumps(result))

    def test_profile_reducer_resolves_refs_and_ranks_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_temp(directory, "time-profile.xml", TIME_PROFILE_XML)
            result = reducer.reduce_file(path)
            worker = reducer.reduce_file(path, filters=reducer.Filters(thread="worker"))
            late = reducer.reduce_file(path, filters=reducer.Filters(start_ms=150))
            other = reducer.reduce_file(path, filters=reducer.Filters(process="Other"))
        summary = result["summary"]
        self.assertEqual((result["analyzer"], summary["samples"], summary["total_weight"]), ("profile", 3, 3.0))
        self.assertEqual(summary["top_self"][0], {"function": "memcpy [libsystem_platform.dylib]", "samples": 2,
                                                  "share": 0.6667, "weight": 2.0})
        self.assertEqual(summary["top_inclusive"][0]["function"], "main [App]")
        self.assertEqual(summary["top_inclusive"][0]["share"], 1.0)
        self.assertEqual([item["function"] for item in summary["top_app_frames"]], ["parse() [App]", "main [App]"])
        self.assertEqual(summary["processes"], [{"value": "App (7)", "count": 3}])
        self.assertEqual((worker["rows_matched"], late["rows_matched"]), (1, 1))
        self.assertEqual(other["status"], "empty")
        self.assertNotIn("alice", json.dumps(result))

    def test_hang_and_detail_reducers(self):
        with tempfile.TemporaryDirectory() as directory:
            hangs = reducer.reduce_file(write_temp(directory, "hangs.xml", POTENTIAL_HANGS_XML))
            leaks = reducer.reduce_file(write_temp(directory, "leaks.xml", LEAKS_XML))
            statistics = reducer.reduce_file(write_temp(directory, "statistics.xml", ALLOCATION_STATISTICS_XML))
            hitches = reducer.reduce_file(write_temp(directory, "hitches.xml", EMPTY_HITCHES_XML))
        self.assertEqual((hangs["summary"]["hangs"], hangs["summary"]["duration"]["median_ms"]), (2, 300.04))
        self.assertEqual(hangs["summary"]["longest"][0]["duration_ms"], 300.043)
        self.assertEqual((leaks["export_kind"], leaks["analyzer"]), ("track-detail", "leaks"))
        self.assertEqual((leaks["summary"]["leaked_objects"], leaks["summary"]["without_stack"]), (3, 1))
        self.assertEqual(leaks["summary"]["by_object"][0]["object"], "Malloc 4.00 KiB")
        overall = statistics["summary"]["overall"]
        self.assertEqual((overall["live_mb"], overall["allocated_mb"]), (55.45, 506.6))
        self.assertEqual(statistics["summary"]["top_live_categories"][0]["category"], "_ContiguousArrayStorage<UInt8>")
        self.assertEqual((hitches["analyzer"], hitches["status"]), ("frames", "empty"))
        self.assertTrue(any("not captured" in note for note in hitches["notes"]))

    def test_baseline_comparison_needs_samples_and_an_interval_clear_of_zero(self):
        baseline = [1.0, 1.1, 0.9, 1.0, 1.05]
        slower = metrics.compare_values(baseline, [value + 1.0 for value in baseline], "prefers smaller")
        self.assertEqual(slower["verdict"], "regression")
        self.assertAlmostEqual(slower["median_delta"], 1.0)
        self.assertAlmostEqual(slower["median_delta_percent"], 100.0)
        same = metrics.compare_values(baseline, [1.05, 1.0, 0.9, 1.1, 1.0], "prefers smaller")
        self.assertEqual(same["verdict"], "no-clear-change")
        self.assertEqual(metrics.compare_values([1.0, 2.0], [3.0, 4.0], "prefers smaller")["verdict"], "insufficient-data")
        group = {"test_identifier": "T/test", "display_name": "Duration", "unit": "s", "baseline": {"polarity": "prefers smaller"}}
        before = [{**group, "device": {"deviceId": "A"}, "statistics": metrics.stats(baseline)}]
        after = [{**group, "device": {"deviceId": "B"}, "statistics": metrics.stats([value + 1.0 for value in baseline])}]
        self.assertEqual(metrics.compare_groups(before, after, "test-and-metric", True, 500)["pairs"], [])
        crossed = metrics.compare_groups(before, after, "test-and-metric", False, 500)
        self.assertEqual([pair["verdict"] for pair in crossed["pairs"]], ["regression"])


if __name__ == "__main__":
    unittest.main()
