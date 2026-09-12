#!/usr/bin/env python3
"""Meaningful offline invariants; no simulator, debugger, or network needed."""

import copy
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).with_name("ui_evidence.py")
SPEC = importlib.util.spec_from_file_location("ui_evidence", SCRIPT)
ui = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ui)


def node(identifier="v:0x1", semantic="save", parent=None):
    result = {"id": identifier, "kind": "view", "class": "UIButton", "parentId": parent,
              "geometry": {"coordinateSpace": "screen-points", "frame": {"x": 0, "y": 0, "width": 20, "height": 20},
                           "screenFrame": {"x": 0, "y": 0, "width": 20, "height": 20},
                           "screenQuad": [{"x": 0, "y": 0}, {"x": 20, "y": 0}, {"x": 20, "y": 20}, {"x": 0, "y": 20}]},
              "properties": {"hidden": False, "alpha": 1.0}, "layout": {"ambiguous": False}}
    if semantic is not None:
        result["accessibilityIdentifier"] = semantic
    return result


def capture(nodes=None, capture_id="c1", truncated=False):
    return {"schemaVersion": ui.SCHEMA, "capture": {"id": capture_id, "timestamp": "2026-09-08T12:00:00Z",
            "provider": "test-native", "coherence": "atomic", "limitations": [], "truncated": truncated,
            "windows": [{"id": "v:0xwindow", "orientation": "portrait", "screenScale": 3,
                         "screenBounds": {"x": 0, "y": 0, "width": 390, "height": 844}}]},
            "target": {"bundleId": "example.test", "pid": 1}, "nodes": [node()] if nodes is None else nodes}


class EvidenceTests(unittest.TestCase):
    def test_geometry_only_change_found_with_new_pointer(self):
        before = capture()
        after = copy.deepcopy(before)
        after["capture"]["id"] = "c2"
        after["nodes"][0]["id"] = "v:0xabcdef"
        after["nodes"][0]["geometry"]["frame"]["width"] = 14
        result = ui.diff(ui.validate(before), ui.validate(after), 10)
        self.assertEqual(result["matchedCount"], 1)
        self.assertEqual(result["changedCount"], 1)
        self.assertEqual(result["changed"][0]["changes"][0]["path"], "/geometry/frame/width")
        self.assertTrue(result["geometryComparable"])

    def test_relaunch_address_churn_in_constraints_is_not_a_change(self):
        # Shape of a live LayoutFixture relaunch: every constraint, item and guide address differs.
        def relaunched(capture_id, base, alpha):
            card, label = node("v:0x%x" % base, "checkout.card"), node("v:0x%x" % (base + 1), "checkout.total", "v:0x%x" % base)
            label["properties"]["textColor"] = {"a": alpha}
            label["layout"]["constraintsAffectingHorizontal"] = [
                {"id": "c:0x%x" % (base + 100 + i), "firstItem": {"kind": "view", "id": label["id"], "class": "UILabel"},
                 "secondItem": {"kind": "layoutGuide", "id": "g:0x%x" % (base + 200 + i), "owningViewId": card["id"]},
                 "constant": 16} for i in range(20)]
            return capture([card, label], capture_id)
        result = ui.diff(ui.validate(relaunched("c1", 0x1000, 0.3)), ui.validate(relaunched("c2", 0x9000, 1.0)), 10)
        self.assertEqual(result["changedCount"], 1)
        self.assertEqual([c["path"] for c in result["changed"][0]["changes"]], ["/properties/textColor/a"])
        self.assertFalse(result["changed"][0]["changesLimited"])

    def test_constraint_retargeted_to_other_identified_view_is_reported(self):
        before = capture([node("a", "first"), node("b", "second"), node("c", "third")])
        before["nodes"][2]["constraints"] = [{"id": "c:0x1", "firstItem": {"kind": "view", "id": "c"},
                                              "secondItem": {"kind": "view", "id": "a"}}]
        after = capture([node("a2", "first"), node("b2", "second"), node("c2", "third")], "c2")
        after["nodes"][2]["constraints"] = [{"id": "c:0x2", "firstItem": {"kind": "view", "id": "c2"},
                                             "secondItem": {"kind": "view", "id": "b2"}}]
        result = ui.diff(ui.validate(before), ui.validate(after), 10)
        self.assertEqual(result["changedCount"], 1)
        change = result["changed"][0]["changes"][0]
        self.assertEqual(change["path"], "/constraints/0/secondItem/id")
        self.assertEqual((change["before"], change["after"]),
                         ("identity:accessibilityIdentifier:first", "identity:accessibilityIdentifier:second"))

    def test_bounded_change_list_keeps_geometry_and_properties_before_layout(self):
        before = capture()
        before["nodes"][0]["layout"]["constraintsAffectingVertical"] = [{"constant": i} for i in range(60)]
        after = copy.deepcopy(before)
        after["capture"]["id"] = "c2"
        for item in after["nodes"][0]["layout"]["constraintsAffectingVertical"]:
            item["constant"] += 1
        after["nodes"][0]["geometry"]["frame"]["height"] = 30
        after["nodes"][0]["properties"]["alpha"] = 0.5
        changed = ui.diff(ui.validate(before), ui.validate(after), 10)["changed"][0]
        self.assertEqual([c["path"] for c in changed["changes"][:2]], ["/geometry/frame/height", "/properties/alpha"])
        self.assertEqual(len(changed["changes"]), ui.MAX_CHANGES)
        self.assertTrue(changed["changesLimited"])

    def test_reused_address_never_connects_unknown_nodes(self):
        before, after = capture([node(semantic=None)]), capture([node(semantic=None)], "c2")
        after["nodes"][0]["class"] = "UIImageView"
        result = ui.diff(ui.validate(before), ui.validate(after), 10)
        self.assertEqual(result["matchedCount"], 0)
        self.assertEqual(result["unmatchedBeforeCount"], 1)
        self.assertEqual(result["unmatchedAfterCount"], 1)

    def test_duplicate_semantic_ids_never_match_or_resolve(self):
        before = capture([node("v:1"), node("v:2")])
        after = capture([node("v:3")], "c2")
        result = ui.diff(ui.validate(before), ui.validate(after), 10)
        self.assertEqual(result["matchedCount"], 0)
        self.assertEqual(result["ambiguousIdentityCount"], 1)
        with self.assertRaisesRegex(ui.EvidenceError, "Ambiguous"):
            ui.query(ui.validate(before), accessibility="save")

    def test_authored_semantic_id_has_priority(self):
        before, after = capture(), capture(capture_id="c2")
        before["nodes"][0]["semanticId"] = after["nodes"][0]["semanticId"] = "authored.save"
        after["nodes"][0]["accessibilityIdentifier"] = "changed.save"
        result = ui.diff(ui.validate(before), ui.validate(after), 10)
        self.assertEqual(result["matchedCount"], 1)
        self.assertEqual(result["changed"][0]["identity"], "semanticId:authored.save")

    def test_rotated_quad_excludes_bounding_box_corner(self):
        raw = capture()
        raw["nodes"][0]["geometry"]["screenQuad"] = [{"x": 10, "y": 0}, {"x": 20, "y": 10}, {"x": 10, "y": 20}, {"x": 0, "y": 10}]
        evidence = ui.validate(raw)
        self.assertEqual(ui.point(evidence, 1, 1, 10)["candidateCount"], 0)
        self.assertEqual(ui.point(evidence, 10, 10, 10)["candidateCount"], 1)
        self.assertEqual(ui.point(evidence, 10, 0, 10)["candidateCount"], 1)
        raw["nodes"][0]["geometry"]["screenQuad"].reverse()
        self.assertEqual(ui.point(ui.validate(raw), 10, 10, 10)["candidateCount"], 1)

    def test_degenerate_quad_never_falls_back_to_bounding_box(self):
        raw = capture()
        raw["nodes"][0]["geometry"]["screenQuad"] = [{"x": 10, "y": 10}] * 4
        result = ui.point(ui.validate(raw), 10, 10, 10)
        self.assertEqual(result["candidateCount"], 0)
        self.assertEqual(result["skipped"]["degenerateOrNonConvexQuad"], 1)

    def test_geometry_candidates_do_not_filter_hidden(self):
        raw = capture()
        raw["nodes"][0]["properties"]["hidden"] = True
        result = ui.point(ui.validate(raw), 10, 10, 10)
        self.assertEqual(result["candidateCount"], 1)
        self.assertIn("no visibility", result["interpretation"])

    def test_missing_quad_or_coordinate_space_skipped(self):
        raw = capture([node("a"), node("b", "other")])
        del raw["nodes"][0]["geometry"]["screenQuad"]
        raw["nodes"][1]["geometry"]["coordinateSpace"] = "window-points"
        result = ui.point(ui.validate(raw), 10, 10, 10)
        self.assertEqual(result["candidateCount"], 0)
        self.assertEqual(result["skipped"], {"missingScreenQuad": 1, "coordinateSpaceNotScreenPoints": 1})

    def test_absent_geometry_reported_distinctly(self):
        raw = capture()
        del raw["nodes"][0]["geometry"]
        result = ui.point(ui.validate(raw), 10, 10, 10)
        self.assertEqual(result["candidateCount"], 0)
        self.assertEqual(result["skipped"], {"missingGeometry": 1})

    def test_native_nonfinite_null_geometry_preserved_as_unknown(self):
        raw = capture()
        raw["nodes"][0]["geometry"]["frame"].update(x=None, finite=False)
        raw["nodes"][0]["geometry"]["screenQuad"][0]["x"] = None
        evidence = ui.validate(raw)
        self.assertTrue(any("unknown" in warning for warning in evidence["warnings"]))
        result = ui.point(evidence, 10, 10, 10)
        self.assertEqual(result["candidateCount"], 0)
        self.assertEqual(result["skipped"], {"unknownNonfiniteQuad": 1})
        raw["nodes"][0]["geometry"]["frame"]["x"] = "bad"
        with self.assertRaises(ui.EvidenceError):
            ui.validate(raw)

    def test_point_window_filter_prevents_display_collision(self):
        raw = capture([node("a", "first"), node("b", "second")])
        raw["nodes"][0]["windowId"] = "screen1.window"
        raw["nodes"][1]["windowId"] = "screen2.window"
        evidence = ui.validate(raw)
        self.assertTrue(any("multiple windows" in warning for warning in ui.point(evidence, 10, 10, 10)["warnings"]))
        result = ui.point(evidence, 10, 10, 10, "screen2.window")
        self.assertEqual([n["id"] for n in result["candidates"]], ["b"])
        with self.assertRaises(ui.EvidenceError):
            ui.point(evidence, 10, 10, 10, "unknown.window")

    def test_invalid_schema_duplicate_id_and_cycle_rejected(self):
        for raw in ({"role": "AXApplication"}, capture([node("a"), node("a")]),
                    capture([node("a", parent="b"), node("b", "other", "a")])):
            with self.subTest(raw=raw):
                with self.assertRaises(ui.EvidenceError):
                    ui.validate(raw)

    def test_dangling_parent_requires_truncated_capture(self):
        raw = capture([node(parent="absent")])
        with self.assertRaisesRegex(ui.EvidenceError, "Dangling"):
            ui.validate(raw)
        raw["capture"]["truncated"] = True
        evidence = ui.validate(raw)
        self.assertTrue(any("absent parents" in warning for warning in evidence["warnings"]))
        self.assertTrue(any("truncated" in warning for warning in ui.summary(evidence, 10)["warnings"]))

    def test_context_mismatch_flagged_without_pointer_noise(self):
        before, after = capture(), capture(capture_id="c2")
        after["capture"]["windows"][0]["id"] = "v:DIFFERENT"
        result = ui.diff(ui.validate(before), ui.validate(after), 10)
        self.assertEqual(result["comparisonContextMismatches"], [])
        after["capture"]["windows"][0]["orientation"] = "landscapeLeft"
        after["target"]["bundleId"] = "other.app"
        result = ui.diff(ui.validate(before), ui.validate(after), 10)
        self.assertFalse(result["geometryComparable"])
        self.assertEqual(len(result["comparisonContextMismatches"]), 2)

    def test_query_depth_ancestors_and_limit_do_not_mutate_evidence(self):
        raw = capture([node("root", "root"), node("child", "child", "root"), node("leaf", "leaf", "child")])
        original = copy.deepcopy(raw)
        evidence = ui.validate(raw)
        shallow = ui.query(evidence, identifier="root", depth=1)
        self.assertEqual([n["id"] for n in shallow["nodes"]], ["root", "child"])
        limited = ui.query(evidence, identifier="leaf", ancestors=True, limit=2)
        self.assertEqual(limited["selectedCount"], 3)
        self.assertEqual(len(limited["nodes"]), 2)
        self.assertTrue(limited["outputLimited"])
        self.assertEqual(raw, original)

    def test_overlapping_class_queries_expand_each_node_once(self):
        raw = capture([node(str(i), str(i), str(i - 1) if i else None) for i in range(1000)])
        result = ui.query(ui.validate(raw), class_name="UIButton", depth=100, limit=5)
        self.assertEqual(result["selectedCount"], 1000)
        self.assertEqual(result["returnedCount"], 5)

    def test_stable_reparenting_detected_unknown_parent_not_invented(self):
        before = capture([node("parentA", "parentA"), node("parentB", "parentB"), node("child", "child", "parentA")])
        after = copy.deepcopy(before)
        after["nodes"][2]["parentId"] = "parentB"
        result = ui.diff(ui.validate(before), ui.validate(after), 10)
        self.assertEqual(result["changedCount"], 1)
        self.assertEqual(result["changed"][0]["changes"][0]["path"], "/relationships/parent")
        del before["nodes"][0]["accessibilityIdentifier"]
        result = ui.diff(ui.validate(before), ui.validate(after), 10)
        self.assertEqual(result["changedCount"], 0)
        self.assertEqual(result["parentComparisonsUnknownCount"], 1)

    def test_change_paths_bounded_and_missing_distinct_from_null(self):
        changes, limited = ui.property_changes({}, {str(i): None for i in range(100)}, limit=3)
        self.assertEqual(len(changes), 3)
        self.assertTrue(limited)
        self.assertFalse(changes[0]["beforePresent"])
        self.assertTrue(changes[0]["afterPresent"])
        changes, _ = ui.property_changes({"enabled": 1}, {"enabled": True})
        self.assertEqual(changes[0]["path"], "/enabled")

    def test_stdout_hard_budget_reduces_payload_and_retains_counts(self):
        raw = capture([node(str(i), str(i)) for i in range(30)])
        for item in raw["nodes"]:
            item["properties"]["sample"] = ["π" * 1000] * 40
        result = ui.query(ui.validate(raw), class_name="UIButton", limit=50)
        encoded = ui.encode_bounded(result)
        self.assertLessEqual(len(encoded.encode("utf-8")) + 1, ui.MAX_STDOUT_BYTES)
        decoded = json.loads(encoded)
        self.assertTrue(decoded["outputLimited"])
        self.assertEqual(decoded["selectedCount"], 30)
        self.assertLess(decoded["returnedCount"], 30)
        self.assertEqual(len(result["nodes"]), 30)

    def test_stdout_budget_also_bounds_large_metadata(self):
        result = {"operation": "summary", "capture": {"id": "c1", "payload": ["x" * 10000] * 100}}
        encoded = ui.encode_bounded(result)
        self.assertLessEqual(len(encoded.encode("utf-8")) + 1, ui.MAX_STDOUT_BYTES)
        self.assertTrue(json.loads(encoded)["outputLimited"])

    def test_invalid_numbers_and_node_count(self):
        raw = capture()
        raw["nodes"][0]["geometry"]["frame"]["x"] = float("inf")
        with self.assertRaises(ui.EvidenceError):
            ui.validate(raw)
        with self.assertRaises(ui.EvidenceError):
            ui.validate(capture([node(str(i)) for i in range(ui.MAX_NODES + 1)]))

    def test_cgrect_infinite_sentinel_preserved_and_excluded_from_point(self):
        raw = capture()
        geometry = raw["nodes"][0]["geometry"]
        geometry["screenFrame"] = dict(x=None, y=None, width=None, height=None,
                                       finite=False, specialValue="CGRectInfinite")
        geometry["screenQuad"] = [dict(x=None, y=None) for _ in range(4)]
        original = copy.deepcopy(raw)
        evidence = ui.validate(raw)
        result = ui.point(evidence, 10, 10, 10)
        self.assertEqual(result["candidateCount"], 0)
        self.assertEqual(result["skipped"], {"unknownNonfiniteQuad": 1})
        self.assertEqual(raw, original)
        self.assertEqual(ui.query(evidence, identifier="v:0x1")["nodes"][0]["geometry"]["screenFrame"]["specialValue"], "CGRectInfinite")

    def test_cli_json_error_and_input_byte_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp, "input.json")
            path.write_text(json.dumps(capture()), encoding="utf-8")
            process = subprocess.run([sys.executable, str(SCRIPT), "summary", str(path)], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0)
            self.assertEqual(json.loads(process.stdout)["nodeCount"], 1)
            process = subprocess.run([sys.executable, str(SCRIPT), "query", str(path), "--id", "absent"], capture_output=True, text=True)
            self.assertEqual(process.returncode, 2)
            self.assertIn("error", json.loads(process.stdout))
            path.write_text('{"schemaVersion":"a","schemaVersion":"b"}', encoding="utf-8")
            with self.assertRaisesRegex(ui.EvidenceError, "Duplicate JSON"):
                ui.load(path)
            with path.open("wb") as stream:
                stream.truncate(ui.MAX_BYTES + 1)
            with self.assertRaisesRegex(ui.EvidenceError, "32 MiB"):
                ui.load(path)


if __name__ == "__main__":
    unittest.main()
