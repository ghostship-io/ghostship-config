"""Boundary tests for the capacity evidence the ranking engine relies on.

The rules under test are the ones a quota reading has to satisfy before the
ranking may treat it as headroom:

* a missing, malformed, or expired window is unknown, never healthy headroom;
* every applicable window that is spent gates the availability of a model;
* a reset in the past is not a refill;
* the urgency never divides by zero and stays inside its bounds.
"""

import importlib.util
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage" / "collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("ai_usage_ranking_bounds", ROOT / "ranking.py")
ranking = importlib.util.module_from_spec(spec)
sys.modules["ai_usage_ranking_bounds"] = ranking
spec.loader.exec_module(ranking)

NOW = 1_800_000_000.0
HOUR = 3600.0


def window(used, reset_in=None, kind="weekly", used_ratio=True, observed=NOW):
    entry = {
        "kind": kind,
        "reset_epoch": None if reset_in is None else NOW + reset_in,
        "observed_at": observed,
    }
    if used_ratio:
        entry["used_ratio"] = used
    return entry


class CapacityBoundaryTests(unittest.TestCase):
    def test_no_window_is_unknown_not_unlimited(self):
        remaining, expires_in, urgency = ranking._capacity([], NOW)
        self.assertIsNone(remaining)
        self.assertIsNone(expires_in)
        self.assertEqual(urgency, 0.0)

    def test_missing_used_ratio_is_unknown(self):
        remaining, _expires_in, _urgency = ranking._capacity([window(None, HOUR)], NOW)
        self.assertIsNone(remaining)

    def test_malformed_used_ratio_is_unknown(self):
        remaining, _expires_in, _urgency = ranking._capacity(
            [window("not a number", HOUR)], NOW
        )
        self.assertIsNone(remaining)

    def test_used_ratio_outside_the_range_is_unknown(self):
        remaining, _expires_in, _urgency = ranking._capacity([window(4.0, HOUR)], NOW)
        self.assertIsNone(remaining)

    def test_a_spent_window_is_not_headroom(self):
        remaining, _expires_in, _urgency = ranking._capacity([window(1.0, HOUR)], NOW)
        self.assertEqual(remaining, 0.0)

    def test_an_expired_window_is_not_a_refill(self):
        # The window says it resets in six hours, but that moment passed an
        # hour ago: the reading is stale, so the headroom is unknown.
        remaining, _expires_in, urgency = ranking._capacity(
            [window(0.2, -7 * HOUR)], NOW
        )
        self.assertIsNone(remaining)
        self.assertEqual(urgency, 0.0)

    def test_the_urgency_never_divides_by_zero(self):
        for hours in (-6.0, -6.0001, -100.0, 0.0, 6.0):
            remaining, expires_in, urgency = ranking._capacity(
                [window(0.1, hours * HOUR)], NOW
            )
            self.assertFalse(math.isnan(urgency))
            self.assertTrue(0.0 <= urgency <= 1.0)
            if remaining is not None:
                self.assertGreaterEqual(remaining, 0.0)

    def test_the_binding_window_gates_the_rest(self):
        # A weekly window that is spent and a session window with room: the
        # account has no headroom until the weekly window resets.
        windows = [window(1.0, 24 * HOUR, kind="weekly"), window(0.1, HOUR, kind="session")]
        remaining, expires_in, _urgency = ranking._capacity(windows, NOW)
        self.assertEqual(remaining, 0.0)
        self.assertAlmostEqual(expires_in, 24 * HOUR, delta=1)

    def test_the_most_constrained_window_sets_the_capacity(self):
        # The session window has the least headroom, so it is the binding
        # one: the capacity and the expiry both come from it.
        windows = [window(0.2, 24 * HOUR, kind="weekly"), window(0.8, HOUR, kind="session")]
        remaining, expires_in, _urgency = ranking._capacity(windows, NOW)
        self.assertAlmostEqual(remaining, 0.2)
        self.assertAlmostEqual(expires_in, HOUR, delta=1)


class AvailabilityBoundaryTests(unittest.TestCase):
    def _rank(self, windows):
        catalog = ranking.Catalog({}) if hasattr(ranking, "Catalog") else None
        return ranking.rank_models(
            models=[ranking.ModelRecord("claude", "claude-opus-5-5")],
            catalog=_EmptyCatalog(),
            quota_windows={"claude": windows} if windows else {},
            free_models=set(),
            usage_tokens={},
            aa_cache={"status": "ok", "index_version": "4.3", "fetched_at_epoch": NOW, "records": [{"id": "id-claude-opus-5-5", "slug": "claude-opus-5-5", "model": "claude-opus-5-5", "release_date": "2026-12-01", "indices": {"intelligence_index": 90.0}, "cost_per_task": 0.2, "median_performance": 100.0, "prices": {}}]},
            now=NOW,
        )

    def test_a_spent_window_makes_the_model_unavailable(self):
        ranked = self._rank([window(1.0, 24 * HOUR), window(0.1, HOUR)])
        self.assertFalse(ranked[0].available)
        self.assertEqual(ranked[0].rank, 0)

    def test_an_unknown_window_makes_the_model_unavailable(self):
        ranked = self._rank([window(None, HOUR)])
        self.assertFalse(ranked[0].available)

    def test_a_spent_window_gates_a_model_with_an_unknown_other_window(self):
        ranked = self._rank([window(1.0, 24 * HOUR), window(None, HOUR)])
        self.assertFalse(ranked[0].available)
        self.assertEqual(ranked[0].remaining, 0.0)

    def test_a_stale_window_gates_a_model(self):
        ranked = self._rank([window(0.1, HOUR, observed=NOW - 2 * HOUR)])
        self.assertFalse(ranked[0].available)

    def test_known_headroom_keeps_the_model_available(self):
        ranked = self._rank([window(0.2, 24 * HOUR), window(0.1, HOUR)])
        self.assertTrue(ranked[0].available)
        self.assertEqual(ranked[0].rank, 1)

    def test_a_stale_reading_is_not_headroom(self):
        # The provider last reported the window two hours ago.
        remaining, _expires_in, urgency = ranking._capacity(
            [window(0.1, HOUR, observed=NOW - 2 * HOUR)], NOW
        )
        self.assertIsNone(remaining)
        self.assertEqual(urgency, 0.0)

    def test_a_reading_from_the_future_is_not_fresh(self):
        remaining, _expires_in, _urgency = ranking._capacity(
            [window(0.1, HOUR, observed=NOW + 2 * HOUR)], NOW
        )
        self.assertIsNone(remaining)

    def test_a_missing_check_time_is_not_headroom(self):
        entry = {"kind": "weekly", "used_ratio": 0.1, "reset_epoch": NOW + HOUR}
        remaining, _expires_in, _urgency = ranking._capacity([entry], NOW)
        self.assertIsNone(remaining)

    def test_a_known_spent_window_gates_even_when_another_is_unknown(self):
        # The weekly window is spent; the session window is malformed. The
        # model is not usable, and the reason is the spent window.
        windows = [window(1.0, 24 * HOUR, kind="weekly"), window(None, HOUR, kind="session")]
        remaining, _expires_in, _urgency = ranking._capacity(windows, NOW)
        self.assertEqual(remaining, 0.0)

    def test_a_model_without_any_window_is_unknown_not_unlimited(self):
        ranked = self._rank([])
        self.assertIsNone(ranked[0].remaining)


class _EmptyCatalog:
    document: dict = {}

    def price_for(self, provider, model):
        return None

    def model_name(self, provider, model):
        return model

    def model_entry(self, provider, model):
        return None


if __name__ == "__main__":
    unittest.main()
