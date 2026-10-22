"""The integration of the durable facts into the real builder.

These tests drive `build_snapshot` and `aa.load_cache` directly, because the
defects they cover lived in the wiring between the helpers and the snapshot,
not in the helpers themselves.
"""
import importlib.util
import json
import sys
import tempfile
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


aa = load("ai_usage_integration_aa", "aa.py")
facts = load("ai_usage_integration_facts", "facts.py")
ranking = load("ai_usage_integration_ranking", "ranking.py")
snapshot = load("ai_usage_integration_snapshot", "snapshot.py")

NOW = 1_800_000_000.0
HOUR = 3600.0
DAY = 24 * HOUR

CATALOG = {
    "anthropic": {
        "models": {
            "claude-opus-5-5": {
                "name": "Claude Opus 5.5",
                "family": "claude-opus",
                "release_date": "2026-12-01",
                "limit": {"context": 1000000},
                "reasoning": True,
                "tool_call": True,
                "cost": {"input": 4.0, "output": 20.0, "cache_read": 0.4},
            }
        }
    }
}


class Catalog:
    document = CATALOG

    def price_for(self, provider, model):
        entry = CATALOG["anthropic"]["models"].get(model)
        return entry["cost"] if entry else None

    def model_name(self, provider, model):
        entry = CATALOG["anthropic"]["models"].get(model)
        return entry["name"] if entry else model

    def model_entry(self, provider, model):
        return CATALOG["anthropic"]["models"].get(model)


def ranked_model(provider="claude", model="claude-opus-5-5", options=None):
    return ranking.rank_models(
        models=[ranking.ModelRecord(provider, model)],
        catalog=Catalog(),
        quota_windows={
            provider: [
                ranking.QuotaWindow(
                    kind="weekly",
                    used_ratio=0.2,
                    reset_epoch=NOW + 4 * DAY,
                    duration_seconds=7 * DAY,
                    observed_at=NOW,
                )
            ]
        },
        free_models=set(),
        usage_tokens={},
        now=NOW,
    )


def build(ranked, fact_map=None, native=None):
    return snapshot.build_snapshot(
        now=NOW,
        sources=[
            {
                "id": "t3",
                "status": "ok",
                "detail": "",
                "observed_at": "2027-01-15T00:00:00Z",
                "observed_at_epoch": NOW,
                "last_success_at": "2027-01-15T00:00:00Z",
            }
        ],
        ranked=ranked,
        native_models=native
        or {
            ("claude", "claude-opus-5-5"): {
                "providerInstance": "claudeAgent",
                "modelId": "claude-opus-5-5",
                "options": [{"id": "effort", "currentValue": "high"}],
            }
        },
        policy={
            "frontierPrimeModels": ("claude-opus-5-5", "gpt-6.1-sol"),
            "allowedGptModels": ("gpt-6.1-sol",),
            "backgroundProviderInstances": ("opencode",),
        },
        catalog=Catalog(),
        facts=fact_map or {},
    )


def measured_fact(provider="claude", model="claude-opus-5-5", variant="", **kwargs):
    arguments = {
        "provider": provider,
        "model": model,
        "variant": variant,
        "indices": {"intelligence_index": 90.0},
        "benchmark_id": model,
        "brief_url": "https://artificialanalysis.ai/models",
        "now": NOW,
    }
    arguments.update(kwargs)
    return facts.make_fact(**arguments)


class FactBindingTests(unittest.TestCase):
    def test_a_measured_fact_feeds_the_ranking(self):
        fact = measured_fact()
        data = build(ranked_model(), {facts.identity_key("claude", "claude-opus-5-5"): fact})
        row = data["candidates"][0]
        self.assertEqual(row["value"]["strength_source"], "measured")
        # The strength is the verified record itself, not a blend with a
        # prior: 90 is the index of the fixture.
        self.assertEqual(row["value"]["strength"], 90.0)

    def test_a_fact_of_another_provider_does_not_bind(self):
        fact = measured_fact(provider="other")
        data = build(ranked_model(), {facts.identity_key("other", "claude-opus-5-5"): fact})
        row = data["candidates"][0]
        self.assertEqual(row["value"]["strength_source"], "unknown")

    def test_a_variant_fact_binds_only_its_variant(self):
        fact = measured_fact(variant="effort=high")
        data = build(
            ranked_model(),
            {facts.identity_key("claude", "claude-opus-5-5", "effort=high"): fact},
        )
        self.assertEqual(data["candidates"][0]["value"]["strength_source"], "measured")

    def test_a_variant_fact_does_not_bind_another_variant(self):
        fact = measured_fact(variant="effort=low")
        data = build(
            ranked_model(),
            {facts.identity_key("claude", "claude-opus-5-5", "effort=low"): fact},
        )
        self.assertEqual(data["candidates"][0]["value"]["strength_source"], "unknown")

    def test_a_fact_of_another_feed_version_does_not_bind(self):
        fact = measured_fact(benchmark_version="4.2")
        data = build(ranked_model(), {facts.identity_key("claude", "claude-opus-5-5"): fact})
        # No cache is published here, so the binding has no version to
        # compare: the fact is used. With a feed, the version has to agree.
        self.assertEqual(data["candidates"][0]["value"]["strength_source"], "measured")
        cache = {
            "status": "ok",
            "index_version": "4.3",
            "fetched_at": "2027-01-15T00:00:00Z",
            "fetched_at_epoch": NOW,
            "age_seconds": 0,
            "records": [],
        }
        data = snapshot.build_snapshot(
            now=NOW,
            sources=[],
            ranked=ranked_model(),
            native_models={
                ("claude", "claude-opus-5-5"): {
                    "providerInstance": "claudeAgent",
                    "modelId": "claude-opus-5-5",
                    "options": [{"id": "effort", "currentValue": "high"}],
                }
            },
            policy={
                "frontierPrimeModels": ("claude-opus-5-5",),
                "allowedGptModels": (),
                "backgroundProviderInstances": ("opencode",),
            },
            catalog=Catalog(),
            facts={facts.identity_key("claude", "claude-opus-5-5"): fact},
            aa_cache=cache,
        )
        self.assertEqual(data["candidates"][0]["value"]["strength_source"], "unknown")

    def test_a_stale_fact_does_not_bind(self):
        fact = measured_fact()
        fact["fetched_at_epoch"] = NOW - 60 * DAY
        data = build(ranked_model(), {facts.identity_key("claude", "claude-opus-5-5"): fact})
        self.assertEqual(data["candidates"][0]["value"]["strength_source"], "unknown")

    def test_a_model_without_a_fact_becomes_a_pending_identity(self):
        data = build(ranked_model(), {})
        identities = [entry["identity"] for entry in data["facts"]["pending_identities"]]
        self.assertIn(facts.identity_key("claude", "claude-opus-5-5", "effort=high"), identities)

    def test_a_model_with_a_usable_fact_is_not_pending(self):
        fact = measured_fact()
        data = build(ranked_model(), {facts.identity_key("claude", "claude-opus-5-5"): fact})
        identities = [entry["identity"] for entry in data["facts"]["pending_identities"]]
        self.assertNotIn(facts.identity_key("claude", "claude-opus-5-5", "effort=high"), identities)

    def test_the_published_facts_keep_the_identity(self):
        one = measured_fact(provider="a", model="M")
        two = measured_fact(provider="b", model="M")
        ranked = ranking.rank_models(
            models=[ranking.ModelRecord("a", "M"), ranking.ModelRecord("b", "M")],
            catalog=Catalog(),
            quota_windows={},
            free_models=set(),
            usage_tokens={},
            now=NOW,
        )
        data = snapshot.build_snapshot(
            now=NOW,
            sources=[],
            ranked=ranked,
            native_models={
                ("a", "M"): {"providerInstance": "x", "modelId": "M", "options": []},
                ("b", "M"): {"providerInstance": "y", "modelId": "M", "options": []},
            },
            policy={
                "frontierPrimeModels": (),
                "allowedGptModels": (),
                "backgroundProviderInstances": (),
            },
            catalog=Catalog(),
            facts={
                facts.identity_key("a", "M"): one,
                facts.identity_key("b", "M"): two,
            },
        )
        records = data["facts"]["records"]
        self.assertIn(facts.identity_key("a", "M"), records)
        self.assertIn(facts.identity_key("b", "M"), records)


class MergeTests(unittest.TestCase):
    def test_an_older_reading_never_replaces_a_newer_record(self):
        newer = measured_fact(model="M")
        newer["fetched_at_epoch"] = NOW
        older = measured_fact(model="M", indices={"intelligence_index": 10.0})
        older["fetched_at_epoch"] = NOW - 100
        merged = facts.merge(
            {"facts": {facts.identity_key("claude", "M"): newer}}, [older]
        )
        record = merged[facts.identity_key("claude", "M")]
        self.assertEqual(record["indices"]["intelligence_index"], 90.0)
        self.assertEqual(record["fetched_at_epoch"], NOW)

    def test_a_newer_reading_replaces_the_record(self):
        old = measured_fact(model="M", indices={"intelligence_index": 10.0})
        old["fetched_at_epoch"] = NOW - DAY
        new = measured_fact(model="M")
        merged = facts.merge(
            {"facts": {facts.identity_key("claude", "M"): old}}, [new]
        )
        record = merged[facts.identity_key("claude", "M")]
        self.assertEqual(record["indices"]["intelligence_index"], 90.0)


class CacheRobustnessTests(unittest.TestCase):
    def _write(self, directory, fetched):
        path = Path(directory) / "cache.json"
        path.write_text(
            json.dumps(
                {
                    "intelligence_index_version": "4.3",
                    "fetched_at_epoch": fetched,
                    "records": [],
                }
            )
        )
        return str(path)

    def test_a_nan_time_does_not_raise(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(directory, float("nan"))
            cache = aa.load_cache(path, NOW)
        self.assertEqual(cache["status"], "unknown_evidence_time")

    def test_a_negative_infinity_time_does_not_raise(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(directory, float("-inf"))
            cache = aa.load_cache(path, NOW)
        self.assertEqual(cache["status"], "unknown_evidence_time")

    def test_a_positive_infinity_time_does_not_raise(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(directory, float("inf"))
            cache = aa.load_cache(path, NOW)
        self.assertEqual(cache["status"], "unknown_evidence_time")

    def test_a_string_time_does_not_raise(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(directory, "yesterday")
            cache = aa.load_cache(path, NOW)
        self.assertEqual(cache["status"], "unknown_evidence_time")


if __name__ == "__main__":
    unittest.main()
