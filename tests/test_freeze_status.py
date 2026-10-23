"""The `ghostship/freeze` status a pull request head carries.

Main requires the status, so this decision is what blocks a merge during a
freeze, whichever tool or button attempts it.
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/freeze-status"
NOW = "2026-10-23T04:00:00Z"


def run(freeze, now=NOW):
    env = {key: value for key, value in os.environ.items()
           if key not in ("GHOSTSHIP_FREEZE", "GHOSTSHIP_FREEZE_NOW")}
    env["GHOSTSHIP_FREEZE_NOW"] = now
    if freeze is not None:
        env["GHOSTSHIP_FREEZE"] = freeze if isinstance(freeze, str) else json.dumps(freeze)
    result = subprocess.run([sys.executable, str(SCRIPT)], env=env, capture_output=True,
                            text=True, check=True)
    lines = dict(line.split("=", 1) for line in result.stdout.splitlines())
    return lines["state"], lines["description"]


class FreezeStatusTests(unittest.TestCase):
    def test_no_freeze_marks_success(self):
        # A repository nobody froze must never block a merge.
        self.assertEqual(run(None), ("success", "not frozen"))
        self.assertEqual(run(""), ("success", "not frozen"))

    def test_a_running_freeze_marks_failure_with_reason_and_until(self):
        state, description = run({"schema": 1, "reason": "history rewrite",
                                  "until": "2026-10-23T06:00:00Z"})
        self.assertEqual(state, "failure")
        self.assertEqual(description, "frozen until 2026-10-23T06:00:00Z: history rewrite")

    def test_an_expired_freeze_marks_success(self):
        # until == now has expired: the freeze holds only while now < until.
        self.assertEqual(run({"reason": "r", "until": NOW}), ("success", "not frozen"))
        self.assertEqual(run({"reason": "r", "until": "2026-10-23T03:59:59Z"}),
                         ("success", "not frozen"))

    def test_an_unreadable_record_is_a_freeze(self):
        # Fail closed: a broken record must not open a frozen repository.
        for raw in ("{not json", json.dumps({"reason": "no until"}),
                    json.dumps({"until": "tomorrow"}), json.dumps({"until": "2026-10-23T06:00:00"})):
            with self.subTest(raw=raw):
                self.assertEqual(run(raw), ("failure", "frozen: unreadable freeze record"))

    def test_the_description_stays_one_line_within_the_limit(self):
        state, description = run({"reason": "line one\nline two " + "x" * 300,
                                   "until": "2026-10-23T06:00:00Z"})
        self.assertEqual(state, "failure")
        self.assertNotIn("\n", description)
        self.assertLessEqual(len(description), 140)


if __name__ == "__main__":
    unittest.main()
