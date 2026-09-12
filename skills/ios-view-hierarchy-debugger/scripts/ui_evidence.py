#!/usr/bin/env python3
"""Offline, bounded queries over ios-ui-evidence/v1 native captures.

Never executes capture content or treats geometry as visibility or hit testing.
Only explicitly authored semantic IDs and unique accessibility identifiers can
connect nodes across captures; process addresses never establish identity.
"""

import argparse
import collections
import json
import math
import pathlib
import sys

SCHEMA = "ios-ui-evidence/v1"
MAX_BYTES = 32 * 1024 * 1024
MAX_NODES = 10000
MAX_CHANGES = 40
MAX_STDOUT_BYTES = 256 * 1024


class EvidenceError(ValueError):
    pass


def finite(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def compact(value, depth=0):
    """Bound individual returned values; source files always remain untouched."""
    if depth >= 10 and isinstance(value, (dict, list)):
        return {"_outputOmitted": "depth-limit"}
    if isinstance(value, str):
        return value if len(value) <= 1024 else value[:1024] + "…[output truncated]"
    if isinstance(value, list):
        result = [compact(item, depth + 1) for item in value[:40]]
        if len(value) > 40:
            result.append({"_outputOmittedItems": len(value) - 40})
        return result
    if isinstance(value, dict):
        result = {key: compact(item, depth + 1) for key, item in list(value.items())[:80]}
        if len(value) > 80:
            result["_outputOmittedFields"] = len(value) - 80
        return result
    return value


def _reject_constant(value):
    raise EvidenceError("Non-finite JSON number: " + value)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError("Duplicate JSON object key: " + key)
        result[key] = value
    return result


def load(path):
    with pathlib.Path(path).open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise EvidenceError("Input exceeds 32 MiB limit")
    try:
        raw = json.loads(data, parse_constant=_reject_constant, object_pairs_hook=_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise EvidenceError("Invalid JSON: " + str(exc)) from exc
    return validate(raw)


def validate(raw):
    stack = [(raw, 0)]
    while stack:
        item, level = stack.pop()
        if level > 64:
            raise EvidenceError("JSON nesting exceeds 64 levels")
        if isinstance(item, dict):
            stack.extend((value, level + 1) for value in item.values())
        elif isinstance(item, list):
            stack.extend((value, level + 1) for value in item)
        elif isinstance(item, (int, float)) and not isinstance(item, bool) and not finite(item):
            raise EvidenceError("Non-finite or excessively large number")
    if not isinstance(raw, dict) or raw.get("schemaVersion") != SCHEMA:
        raise EvidenceError("Expected schemaVersion " + SCHEMA + "; raw AX trees are not native evidence")
    capture = raw.get("capture")
    if not isinstance(capture, dict):
        raise EvidenceError("capture must be an object")
    for field in ("id", "provider", "timestamp"):
        if not isinstance(capture.get(field), str) or not capture[field]:
            raise EvidenceError("capture." + field + " must be a nonempty string")
    if "truncated" in capture and not isinstance(capture["truncated"], bool):
        raise EvidenceError("capture.truncated must be boolean")
    if "target" in raw and not isinstance(raw["target"], dict):
        raise EvidenceError("target must be an object")
    nodes = raw.get("nodes")
    if not isinstance(nodes, list) or len(nodes) > MAX_NODES:
        raise EvidenceError("nodes must be an array with at most 10000 entries")
    by_id = {}
    warnings = []
    if capture.get("truncated"):
        warnings.append("Capture is truncated; absence does not establish nonexistence")
    if capture.get("coherence") != "atomic":
        warnings.append("Capture does not declare atomic coherence; inspect capture.coherence and limitations")
    unknown_geometry = 0
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]:
            raise EvidenceError("Every node requires a nonempty string id")
        if node["id"] in by_id:
            raise EvidenceError("Duplicate node id: " + node["id"])
        if not isinstance(node.get("kind"), str) or not node["kind"]:
            raise EvidenceError("Node " + node["id"] + " requires kind")
        for relation in ("parentId", "windowId"):
            if node.get(relation) is not None and not isinstance(node[relation], str):
                raise EvidenceError(relation + " must be a string or null")
        for bag in ("geometry", "properties", "layout", "layer", "visibility"):
            if bag in node and not isinstance(node[bag], dict):
                raise EvidenceError(bag + " must be an object")
        geometry = node.get("geometry", {})
        for name in ("frame", "bounds", "screenFrame"):
            if name in geometry:
                rect = geometry[name]
                if not isinstance(rect, dict) or not all(k in rect for k in ("x", "y", "width", "height")):
                    raise EvidenceError("Invalid " + name + " for " + node["id"])
                if not all(finite(rect[k]) for k in ("x", "y", "width", "height")):
                    if rect.get("finite") is not False or not all(rect[k] is None or finite(rect[k]) for k in ("x", "y", "width", "height")):
                        raise EvidenceError("Invalid " + name + " for " + node["id"])
                    unknown_geometry += 1
                    continue
                if rect["width"] < 0 or rect["height"] < 0:
                    raise EvidenceError("Negative rectangle size for " + node["id"])
                if any(abs(rect[k]) > 1e12 for k in ("x", "y", "width", "height")):
                    raise EvidenceError("Rectangle coordinate magnitude exceeds 1e12")
        if "screenQuad" in geometry:
            quad = geometry["screenQuad"]
            if not isinstance(quad, list) or len(quad) != 4 or not all(
                isinstance(p, dict) and all(k in p and (p[k] is None or finite(p[k])) for k in ("x", "y")) for p in quad
            ):
                raise EvidenceError("screenQuad requires four numeric-or-null x/y points for " + node["id"])
            if any(p[k] is None for p in quad for k in ("x", "y")):
                unknown_geometry += 1
            if any(p[k] is not None and abs(p[k]) > 1e12 for p in quad for k in ("x", "y")):
                raise EvidenceError("screenQuad coordinate magnitude exceeds 1e12")
        by_id[node["id"]] = node
    if unknown_geometry:
        warnings.append(str(unknown_geometry) + " geometry value(s) contain provider-reported nonfinite or sentinel nulls; treat as unknown")
    dangling = [n["id"] for n in nodes if n.get("parentId") and n["parentId"] not in by_id]
    if dangling:
        if not capture.get("truncated"):
            raise EvidenceError("Dangling parentId in complete capture: " + ", ".join(dangling[:5]))
        warnings.append(str(len(dangling)) + " node(s) have absent parents in truncated capture")
    done = set()
    for identifier in by_id:
        visiting = set()
        cursor = identifier
        while cursor in by_id and cursor not in done:
            if cursor in visiting:
                raise EvidenceError("Cycle in parent hierarchy at " + cursor)
            visiting.add(cursor)
            cursor = by_id[cursor].get("parentId")
        done.update(visiting)
    return {"raw": raw, "nodes": nodes, "by_id": by_id, "warnings": warnings}


def identity(node):
    for field in ("semanticId", "accessibilityIdentifier"):
        value = node.get(field)
        if field == "accessibilityIdentifier" and value is None:
            value = node.get("properties", {}).get(field)
        if isinstance(value, str) and value.strip():
            return field + ":" + value
    return None


def base(evidence, operation):
    raw = evidence["raw"]
    return {"operation": operation, "schemaVersion": SCHEMA, "capture": compact(raw["capture"]),
            "target": compact(raw.get("target", {})), "warnings": list(evidence["warnings"])}


def summary(evidence, limit):
    result = base(evidence, "summary")
    nodes = evidence["nodes"]
    roots = [n["id"] for n in nodes if not n.get("parentId")]
    classes = collections.Counter(n.get("class", "<unknown>") for n in nodes)
    result.update(nodeCount=len(nodes), rootCount=len(roots), roots=roots[:limit],
                  classes=[{"class": k, "count": v} for k, v in classes.most_common(limit)],
                  ambiguousLayoutCount=sum(n.get("layout", {}).get("ambiguous") is True for n in nodes),
                  missingGeometryCount=sum(not n.get("geometry") for n in nodes),
                  outputLimited=len(roots) > limit or len(classes) > limit)
    return result


def query(evidence, identifier=None, accessibility=None, class_name=None, ancestors=False, depth=0, limit=50):
    nodes, by_id = evidence["nodes"], evidence["by_id"]
    if identifier is not None:
        matches = [by_id[identifier]] if identifier in by_id else []
    elif accessibility is not None:
        matches = [n for n in nodes if n.get("accessibilityIdentifier", n.get("properties", {}).get("accessibilityIdentifier")) == accessibility]
        if len(matches) > 1:
            raise EvidenceError("Ambiguous accessibility identifier; " + str(len(matches)) + " matches. Query by capture-local --id")
    else:
        matches = [n for n in nodes if n.get("class") == class_name]
    if not matches:
        raise EvidenceError("Query matched no captured nodes; absence may reflect capture limits")
    children = collections.defaultdict(list)
    for node in nodes:
        children[node.get("parentId")].append(node["id"])
    selected, seen = [], set()
    def add(key):
        if key in by_id and key not in seen:
            seen.add(key)
            selected.append(key)
    for node in matches:
        add(node["id"])
    if ancestors:
        for node in matches:
            cursor = node.get("parentId")
            while cursor in by_id:
                add(cursor)
                cursor = by_id[cursor].get("parentId")
    frontier = collections.deque((n["id"], 0) for n in matches)
    scheduled = {n["id"] for n in matches}
    while frontier:
        key, level = frontier.popleft()
        if level < depth:
            for child in children[key]:
                add(child)
                if child not in scheduled:
                    scheduled.add(child)
                    frontier.append((child, level + 1))
    result = base(evidence, "query")
    result.update(matchCount=len(matches), selectedCount=len(selected), returnedCount=min(limit, len(selected)),
                  nodes=[compact(by_id[key]) for key in selected[:limit]], outputLimited=len(selected) > limit)
    return result


def quad_contains(quad, x, y):
    """Return True/False, or None for degenerate/non-convex ordered quads."""
    cross = lambda a, b, c: (b["x"]-a["x"])*(c["y"]-a["y"]) - (b["y"]-a["y"])*(c["x"]-a["x"])
    turns = [cross(quad[i], quad[(i+1)%4], quad[(i+2)%4]) for i in range(4)]
    scale = max(1, max(abs(p[a]-quad[0][a]) for p in quad for a in ("x", "y")))
    epsilon = 1e-12 * scale * scale
    area2 = abs(sum(quad[i]["x"]*quad[(i+1)%4]["y"]-quad[(i+1)%4]["x"]*quad[i]["y"] for i in range(4)))
    if area2 <= epsilon or (any(t > epsilon for t in turns) and any(t < -epsilon for t in turns)):
        return None
    point = {"x": x, "y": y}
    sides = [cross(quad[i], quad[(i+1)%4], point) for i in range(4)]
    return not (any(s > epsilon for s in sides) and any(s < -epsilon for s in sides))


def point(evidence, x, y, limit, window_id=None):
    if not finite(x) or not finite(y):
        raise EvidenceError("Point coordinates must be finite")
    candidates, skipped = [], collections.Counter()
    if window_id is not None and not any(n.get("windowId") == window_id or n["id"] == window_id for n in evidence["nodes"]):
        raise EvidenceError("Unknown capture-local --window-id")
    for node in evidence["nodes"]:
        if window_id is not None and node.get("windowId") != window_id and node["id"] != window_id:
            continue
        geometry = node.get("geometry", {})
        if not geometry:
            skipped["missingGeometry"] += 1
            continue
        if geometry.get("coordinateSpace") != "screen-points":
            skipped["coordinateSpaceNotScreenPoints"] += 1
            continue
        quad = geometry.get("screenQuad")
        if quad is None:
            skipped["missingScreenQuad"] += 1
            continue
        if any(p[k] is None for p in quad for k in ("x", "y")):
            skipped["unknownNonfiniteQuad"] += 1
            continue
        contains = quad_contains(quad, x, y)
        if contains is None:
            skipped["degenerateOrNonConvexQuad"] += 1
        elif contains:
            candidates.append(node)
    result = base(evidence, "point")
    result.update(point={"x": x, "y": y, "coordinateSpace": "screen-points"},
                  interpretation="Geometry candidates only; no visibility, occlusion, z-order or hit-test conclusion",
                  candidateCount=len(candidates), candidates=[compact(n) for n in candidates[:limit]],
                  skipped=dict(skipped), outputLimited=len(candidates) > limit)
    result["windowIdFilter"] = window_id
    windows = {n.get("windowId") for n in candidates}
    result["candidateWindowIds"] = sorted(str(window) for window in windows)
    if window_id is None and len(windows) > 1:
        result["warnings"].append("Candidates span multiple windows; use --window-id to isolate a window and avoid display-coordinate collisions")
    return result


def property_changes(before, after, prefix="", limit=MAX_CHANGES):
    """Iterative diff; missing and JSON null are distinct. Bound returned paths."""
    changes = []
    stack = [(prefix, True, before, True, after)]
    remaining = False
    while stack:
        path, old_present, old, new_present, new = stack.pop()
        if old_present and new_present and isinstance(old, dict) and isinstance(new, dict):
            for key in reversed(sorted(set(old) | set(new))):
                escaped = key.replace("~", "~0").replace("/", "~1")
                stack.append((path + "/" + escaped, key in old, old.get(key), key in new, new.get(key)))
            continue
        if old_present and new_present and isinstance(old, list) and isinstance(new, list):
            for index in reversed(range(max(len(old), len(new)))):
                stack.append((path + "/" + str(index), index < len(old), old[index] if index < len(old) else None,
                              index < len(new), new[index] if index < len(new) else None))
            continue
        if old_present == new_present and type(old) is type(new) and old == new:
            continue
        if len(changes) == limit:
            remaining = True
            break
        changes.append({"path": path or "/", "beforePresent": old_present, "afterPresent": new_present,
                        "before": compact(old), "after": compact(new)})
    return changes, remaining


# Nested pointer-style references that are meaningful only inside one capture.
CAPTURE_LOCAL_KEYS = frozenset(("id", "parentId", "windowId", "owningViewId"))
CAPTURE_LOCAL = "<capture-local>"
# Most diagnostic sections first, so a bounded change list keeps them.
DIFF_SECTION_ORDER = ("class", "kind", "geometry", "visibility", "properties", "layer", "layout", "constraints")


def normalized_references(value, evidence, groups, counter):
    """Replace nested capture-local references with the referenced node's unique
    durable identity, or a placeholder, so relaunch address churn is not a change."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in CAPTURE_LOCAL_KEYS and isinstance(item, str):
                counter[0] += 1
                target = evidence["by_id"].get(item)
                durable = identity(target) if target is not None else None
                result[key] = "identity:" + durable if durable and len(groups.get(durable, ())) == 1 else CAPTURE_LOCAL
            else:
                result[key] = normalized_references(item, evidence, groups, counter)
        return result
    if isinstance(value, list):
        return [normalized_references(item, evidence, groups, counter) for item in value]
    return value


def ordered_changes(before, after, limit=MAX_CHANGES):
    """Diff node sections in DIFF_SECTION_ORDER, sharing one bounded change budget."""
    rank = {key: index for index, key in enumerate(DIFF_SECTION_ORDER)}
    changes = []
    for key in sorted(set(before) | set(after), key=lambda k: (rank.get(k, len(rank)), k)):
        section, limited = property_changes({key: before[key]} if key in before else {},
                                            {key: after[key]} if key in after else {}, limit=limit - len(changes))
        changes.extend(section)
        if limited:
            return changes, True
    return changes, False


def diff(before, after, limit):
    def index(evidence):
        groups = collections.defaultdict(list)
        for node in evidence["nodes"]:
            key = identity(node)
            if key is not None:
                groups[key].append(node)
        return groups
    left, right = index(before), index(after)
    keys = sorted(set(left) | set(right))
    ambiguous = [key for key in keys if len(left[key]) > 1 or len(right[key]) > 1]
    matched = [key for key in keys if len(left[key]) == 1 and len(right[key]) == 1]
    mismatches = []
    for field in ("bundleId", "deviceUDID", "simulatorUDID", "orientation", "coordinateSpace", "screenScale", "screenBounds"):
        a, b = before["raw"].get("target", {}), after["raw"].get("target", {})
        if field in a and field in b and a[field] != b[field]:
            mismatches.append({"path": "target." + field, "before": compact(a[field]), "after": compact(b[field])})
    for field in ("orientation", "coordinateSpace"):
        a, b = before["raw"]["capture"], after["raw"]["capture"]
        if field in a and field in b and a[field] != b[field]:
            mismatches.append({"path": "capture." + field, "before": compact(a[field]), "after": compact(b[field])})
    window_facts = []
    for evidence in (before, after):
        windows = evidence["raw"]["capture"].get("windows")
        facts = []
        if isinstance(windows, list):
            for window in windows:
                if isinstance(window, dict):
                    facts.append({key: window[key] for key in ("screenBounds", "screenScale", "screenNativeScale", "orientation") if key in window})
        window_facts.append(sorted(facts, key=lambda fact: json.dumps(fact, sort_keys=True)))
    if window_facts[0] != window_facts[1]:
        mismatches.append({"path": "capture.windows.screenMetadata", "before": compact(window_facts[0]), "after": compact(window_facts[1])})
    coordinate_sets = [{n.get("geometry", {}).get("coordinateSpace") for n in e["nodes"] if n.get("geometry")} for e in (before, after)]
    if coordinate_sets[0] != coordinate_sets[1]:
        mismatches.append({"path": "nodes.geometry.coordinateSpace", "before": sorted(str(x) for x in coordinate_sets[0]), "after": sorted(str(x) for x in coordinate_sets[1])})
    references = [0]
    def comparable(node, evidence, groups):
        return {key: normalized_references(value, evidence, groups, references)
                for key, value in node.items() if key not in ("id", "parentId", "windowId")}
    def parent_identity(node, evidence, groups):
        parent_id = node.get("parentId")
        if not parent_id:
            return True, None
        parent = evidence["by_id"].get(parent_id)
        if parent is None:
            return False, None
        key = identity(parent)
        if key is None or len(groups[key]) != 1:
            return False, None
        return True, key
    changed = []
    unknown_parent_pairs = 0
    for key in matched:
        changes, truncated = ordered_changes(comparable(left[key][0], before, left), comparable(right[key][0], after, right))
        old_known, old_parent = parent_identity(left[key][0], before, left)
        new_known, new_parent = parent_identity(right[key][0], after, right)
        if old_known and new_known:
            if old_parent != new_parent:
                if len(changes) < MAX_CHANGES:
                    changes.append({"path": "/relationships/parent", "beforePresent": True, "afterPresent": True,
                                    "before": old_parent, "after": new_parent})
                else:
                    truncated = True
        else:
            unknown_parent_pairs += 1
        if changes:
            changed.append({"identity": key, "beforeId": left[key][0]["id"], "afterId": right[key][0]["id"],
                            "changes": changes, "changesLimited": truncated})
    result = {"operation": "diff", "schemaVersion": SCHEMA, "beforeCapture": compact(before["raw"]["capture"]),
              "afterCapture": compact(after["raw"]["capture"]), "warnings": before["warnings"] + after["warnings"],
              "identityPolicy": "Unique semanticId, otherwise unique accessibilityIdentifier; never process addresses. "
                                "Nested capture-local references compare as the referenced node's unique identity, otherwise as " + CAPTURE_LOCAL,
              "matchedCount": len(matched), "changedCount": len(changed), "changed": changed[:limit],
              "ambiguousIdentityCount": len(ambiguous), "ambiguousIdentities": ambiguous[:limit],
              "unmatchedBeforeCount": len(before["nodes"]) - len(matched),
              "unmatchedAfterCount": len(after["nodes"]) - len(matched),
              "comparisonContextMismatches": mismatches, "geometryComparable": not mismatches,
              "outputLimited": len(changed) > limit or len(ambiguous) > limit}
    result["warnings"].append("Unmatched nodes do not prove insertion/removal; raw parent/window addresses are excluded, uniquely identified parents are compared")
    result["parentComparisonsUnknownCount"] = unknown_parent_pairs
    result["captureLocalReferencesNormalized"] = references[0]
    if not window_facts[0] or not window_facts[1]:
        result["warnings"].append("Window coordinate/orientation metadata is missing; geometric comparability is unverified")
        result["geometryComparable"] = None if not mismatches else False
    if ambiguous:
        result["warnings"].append("Duplicate semantic identifiers remain unmatched")
    if mismatches:
        result["warnings"].append("Comparison context differs; geometry changes need normalization or recapture")
    return result


def encode_bounded(result):
    """Hard bound on stdout including newline, with explicit omission metadata."""
    encode = lambda item: json.dumps(item, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    output = encode(result)
    original_bytes = len(output.encode("utf-8")) + 1
    if original_bytes <= MAX_STDOUT_BYTES:
        return output
    result = dict(result)
    result["outputLimited"] = True
    result["outputLimitReason"] = "stdout-byte-budget"
    result["stdoutLimitBytes"] = MAX_STDOUT_BYTES
    result["unboundedOutputBytes"] = original_bytes
    # Payload lists are prefix samples. Counts describing the original capture
    # remain intact, and the returned node count is corrected when reduced.
    for field in ("nodes", "candidates", "changed", "classes", "roots", "ambiguousIdentities"):
        if not isinstance(result.get(field), list):
            continue
        while len(result[field]) > 1:
            result[field] = result[field][:max(1, len(result[field]) // 2)]
            if field == "nodes":
                result["returnedCount"] = len(result[field])
            output = encode(result)
            if len(output.encode("utf-8")) + 1 <= MAX_STDOUT_BYTES:
                return output
        if result[field]:
            value = result[field][0]
            result[field] = [{key: compact(value[key]) for key in ("id", "class", "identity") if key in value}
                             if isinstance(value, dict) else compact(value)]
            if isinstance(result[field][0], dict):
                result[field][0]["_outputOmitted"] = "payload exceeds stdout budget; query narrower evidence"
            output = encode(result)
            if len(output.encode("utf-8")) + 1 <= MAX_STDOUT_BYTES:
                return output
    # Even metadata can be adversarially large. Preserve only bounded identifiers
    # and scalar counts if list reduction could not satisfy the hard byte limit.
    fallback = {"operation": compact(result.get("operation")), "schemaVersion": SCHEMA,
                "outputLimited": True, "outputLimitReason": "stdout-byte-budget",
                "stdoutLimitBytes": MAX_STDOUT_BYTES, "unboundedOutputBytes": original_bytes,
                "outputOmitted": "Payload and metadata exceed budget; use a narrower query or inspect the source file"}
    for key in ("nodeCount", "matchCount", "selectedCount", "matchedCount", "changedCount", "candidateCount"):
        if isinstance(result.get(key), int):
            fallback[key] = result[key]
    for key in ("capture", "beforeCapture", "afterCapture"):
        if isinstance(result.get(key), dict):
            fallback[key] = {"id": compact(result[key].get("id"))}
    return encode(fallback)


def bounded_int(minimum, maximum):
    def convert(value):
        try:
            result = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("Expected integer") from exc
        if not minimum <= result <= maximum:
            raise argparse.ArgumentTypeError("Expected " + str(minimum) + ".." + str(maximum))
        return result
    return convert


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="operation", required=True)
    for name in ("summary", "query", "point", "diff"):
        sub = subs.add_parser(name)
        sub.add_argument("file" if name != "diff" else "before")
        if name == "diff":
            sub.add_argument("after")
        sub.add_argument("--limit", type=bounded_int(1, 500), default=50)
        if name == "query":
            match = sub.add_mutually_exclusive_group(required=True)
            match.add_argument("--id")
            match.add_argument("--identifier")
            match.add_argument("--class", dest="class_name")
            sub.add_argument("--ancestors", action="store_true")
            sub.add_argument("--depth", type=bounded_int(0, 100), default=0)
        if name == "point":
            sub.add_argument("--x", type=float, required=True)
            sub.add_argument("--y", type=float, required=True)
            sub.add_argument("--window-id", help="Capture-local window ID; isolates screen-coordinate candidates")
    args = parser.parse_args(argv)
    try:
        if args.operation == "diff":
            result = diff(load(args.before), load(args.after), args.limit)
        else:
            evidence = load(args.file)
            if args.operation == "summary":
                result = summary(evidence, args.limit)
            elif args.operation == "query":
                result = query(evidence, args.id, args.identifier, args.class_name, args.ancestors, args.depth, args.limit)
            else:
                result = point(evidence, args.x, args.y, args.limit, args.window_id)
        print(encode_bounded(result))
        return 0
    except (EvidenceError, OSError, ValueError, TypeError, RecursionError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)[:1024]}, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    sys.exit(main())
