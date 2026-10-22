#!/usr/bin/env python3
"""Fail when a test reads a path that the repository does not contain.

Tests read only committed fixtures. A scratch path such as `/tmp/...`,
`/home/...` or `/workspace/...` exists on the machine that happens to run the
test, not in the repository, so the test passes there and fails everywhere
else. A test that needs such a path builds it in a temporary directory, or
states on the line why the reference is harmless:

    root = Path("/home/t3code/.t3/worktrees")  # fixture-path-ok: a name, never read
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# The roots that hold machine state rather than repository content.
SCRATCH_ROOTS = ("/tmp", "/var/tmp", "/home", "/workspace")
# The comment that allows a reference, with the reason it is harmless.
APPROVAL = "fixture-path-ok:"
# The calls that read a path.
READERS = ("open", "Path")


class Finding:
    """One scratch path that a test reads."""

    def __init__(self, path: str, line: int, text: str, reason: str):
        self.path = path
        self.line = line
        self.text = text
        self.reason = reason

    def __repr__(self) -> str:
        return f"Finding({self.path!r}, {self.line!r}, {self.reason!r})"

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.reason}"


def is_scratch(path: str) -> bool:
    """True when a path points at machine state instead of repository content."""
    return any(path == root or path.startswith(root + "/") for root in SCRATCH_ROOTS)


def approved(line: str) -> bool:
    """True when the line states why the reference is harmless."""
    index = line.find(APPROVAL)
    if index < 0:
        return False
    return bool(line[index + len(APPROVAL):].strip())


def scan_source(source: str, name: str = "<test>") -> list[Finding]:
    """The scratch paths a source file reads."""
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return [Finding(name, error.lineno or 0, "", f"the file does not parse: {error}")]
    lines = source.splitlines()
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function = node.func
        if not isinstance(function, ast.Name) or function.id not in READERS:
            continue
        target = node.args[0]
        if not isinstance(target, ast.Constant) or not isinstance(target.value, str):
            continue
        if not is_scratch(target.value):
            continue
        line = lines[node.lineno - 1] if 0 < node.lineno <= len(lines) else ""
        if approved(line):
            continue
        findings.append(Finding(name, node.lineno, line.strip(),
                                f"the test reads {target.value}, which the repository does not contain"))
    return findings


def scan_file(path: Path) -> list[Finding]:
    """The scratch paths one file reads."""
    try:
        source = path.read_text()
    except (OSError, UnicodeDecodeError):
        return []
    return scan_source(source, str(path))


def scan_tree(root: Path) -> list[Finding]:
    """The scratch paths the test files under a directory read."""
    findings: list[Finding] = []
    for path in sorted(root.rglob("*.py")):
        findings.extend(scan_file(path))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check-test-fixtures", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root", nargs="?", default="tests", help="the directory of tests")
    arguments = parser.parse_args(argv)
    findings = scan_tree(Path(arguments.root))
    for finding in findings:
        print(f"{finding.path}:{finding.line}: {finding.reason}", file=sys.stderr)
        print(f"    {finding.text}", file=sys.stderr)
    if findings:
        print(f"test fixture lint: {len(findings)} scratch path(s) under {arguments.root}. "
              "Read committed fixtures, build a temporary directory, or state on the line why the "
              f"reference is harmless with a `{APPROVAL} <reason>` comment.", file=sys.stderr)
        return 1
    print(f"test fixture lint: no scratch paths under {arguments.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
