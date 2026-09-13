#!/usr/bin/env python3
"""Self-test for this skill's classification logic.

    python3 scripts/test_selftest.py            run the offline checks
    python3 scripts/test_selftest.py --bundle B also check against a real bundle

Offline checks need no Xcode and no bundle. They guard the two pieces of
judgement that would be dangerous to get wrong:

1. Infrastructure signal patterns. A false positive tells the caller to retry a
   real failure, which is the exact mistake this skill exists to prevent. A
   healthy run's testmanagerd.log legitimately contains `(result:error)`,
   `TESTMANAGERD_SIM_SOCK` and `Requesting crash report collection for process
   names: …` -- loose patterns match all three.

2. Coverage region classification. Treating an autoclosure as dead code sends a
   developer hunting for a gap that does not exist.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


test_results = _load("test_results")
coverage_report = _load("coverage_report")
xctest_selection = _load("xctest_selection")
xcresult_util = _load("xcresult_util")


# Real xcodebuild and testmanagerd wording for genuine runner failures.
INFRA_POSITIVE = [
    "Finished executing tests (cancelled: Yes)",
    "Lost connection to the test runner. If you believe this error represents a bug",
    "Failed to establish communication with the test runner.",
    "Failed to install or launch the test runner",
    "The test runner exited with code 1 before finishing running tests.",
    "early unexpected exit, operation never finished bootstrapping",
    "Canceling tests due to timeout in -[MyUITests testFoo]",
    "Test operation failure: Test runner never began executing tests",
    "Unable to lookup in current state: Shutdown",
    "Timed out waiting for the test runner to launch",
    "Failed to boot the simulator",
]

# Lines that appear in a HEALTHY run, or that are product failures. None of
# these may be classified as infrastructure.
INFRA_NEGATIVE = [
    "Got reply to control session initiation request (result:error): <XCTCapabilities>",
    "Calling -[SimDevice getenv:error:] for TESTMANAGERD_SIM_SOCK",
    "Requesting crash report collection for process names: runningboardd, testmanagerd, SpringBoard",
    "Got reply to authorization request for pid 37217 (result:error): 1: (null)",
    "Finished executing tests (cancelled: No)",
    "Parallelization disabled; test execution driven by the test process",
    "Connected socket 36 to testmanagerd for Sim iPhone 17 Pro",
    "FlakyTests.swift:15: error: XCTAssertGreaterThan failed: (\"1\") is not greater than (\"1\")",
    "XCTAssertEqual failed: (\"a\") is not equal to (\"b\")",
]


class DiagnosticSignals(unittest.TestCase):
    def _match(self, line: str):
        return [meaning for pattern, meaning in test_results.DIAG_SIGNALS
                if re.search(pattern, line, re.I)]

    def test_real_runner_failures_are_detected(self):
        for line in INFRA_POSITIVE:
            with self.subTest(line=line[:50]):
                self.assertTrue(self._match(line),
                                f"missed a real infrastructure failure: {line}")

    def test_healthy_and_product_lines_are_not_flagged(self):
        for line in INFRA_NEGATIVE:
            with self.subTest(line=line[:50]):
                self.assertFalse(
                    self._match(line),
                    f"FALSE POSITIVE -- would wrongly justify a retry: {line}")


class FailureTextClassification(unittest.TestCase):
    def test_assertion_failures_are_not_infrastructure(self):
        for text in ("XCTAssertGreaterThan failed: (\"1\") is not greater than (\"1\")",
                     "Expectation failed: value == 42",
                     "#expect(result.isEmpty) failed"):
            self.assertIsNone(test_results._infra_match(text), text)

    def test_runner_failures_are_infrastructure(self):
        for text in ("Lost connection to the test runner",
                     "Unable to lookup in current state: Shutdown",
                     "Failed to install the runner app"):
            self.assertIsNotNone(test_results._infra_match(text), text)


class CoverageRegionClassification(unittest.TestCase):
    def test_synthesised_regions_are_recognised(self):
        for name in ("implicit closure #2 in NoteIndex.init(notes:)",
                     "autoclosure #1 in Foo.bar()",
                     "default argument 0 of Foo.init(x:)",
                     "protocol witness for Equatable.== in conformance Foo",
                     "@objc Foo.bar()"):
            self.assertTrue(coverage_report.SYNTHESISED.search(name), name)

    def test_ordinary_functions_are_not(self):
        for name in ("NoteIndex.search(_:)", "Note.init(id:title:body:tags:)",
                     "ContentView.body.getter"):
            self.assertFalse(coverage_report.SYNTHESISED.search(name), name)

    def test_explanations_name_the_real_cause(self):
        cases = [
            ({"source": "index[key] = Array(Set(index[key] ?? [])).sorted()",
              "enclosingLineHits": 336, "region": "implicit closure #2",
              "syntheticRegion": True}, "fallback"),
            ({"source": 'XCTAssertNotEqual(a, b, "message")',
              "enclosingLineHits": 1, "region": "implicit closure #5",
              "syntheticRegion": True}, "ASSERTION FAILS"),
            ({"source": "|| app.tables.firstMatch.waitForExistence(timeout: 5))",
              "enclosingLineHits": 1, "region": "implicit closure #2",
              "syntheticRegion": True}, "short-circuited"),
        ]
        for entry, expected in cases:
            with self.subTest(expected=expected):
                self.assertIn(expected, coverage_report._explain(entry))


class ArchiveParsing(unittest.TestCase):
    def test_multiline_hits_are_all_parsed(self):
        """Regression: the pattern needs re.M or only line 1 ever matches."""
        sample = "  1: *\n 11: 4927\n 47: 336 [\n(1, 26, 21)\n]\n 68: 2201 [\n"
        hits = {int(m.group(1)): m.group(2)
                for m in coverage_report.ARCHIVE_LINE.finditer(sample)}
        self.assertEqual(hits.get(1), "*")
        self.assertEqual(hits.get(11), "4927")
        self.assertEqual(hits.get(47), "336")
        self.assertEqual(hits.get(68), "2201")


class PathNormalisation(unittest.TestCase):
    """Bundles built under different checkout roots must still compare.

    Without this, CI-versus-laptop coverage reports every file as
    removed+added and fully covered code reads as 0%.
    """

    CI = {"/build/ws/App/Sources/NoteIndex.swift": {},
          "/build/ws/App/Sources/ContentView.swift": {}}
    MAC = {"/Users/sam/dev/App/Sources/NoteIndex.swift": {},
           "/Users/sam/dev/App/Sources/ContentView.swift": {}}

    def test_identical_roots_need_no_work(self):
        a, b, _, strategy = coverage_report._normalise_keys(
            dict(self.CI), dict(self.CI), None)
        self.assertEqual(strategy, "none-needed")
        self.assertEqual(set(a), set(b))

    def test_different_roots_are_reconciled(self):
        a, b, _, strategy = coverage_report._normalise_keys(
            dict(self.CI), dict(self.MAC), None)
        self.assertEqual(strategy, "common-root")
        self.assertEqual(len(set(a) & set(b)), 2,
                         "files under different roots should still match")

    def test_explicit_prefix_is_honoured(self):
        a, b, _, strategy = coverage_report._normalise_keys(
            dict(self.CI), dict(self.CI), "/build/ws")
        self.assertEqual(strategy, "explicit")
        self.assertIn("App/Sources/NoteIndex.swift", a)

    def test_common_root_of_disjoint_paths_is_empty(self):
        self.assertEqual(coverage_report._common_root(["/a/b", "/c/d"]), "")
        self.assertEqual(
            coverage_report._common_root(["/a/b/c.swift", "/a/b/d.swift"]), "/a/b")


class SelectionVerification(unittest.TestCase):
    """A selection that matches nothing exits 0 and looks like a pass.

    `swift test --filter` is a regex over the SYMBOL identifiers that
    `swift test list` prints, not over the @Suite/@Test display names written
    in the source. A filter copied from a display name silently runs nothing.
    Moved here from ios-instruments-profiler, which needed it to avoid wasting
    a measured run; selection is a test concern, so it lives with the tests.
    """

    LISTING = ("Building for debugging...\nBuild complete! (0.33 secs)\n"
               "CoreKitTests.SearchTests/testQuery\n"
               "CoreKitTests.HeavyWorkloadTests/linearSearchIsSlow()\n")

    def test_swiftpm_identifiers_skip_build_noise(self):
        ids = xctest_selection.swiftpm_identifiers(self.LISTING)
        self.assertEqual(ids, ["CoreKitTests.SearchTests/testQuery",
                               "CoreKitTests.HeavyWorkloadTests/linearSearchIsSlow()"])

    def test_filter_matches_symbols_not_display_names(self):
        ids = xctest_selection.swiftpm_identifiers(self.LISTING)
        self.assertEqual(xctest_selection.regex_matches(ids, "HeavyWorkloadTests"),
                         [ids[1]])
        # The @Suite display name matches NOTHING -- and exits 0 in real use.
        self.assertEqual(xctest_selection.regex_matches(ids, "HeavyDemo"), [])

    def test_display_names_are_mapped_back_to_symbols(self):
        names = xctest_selection.display_names(
            '@Suite("HeavyDemo")\nstruct HeavyWorkloadTests {\n'
            '    @Test("Slow path")\n    func linearSearchIsSlow() {}\n}\n')
        self.assertEqual(names.get("HeavyDemo"), "HeavyWorkloadTests")
        self.assertEqual(names.get("Slow path"), "linearSearchIsSlow")

    def test_a_display_name_filter_suggests_the_real_symbol(self):
        ids = xctest_selection.swiftpm_identifiers(self.LISTING)
        names = xctest_selection.display_names(
            '@Suite("HeavyDemo")\nstruct HeavyWorkloadTests {}\n')
        self.assertIn("HeavyWorkloadTests",
                      xctest_selection.suggest("HeavyDemo", ids, names))

    def test_xcodebuild_enumeration_is_flattened(self):
        payload = {"values": [{"kind": "plan", "name": "Fast", "children": [
            {"kind": "target", "name": "AppTests", "children": [
                {"kind": "class", "name": "SearchTests",
                 "children": [{"kind": "test", "name": "testQuery()"}]}]}]}]}
        self.assertEqual(xctest_selection.enumerated_identifiers(payload),
                         ["AppTests/SearchTests/testQuery()"])

    def test_only_testing_matches_on_path_boundaries(self):
        m = xctest_selection.selector_matches
        self.assertTrue(m("AppTests/SearchTests/testQuery()", "AppTests/SearchTests"))
        self.assertTrue(m("AppTests/SearchTests/testQuery()", "AppTests"))
        # A prefix that is not a path boundary must not match.
        self.assertFalse(m("AppTests/SearchTestsExtra/testQuery()",
                           "AppTests/SearchTests"))

    def test_evaluate_reports_an_empty_selection(self):
        ids = xctest_selection.swiftpm_identifiers(self.LISTING)
        names = xctest_selection.display_names('@Suite("HeavyDemo")\nstruct HeavyWorkloadTests {}\n')
        bad = xctest_selection.evaluate(ids, [("filter", "HeavyDemo")], [],
                                        xctest_selection.regex_matches, names)
        self.assertEqual((bad["unmatched_selectors"], bad["selected"]), (1, 0))
        good = xctest_selection.evaluate(ids, [("filter", "SearchTests")], [],
                                         xctest_selection.regex_matches, names)
        self.assertEqual((good["unmatched_selectors"], good["selected"]), (0, 1))


class SharedHelpers(unittest.TestCase):
    """One error class and one bundle validator for the whole skill.

    These lived in three copies with three different error messages until they
    were pulled into xcresult_util. Five separate ToolError classes also meant
    `except ToolError` in one module could not catch another module's failure.
    """

    def test_one_error_class_is_shared(self):
        """Every script's ToolError must come from xcresult_util.

        Asserted by definition site rather than object identity: this test
        module loads helpers through its own loader, so the same class can
        legitimately exist as two objects here while still having one source.
        """
        import compare_runs
        import coverage_report
        import test_results
        for mod in (test_results, coverage_report, compare_runs):
            self.assertEqual(mod.ToolError.__module__, "xcresult_util",
                             f"{mod.__name__} defines its own ToolError")

    def test_no_script_redefines_the_shared_helpers(self):
        """Guard against a copy creeping back in."""
        for name in ("test_results", "coverage_report", "compare_runs"):
            src = (HERE / f"{name}.py").read_text()
            for banned in ("class ToolError(", "def resolve_bundle(",
                           "def xcresulttool("):
                self.assertNotIn(banned, src,
                                 f"{name}.py redefines {banned.strip('(')} -- "
                                 f"import it from xcresult_util instead")

    def test_bundle_validation_rejects_each_bad_shape(self):
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="xcrutil-"))
        cases = {
            "missing": d / "nope.xcresult",
            "a plain file": d / "file.xcresult",
            "directory without Info.plist": d / "shell.xcresult",
        }
        cases["a plain file"].write_text("x")
        cases["directory without Info.plist"].mkdir()
        for label, path in cases.items():
            with self.subTest(label):
                with self.assertRaises(xcresult_util.ToolError):
                    xcresult_util.resolve_bundle(path)

    def test_bundle_validation_accepts_a_real_shape(self):
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="xcrutil-")) / "ok.xcresult"
        d.mkdir(parents=True)
        (d / "Info.plist").write_text("<plist/>")
        self.assertEqual(xcresult_util.resolve_bundle(d).name, "ok.xcresult")

    def test_run_returns_outcome_rather_than_raising(self):
        """Exit codes are data here: xcodebuild and leaks use them for findings."""
        ok = xcresult_util.run(["true"])
        bad = xcresult_util.run(["false"])
        self.assertEqual(ok["exit"], 0)
        self.assertEqual(bad["exit"], 1)
        self.assertFalse(bad["timedOut"])

    def test_run_reports_a_missing_binary_without_raising(self):
        r = xcresult_util.run(["definitely-not-a-real-binary-xyz"])
        self.assertEqual(r["exit"], 127)

    def test_timeouts_are_named_per_operation(self):
        for key in ("read", "compare", "merge", "enumerate"):
            self.assertIsInstance(xcresult_util.TIMEOUTS[key], int)
        # merging N bundles legitimately takes longer than reading one
        self.assertGreater(xcresult_util.TIMEOUTS["merge"],
                           xcresult_util.TIMEOUTS["read"])


class DurationParsing(unittest.TestCase):
    def test_units(self):
        self.assertAlmostEqual(test_results._parse_duration("0.0016s"), 0.0016)
        self.assertAlmostEqual(test_results._parse_duration("250ms"), 0.25)
        self.assertAlmostEqual(test_results._parse_duration("2m"), 120.0)
        self.assertIsNone(test_results._parse_duration(None))
        self.assertIsNone(test_results._parse_duration("unknown"))


class FrameworkDetection(unittest.TestCase):
    def test_xctest_naming(self):
        for n in ("testFoo()", "testSearchPerformance()", "test_legacy()"):
            self.assertEqual(test_results._framework_of(n), "XCTest", n)

    def test_swift_testing_naming(self):
        for n in ("Tokenizer splits and lowercases", "A missing word finds nothing"):
            self.assertEqual(test_results._framework_of(n), "Swift Testing", n)


class BundleChecks(unittest.TestCase):
    """Run only when --bundle is supplied. Requires macOS with Xcode."""
    bundle: Path = None  # set by main()

    def setUp(self):
        if not self.bundle:
            self.skipTest("no --bundle supplied")

    def test_summary_reports_both_counting_rules(self):
        s = test_results.summary(self.bundle)
        self.assertIn("testCases", s["counts"])
        self.assertIn("testRuns", s["counts"])
        self.assertIsInstance(s["counts"]["reconciled"], bool)

    def test_triage_never_crashes(self):
        t = test_results.triage(self.bundle, read_diagnostics=False)
        self.assertIn("hiddenFlakes", t)
        self.assertIn("cleanGreen", t)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bundle", type=Path, help="also check against a real .xcresult")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    if args.bundle:
        BundleChecks.bundle = args.bundle.expanduser().resolve()

    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
