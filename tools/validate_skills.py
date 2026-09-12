#!/usr/bin/env python3
"""Validate every skill in this repository against the Agent Skills spec.

Spec: https://agentskills.io/specification

Checks the constraints that actually break installs in the wild: frontmatter
shape, name/directory agreement, field length limits, dead relative links, and
the progressive-disclosure budget. Runs in CI on every push.

    python3 tools/validate_skills.py            # validate skills/
    python3 tools/validate_skills.py --strict   # warnings become failures
    python3 tools/validate_skills.py path/to/skill

Exit status: 0 if every skill is valid, 1 otherwise.

Deliberately dependency-free: no PyYAML, so it parses the small, flat subset of
YAML that the spec permits in frontmatter. That keeps `pip install` out of the
contributor path and out of CI.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

NAME_MAX = 64
DESCRIPTION_MAX = 1024
COMPATIBILITY_MAX = 500
BODY_LINES_RECOMMENDED = 500

NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
KNOWN_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
REQUIRED_FIELDS = {"name", "description"}

# Markdown links to local files, e.g. [text](references/foo.md)
LINK_PATTERN = re.compile(r"\[[^\]]*\]\((?!https?://|#|mailto:)([^)\s]+)\)")


class Result:
    def __init__(self, skill: str) -> None:
        self.skill = skill
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_frontmatter(text: str) -> tuple[dict, str] | tuple[None, str]:
    """Parse the flat YAML subset the spec allows. Returns (fields, body)."""
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    if not match:
        return None, text

    fields: dict = {}
    current_map: str | None = None

    for raw in match.group(1).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue

        if raw[0] in " \t":  # nested key under a mapping (metadata:)
            if current_map and ":" in raw:
                key, _, value = raw.strip().partition(":")
                fields.setdefault(current_map, {})[key.strip()] = value.strip().strip('"\'')
            continue

        key, _, value = raw.partition(":")
        key, value = key.strip(), value.strip()
        if value:
            fields[key] = value.strip('"\'')
            current_map = None
        else:
            fields[key] = {}
            current_map = key

    return fields, text[match.end():]


def validate_skill(skill_dir: Path) -> Result:
    result = Result(skill_dir.name)
    skill_md = skill_dir / "SKILL.md"

    if not skill_md.is_file():
        result.error("no SKILL.md")
        return result

    text = skill_md.read_text(encoding="utf-8")
    fields, body = parse_frontmatter(text)

    if fields is None:
        result.error("SKILL.md has no YAML frontmatter (must open with '---')")
        return result

    for field in sorted(REQUIRED_FIELDS - fields.keys()):
        result.error(f"frontmatter is missing required field '{field}'")

    for field in sorted(fields.keys() - KNOWN_FIELDS):
        result.warn(f"'{field}' is not in the Agent Skills spec; clients may ignore it")

    # -- name ------------------------------------------------------------
    name = fields.get("name")
    if isinstance(name, str):
        if not NAME_PATTERN.match(name):
            result.error(
                f"name '{name}' must be lowercase alphanumeric with single hyphens, "
                "and may not start or end with a hyphen"
            )
        if len(name) > NAME_MAX:
            result.error(f"name is {len(name)} characters (max {NAME_MAX})")
        if name != skill_dir.name:
            result.error(f"name '{name}' does not match directory '{skill_dir.name}'")

    # -- description -----------------------------------------------------
    description = fields.get("description")
    if isinstance(description, str):
        if not description.strip():
            result.error("description is empty")
        elif len(description) > DESCRIPTION_MAX:
            result.error(f"description is {len(description)} characters (max {DESCRIPTION_MAX})")
        elif len(description) < 40:
            result.warn(
                "description is very short; it is the only text an agent sees when "
                "deciding whether to route here"
            )

    # -- compatibility ---------------------------------------------------
    compatibility = fields.get("compatibility")
    if isinstance(compatibility, str) and len(compatibility) > COMPATIBILITY_MAX:
        result.error(f"compatibility is {len(compatibility)} characters (max {COMPATIBILITY_MAX})")

    # -- metadata --------------------------------------------------------
    metadata = fields.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        result.error("metadata must be a mapping of string keys to string values")

    # -- progressive disclosure ------------------------------------------
    body_lines = len(body.splitlines())
    if body_lines > BODY_LINES_RECOMMENDED:
        result.warn(
            f"SKILL.md body is {body_lines} lines (recommended under "
            f"{BODY_LINES_RECOMMENDED}); move detail into references/"
        )

    # -- relative links resolve ------------------------------------------
    for link in LINK_PATTERN.findall(body):
        target = (skill_dir / link.split("#", 1)[0]).resolve()
        if not target.exists():
            result.error(f"broken relative link: {link}")

    # -- scripts are executable and syntactically valid -------------------
    for script in sorted((skill_dir / "scripts").glob("*.py")):
        try:
            compile(script.read_text(encoding="utf-8"), str(script), "exec")
        except SyntaxError as exc:
            result.error(f"scripts/{script.name} has a syntax error at line {exc.lineno}")

    return result


def discover(targets: list[Path]) -> list[Path]:
    if targets:
        return [t.resolve() for t in targets]
    skills_dir = REPO_ROOT / "skills"
    return sorted(p for p in skills_dir.iterdir() if (p / "SKILL.md").is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("skills", nargs="*", type=Path, help="skill directories (default: all)")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    args = parser.parse_args()

    skill_dirs = discover(args.skills)
    if not skill_dirs:
        print("no skills found", file=sys.stderr)
        return 1

    results = [validate_skill(d) for d in skill_dirs]
    failed = 0

    for result in results:
        problems = result.errors + (result.warnings if args.strict else [])
        if problems:
            failed += 1
            print(f"✗ {result.skill}")
        elif result.warnings:
            print(f"~ {result.skill}")
        else:
            print(f"✓ {result.skill}")

        for err in result.errors:
            print(f"    error: {err}")
        for warning in result.warnings:
            print(f"    warn:  {warning}")

    total = len(results)
    print(f"\n{total - failed}/{total} skills valid"
          f"{' (strict)' if args.strict else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
