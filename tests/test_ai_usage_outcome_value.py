"""The outcome-value maths of the ranking's value policy.

The policy values a model by the outcome it is expected to deliver, not by
the raw intelligence index: a prior from the intelligence index inside its
tier, shrunk toward the measured outcomes, and combined with the measured
efficiency. The trust of a route then scales the value, and a free route
leads while it is close enough to the best paid one.
"""

import sys
import unittest
from pathlib import Path

COLLECTOR = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage/collector"
if str(COLLECTOR) not in sys.path:
    sys.path.insert(0, str(COLLECTOR))

import ranking  # noqa: E402
import value_policy  # noqa: E402


def value_policy_module():
    """The module this test asks for, and a clear failure when it is absent."""
    return value_policy


class OutcomePriorTests(unittest.TestCase):
    """p0: where the intelligence index sits inside its tier."""

    def test_the_top_of_the_range_is_the_ceiling(self):
        policy = value_policy_module()
        self.assertAlmostEqual(policy.outcome_prior(45.1, 24.7, 45.1), 0.900, places=4)

    def test_a_mid_range_index_is_interpolated(self):
        policy = value_policy_module()
        self.assertAlmostEqual(policy.outcome_prior(42.7, 24.7, 45.1), 0.8529, places=4)

    def test_the_bottom_of_the_range_is_the_floor(self):
        policy = value_policy_module()
        self.assertAlmostEqual(policy.outcome_prior(24.7, 24.7, 45.1), 0.5, places=4)

    def test_a_missing_index_gets_the_neutral_prior(self):
        policy = value_policy_module()
        self.assertAlmostEqual(policy.outcome_prior(None, 24.7, 45.1), 0.5, places=4)

    def test_a_one_model_tier_gets_the_ceiling(self):
        policy = value_policy_module()
        self.assertAlmostEqual(policy.outcome_prior(30, 30, 30), 0.9, places=4)

    def test_the_prior_is_clamped_to_its_bounds(self):
        policy = value_policy_module()
        self.assertAlmostEqual(policy.outcome_prior(60.0, 24.7, 45.1), 0.9, places=4)
        self.assertAlmostEqual(policy.outcome_prior(10.0, 24.7, 45.1), 0.5, places=4)


class OutcomeQualityTests(unittest.TestCase):
    """p: the prior shrunk toward the measured outcomes."""

    def test_no_evidence_leaves_the_prior(self):
        policy = value_policy_module()
        self.assertAlmostEqual(policy.outcome_quality(0.9, 0, 0), 0.900, places=4)

    def test_evidence_shrinks_the_prior(self):
        policy = value_policy_module()
        self.assertAlmostEqual(policy.outcome_quality(0.9, 173, 106), 0.6284, places=4)
        self.assertAlmostEqual(policy.outcome_quality(0.9, 173, 106), 115 / 183, places=6)

    def test_a_mid_prior_is_shrunk_the_same_way(self):
        policy = value_policy_module()
        self.assertAlmostEqual(policy.outcome_quality(0.85294, 148, 104), 0.7122, places=4)

    def test_the_prior_strength_is_ten_outcomes(self):
        policy = value_policy_module()
        self.assertEqual(policy.OUTCOME_PRIOR_STRENGTH, 10)
        self.assertAlmostEqual(
            policy.outcome_quality(0.5, 3, 1), (10 * 0.5 + 1) / 13, places=6
        )

    def test_impossible_counts_are_rejected(self):
        policy = value_policy_module()
        with self.assertRaises(ValueError):
            policy.outcome_quality(0.9, 5, 6)
        with self.assertRaises(ValueError):
            policy.outcome_quality(0.9, -1, 0)
        with self.assertRaises(ValueError):
            policy.outcome_quality(0.9, 5, -1)


class OutcomeValueTests(unittest.TestCase):
    """value: the outcome-weighted quality and the measured efficiency."""

    def test_the_value_uses_the_policy_weights(self):
        policy = value_policy_module()
        self.assertAlmostEqual(
            policy.outcome_value(0.9, 1 / (1 + 0.5)), 0.83, places=6
        )

    def test_a_missing_quality_leaves_the_value_unknown(self):
        policy = value_policy_module()
        self.assertIsNone(policy.outcome_value(None, 0.5))

    def test_a_missing_efficiency_leaves_the_value_unknown(self):
        policy = value_policy_module()
        self.assertIsNone(policy.outcome_value(0.9, None))


class TrustTests(unittest.TestCase):
    """The trust level orders the tiers and halves an untrusted value."""

    def test_the_levels_are_in_rank_order(self):
        policy = value_policy_module()
        self.assertEqual(
            tuple(policy.TRUST_LEVELS), ("trusted", "backup", "untrusted", "excluded")
        )
        self.assertEqual(policy.trust_rank("trusted"), 0)
        self.assertEqual(policy.trust_rank("backup"), 1)
        self.assertEqual(policy.trust_rank("untrusted"), 2)
        self.assertEqual(policy.trust_rank("excluded"), 3)

    def test_an_unknown_level_ranks_as_trusted(self):
        policy = value_policy_module()
        self.assertEqual(policy.trust_rank(None), 0)
        self.assertEqual(policy.trust_rank("weird"), 0)

    def test_untrusted_halves_the_value(self):
        policy = value_policy_module()
        self.assertEqual(policy.UNTRUSTED_VALUE_FACTOR, 0.5)
        self.assertAlmostEqual(
            policy.trust_adjusted_value(0.46, "untrusted"), 0.23, places=6
        )

    def test_the_other_levels_leave_the_value_alone(self):
        policy = value_policy_module()
        self.assertAlmostEqual(
            policy.trust_adjusted_value(0.46, "backup"), 0.46, places=6
        )
        self.assertAlmostEqual(
            policy.trust_adjusted_value(0.46, "trusted"), 0.46, places=6
        )
        self.assertAlmostEqual(
            policy.trust_adjusted_value(0.46, "excluded"), 0.46, places=6
        )

    def test_a_missing_value_stays_missing(self):
        policy = value_policy_module()
        self.assertIsNone(policy.trust_adjusted_value(None, "untrusted"))


class FreeRouteTests(unittest.TestCase):
    """A free route leads while it is within the margin of the best paid one."""

    def test_the_margin_is_ten_points(self):
        policy = value_policy_module()
        self.assertEqual(policy.FREE_ROUTE_MARGIN, 0.10)
        self.assertTrue(policy.free_route_leads(0.80, 0.90))
        self.assertFalse(policy.free_route_leads(0.79, 0.90))

    def test_a_missing_quality_never_leads(self):
        policy = value_policy_module()
        self.assertFalse(policy.free_route_leads(None, 0.90))
        self.assertFalse(policy.free_route_leads(0.80, None))


class PolicyDocumentTests(unittest.TestCase):
    """The published policy states the outcome maths and the trust order."""

    def test_the_outcome_section_is_published(self):
        document = value_policy_module().policy_document()
        outcome = document["outcome"]
        self.assertIn("0.5 + 0.4", outcome["prior"])
        self.assertIn("(k * p0 + s) / (k + n)", outcome["quality"])
        self.assertIn("0.70 * p + 0.30 * E", outcome["value"])
        self.assertEqual(outcome["prior_strength"], 10)
        self.assertEqual(outcome["free_route_margin"], 0.10)
        self.assertEqual(outcome["untrusted_value_factor"], 0.5)

    def test_the_trust_section_is_published(self):
        document = value_policy_module().policy_document()
        trust = document["trust"]
        self.assertEqual(tuple(trust["levels"]), ("trusted", "backup", "untrusted", "excluded"))
        self.assertEqual(trust["order"]["backup"], 1)
        self.assertEqual(trust["order"]["excluded"], 3)

    def test_the_existing_sections_are_unchanged(self):
        document = value_policy_module().policy_document()
        self.assertEqual(
            document["value"]["weights"], {"intelligence": 0.70, "cost_per_task": 0.30}
        )
        self.assertEqual(
            document["value_3d"]["weights"],
            {"intelligence": 0.45, "three_d": 0.25, "cost_per_task": 0.30},
        )
        self.assertEqual(document["value"]["formula"], "0.70 * I + 0.30 * E")
        self.assertEqual(document["cost_transform_in_force"], "inverse")
        self.assertFalse(document["renormalized"])


class UnchangedScoreTests(unittest.TestCase):
    """The measured value_score of the ranking is not touched by this change."""

    def test_value_score_still_reads_the_measured_record(self):
        cache = {
            "status": "ok",
            "index_version": "4.3",
            "fetched_at": "2025-09-20T00:00:00Z",
            "fetched_at_epoch": 1_760_000_000.0,
            "records": [
                {
                    "id": "id-p-m",
                    "slug": "m",
                    "model": "m",
                    "release_date": "2025-09-20",
                    "indices": {"intelligence_index": 80.0},
                    "cost_per_task": 0.5,
                    "median_performance": 100.0,
                    "prices": {},
                }
            ],
        }
        self.assertAlmostEqual(ranking.value_score(cache, "p", "m"), 0.76, places=6)
        self.assertIsNone(ranking.value_score(None, "p", "m"))


if __name__ == "__main__":
    unittest.main()
