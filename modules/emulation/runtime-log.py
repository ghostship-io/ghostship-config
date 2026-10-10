"""Classify missing-runtime diagnostics with bounded, linear log searches."""

import re


RUNTIME = re.compile(r"bios|firmware|keys|prod\.keys|title\.keys|mcpx|bootrom|system card")
MISSING = re.compile(r"missing|required|cannot open|not found")


def missing_runtime(log):
    for line in log.splitlines():
        # Independent literal alternatives avoid repeated wildcard scans.
        if MISSING.search(line) and RUNTIME.search(line):
            return True
    return False
