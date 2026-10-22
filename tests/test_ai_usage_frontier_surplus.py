"""The frontier surplus: when a frontier model may carry volume work.

A weekly or monthly allowance that resets within a day will be lost if it is
not used, so it may carry volume work. The short session window never
counts: it would let the review capacity be spent days before the week or
the month does. The session window also holds the reserve: when it is ahead
of the line, the review capacity is under pressure and nothing is spared.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage" / "collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("ai_usage_ranking_surplus", ROOT / "ranking.py")
ranking = importlib.util.module_from_spec(spec)
sys.modules["ai_usage_ranking_surplus"] = ranking
spec.loader.exec_module(ranking)

NOW = 1_800_000_000.0
HOUR = 3600.0
DAY = 24 * HOUR


def window(used=0.1, reset_in=DAY, kind="weekly", observed=NOW):
    return ranking.QuotaWindow(
        kind=kind,
        used_ratio=used,
        reset_epoch=NOW + reset_in,
        duration_seconds=7 * DAY if kind == "weekly" else (30 * DAY if kind == "monthly" else 5 * HOUR),
        observed_at=observed,
    )


class SurplusTests(unittest.TestCase):
    def test_a_weekly_allowance_that_resets_within_a_day_is_surplus(self):
        surplus = ranking._frontier_surplus([window(0.2, 12 * HOUR, "weekly")], NOW)
        self.assertTrue(surplus["available"])
        self.assertAlmostEqual(surplus["surplus_ratio"], 0.8)
        self.assertEqual(surplus["expires_in_seconds"], 12 * 3600)

    def test_the_boundary_is_a_day(self):
        inside = ranking._frontier_surplus([window(0.2, DAY, "weekly")], NOW)
        self.assertTrue(inside["available"])
        outside = ranking._frontier_surplus([window(0.2, DAY + HOUR, "weekly")], NOW)
        self.assertFalse(outside["available"])

    def test_the_session_window_is_never_a_surplus(self):
        surplus = ranking._frontier_surplus([window(0.2, 2 * HOUR, "session")], NOW)
        self.assertFalse(surplus["available"])
        self.assertIn("weekly or monthly", surplus["reason"])

    def test_a_spent_allowance_is_no_surplus(self):
        surplus = ranking._frontier_surplus([window(1.0, 12 * HOUR, "weekly")], NOW)
        self.assertFalse(surplus["available"])

    def test_an_unknown_window_is_no_surplus(self):
        surplus = ranking._frontier_surplus(
            [window(None, 12 * HOUR, "weekly"), window(0.1, 2 * HOUR, "session")], NOW
        )
        self.assertFalse(surplus["available"])

    def test_a_session_ahead_of_the_line_spares_nothing(self):
        # The session window is used faster than the line allows: the review
        # capacity is under pressure.
        windows = [
            window(0.2, 12 * HOUR, "weekly"),
            window(0.9, 2 * HOUR, "session"),
        ]
        surplus = ranking._frontier_surplus(windows, NOW)
        self.assertFalse(surplus["available"])
        self.assertIn("ahead of the line", surplus["reason"])

    def test_a_weekly_surplus_with_a_calm_session_is_available(self):
        windows = [
            window(0.2, 12 * HOUR, "weekly"),
            window(0.1, 2 * HOUR, "session"),
        ]
        surplus = ranking._frontier_surplus(windows, NOW)
        self.assertTrue(surplus["available"])


class SurplusInTheTiersTests(unittest.TestCase):
    def _rank(self, windows):
        return ranking.rank_models(
            models=[ranking.ModelRecord("claude", "claude-opus-5-5")],
            catalog=_Catalog(),
            quota_windows={"claude": windows},
            free_models=set(),
            usage_tokens={},
            aa_cache={"status": "ok", "index_version": "4.3", "fetched_at_epoch": NOW, "records": [{"id": "id-claude-opus-5-5", "slug": "claude-opus-5-5", "model": "claude-opus-5-5", "release_date": "2026-12-01", "indices": {"intelligence_index": 90.0}, "cost_per_task": 0.2, "median_performance": 100.0, "prices": {}}]},
            now=NOW,
        )

    def test_a_frontier_model_with_an_expiring_surplus_holds_a_bulk_rank(self):
        ranked = self._rank([window(0.2, 12 * HOUR, "weekly"), window(0.1, 2 * HOUR, "session")])
        tiers = {entry.tier for entry in ranked}
        self.assertIn("frontier", tiers)
        self.assertIn("bulk", tiers)

    def test_a_frontier_model_without_an_expiring_surplus_stays_out_of_bulk(self):
        ranked = self._rank([window(0.2, 5 * DAY, "weekly"), window(0.1, 2 * HOUR, "session")])
        tiers = {entry.tier for entry in ranked}
        self.assertIn("frontier", tiers)
        self.assertNotIn("bulk", tiers)

    def test_a_frontier_model_with_a_spent_allowance_stays_out_of_bulk(self):
        ranked = self._rank([window(1.0, 12 * HOUR, "weekly"), window(0.1, 2 * HOUR, "session")])
        tiers = {entry.tier for entry in ranked}
        self.assertNotIn("bulk", tiers)

    def test_no_available_frontier_leaves_the_review_without_a_rank(self):
        # Every window is spent: the model cannot serve the review either.
        ranked = self._rank([window(1.0, 12 * HOUR, "weekly"), window(1.0, 2 * HOUR, "session")])
        self.assertFalse(any(entry.available for entry in ranked))
        self.assertFalse(any(entry.tier == "frontier" for entry in ranked))


class _Catalog:
    """A catalog that knows the model, so it can hold the frontier."""

    document = {
        "anthropic": {
            "models": {
                "claude-opus-5-5": {
                    "name": "Claude Opus 5.5",
                    "family": "claude-opus",
                    "release_date": "2026-12-01",
                    "limit": {"context": 1000000},
                    "reasoning": True,
                    "tool_call": True,
                    "cost": {"input": 4.0, "output": 20.0},
                }
            }
        }
    }

    def price_for(self, provider, model):
        entry = self.document["anthropic"]["models"].get(model)
        return entry["cost"] if entry else None

    def model_name(self, provider, model):
        entry = self.document["anthropic"]["models"].get(model)
        return entry["name"] if entry else model

    def model_entry(self, provider, model):
        return self.document["anthropic"]["models"].get(model)


if __name__ == "__main__":
    unittest.main()
