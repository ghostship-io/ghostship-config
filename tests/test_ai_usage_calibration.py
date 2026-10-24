"""How well a free route's reading predicted its refusals.

The owner's bar (ghostship-agent #462) is that a limit reading is only
trustworthy when it predicted the refusals that happened. These tests pin the
two ways it can be wrong, the daily buckets, the two-consecutive-day
acceptance rule, the published data and the probe that fails on it.
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "modules" / "self-hosted" / "ai-usage" / "collector"
if str(COLLECTOR) not in sys.path:
    sys.path.insert(0, str(COLLECTOR))

import catalog as catalog_module  # noqa: E402
import calibration  # noqa: E402
import main  # noqa: E402
import snapshot as snapshot_module  # noqa: E402

# 2026-10-24T12:00Z is 2026-10-24T02:00 in the counts' zone (Pacific/Honolulu),
# so the complete days of the window end with 2026-10-23.
NOW = 1_792_843_200.0
HOUR = 3600.0
DAY = 86400.0


def at(day, hour=0.0):
    """An instant on the UTC clock, `day` days before the reading."""
    return NOW - day * DAY + hour * HOUR


def event(model, when, outcome="success", usage=None, provider="openrouter"):
    return {
        "provider": provider,
        "model": model,
        "at": when,
        "outcome": outcome,
        "usage": usage,
        "window_hint": None,
    }


def build(events, routes=(("openrouter", "example-free"),), now=NOW, days=14):
    return calibration.build(events, routes, now, window_days=days)


class FalseAvailableTests(unittest.TestCase):
    """A refusal met a reading that offered the route."""

    def test_a_refusal_after_successes_is_a_false_available(self):
        document = build([
            event("example-free", at(1, 0)),
            event("example-free", at(1, 1)),
            event("example-free", at(1, 2), outcome="limit"),
        ])
        row = document["routes"]["openrouter/example-free"]
        day = row["days"]["2026-10-23"]
        self.assertEqual(day["refusals"], 1)
        self.assertEqual(day["false_available"], 1)
        self.assertEqual(day["false_exhausted"], 0)
        self.assertEqual(row["state"], "warn")

    def test_a_refusal_that_meets_a_spent_reading_is_not_counted(self):
        document = build([
            event("example-free", at(1, 0)),
            event("example-free", at(1, 2), outcome="limit"),
            event("example-free", at(1, 3), outcome="limit"),
            event("example-free", at(1, 4), outcome="limit"),
        ])
        row = document["routes"]["openrouter/example-free"]
        self.assertEqual(row["window"]["refusals"], 3)
        self.assertEqual(row["window"]["false_available"], 1)


class FalseExhaustedTests(unittest.TestCase):
    """A success met a reading that showed the route spent."""

    def test_the_first_success_of_a_run_is_a_false_exhausted(self):
        document = build([
            event("example-free", at(1, 0)),
            event("example-free", at(1, 1), outcome="limit"),
            event("example-free", at(1, 2)),
            event("example-free", at(1, 3)),
        ])
        row = document["routes"]["openrouter/example-free"]
        self.assertEqual(row["window"]["false_exhausted"], 1)
        self.assertEqual(row["window"]["successes"], 3)
        self.assertEqual(row["state"], "warn")


class DailyBucketsTests(unittest.TestCase):
    """The counts follow the collector's own day boundary."""

    def test_two_refusals_on_two_days_are_two_rows(self):
        document = build([
            event("example-free", at(2, 0)),
            event("example-free", at(2, 2), outcome="limit"),
            event("example-free", at(1, 0)),
            event("example-free", at(1, 2), outcome="limit"),
        ])
        row = document["routes"]["openrouter/example-free"]
        self.assertEqual(sorted(row["days"]), ["2026-10-22", "2026-10-23"])
        self.assertEqual(row["days"]["2026-10-22"]["false_available"], 1)
        self.assertEqual(row["days"]["2026-10-23"]["false_available"], 1)


class AcceptanceTests(unittest.TestCase):
    """A route fails when it was falsely available two days running."""

    def false_available_days(self):
        return [
            event("example-free", at(2, 0)),
            event("example-free", at(2, 2), outcome="limit"),
            event("example-free", at(1, 0)),
            event("example-free", at(1, 2), outcome="limit"),
        ]

    def test_two_consecutive_days_fail_the_acceptance(self):
        document = build(self.false_available_days())
        row = document["routes"]["openrouter/example-free"]
        self.assertEqual(row["false_available_streak_days"], 2)
        self.assertEqual(row["state"], "fail")
        self.assertEqual(document["acceptance"]["state"], "fail")
        self.assertEqual(document["acceptance"]["failed_routes"], ["openrouter/example-free"])
        self.assertEqual(document["acceptance"]["checked_days"], ["2026-10-22", "2026-10-23"])
        ok, reason = calibration.probe({"free_calibration": document})
        self.assertFalse(ok)
        self.assertIn("openrouter/example-free", reason)

    def test_one_false_day_is_a_warning_not_a_failure(self):
        document = build([
            event("example-free", at(1, 0)),
            event("example-free", at(1, 2), outcome="limit"),
        ])
        row = document["routes"]["openrouter/example-free"]
        self.assertEqual(row["false_available_streak_days"], 1)
        self.assertEqual(row["state"], "warn")
        self.assertEqual(document["acceptance"]["state"], "ok")
        ok, _reason = calibration.probe({"free_calibration": document})
        self.assertTrue(ok)

    def test_a_clean_day_breaks_the_streak(self):
        document = build([
            # A clean day, then a refusal on the next one: the streak is one.
            event("example-free", at(2, 0)),
            event("example-free", at(1, 0)),
            event("example-free", at(1, 2), outcome="limit"),
        ])
        row = document["routes"]["openrouter/example-free"]
        self.assertEqual(row["false_available_streak_days"], 1)
        self.assertEqual(document["acceptance"]["state"], "ok")

    def test_a_route_with_no_evidence_is_unmeasured_not_clean(self):
        document = build([], routes=(("openrouter", "quiet-free"),))
        row = document["routes"]["openrouter/quiet-free"]
        self.assertEqual(row["state"], "unmeasured")
        self.assertEqual(row["window"]["refusals"], 0)
        self.assertEqual(document["acceptance"]["state"], "ok")


class ProbeTests(unittest.TestCase):
    """The probe fails on a failing acceptance and on no reading at all."""

    def test_a_missing_calibration_fails(self):
        ok, reason = calibration.probe({})
        self.assertFalse(ok)
        self.assertIn("no free calibration", reason)
        ok, reason = calibration.probe(None)
        self.assertFalse(ok)
        self.assertIn("no calibration", reason)

    def test_the_cli_probe_returns_nonzero_on_a_failed_acceptance(self):
        document = {"free_calibration": build(AcceptanceTests().false_available_days())}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "routing.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            self.assertEqual(main.main(["--calibration-probe", "--snapshot", str(path)]), 1)
        passing = {"free_calibration": build([])}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "routing.json"
            path.write_text(json.dumps(passing), encoding="utf-8")
            self.assertEqual(main.main(["--calibration-probe", "--snapshot", str(path)]), 0)
        self.assertEqual(
            main.main(["--calibration-probe", "--snapshot", "/tmp/absent-snapshot.json"]),
            1,
        )


class PublicationTests(unittest.TestCase):
    """The Free models data carries the counts."""

    def setUp(self):
        self.document = build(AcceptanceTests().false_available_days())

    def test_the_metrics_carry_each_day_and_the_acceptance(self):
        samples = main.calibration_samples(self.document)
        days = {
            (labels["day"], value)
            for name, labels, value in samples
            if name == "ghostship_ai_free_route_false_available"
            and labels["provider"] == "openrouter"
            and labels["model"] == "example-free"
        }
        self.assertEqual(days, {("2026-10-22", 1.0), ("2026-10-23", 1.0)})
        acceptance = [
            (labels["state"], value)
            for name, labels, value in samples
            if name == "ghostship_ai_free_route_calibration_acceptance"
        ]
        self.assertEqual(acceptance, [("fail", 1.0)])

    def test_the_snapshot_publishes_the_block_and_the_route_summary(self):
        ranked = [SnapshotRow("openrouter", "example-free")]
        document = snapshot_module.build_snapshot(
            now=NOW,
            sources=[],
            ranked=ranked,
            policy={},
            catalog=catalog_module.Catalog({}),
            free_calibration=self.document,
        )
        self.assertEqual(
            document["free_calibration"]["acceptance"]["state"], "fail"
        )
        row = document["candidates"][0]
        self.assertEqual(row["calibration"]["state"], "fail")
        self.assertEqual(row["calibration"]["false_available"], 2)
        self.assertEqual(row["calibration"]["false_available_streak_days"], 2)


class SnapshotRow:
    """The least a ranking entry needs for the snapshot to publish it."""

    def __init__(self, provider, model):
        self.provider = provider
        self.model = model
        self.tier = "free"
        self.tiers = ("free",)
        self.rank = 1
        self.score = 1.0
        self.quality = 60.0
        self.remaining = None
        self.expires_in_seconds = None
        self.available = True
        self.reasons = ()
        self.windows = ()
        self.settled = True
        self.pending_reason = ""
        self.account = "openrouter"
        self.pace = None
        self.pace_binding = None
        self.capacity_binding = None
        self.applied_windows = ()
        self.used_tokens = 0.0
        self.three_d_tokens = 0.0
        self.value = None
        self.workhorses = ()
        self.observed_failure = {}
        self.availability_reason = ""
        self.unlimited = False
        self.capacity_basis = "inferred"
        self.capacity_inference = {}


if __name__ == "__main__":
    unittest.main()
