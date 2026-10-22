"""The canonical provider-model to Artificial Analysis binding.

The fixtures are trimmed copies of the real feed cache and of the live
candidate identities from the 2026-10-21 audit. The records keep the feed's own
id, slug, name, release date and indices; the candidates keep the provider's
own model ids. The tests therefore reproduce the real naming differences that
the name-equality lookup missed, and they still refuse a wrong release, a
wrong reasoning variant, a punctuation-different model and an ambiguous set.
"""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage" / "collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ai-usage"

import aa_bind


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


snapshot = load("ai_usage_bind_snapshot", "snapshot.py")
ranking = load("ai_usage_bind_ranking", "ranking.py")

NOW = 1_800_000_000.0


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class BindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cache = fixture("aa-records.json")
        cls.records = cls.cache["records"]

    def resolve(self, provider, model, options=None):
        return aa_bind.resolve(self.records, provider, model, options=options)

    def record(self, slug):
        return next(record for record in self.records if record["slug"] == slug)

    def test_a_checkpointed_id_binds_to_its_own_aa_record(self):
        binding = self.resolve(
            "ollama",
            "deepseek-v4.1-flash:1017",
            options=[{"id": "variant", "current_value": "high"}],
        )
        record = self.record("deepseek-v4-1-flash-1017")
        self.assertEqual(binding["state"], "measured")
        self.assertEqual(binding["id"], record["id"])
        self.assertEqual(binding["slug"], record["slug"])
        self.assertEqual(binding["name"], "DeepSeek V4.1 Flash 1017 (Max)")
        self.assertEqual(binding["record"]["indices"]["intelligence_index"], 45.1)
        # The measurement condition is the record's own Max, not the native
        # High, and the mismatch is published rather than guessed away.
        self.assertEqual(binding["measured_variant"], "max")
        self.assertEqual(binding["native_variant"], "high")
        self.assertEqual(binding["variant_match"], "variant_mismatch")

    def test_the_base_and_the_checkpoint_are_different_records(self):
        base = self.resolve("ollama", "deepseek-v4.1-flash")
        self.assertEqual(base["slug"], "deepseek-v4-1-flash")
        self.assertEqual(base["record"]["indices"]["intelligence_index"], 39.5)
        checkpoint = self.resolve("ollama", "deepseek-v4.1-flash:1017")
        self.assertNotEqual(base["id"], checkpoint["id"])

    def test_a_reasoning_id_never_borrows_the_non_reasoning_record(self):
        binding = self.resolve("ollama", "deepseek-v4.1-flash")
        self.assertNotEqual(binding["slug"], "deepseek-v4-1-flash-non-reasoning")
        self.assertEqual(binding["record"]["indices"]["intelligence_index"], 39.5)

    def test_a_promotion_wrapper_is_not_an_identity(self):
        for provider, model in (
            ("opencode-go", "minimax-m3.1-flash-free"),
            ("kilo", "minimax/minimax-m3.1-flash:free"),
            ("ollama", "minimax-m3.1-flash"),
        ):
            binding = self.resolve(provider, model)
            self.assertEqual(binding["state"], "measured")
            self.assertEqual(binding["slug"], "minimax-m3-1-flash")
            self.assertEqual(binding["record"]["indices"]["intelligence_index"], 42.7)

    def test_the_reflection_beam_identity_is_resolved_and_is_text_only(self):
        for model in ("beam", "beam-free", "Beam 1.0 501B A23B"):
            binding = self.resolve("ollama", model)
            self.assertEqual(binding["state"], "measured")
            self.assertEqual(binding["slug"], "reflection-beam")
            self.assertTrue(aa_bind.is_text_only(binding["record"]))

    def test_the_gpt_variant_is_the_native_effort_and_punctuation_does_not_bind(self):
        high = self.resolve(
            "codex", "gpt-6.1-sol", options=[{"id": "reasoningEffort", "current_value": "high"}]
        )
        self.assertEqual(high["slug"], "gpt-6-1-sol-high")
        self.assertEqual(high["variant_match"], "exact")
        low = self.resolve(
            "codex", "gpt-6.1-sol", options=[{"id": "reasoningEffort", "current_value": "low"}]
        )
        self.assertEqual(low["slug"], "gpt-6-1-sol-low")
        # A different punctuation is a different model id: it does not inherit
        # the permission or the measurement of gpt-6.1-sol.
        self.assertEqual(self.resolve("codex", "gpt-61-sol")["state"], "missing")

    def test_a_dated_id_binds_only_to_its_release_date(self):
        binding = self.resolve("codex", "gpt-4o-2024-11-20")
        self.assertEqual(binding["slug"], "gpt-4o")
        self.assertEqual(binding["release_date"], "2024-11-20")
        refused = self.resolve("codex", "gpt-4o-2024-08-06")
        self.assertEqual(refused["state"], "missing")
        self.assertIn("release date", refused["reason"])

    def test_a_release_date_that_the_feed_does_not_confirm_is_refused(self):
        refused = self.resolve("claude", "claude-opus-4-5-20251101")
        self.assertEqual(refused["state"], "missing")
        self.assertIn("release date", refused["reason"])
        confirmed = self.resolve("claude", "claude-sonnet-4-5-20250929")
        self.assertEqual(confirmed["state"], "measured")
        self.assertEqual(confirmed["slug"], "claude-4-5-sonnet")

    def test_an_alias_is_resolved_from_its_own_evidence(self):
        binding = self.resolve("claude", "claude-opus-5-5")
        self.assertEqual(binding["slug"], "claude-opus-5-5")
        self.assertEqual(binding["record"]["indices"]["intelligence_index"], 57.6)
        self.assertEqual(binding["measured_variant"], "max")

    def test_provider_namespaces_and_packaging_are_not_identity(self):
        cases = (
            ("cloudflare-workers-ai", "@cf/google/gemma-4-26b-a4b-it", "gemma-4-26b-a4b"),
            ("openrouter", "google/gemma-4-26b-a4b-it:free", "gemma-4-26b-a4b"),
            ("requesty", "gemma-4-31b-it", "gemma-4-31b"),
            ("nvidia", "nvidia/nemotron-3-ultra-550b-a55b", "nvidia-nemotron-3-ultra-550b-a55b"),
            ("ovh", "Meta-Llama-3_3-70B-Instruct", "llama-3-3-instruct-70b"),
            ("upstage", "solar-pro3", "solar-pro-3"),
        )
        for provider, model, slug in cases:
            binding = self.resolve(provider, model)
            self.assertEqual(binding["state"], "measured", model)
            self.assertEqual(binding["slug"], slug, model)

    def test_an_unknown_or_ambiguous_identity_is_never_guessed(self):
        # A model the feed has not measured.
        missing = self.resolve("opencode-go", "grok-code")
        self.assertEqual(missing["state"], "missing")
        self.assertTrue(missing["reason"])
        # Several measured variants and no base record: no variant is picked.
        ambiguous = self.resolve("claude", "claude-sonnet-5-5")
        self.assertEqual(ambiguous["state"], "ambiguous")
        self.assertIn("variants", ambiguous["reason"])
        # A parameter label the feed does not publish is not stripped.
        self.assertEqual(
            self.resolve("nvidia", "nvidia/nemotron-3.5-lightning-30b-a3b")["state"],
            "missing",
        )

    def test_every_live_candidate_gets_a_state_and_a_reason(self):
        for candidate in fixture("live-candidates.json"):
            binding = self.resolve(candidate["provider"], candidate["model"])
            self.assertIn(binding["state"], ("measured", "missing", "ambiguous"))
            if binding["state"] != "measured":
                self.assertTrue(binding["reason"], candidate["model"])
            else:
                self.assertTrue(binding["id"], candidate["model"])
                self.assertTrue(binding["slug"], candidate["model"])


class CatalogCoverageShapeTests(unittest.TestCase):
    """The published coverage names every candidate and its benchmark condition."""

    def setUp(self):
        self.cache = fixture("aa-records.json")
        self.cache["status"] = "ok"
        self.cache["fetched_at_epoch"] = NOW - 60.0
        self.cache["age_seconds"] = 60.0
        catalog = {
            "ollama": {
                "models": {
                    "deepseek-v4.1-flash:1017": {
                        "name": "DeepSeek V4.1 Flash 1017",
                        "family": "deepseek",
                        "release_date": "2026-12-01",
                        "modalities": {"input": ["text"]},
                        "cost": {"input": 0.15, "output": 0.6},
                    },
                    "beam": {
                        "name": "Beam",
                        "family": "beam",
                        "release_date": "2026-12-01",
                        "modalities": {"input": ["text", "image"]},
                        "cost": {"input": 0.2, "output": 0.8},
                    },
                    "unlisted-model": {
                        "name": "Unlisted Model",
                        "family": "unlisted",
                        "release_date": "2026-12-01",
                        "modalities": {"input": ["text"]},
                        "cost": {"input": 1.0, "output": 2.0},
                    },
                }
            }
        }

        class Catalog:
            document = catalog

            def model_entry(self, provider, model):
                return catalog["ollama"]["models"].get(model)

            def price_for(self, provider, model):
                entry = self.model_entry(provider, model)
                return entry["cost"] if entry else None

            def model_name(self, provider, model):
                entry = self.model_entry(provider, model)
                return entry["name"] if entry else model

            def release_date(self, provider, model):
                entry = self.model_entry(provider, model)
                return entry.get("release_date") if entry else None

        self.catalog = Catalog()
        records = [
            ranking.ModelRecord("ollama", "deepseek-v4.1-flash:1017"),
            ranking.ModelRecord("ollama", "beam"),
            ranking.ModelRecord("ollama", "unlisted-model"),
        ]
        ranked = ranking.rank_models(
            models=records,
            catalog=self.catalog,
            quota_windows={},
            free_models=set(),
            promo_models={("ollama", "deepseek-v4.1-flash:1017")},
            usage_tokens={},
            now=NOW,
        )
        self.snapshot = snapshot.build_snapshot(
            now=NOW,
            sources=[{"id": "t3", "status": "ok", "reason": "ok", "observed_at_epoch": NOW}],
            ranked=ranked,
            native_models={
                ("ollama", "deepseek-v4.1-flash:1017"): {
                    "providerInstance": "ollama",
                    "modelId": "deepseek-v4.1-flash:1017",
                    "options": [{"id": "variant", "currentValue": "high"}],
                },
                ("ollama", "beam"): {
                    "providerInstance": "ollama",
                    "modelId": "beam",
                    "options": [],
                },
            },
            policy={
                "frontierPrimeModels": (),
                "allowedGptModels": (),
                "backgroundProviderInstances": ("ollama",),
            },
            catalog=self.catalog,
            facts={},
            aa_cache=self.cache,
            free_models=set(),
            promo_models={("ollama", "deepseek-v4.1-flash:1017")},
        )
        self.rows = {row["model"]: row for row in self.snapshot["candidates"]}

    def test_every_candidate_has_a_coverage_row_with_its_condition(self):
        coverage = self.snapshot["aa_coverage"]
        self.assertEqual(coverage["total"], len(self.snapshot["candidates"]))
        self.assertEqual(coverage["states"]["measured"], 2)
        self.assertEqual(coverage["states"]["missing"], 1)
        entries = {entry["model"]: entry for entry in coverage["candidates"]}
        deepseek = entries["deepseek-v4.1-flash:1017"]
        self.assertEqual(deepseek["aa_slug"], "deepseek-v4-1-flash-1017")
        self.assertEqual(deepseek["aa_name"], "DeepSeek V4.1 Flash 1017 (Max)")
        self.assertEqual(deepseek["measured_variant"], "max")
        self.assertEqual(deepseek["native_variant"], "high")
        self.assertEqual(deepseek["variant_match"], "variant_mismatch")
        self.assertTrue(deepseek["matched_by"])
        unlisted = entries["unlisted-model"]
        self.assertEqual(unlisted["state"], "missing")
        self.assertTrue(unlisted["reason"])
        self.assertIsNone(unlisted["aa_id"])

    def test_the_unranked_model_is_visible_without_a_value(self):
        unlisted = self.rows["unlisted-model"]
        self.assertEqual(unlisted["aa"]["state"], "missing")
        self.assertIsNone(unlisted["value"]["value"])
        self.assertIsNone(unlisted["value"]["strength"])
        self.assertEqual(unlisted["rank"], {})
        self.assertEqual(unlisted["role"], "unranked")

    def test_the_benchmark_condition_is_displayed_not_guessed(self):
        deepseek = self.rows["deepseek-v4.1-flash:1017"]
        self.assertEqual(deepseek["aa"]["name"], "DeepSeek V4.1 Flash 1017 (Max)")
        self.assertEqual(deepseek["aa"]["condition"]["measured_variant"], "max")
        self.assertEqual(deepseek["aa"]["condition"]["native_variant"], "high")
        self.assertTrue(deepseek["aa"]["variant_mismatch"])
        # The model cannot be aligned to Max here, so it is not selectable and
        # its quality is never rewritten to a guessed High.
        self.assertFalse(deepseek["aa"]["selectable"])
        self.assertEqual(deepseek["value"]["strength"], 45.1)

    def test_the_text_only_evidence_keeps_beam_out_of_the_3d_tier(self):
        beam = self.rows["beam"]
        self.assertTrue(beam["aa"]["text_only"])
        self.assertNotIn("3d", beam["tiers"])
        self.assertNotEqual(beam["role"], "prime")


if __name__ == "__main__":
    unittest.main()
