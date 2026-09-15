#!/usr/bin/env python3
"""Shared plumbing for the iOS build engineer scripts.

Dependency-free, Python 3.9+. Everything here is read-only except the callers
that explicitly run a build.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

TIMEOUT_QUERY = 300
TIMEOUT_BUILD = 3600


class BuildError(Exception):
    """A condition the caller must report rather than work around."""


def emit(payload) -> None:
    """Every script speaks JSON on stdout so an agent never parses prose."""
    json.dump(payload, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def fail(message: str, code: int = 1, **extra):
    emit({"ok": False, "error": message, **extra})
    raise SystemExit(code)


def run(cmd, cwd=None, env=None, timeout=TIMEOUT_QUERY, stdin=None):
    """Run a command and return CompletedProcess. Never raises on non-zero."""
    merged = dict(os.environ)
    if env:
        merged.update(env)
    try:
        return subprocess.run(
            cmd, cwd=cwd, env=merged, input=stdin,
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise BuildError("%s not found on PATH" % cmd[0]) from exc
    except subprocess.TimeoutExpired as exc:
        raise BuildError("%s timed out after %ss" % (" ".join(cmd[:3]), timeout)) from exc


def run_json(cmd, **kwargs):
    """Run a command expected to emit JSON. Returns None when it does not."""
    proc = run(cmd, **kwargs)
    try:
        return json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return None


def require_xcode() -> None:
    """Full Xcode, not the Command Line Tools package.

    The standalone CLT package has no simctl and cannot build or run iOS apps,
    but it does provide xcodebuild — so checking for xcodebuild alone passes on
    a machine that cannot do any of this skill's work.
    """
    if shutil.which("xcrun") is None:
        raise BuildError("xcrun not found; install Xcode")
    if run(["xcrun", "--find", "simctl"]).returncode != 0:
        raise BuildError(
            "simctl is unavailable — this looks like the Command Line Tools package "
            "rather than full Xcode. Install Xcode.app and select it with DEVELOPER_DIR "
            "or xcode-select -s."
        )


def developer_dir() -> str:
    override = os.environ.get("DEVELOPER_DIR")
    if override:
        return override
    proc = run(["xcode-select", "-p"])
    return proc.stdout.strip()


# ---------------------------------------------------------------- containers

def find_containers(root: Path):
    """Locate build containers. A workspace wins over a project, because that is
    what Xcode itself opens when both are present in a directory."""
    workspaces = [
        p for p in sorted(root.glob("*.xcworkspace"))
        if p.name != "project.xcworkspace"
    ]
    projects = sorted(root.glob("*.xcodeproj"))
    packages = [root / "Package.swift"] if (root / "Package.swift").is_file() else []
    return {"workspaces": workspaces, "projects": projects, "packages": packages}


class Container:
    """The -project/-workspace pair, resolved once so every command agrees."""

    def __init__(self, project=None, workspace=None, package=None, scheme=None,
                 configuration=None, derived_data=None):
        self.project = str(Path(project).resolve()) if project else None
        self.workspace = str(Path(workspace).resolve()) if workspace else None
        self.package = str(Path(package).resolve()) if package else None
        self.scheme = scheme
        self.configuration = configuration
        self.derived_data = str(Path(derived_data).resolve()) if derived_data else None

    @classmethod
    def discover(cls, root, **kwargs):
        found = find_containers(Path(root).resolve())
        if found["workspaces"]:
            return cls(workspace=found["workspaces"][0], **kwargs)
        if found["projects"]:
            return cls(project=found["projects"][0], **kwargs)
        if found["packages"]:
            return cls(package=found["packages"][0].parent, **kwargs)
        raise BuildError(
            "no .xcworkspace, .xcodeproj or Package.swift in %s" % root
        )

    @property
    def cwd(self):
        for candidate in (self.workspace, self.project):
            if candidate:
                return str(Path(candidate).parent)
        return self.package

    def flags(self):
        if self.workspace:
            return ["-workspace", self.workspace]
        if self.project:
            return ["-project", self.project]
        return []  # a package is addressed by cwd + -scheme

    def common(self):
        args = list(self.flags())
        if self.scheme:
            args += ["-scheme", self.scheme]
        if self.configuration:
            args += ["-configuration", self.configuration]
        if self.derived_data:
            args += ["-derivedDataPath", self.derived_data]
        return args

    def describe(self):
        return {
            "workspace": self.workspace,
            "project": self.project,
            "package": self.package,
            "scheme": self.scheme,
            "configuration": self.configuration,
            "derivedDataPath": self.derived_data,
        }


# ---------------------------------------------------------------- schemes

def list_schemes(container):
    data = run_json(["xcodebuild", "-list", "-json"] + container.flags(),
                    cwd=container.cwd)
    if data is None:
        raise BuildError(
            "xcodebuild -list produced no JSON. The container may be invalid, or "
            "package resolution may be required first."
        )
    node = data.get("workspace") or data.get("project") or {}
    return {
        "kind": "workspace" if "workspace" in data else "project",
        "name": node.get("name"),
        "schemes": node.get("schemes", []),
        "targets": node.get("targets", []),
        "configurations": node.get("configurations", []),
    }


def shared_schemes(container):
    """Schemes stored in xcshareddata. A scheme under xcuserdata is invisible to
    xcodebuild on any other machine, which is why this is reported separately."""
    shared = set()
    for base in (container.workspace, container.project):
        if not base:
            continue
        folder = Path(base) / "xcshareddata" / "xcschemes"
        if folder.is_dir():
            shared.update(p.stem for p in folder.glob("*.xcscheme"))
    root = Path(container.cwd) if container.cwd else None
    if root:
        for proj in root.glob("*.xcodeproj"):
            folder = proj / "xcshareddata" / "xcschemes"
            if folder.is_dir():
                shared.update(p.stem for p in folder.glob("*.xcscheme"))
    return shared


# ---------------------------------------------------------------- settings

def build_settings(container, destination, extra=None, action=None):
    """Resolved build settings for one scheme, as JSON.

    -showBuildSettings with -scheme returns a single entry, but -target and
    -alltargets return one per target. Selecting by the target key keeps the
    answer correct in every case; a first-match text regex does not.
    """
    cmd = ["xcodebuild", "-showBuildSettings", "-json"] + container.common()
    if destination:
        cmd += ["-destination", destination]
    if action:
        cmd += [action]
    cmd += list(extra or [])

    data = run_json(cmd, cwd=container.cwd, timeout=TIMEOUT_QUERY)
    if not data:
        proc = run(cmd, cwd=container.cwd, timeout=TIMEOUT_QUERY)
        raise BuildError(
            "could not read build settings: %s"
            % (proc.stderr.strip() or proc.stdout.strip())[-800:]
        )
    if container.scheme and len(data) > 1:
        for entry in data:
            if entry.get("target") == container.scheme:
                return entry.get("buildSettings", {})
    return data[0].get("buildSettings", {})


def resolve_product(settings):
    """Locate the product without guessing a DerivedData path.

    TARGET_BUILD_DIR is the target's own output directory and stays correct
    under a custom CONFIGURATION_BUILD_DIR; BUILT_PRODUCTS_DIR is the shared
    collection point and is the safer fallback only when the former is absent.
    """
    base = settings.get("TARGET_BUILD_DIR") or settings.get("BUILT_PRODUCTS_DIR")
    name = settings.get("FULL_PRODUCT_NAME") or settings.get("WRAPPER_NAME")
    if not base or not name:
        raise BuildError(
            "build settings carry no TARGET_BUILD_DIR/FULL_PRODUCT_NAME — "
            "this target may not produce a bundle"
        )
    return {
        "appPath": str(Path(base) / name),
        "bundleId": settings.get("PRODUCT_BUNDLE_IDENTIFIER"),
        "executable": settings.get("EXECUTABLE_PATH"),
        "platform": settings.get("PLATFORM_NAME"),
        "configuration": settings.get("CONFIGURATION"),
        "archs": settings.get("ARCHS"),
        "productType": settings.get("PRODUCT_TYPE"),
    }


# ---------------------------------------------------------------- diagnostics

_FRAGMENT = re.compile(r"([A-Za-z]+)=([^&]*)")


def _source_location(url):
    if not url:
        return None
    head, _, fragment = url.partition("#")
    parts = dict(_FRAGMENT.findall(fragment))
    return {
        "file": head.replace("file://", ""),
        "line": parts.get("StartingLineNumber"),
        "column": parts.get("StartingColumnNumber"),
    }


def read_build_results(bundle):
    """Structured build diagnostics from a result bundle.

    This is the first-party channel and it replaces scraping xcodebuild stdout:
    a build failure that prints hundreds of log lines reduces to a typed issue
    with an exact file, line and column.
    """
    bundle = Path(bundle)
    if not bundle.exists():
        return None
    data = run_json(
        ["xcrun", "xcresulttool", "get", "build-results", "--path", str(bundle)],
        timeout=TIMEOUT_QUERY,
    )
    if not data:
        return None

    def issues(key):
        out = []
        for item in data.get(key, []) or []:
            out.append({
                "type": item.get("issueType"),
                "message": item.get("message"),
                "target": item.get("targetName"),
                "location": _source_location(item.get("sourceURL")),
            })
        return out

    return {
        "status": data.get("status"),
        "errorCount": data.get("errorCount"),
        "warningCount": data.get("warningCount"),
        "analyzerWarningCount": data.get("analyzerWarningCount"),
        "destination": data.get("destination"),
        "errors": issues("errors"),
        "warnings": issues("warnings")[:50],
        "analyzerWarnings": issues("analyzerWarnings")[:50],
    }


ERROR_LINE = re.compile(r"^.*?\berror:\s*(.+)$", re.M)


def text_fallback_errors(stdout, limit=8):
    """Last-resort extraction when no result bundle exists.

    exportArchive produces no bundle at all on failure, so this path is real and
    not merely defensive. It is explicitly labelled as unstructured so a caller
    never presents it with the same confidence as bundle-derived diagnostics.
    """
    hits = [m.group(1).strip() for m in ERROR_LINE.finditer(stdout or "")]
    if not hits:
        hits = [line for line in (stdout or "").splitlines()[-limit:] if line.strip()]
    seen, unique = set(), []
    for hit in hits:
        if hit not in seen:
            seen.add(hit)
            unique.append(hit)
    return unique[:limit]
