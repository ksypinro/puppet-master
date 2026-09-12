#!/usr/bin/env python3
"""Check that a test selection really selects tests, before spending a measured run on it.

A wrong selection is silent. `swift test --filter` matches the identifiers printed by `swift test list`
(PackageTests.SearchTests/testQuery, Suite/function(parameters:)), not the display names written in
@Suite("…") or @Test("…"), so a filter taken from a display name runs nothing and still exits 0.
xcodebuild's -only-testing has the same shape: one typo narrows the run to nothing while the command
reports success.

This enumerates tests the way each tool does, applies the selection, and exits 3 when a selector matches
nothing or the selection is empty. Exit 0 means every selector matched at least one test.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "ios.test.selection.v1"
# Lines `swift test list` prints that are not test identifiers.
NOISE = re.compile(r"^(building|build complete|compiling|fetching|resolving|planning|warning:|note:|\[\d+/\d+\])", re.IGNORECASE)
SUITE_NAME = re.compile(r'@Suite\s*\(\s*"([^"]+)"')
TEST_NAME = re.compile(r'@Test\s*\(\s*"([^"]+)"')
TYPE_DECL = re.compile(r"\b(?:struct|final class|class|actor|enum)\s+([A-Za-z_][A-Za-z0-9_]*)")
FUNC_DECL = re.compile(r"\bfunc\s+([A-Za-z_][A-Za-z0-9_]*)")
EXAMPLES = 3


def run(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError(str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"command timed out after {timeout}s") from exc


def swiftpm_identifiers(text: str) -> list[str]:
    """Test identifiers from `swift test list` output, without the build chatter."""
    identifiers = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or NOISE.match(line) or " " in line or "/" not in line:
            continue
        identifiers.append(line)
    return identifiers


def regex_matches(identifiers: list[str], pattern: str) -> list[str]:
    """SwiftPM treats --filter as a regular expression searched against each identifier."""
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise RuntimeError(f"invalid --filter regular expression {pattern!r}: {exc}") from exc
    return [identifier for identifier in identifiers if compiled.search(identifier)]


def enumerated_identifiers(payload: dict[str, Any]) -> list[str]:
    """Target/Class/test() identifiers from xcodebuild -enumerate-tests JSON.

    The tree is plan → target → class → test; the plan name is not part of an -only-testing identifier.
    """
    identifiers: list[str] = []

    def walk(nodes: list[dict[str, Any]], path: tuple[str, ...]) -> None:
        for node in nodes or []:
            name, kind = node.get("name"), node.get("kind")
            here = path if kind == "plan" or not name else (*path, name)
            if kind == "test" and here:
                identifiers.append("/".join(here))
            walk(node.get("children", []), here)

    walk(payload.get("values", []), ())
    return identifiers


def selector_matches(identifier: str, selector: str) -> bool:
    """-only-testing / -skip-testing match a whole identifier or a prefix at a path boundary."""
    return identifier == selector or identifier.startswith(selector.rstrip("/") + "/")


def display_names(source: str) -> dict[str, str]:
    """Map @Suite("…") and @Test("…") display names to the symbol that follows them."""
    index: dict[str, str] = {}
    lines = source.splitlines()
    for number, line in enumerate(lines):
        for pattern, declaration in ((SUITE_NAME, TYPE_DECL), (TEST_NAME, FUNC_DECL)):
            found = pattern.search(line)
            if not found:
                continue
            for candidate in lines[number:number + 4]:
                symbol = declaration.search(candidate)
                if symbol:
                    index[found.group(1)] = symbol.group(1)
                    break
    return index


def display_name_index(package: Path) -> dict[str, str]:
    index: dict[str, str] = {}
    for path in sorted(package.rglob("*.swift")):
        if ".build" in path.parts:
            continue
        try:
            index.update(display_names(path.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return index


def suggest(selector: str, identifiers: list[str], names: dict[str, str]) -> str | None:
    """Explain an unmatched selector: a display name used by mistake, or the nearest real identifier."""
    symbol = names.get(selector)
    if symbol:
        return (f"{selector!r} is a display name from @Suite/@Test; the identifier uses the symbol {symbol!r}. "
                f"Filter on {symbol!r} instead.")
    lowered = selector.casefold()
    contains = [identifier for identifier in identifiers if lowered in identifier.casefold()][:EXAMPLES]
    if contains:
        return f"no exact match; identifiers containing it: {', '.join(contains)}"
    close = difflib.get_close_matches(selector, identifiers, n=EXAMPLES, cutoff=0.5)
    return f"closest identifiers: {', '.join(close)}" if close else None


def evaluate(identifiers: list[str], include: list[tuple[str, str]], exclude: list[tuple[str, str]],
             match, names: dict[str, str]) -> dict[str, Any]:
    """Apply selectors, recording what each one matched. include/exclude are (kind, value) pairs."""
    selectors: list[dict[str, Any]] = []
    unmatched = 0
    for kind, value in [*include, *exclude]:
        matched = match(identifiers, value)
        entry: dict[str, Any] = {"kind": kind, "value": value, "matches": len(matched), "examples": matched[:EXAMPLES]}
        if not matched:
            unmatched += 1
            hint = suggest(value, identifiers, names)
            if hint:
                entry["suggestion"] = hint
        selectors.append(entry)

    selected = set(identifiers)
    if include:
        selected = {identifier for _, value in include for identifier in match(identifiers, value)}
    for _, value in exclude:
        selected -= set(match(identifiers, value))
    return {"selectors": selectors, "selected": len(selected), "unmatched_selectors": unmatched}


def check_swiftpm(args: argparse.Namespace) -> dict[str, Any]:
    package = args.package_path.expanduser().resolve()
    completed = run(["swift", "test", "list", "--package-path", str(package)], args.timeout)
    if completed.returncode != 0:
        raise RuntimeError(f"swift test list failed ({completed.returncode}): {completed.stdout.strip()[-400:]}")
    identifiers = swiftpm_identifiers(completed.stdout)
    if not identifiers:
        raise RuntimeError("swift test list printed no test identifiers")
    result = evaluate(identifiers,
                      [("filter", value) for value in args.filter],
                      [("skip", value) for value in args.skip],
                      regex_matches, display_name_index(package))
    return {"mode": "swiftpm", "package": str(package), "tests": len(identifiers), **result,
            "notes": ["--filter is a regular expression matched against the identifiers above, not against "
                      "@Suite/@Test display names."]}


def check_xcodebuild(args: argparse.Namespace) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as scratch:
        destination_file = Path(scratch) / "tests.json"
        argv = ["xcodebuild"]
        if args.xctestrun:
            argv += ["test-without-building", "-xctestrun", str(args.xctestrun.expanduser().resolve())]
        else:
            argv += ["test"]
            if args.project:
                argv += ["-project", str(args.project.expanduser().resolve())]
            if args.workspace:
                argv += ["-workspace", str(args.workspace.expanduser().resolve())]
            argv += ["-scheme", args.scheme]
        if args.destination:
            argv += ["-destination", args.destination]
        if args.test_plan:
            argv += ["-testPlan", args.test_plan]
        argv += ["-enumerate-tests", "-test-enumeration-format", "json", "-test-enumeration-style", "hierarchical",
                 "-test-enumeration-output-path", str(destination_file)]
        completed = run(argv, args.timeout)
        if completed.returncode != 0 or not destination_file.exists():
            raise RuntimeError(f"xcodebuild -enumerate-tests failed ({completed.returncode}): {completed.stdout.strip()[-400:]}")
        payload = json.loads(destination_file.read_text(encoding="utf-8"))
    identifiers = enumerated_identifiers(payload)
    if not identifiers:
        raise RuntimeError("xcodebuild enumerated no tests")
    result = evaluate(identifiers,
                      [("only-testing", value) for value in args.only_testing],
                      [("skip-testing", value) for value in args.skip_testing],
                      lambda ids, value: [i for i in ids if selector_matches(i, value)], {})
    return {"mode": "xcodebuild", "tests": len(identifiers), **result,
            "notes": ["-only-testing and -skip-testing take Target, Target/Class or Target/Class/method() identifiers."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    package = subparsers.add_parser("swiftpm", help="Check swift test --filter selections against swift test list")
    package.add_argument("--package-path", type=Path, required=True)
    package.add_argument("--filter", action="append", default=[], help="Regular expression, as passed to swift test --filter")
    package.add_argument("--skip", action="append", default=[], help="Regular expression, as passed to swift test --skip")

    project = subparsers.add_parser("xcodebuild", help="Check -only-testing selections against -enumerate-tests")
    source = project.add_mutually_exclusive_group(required=True)
    source.add_argument("--xctestrun", type=Path, help="Built .xctestrun; avoids a build")
    source.add_argument("--project", type=Path)
    source.add_argument("--workspace", type=Path)
    project.add_argument("--scheme")
    project.add_argument("--destination")
    project.add_argument("--test-plan")
    project.add_argument("--only-testing", action="append", default=[], metavar="IDENTIFIER")
    project.add_argument("--skip-testing", action="append", default=[], metavar="IDENTIFIER")

    for sub in (package, project):
        sub.add_argument("--timeout", type=float, default=300.0)
        sub.add_argument("--save", type=Path)
        sub.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.command == "xcodebuild" and (args.project or args.workspace) and not args.scheme:
        parser.error("--scheme is required with --project or --workspace")

    try:
        result = check_swiftpm(args) if args.command == "swiftpm" else check_xcodebuild(args)
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2

    if result["unmatched_selectors"]:
        result["status"] = "unmatched-selector"
    elif result["selected"] == 0:
        result["status"] = "empty-selection"
    else:
        result["status"] = "ok"
    report = {"schema_version": SCHEMA_VERSION, **result}
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.save:
        destination = args.save.expanduser().resolve()
        if destination.exists() and not args.force:
            print(json.dumps({"status": "error", "error": f"refusing to overwrite {destination}"}), file=sys.stderr)
            return 2
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "ok" else 3


if __name__ == "__main__":
    sys.exit(main())
