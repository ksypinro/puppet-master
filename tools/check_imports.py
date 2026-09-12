#!/usr/bin/env python3
"""Verify that every script in this repository imports the standard library only.

The stdlib-only guarantee is why install.sh never touches the network and why CI
needs no install step. It is easy to break by accident in review, so it is
enforced here. See docs/DEPENDENCIES.md for the rationale.

    python3 tools/check_imports.py

Exit status: 0 if clean, 1 if a third-party import is found.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("skills", "tools")

# Provided by Xcode's embedded Python inside the LLDB process, never from PyPI.
# lldb-code-state-debugger splits its client and worker precisely so that only
# the worker -- which runs inside LLDB -- ever imports this.
TOOLCHAIN_PROVIDED = {"lldb"}

# Python 3.9 has no sys.stdlib_module_names, and CI tests against 3.9 because
# that is what macOS ships. Fall back to the 3.9 stdlib set when it is absent.
STDLIB_FALLBACK = {
    "__future__", "abc", "argparse", "ast", "asyncio", "base64", "binascii",
    "bisect", "builtins", "bz2", "calendar", "cmath", "cmd", "codecs",
    "collections", "colorsys", "concurrent", "configparser", "contextlib",
    "copy", "csv", "ctypes", "dataclasses", "datetime", "decimal", "difflib",
    "dis", "email", "enum", "errno", "faulthandler", "fcntl", "filecmp",
    "fileinput", "fnmatch", "fractions", "ftplib", "functools", "gc", "getopt",
    "getpass", "gettext", "glob", "gzip", "hashlib", "heapq", "hmac", "html",
    "http", "imaplib", "importlib", "inspect", "io", "ipaddress", "itertools",
    "json", "keyword", "linecache", "locale", "logging", "lzma", "mailbox",
    "marshal", "math", "mimetypes", "mmap", "multiprocessing", "netrc",
    "numbers", "operator", "os", "pathlib", "pickle", "pkgutil", "platform",
    "plistlib", "poplib", "posixpath", "pprint", "pty", "pwd", "py_compile",
    "queue", "quopri", "random", "re", "readline", "reprlib", "resource",
    "runpy", "sched", "secrets", "select", "selectors", "shelve", "shlex",
    "shutil", "signal", "site", "smtplib", "socket", "socketserver", "sqlite3",
    "ssl", "stat", "statistics", "string", "stringprep", "struct",
    "subprocess", "symtable", "sys", "sysconfig", "tarfile", "telnetlib",
    "tempfile", "termios", "textwrap", "threading", "time", "timeit", "token",
    "tokenize", "trace", "traceback", "tracemalloc", "tty", "types", "typing",
    "unicodedata", "unittest", "urllib", "uuid", "venv", "warnings", "wave",
    "weakref", "webbrowser", "xml", "xmlrpc", "zipfile", "zipimport", "zlib",
}


def stdlib_names() -> set[str]:
    names = getattr(sys, "stdlib_module_names", None)
    return set(names) if names else STDLIB_FALLBACK


def local_module_names(files: list[Path]) -> set[str]:
    """Sibling modules a script may import, e.g. `debugger`, `lldb_ui`."""
    return {p.stem for p in files}


def imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def main() -> int:
    files = sorted(
        p
        for directory in SCAN_DIRS
        for p in (REPO_ROOT / directory).rglob("*.py")
        if "__pycache__" not in p.parts
    )
    if not files:
        print("no Python files found", file=sys.stderr)
        return 1

    allowed = stdlib_names() | local_module_names(files) | TOOLCHAIN_PROVIDED
    violations: list[str] = []

    for path in files:
        for name in sorted(imported_names(path) - allowed):
            violations.append(f"{path.relative_to(REPO_ROOT)}: {name}")

    if violations:
        print("Third-party imports found. See docs/DEPENDENCIES.md.\n")
        for violation in violations:
            print(f"  {violation}")
        return 1

    print(f"stdlib-only verified across {len(files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
