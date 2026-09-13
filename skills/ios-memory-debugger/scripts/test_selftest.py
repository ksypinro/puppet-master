#!/usr/bin/env python3
"""Self-test for this skill's classification logic.

    python3 scripts/test_selftest.py              offline checks only
    python3 scripts/test_selftest.py --graph G     also check a real .memgraph

Offline checks need no Xcode and no graph. They guard the judgements that
would otherwise report something false about an application's memory.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


util = _load("memgraph_util")
dom = _load("memgraph_dominator")


class ArtifactClassification(unittest.TestCase):
    """Six failure classes the Apple readers cannot tell apart afterwards."""

    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp(prefix="memselftest-"))
        (cls.dir / "empty.memgraph").write_bytes(b"")
        (cls.dir / "bogus.memgraph").write_bytes(b"not a memory graph at all")
        (cls.dir / "tiny.memgraph").write_bytes(b"MEMGRAPH" + b"\0" * 100)
        (cls.dir / "big.memgraph").write_bytes(b"MEMGRAPH" + b"\0" * 20000)
        (cls.dir / "plist.memgraph").write_bytes(b"bplist00" + b"\0" * 20000)
        noperm = cls.dir / "noperm.memgraph"
        noperm.write_bytes(b"MEMGRAPH" + b"\0" * 20000)
        noperm.chmod(0)
        (cls.dir / "adir.memgraph").mkdir()

    def _status(self, name):
        return util.classify_artifact(self.dir / name)["status"]

    def test_missing(self):
        self.assertEqual(self._status("nope.memgraph"), "missing")

    def test_empty_is_not_confused_with_malformed(self):
        # The readers give both "isn't in the correct format". A stat does not.
        self.assertEqual(self._status("empty.memgraph"), "empty")
        self.assertEqual(self._status("bogus.memgraph"), "unknown-format")

    def test_truncated_is_rejected_before_a_reader_aborts(self):
        self.assertEqual(self._status("tiny.memgraph"), "too-small")

    def test_directory(self):
        self.assertEqual(self._status("adir.memgraph"), "not-a-file")

    def test_no_permission(self):
        if os.geteuid() == 0:
            self.skipTest("running as root; permission check is meaningless")
        self.assertEqual(self._status("noperm.memgraph"), "no-permission")

    def test_both_graph_signatures_are_accepted(self):
        """MEMGRAPH comes from --fullStackHistory; bplist00 from a plain capture.

        Demanding the documented MEMGRAPH magic rejects every ordinary capture.
        """
        mem = util.classify_artifact(self.dir / "big.memgraph")
        plist = util.classify_artifact(self.dir / "plist.memgraph")
        self.assertEqual(mem["status"], "ok")
        self.assertEqual(plist["status"], "ok")
        self.assertTrue(mem["fullStackHistory"])
        self.assertFalse(plist["fullStackHistory"])


class SignalDetection(unittest.TestCase):
    """A truncated graph aborts the readers. The shell and Python disagree on how."""

    def test_shell_and_python_signal_conventions(self):
        self.assertTrue(util.died_on_signal(134))   # shell: 128 + SIGABRT
        self.assertTrue(util.died_on_signal(-6))    # python subprocess
        self.assertTrue(util.died_on_signal(-9))    # SIGKILL

    def test_ordinary_exits_are_not_signals(self):
        for status in (0, 1, 2, 127, 255, None):
            self.assertFalse(util.died_on_signal(status), status)


class LeaksExitSemantics(unittest.TestCase):
    """Half of leaks' modes return 0 whether or not leaks exist."""

    def test_modes_that_encode_the_finding(self):
        for mode in ([], ["--fullStacks"], ["--groupByType"], ["--diffFrom=x"]):
            self.assertTrue(util.exit_carries_finding(mode), mode)

    def test_modes_that_do_not(self):
        for mode in (["--referenceTree"], ["--autoreleasePools"],
                     ["--debug=layout"], ["--trace=0x1"], ["--traceTree=0x1"]):
            self.assertFalse(util.exit_carries_finding(mode), mode)

    def test_exit_one_means_leaks_only_for_carrying_modes(self):
        found = util.interpret_leaks(
            {"exit": 1, "stdout": "", "stderr": "", "timedOut": False}, [])
        self.assertEqual(found["finding"], "leaks-found")

    def test_exit_zero_in_a_noncarrying_mode_is_unknown_not_clean(self):
        """The trap: --referenceTree returns 0 on a graph with four leaks."""
        verdict = util.interpret_leaks(
            {"exit": 0, "stdout": "some tree output", "stderr": "",
             "timedOut": False}, ["--referenceTree"])
        self.assertEqual(verdict["finding"], "unknown")
        self.assertIn("returns 0 whether or not", verdict["note"])

    def test_a_summary_line_always_wins_over_the_exit_code(self):
        verdict = util.interpret_leaks(
            {"exit": 0, "timedOut": False, "stderr": "",
             "stdout": "Process 1: 4 leaks for 82032 total leaked bytes.\n"},
            ["--referenceTree"])
        self.assertEqual(verdict["finding"], "leaks-found")
        self.assertEqual(verdict["leakCount"], 4)
        self.assertEqual(verdict["leakedBytes"], 82032)

    def test_a_crash_never_reports_a_finding(self):
        for status in (134, -6):
            verdict = util.interpret_leaks(
                {"exit": status, "stdout": "", "stderr": "NSRangeException",
                 "timedOut": False}, [])
            self.assertEqual(verdict["operation"], "crashed")
            self.assertEqual(verdict["finding"], "unknown")

    def test_an_error_never_reports_zero_leaks(self):
        verdict = util.interpret_leaks(
            {"exit": 255, "stdout": "", "stderr": "unable to read input graph",
             "timedOut": False}, [])
        self.assertEqual(verdict["operation"], "failed")
        self.assertNotEqual(verdict["finding"], "no-leaks-detected")


class SizeParsing(unittest.TestCase):
    """The dominator tree mixes units within one output."""

    def test_all_observed_unit_forms(self):
        cases = {"978K": 1001472, "64 bytes": 64, "82.5K": 84480,
                 "163840 bytes": 163840, "1 MB": 1048576, "256 bytes": 256}
        for text, expected in cases.items():
            self.assertEqual(dom.parse_size(text), expected, text)

    def test_unparseable_returns_none(self):
        for bad in ("", "lots", "12 furlongs", "K"):
            self.assertIsNone(dom.parse_size(bad), bad)


class DominatorLineParsing(unittest.TestCase):
    """Depth lives in the trailing whitespace and must not be stripped.

    `+ ! ` and `+ !   ` are different depths distinguished ONLY by trailing
    spaces. An rstrip() here silently flattens the ownership chain.
    """

    SAMPLE = "\n".join([
        "    1472 (978K) << TOTAL >>",
        "      8 (176K) VM: __DATA  0x1027a8000-0x1027ac000 [V=16K] rw-/rw-",
        "      + 4 (160K) retainedCache --> <NSMutableArray 0x1030a19a0> [48]",
        "      + ! 3 (160K) <NSMutableArray (Storage) 0x1030a10e0> [16]",
        "      + !   2 (160K) <NSConcreteMutableData 0x1030a19f0> [48]",
        "      + !     1 (160K) <NSConcreteMutableData (Bytes Storage) 0x8d9800000> [163840]",
        "      + 1 (32 bytes) <Class.data (class_rw_t) 0x8d9002ba0> [32]",
    ])

    def _rows(self):
        rows, stack = [], []
        for line in self.SAMPLE.splitlines():
            m = dom.DOM_LINE.match(line)
            self.assertIsNotNone(m, line)
            width = len(m.group("indent"))
            while stack and stack[-1][0] >= width:
                stack.pop()
            rows.append({"depth": len(stack), "rest": m.group("rest"),
                         "size": dom.parse_size(m.group("size")),
                         "count": int(m.group("count"))})
            stack.append((width, len(rows) - 1))
        return rows

    def test_every_line_parses(self):
        self.assertEqual(len(self._rows()), 7)

    def test_depth_increases_through_the_chain(self):
        depths = [r["depth"] for r in self._rows()]
        self.assertEqual(depths[:6], [0, 1, 2, 3, 4, 5],
                         "trailing spaces carry depth; do not strip them")

    def test_a_sibling_returns_to_the_parent_depth(self):
        rows = self._rows()
        self.assertEqual(rows[6]["depth"], rows[2]["depth"])

    def test_retained_size_is_constant_down_a_chain(self):
        chain = [r["size"] for r in self._rows()[2:6]]
        self.assertEqual(len(set(chain)), 1,
                         "every link of an ownership chain retains the same total")

    def test_node_and_reference_extraction(self):
        rest = "retainedCache --> <NSMutableArray 0x1030a19a0> [48]"
        node = dom.NODE.search(rest)
        ref = dom.REF.match(rest)
        self.assertEqual(node.group("class"), "NSMutableArray")
        self.assertEqual(node.group("addr"), "0x1030a19a0")
        self.assertEqual(node.group("bytes"), "48")
        self.assertEqual(ref.group("ref").strip(), "retainedCache")

    def test_vm_rows_are_recognised(self):
        self.assertEqual(
            dom.VM_ROW.match("VM: __DATA  0x1-0x2 [V=16K] rw-/rw-").group("region"),
            "__DATA")


class HistoryModes(unittest.TestCase):
    def test_peak_mode_requests_full_logging_semantics(self):
        self.assertIn("-highWaterMark", dom.HISTORY_MODES["peak"])

    def test_every_mode_is_an_argument_list(self):
        for name, args in dom.HISTORY_MODES.items():
            self.assertTrue(args and all(a.startswith("-") for a in args), name)


class GraphChecks(unittest.TestCase):
    """Only with --graph. Requires macOS and Xcode."""
    graph: Path = None

    def setUp(self):
        if not self.graph:
            self.skipTest("no --graph supplied")

    def test_real_graph_classifies_and_probes_clean(self):
        info = util.require_graph(self.graph)
        self.assertEqual(info["status"], "ok")
        self.assertEqual(info["probe"], "ok")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--graph", type=Path)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    if args.graph:
        GraphChecks.graph = args.graph.expanduser().resolve()

    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
