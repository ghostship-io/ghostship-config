"""Quality comes from the verified Artificial Analysis record, and nowhere else.

There is no prior, no blend and no fallback. A model without an exact, fresh,
current-version record is unranked: it waits for the feed instead of being
promoted by a guess.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage" / "collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


facts = load("ai_usage_aaonly_facts", "facts.py")
ranking = load("ai_usage_aaonly_ranking", "ranking.py")
snapshot = load("ai_usage_aaonly_snapshot", "snapshot.py")

NOW = 1_800_000_000.0
DAY = 24 * 3600.0

CATALOG = {
    "minimax": {
        "models": {
            "minimax-m3.1-flash-free": {
                "name": "MiniMax M3.1 Flash Free",
                "family": "minimax",
                "release_date": "2026-12-01",
                "modalities": {"input": ["text", "image"]},
                "cost": {"input": 0.0, "output": 0.0},
            },
            "deepseek-v4.1-flash:1017": {
                "name": "DeepSeek V4.1 Flash 1017",
                "family": "deepseek-flash",
                "release_date": "2026-12-01",
                "modalities": {"input": ["text"]},
                "cost": {"input": 0.15, "output": 0.6},
            },
        }
    }
}


class Catalog:
    document = CATALOG

    def model_entry(self, provider, model):
        return CATALOG["minimax"]["models"].get(model)

    def price_for(self, provider, model):
        entry = self.model_entry(provider, model)
        return entry["cost"] if entry else None

    def model_name(self, provider, model):
        entry = self.model_entry(provider, model)
        return entry["name"] if entry else model

    def release_date(self, provider, model):
        entry = self.model_entry(provider, model)
        return entry.get("release_date") if entry else None


def cache(records, version="4.3", fetched=NOW):
    return {
        "status": "ok",
        "index_version": version,
        "fetched_at": "2027-01-15T00:00:00Z",
        "fetched_at_epoch": fetched,
        "age_seconds": max(0.0, NOW - fetched),
        "records": records,
    }


def build(records, ranked=None, facts_map=None, aa_version="4.3", fetched=NOW):
    models = [
        ranking.ModelRecord("minimax", "minimax-m3.1-flash-free"),
        ranking.ModelRecord("minimax", "deepseek-v4.1-flash:1017"),
    ]
    feed = cache(records, version=aa_version, fetched=fetched)
    ranked = ranked or ranking.rank_models(
        models=models,
        catalog=Catalog(),
        quota_windows={},
        free_models={("minimax", "minimax-m3.1-flash-free")},
        promo_models={("minimax", "deepseek-v4.1-flash:1017")},
        usage_tokens={},
        aa_cache=feed,
        now=NOW,
    )
    return snapshot.build_snapshot(
        now=NOW,
        sources=[
            {"id": "t3", "status": "ok", "reason": "ok", "observed_at_epoch": NOW}
        ],
        ranked=ranked,
        native_models={
            ("minimax", "minimax-m3.1-flash-free"): {
                "providerInstance": "opencode",
                "modelId": "minimax-m3.1-flash-free",
                "options": [],
            },
            ("minimax", "deepseek-v4.1-flash:1017"): {
                "providerInstance": "opencode",
                "modelId": "deepseek-v4.1-flash:1017",
                "options": [],
            },
        },
        policy={
            "frontierPrimeModels": (),
            "allowedGptModels": (),
            "backgroundProviderInstances": ("opencode",),
        },
        catalog=Catalog(),
        facts=facts_map or {},
        aa_cache=feed,
        free_models={("minimax", "minimax-m3.1-flash-free")},
        promo_models={("minimax", "deepseek-v4.1-flash:1017")},
    )


MINIMAX = {
    "model": "minimax-m3.1-flash-free",
    "indices": {
        "intelligence_index": 42.7,
        "coding_index": 43.4,
        "agentic_index": 40.0,
        "engineering_index": 43.4,
    },
    "cost_per_task": 0.22,
    "median_performance": 100.0,
}


class AAOnlyTests(unittest.TestCase):
    def test_an_unmatched_model_cannot_beat_a_matched_one(self):
        data = build([MINIMAX])
        winners = {entry["model"] for entry in data["tier_winners"].get("bulk", [])}
        self.assertEqual(winners, {"minimax-m3.1-flash-free"})
        deepseek = [row for row in data["candidates"] if "deepseek" in row["model"]]
        if deepseek:
            self.assertEqual(deepseek[0]["aa"]["state"], "missing")
            self.assertEqual(deepseek[0]["rank"], {})

    def test_an_unmatched_model_carries_no_quality_number(self):
        data = build([MINIMAX])
        deepseek = [row for row in data["candidates"] if "deepseek" in row["model"]][0]
        # A prior may not stand in for a measurement at the public layer.
        self.assertIsNone(deepseek["quality"]["value"])
        self.assertEqual(deepseek["quality"]["source"], "unknown")
        self.assertFalse(deepseek["quality"]["measured"])

    def test_an_unmatched_model_has_no_strength_and_no_value(self):
        data = build([MINIMAX])
        deepseek = [row for row in data["candidates"] if "deepseek" in row["model"]][0]
        self.assertIsNone(deepseek["value"]["strength"])
        self.assertIsNone(deepseek["value"]["value"])
        self.assertEqual(deepseek["value"]["strength_source"], "unknown")

    def test_a_matched_model_carries_the_indices_as_indices(self):
        data = build([MINIMAX])
        row = [row for row in data["candidates"] if row["model"] == "minimax-m3.1-flash-free"][0]
        self.assertEqual(row["value"]["strength"], 42.7)
        self.assertEqual(row["value"]["strength_source"], "measured")
        self.assertEqual(row["aa"]["indices"]["intelligence"], 42.7)
        self.assertEqual(row["aa"]["indices"]["coding"], 43.4)
        self.assertIsNotNone(row["value"]["components"]["intelligence"])
        self.assertEqual(
            row["value"]["components"]["intelligence"]["source"], "measured"
        )

    def test_matched_records_compare_on_the_record_only(self):
        other = {
            "model": "deepseek-v4.1-flash:1017",
            "indices": {
                "intelligence_index": 50.0,
                "coding_index": 50.0,
                "agentic_index": 50.0,
                "engineering_index": 50.0,
            },
            "cost_per_task": 0.1,
            "median_performance": 120.0,
        }
        data = build([MINIMAX, other])
        by_model = {row["model"]: row for row in data["candidates"]}
        # The quality comparison is the measured record, never a prior. The
        # value also carries the listed price, so the free model may still
        # win: that is a cost preference, not a quality estimate.
        self.assertEqual(by_model["deepseek-v4.1-flash:1017"]["value"]["strength"], 50.0)
        self.assertEqual(by_model["minimax-m3.1-flash-free"]["value"]["strength"], 42.7)
        for row in by_model.values():
            self.assertEqual(row["value"]["strength_source"], "measured")
            self.assertEqual(row["quality"]["source"], "measured")

    def test_a_stale_record_is_unranked(self):
        data = build([MINIMAX], fetched=NOW - 10 * DAY)
        winners = {entry["model"] for entry in data["tier_winners"].get("bulk", [])}
        self.assertEqual(winners, set())
        row = [row for row in data["candidates"] if row["model"] == "minimax-m3.1-flash-free"][0]
        self.assertEqual(row["value"]["strength_source"], "unknown")

    def test_a_cache_without_a_version_is_unusable(self):
        data = build([MINIMAX], aa_version="")
        winners = {entry["model"] for entry in data["tier_winners"].get("bulk", [])}
        self.assertEqual(winners, set())

    def test_a_record_from_the_future_is_unranked(self):
        data = build([MINIMAX], fetched=NOW + DAY)
        winners = {entry["model"] for entry in data["tier_winners"].get("bulk", [])}
        self.assertEqual(winners, set())

    def test_the_public_metrics_carry_no_prior(self):
        data = build([MINIMAX])
        samples = snapshot.decision_samples(data)
        names = {name for name, _labels, _value in samples}
        self.assertNotIn("ghostship_ai_model_quality", names)
        strengths = [
            (labels, value)
            for name, labels, value in samples
            if name == "ghostship_ai_model_strength"
        ]
        # The strength of the matched model is its index; the unmatched model
        # has no strength series at all.
        self.assertEqual([labels["model"] for labels, _value in strengths], ["minimax-m3.1-flash-free"])
        self.assertEqual(strengths[0][1], 42.7)


if __name__ == "__main__":
    unittest.main()
