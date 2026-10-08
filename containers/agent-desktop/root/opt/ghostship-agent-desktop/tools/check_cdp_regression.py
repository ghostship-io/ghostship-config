#!/usr/bin/env python3
"""Assert the CDP detection expectations after a Bladebro or Chrome update.

Fails on missing results, Chrome startup failures, too few page samples,
unsuccessful commands, and detection outcomes that differ from the known
matrix. Intended to run inside the desktop container; see
docs/cdp-detection.md.
"""

import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent

CHECKS = {
    "A6": {"detected": False, "op": "Target.attachToTarget"},
    "A10": {"detected": False, "op": "Runtime.evaluate"},
    "A13": {"detected": True, "op": "Runtime.enable", "min_detected": 2},
    "C2": {"detected": False, "functional": True},
}
MIN_SAMPLES = 5


def evaluate_results(results):
    failures = []
    seen = {row.get("variant"): row for row in results}
    for variant, check in CHECKS.items():
        row = seen.get(variant)
        if row is None:
            failures.append(f"{variant}: missing result")
            continue
        if row.get("error"):
            failures.append(f"{variant}: error {row['error']}")
        if not row.get("ready", False):
            failures.append(f"{variant}: chrome not ready")
        reports = row.get("reports", 0)
        if reports < MIN_SAMPLES:
            failures.append(f"{variant}: too few page samples ({reports} < {MIN_SAMPLES})")
        if "after_detected" not in row:
            failures.append(f"{variant}: detection field missing")
        else:
            detected = bool(row["after_detected"])
            if detected != check["detected"]:
                failures.append(f"{variant}: detected={detected} expected={check['detected']}")
            if detected and row.get("detected_reports", 0) < check.get("min_detected", 1):
                failures.append(
                    f"{variant}: unstable detection ({row.get('detected_reports', 0)} reports)"
                )
        executed = " ".join(row.get("executed") or [])
        if "op" in check and check["op"] not in executed:
            failures.append(f"{variant}: expected operation {check['op']} missing ({executed!r})")
        if check.get("functional"):
            if "exit=0" not in executed:
                failures.append(f"{variant}: command did not succeed ({executed!r})")
            if not (row.get("output") or "").strip():
                failures.append(f"{variant}: command produced no output")
    return failures


def main():
    out = pathlib.Path("/config/agent-desktop/cdp-matrix/regression")
    command = [
        "python3",
        str(HERE / "run_cdp_matrix.py"),
        "--variants",
        ",".join(CHECKS),
        "--out",
        str(out),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-2000:])
        print(result.stderr[-2000:], file=sys.stderr)
        return 2
    summary = out / "results.json"
    if not summary.exists():
        print(f"missing results file: {summary}", file=sys.stderr)
        return 2
    results = json.loads(summary.read_text(encoding="utf-8"))
    failures = evaluate_results(results)
    for row in results:
        print(
            f"{row.get('variant')}: detected={row.get('after_detected')} "
            f"reports={row.get('reports')} error={row.get('error')}"
        )
    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1
    print("CDP detection expectations hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
