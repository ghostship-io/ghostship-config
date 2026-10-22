"""The durable facts of a model: reuse, staleness, and the bounded estimate."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage" / "collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("ai_usage_facts", ROOT / "facts.py")
facts = importlib.util.module_from_spec(spec)
sys.modules["ai_usage_facts"] = facts
spec.loader.exec_module(facts)

NOW = 1_800_000_000.0
DAY = 24 * 3600.0


def measured_fact(model="MiniMax M3.1 Flash", provider="minimax", **kwargs):
    arguments = {
        "provider": provider,
        "model": model,
        "indices": {"intelligence_index": 42.0, "coding_index": 40.0},
        "benchmark_id": "minimax/minimax-m3.1-flash",
        "brief_url": "https://artificialanalysis.ai/models",
        "now": NOW,
    }
    arguments.update(kwargs)
    return facts.make_fact(**arguments)


class FactTests(unittest.TestCase):
    def test_a_fact_carries_its_evidence(self):
        fact = measured_fact()
        self.assertEqual(fact["source"], "measured")
        self.assertEqual(fact["benchmark_version"], "4.3")
        self.assertTrue(fact["evidence_fingerprint"])
        self.assertEqual(fact["indices"]["intelligence_index"], 42.0)

    def test_a_fact_of_the_same_evidence_has_the_same_fingerprint(self):
        self.assertEqual(
            measured_fact()["evidence_fingerprint"], measured_fact()["evidence_fingerprint"]
        )
        self.assertNotEqual(
            measured_fact()["evidence_fingerprint"],
            measured_fact(indices={"intelligence_index": 43.0})["evidence_fingerprint"],
        )

    def test_a_current_fact_is_reused(self):
        fact = measured_fact()
        needed, why = facts.needs_research(fact, facts.identity_key("minimax", "MiniMax M3.1 Flash"), NOW)
        self.assertFalse(needed)
        self.assertEqual(why, "")

    def test_a_new_identity_is_researched_again(self):
        fact = measured_fact()
        needed, why = facts.needs_research(fact, "other:model", NOW)
        self.assertTrue(needed)
        self.assertIn("identity", why)

    def test_a_new_benchmark_version_is_researched_again(self):
        fact = measured_fact()
        fact["benchmark_version"] = "3.9"
        needed, why = facts.needs_research(fact, facts.identity_key("minimax", "MiniMax M3.1 Flash"), NOW)
        self.assertTrue(needed)
        self.assertIn("benchmark version", why)

    def test_a_stale_fact_is_researched_again(self):
        fact = measured_fact()
        needed, why = facts.needs_research(fact, facts.identity_key("minimax", "MiniMax M3.1 Flash"), NOW + 60 * DAY)
        self.assertTrue(needed)
        self.assertIn("stale", why)

    def test_a_pending_fact_waits_visibly(self):
        fact = facts.pending_fact(
            provider="minimax", model="MiniMax M3.1 Flash", reason="the brief is expected", now=NOW
        )
        self.assertEqual(fact["status"], "pending")
        self.assertEqual(fact["pending_reason"], "the brief is expected")
        needed, why = facts.needs_research(fact, facts.identity_key("minimax", "MiniMax M3.1 Flash"), NOW)
        self.assertTrue(needed)
        self.assertIn("expected", why)

    def test_an_estimate_is_bounded_and_labelled(self):
        fact = facts.estimated_fact(
            provider="stealth", model="some-model", strength=90.0, basis="a prior, not a measurement", now=NOW
        )
        self.assertEqual(fact["source"], "estimated")
        self.assertEqual(fact["status"], "estimated")
        self.assertLessEqual(fact["confidence"], facts.ESTIMATE_CONFIDENCE)
        self.assertIn("prior", fact["basis"])

    def test_the_merge_keeps_the_newer_evidence(self):
        state = {"facts": {facts.identity_key("minimax", "M"): measured_fact(model="M")}}
        newer = measured_fact(model="M", indices={"intelligence_index": 50.0})
        merged = facts.merge(state, [newer])
        key = facts.identity_key("minimax", "M")
        self.assertEqual(merged[key]["indices"]["intelligence_index"], 50.0)

    def test_the_merge_keeps_the_fact_when_the_evidence_is_the_same(self):
        fact = measured_fact(model="M")
        state = {"facts": {facts.identity_key("minimax", "M"): fact}}
        merged = facts.merge(state, [measured_fact(model="M")])
        key = facts.identity_key("minimax", "M")
        self.assertEqual(merged[key]["evidence_fingerprint"], fact["evidence_fingerprint"])

    def test_the_key_carries_the_reasoning_variant(self):
        self.assertNotEqual(
            facts.identity_key("p", "model", "high"),
            facts.identity_key("p", "model", "low"),
        )


class FactBoundaryTests(unittest.TestCase):
    """The probes the root frontier ran against the durable facts."""

    def test_a_fact_from_the_future_is_not_current(self):
        fact = measured_fact()
        fact["fetched_at_epoch"] = NOW + 86400
        self.assertFalse(facts.is_current(fact, NOW))

    def test_a_nan_fetched_at_is_not_current(self):
        fact = measured_fact()
        fact["fetched_at_epoch"] = float("nan")
        self.assertFalse(facts.is_current(fact, NOW))

    def test_an_infinite_fetched_at_is_not_current(self):
        fact = measured_fact()
        fact["fetched_at_epoch"] = float("inf")
        self.assertFalse(facts.is_current(fact, NOW))

    def test_a_pending_fact_waits_for_its_next_check(self):
        fact = facts.pending_fact(
            provider="minimax",
            model="MiniMax M3.1 Flash",
            reason="the brief is expected",
            next_check_at=NOW + 3600,
            now=NOW,
        )
        needed, why = facts.needs_research(
            fact, facts.identity_key("minimax", "MiniMax M3.1 Flash"), NOW
        )
        self.assertFalse(needed)
        self.assertIn("later", why)

    def test_a_pending_fact_is_researched_when_the_check_is_due(self):
        fact = facts.pending_fact(
            provider="minimax",
            model="MiniMax M3.1 Flash",
            reason="the brief is expected",
            next_check_at=NOW - 60,
            now=NOW,
        )
        needed, _why = facts.needs_research(
            fact, facts.identity_key("minimax", "MiniMax M3.1 Flash"), NOW
        )
        self.assertTrue(needed)

    def test_the_index_keeps_the_provider_and_the_variant(self):
        one = measured_fact(model="M", provider="a")
        two = measured_fact(model="M", provider="b")
        three = measured_fact(model="M", provider="a", variant="high")
        indexed = facts.index(
            {
                facts.identity_key("a", "M"): one,
                facts.identity_key("b", "M"): two,
                facts.identity_key("a", "M", "high"): three,
            }
        )
        self.assertEqual(len(indexed), 3)
        self.assertIn(facts.identity_key("a", "M", "high"), indexed)

    def test_a_fresh_measurement_refreshes_a_stale_record(self):
        stale = measured_fact(model="M")
        stale["fetched_at_epoch"] = NOW - 60 * DAY
        fresh = measured_fact(model="M")
        state = {"facts": {facts.identity_key("minimax", "M"): stale}}
        merged = facts.merge(state, [fresh])
        key = facts.identity_key("minimax", "M")
        self.assertEqual(merged[key]["fetched_at_epoch"], fresh["fetched_at_epoch"])
        self.assertTrue(facts.is_current(merged[key], NOW))

    def test_an_estimate_rejects_a_non_finite_or_out_of_range_strength(self):
        for strength in (float("nan"), float("inf"), -1.0, 101.0):
            with self.assertRaises(ValueError):
                facts.estimated_fact(
                    provider="p", model="m", strength=strength, basis="a prior", now=NOW
                )

    def test_an_estimate_rejects_a_confidence_above_the_ceiling(self):
        with self.assertRaises(ValueError):
            facts.estimated_fact(
                provider="p",
                model="m",
                strength=50.0,
                basis="a prior",
                confidence=0.95,
                now=NOW,
            )

    def test_an_estimate_keeps_its_confidence_and_strength_apart(self):
        fact = facts.estimated_fact(
            provider="p", model="m", strength=90.0, basis="a prior", now=NOW
        )
        self.assertEqual(fact["indices"]["intelligence_index"], 90.0)
        self.assertEqual(fact["confidence"], facts.ESTIMATE_CONFIDENCE)
        self.assertEqual(fact["strength_scale"], {"min": 0.0, "max": 100.0})


if __name__ == "__main__":
    unittest.main()
