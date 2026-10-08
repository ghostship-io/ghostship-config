#!/usr/bin/env python3
"""Assert the CDP detection expectations after a Bladebro or Chrome update.

Runs the key matrix variants and fails when the clean operations start being
detected or the positive control stops being detected. Intended to run inside
the desktop container; see docs/cdp-detection.md.
"""

import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
EXPECT = {
    "A6": False,
    "A10": False,
    "A13": True,
    "C2": False,
}


def main():
    out = pathlib.Path("/config/agent-desktop/cdp-matrix/regression")
    command = [
        "python3",
        str(HERE / "run_cdp_matrix.py"),
        "--variants",
        ",".join(EXPECT),
        "--out",
        str(out),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-2000:])
        print(result.stderr[-2000:], file=sys.stderr)
        return 2
    results = json.loads((out / "results.json").read_text(encoding="utf-8"))
    failures = []
    for row in results:
        variant = row.get("variant")
        if variant not in EXPECT:
            continue
        expected = EXPECT[variant]
        actual = bool(row.get("after_detected"))
        status = "ok" if actual == expected else "FAIL"
        print(f"{variant}: detected={actual} expected={expected} {status}")
        if actual != expected:
            failures.append(variant)
    if failures:
        print(f"CDP regression detected for: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("CDP detection expectations hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
