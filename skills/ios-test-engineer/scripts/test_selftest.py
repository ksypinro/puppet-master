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
