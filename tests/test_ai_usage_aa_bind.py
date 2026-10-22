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
        # The feed publishes two conditions of the undated id and the id
        # publishes no effort: that is unknown, not the first record.
        ambiguous = self.resolve("ollama", "deepseek-v4.1-flash")
        self.assertEqual(ambiguous["state"], "ambiguous")
        base = self.resolve(
            "ollama",
            "deepseek-v4.1-flash",
            options=[{"id": "variant", "current_value": "max"}],
        )
        self.assertEqual(base["slug"], "deepseek-v4-1-flash")
        self.assertEqual(base["record"]["indices"]["intelligence_index"], 39.5)
        checkpoint = self.resolve(
            "ollama",
            "deepseek-v4.1-flash:1017",
            options=[{"id": "variant", "current_value": "max"}],
        )
        self.assertEqual(checkpoint["slug"], "deepseek-v4-1-flash-1017")
        self.assertNotEqual(base["id"], checkpoint["id"])

    def test_the_choice_does_not_depend_on_the_cache_order(self):
        for model, options in (
            ("deepseek-v4.1-flash", [{"id": "variant", "current_value": "max"}]),
            ("deepseek-v4.1-flash:1017", [{"id": "variant", "current_value": "high"}]),
            ("beam", None),
        ):
            forward = aa_bind.resolve(self.records, "ollama", model, options=options)
            reverse = aa_bind.resolve(
                list(reversed(self.records)), "ollama", model, options=options
            )
            self.assertEqual(forward["state"], reverse["state"], model)
            self.assertEqual(forward.get("id"), reverse.get("id"), model)

    def test_a_reasoning_id_never_borrows_the_non_reasoning_record(self):
        binding = self.resolve(
            "ollama",
            "deepseek-v4.1-flash",
            options=[{"id": "variant", "current_value": "max"}],
        )
        self.assertNotEqual(binding["slug"], "deepseek-v4-1-flash-non-reasoning")
        self.assertEqual(binding["record"]["indices"]["intelligence_index"], 39.5)
        # An id with no published effort is ambiguous across the two
        # conditions, never the non-reasoning record by order.
        ambiguous = self.resolve("ollama", "deepseek-v4.1-flash")
        self.assertEqual(ambiguous["state"], "ambiguous")

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
        confirmed = self.resolve(
            "claude",
            "claude-sonnet-4-5-20250929",
            options=[{"id": "variant", "current_value": "non-reasoning"}],
        )
        self.assertEqual(confirmed["state"], "measured")
        self.assertEqual(confirmed["slug"], "claude-4-5-sonnet")
        self.assertEqual(confirmed["release_date"], "2025-09-29")

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
            # The gemma records publish a reasoning and a non-reasoning
            # condition, so the identity is proven by a published effort.
            options = [{"id": "reasoningEffort", "current_value": "reasoning"}]
            binding = self.resolve(provider, model, options=options)
            self.assertEqual(binding["state"], "measured", model)
            self.assertEqual(binding["slug"], slug, model)

    def test_an_unknown_or_ambiguous_identity_is_never_guessed(self):
        # A model the feed has not measured.
        missing = self.resolve("opencode-go", "grok-code")
        self.assertEqual(missing["state"], "missing")
        self.assertTrue(missing["reason"])
        # Several measured conditions and no published effort: no condition
        # is picked, not even the base slug.
        ambiguous = self.resolve("claude", "claude-sonnet-5-5")
        self.assertEqual(ambiguous["state"], "ambiguous")
        self.assertIn("measured conditions", ambiguous["reason"])
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
        # The AA record is selected independently of the native setting.
        self.assertEqual(deepseek["variant_match"], "reference")
        self.assertEqual(deepseek["native_variant"], "")
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
        self.assertEqual(deepseek["aa"]["condition"]["native_variant"], "")
        self.assertFalse(deepseek["aa"]["variant_mismatch"])
        # The benchmark condition is the reference's Max; the owner-approved
        # DeepSeek Flash exception runs High, independent of it.
        self.assertEqual(deepseek["aa"]["condition"]["measured_variant"], "max")
        self.assertEqual(deepseek["aa"]["condition"]["execution_default"], "high")
        self.assertTrue(deepseek["aa"]["condition"]["execution_exception"])
        self.assertTrue(deepseek["aa"]["selectable"])
        self.assertEqual(deepseek["aa"]["alignment"], {"variant": "high"})
        self.assertEqual(deepseek["value"]["strength"], 45.1)

    def test_the_text_only_evidence_keeps_beam_out_of_the_3d_tier(self):
        beam = self.rows["beam"]
        self.assertTrue(beam["aa"]["text_only"])
        self.assertNotIn("3d", beam["tiers"])
        self.assertNotEqual(beam["role"], "prime")


if __name__ == "__main__":
    unittest.main()


class ValuePolicyTests(unittest.TestCase):
    """The owner's combined value: 0.80 * intelligence + 0.20 * efficiency."""

    def _cache(self, records):
        return {
            "status": "ok",
            "index_version": "4.3",
            "fetched_at_epoch": NOW - 60.0,
            "age_seconds": 60.0,
            "records": records,
        }

    def _build(self, catalog, cache, options=None):
        class Catalog:
            def model_entry(self, provider, model):
                return catalog.get((provider, model))

            def price_for(self, provider, model):
                entry = self.model_entry(provider, model) or {}
                return entry.get("cost")

            def model_name(self, provider, model):
                entry = self.model_entry(provider, model) or {}
                return entry.get("name", model)

            def release_date(self, provider, model):
                entry = self.model_entry(provider, model) or {}
                return entry.get("release_date")

        models = [ranking.ModelRecord(provider, model) for provider, model in catalog]
        ranked = ranking.rank_models(
            models=models,
            catalog=Catalog(),
            quota_windows={},
            free_models=set(),
            promo_models=set(catalog),
            usage_tokens={},
            aa_cache=cache,
            now=NOW,
        )
        data = snapshot.build_snapshot(
            now=NOW,
            sources=[{"id": "t3", "status": "ok", "reason": "ok", "observed_at_epoch": NOW}],
            ranked=ranked,
            native_models={
                key: {
                    "providerInstance": key[0],
                    "modelId": key[1],
                    "options": (options or {}).get(key, []),
                }
                for key in catalog
            },
            policy={
                "frontierPrimeModels": (),
                "allowedGptModels": (),
                "backgroundProviderInstances": tuple({key[0] for key in catalog}),
            },
            catalog=Catalog(),
            facts={},
            aa_cache=cache,
            free_models=set(),
            promo_models=set(catalog),
        )
        return {row["model"]: row for row in data["candidates"]}

    def _catalog(self):
        return {
            ("ollama", "minimax-m3.1-flash"): {
                "name": "MiniMax M3.1 Flash",
                "family": "minimax",
                "release_date": "2026-12-01",
                "modalities": {"input": ["text"]},
                "cost": {"input": 0.0, "output": 0.0},
            },
            ("ollama", "deepseek-v4.1-flash:1017"): {
                "name": "DeepSeek V4.1 Flash 1017",
                "family": "deepseek",
                "release_date": "2026-12-01",
                "modalities": {"input": ["text"]},
                "cost": {"input": 0.15, "output": 0.6},
            },
        }

    def _records(self):
        base = fixture("aa-records.json")["records"]
        return [
            record
            for record in base
            if record["slug"] in ("minimax-m3-1-flash", "deepseek-v4-1-flash-1017")
        ]

    def test_the_score_is_the_published_policy_on_the_measured_inputs(self):
        rows = self._build(
            self._catalog(),
            self._cache(self._records()),
            options={("ollama", "deepseek-v4.1-flash:1017"): [{"id": "variant", "currentValue": "high"}]},
        )
        minimax = rows["minimax-m3.1-flash"]
        deepseek = rows["deepseek-v4.1-flash:1017"]
        # The published components are the transforms of the measured inputs,
        # and the value is exactly the published weighted sum of them.
        minimax_components = minimax["value"]["components"]
        self.assertAlmostEqual(
            minimax_components["intelligence"]["value"], 42.7 / 100.0, places=4
        )
        self.assertAlmostEqual(
            minimax_components["cost_per_task"]["value"], 1.0 / (1.0 + 0.2201), places=4
        )
        self.assertAlmostEqual(
            minimax["value"]["value"],
            round(
                0.8 * minimax_components["intelligence"]["value"]
                + 0.2 * minimax_components["cost_per_task"]["value"],
                6,
            ),
            places=6,
        )
        deepseek_components = deepseek["value"]["components"]
        self.assertAlmostEqual(
            deepseek_components["intelligence"]["value"], 45.1 / 100.0, places=4
        )
        self.assertAlmostEqual(
            deepseek_components["cost_per_task"]["value"], 1.0 / (1.0 + 0.262), places=4
        )
        self.assertAlmostEqual(
            deepseek["value"]["value"],
            round(
                0.8 * deepseek_components["intelligence"]["value"]
                + 0.2 * deepseek_components["cost_per_task"]["value"],
                6,
            ),
            places=6,
        )
        self.assertEqual(minimax["value"]["weights"], {"intelligence": 0.8, "cost_per_task": 0.2})
        self.assertIn("transforms", minimax["value"])
        self.assertTrue(minimax["value"]["transforms"]["cost_per_task"])
        self.assertEqual(minimax["aa"]["indices"]["intelligence"], 42.7)
        self.assertEqual(deepseek["aa"]["indices"]["intelligence"], 45.1)
        # The raw feed cost stays distinct from the provider's token listing.
        self.assertEqual(minimax["aa"]["cost_per_task"], 0.2201)
        self.assertEqual(minimax["price"]["input"], 0.0)

    def test_the_policy_is_published_with_the_snapshot(self):
        rows = self._build(self._catalog(), self._cache(self._records()))
        policy = snapshot.VALUE_POLICY
        self.assertEqual(policy["formula"], "0.80 * I + 0.20 * E")
        self.assertEqual(policy["weights"], {"intelligence": 0.8, "cost_per_task": 0.2})
        self.assertIn("units", policy)
        self.assertIn("not_aa_claim", policy)

    def test_a_missing_cost_leaves_the_value_unknown_but_the_index_visible(self):
        records = self._records()
        for record in records:
            record["cost_per_task"] = None
        rows = self._build(self._catalog(), self._cache(records))
        minimax = rows["minimax-m3.1-flash"]
        self.assertIsNone(minimax["value"]["value"])
        self.assertEqual(minimax["value"]["missing"], ["cost_per_task"])
        self.assertEqual(minimax["value"]["strength"], 42.7)
        self.assertEqual(minimax["aa"]["indices"]["intelligence"], 42.7)
        self.assertEqual(minimax["value"]["coverage"], 0.5)

    def test_a_zero_cost_is_a_valid_efficiency_of_one(self):
        records = self._records()
        for record in records:
            record["cost_per_task"] = 0.0
        rows = self._build(self._catalog(), self._cache(records))
        minimax = rows["minimax-m3.1-flash"]
        self.assertEqual(minimax["value"]["components"]["cost_per_task"]["value"], 1.0)
        expected = 0.8 * (42.7 / 100.0) + 0.2 * 1.0
        self.assertAlmostEqual(minimax["value"]["value"], round(expected, 6), places=6)

    def test_a_negative_or_infinite_cost_is_unknown_not_free(self):
        for bad in (-1.0, float("inf")):
            records = self._records()
            for record in records:
                record["cost_per_task"] = bad
            rows = self._build(self._catalog(), self._cache(records))
            minimax = rows["minimax-m3.1-flash"]
            self.assertIsNone(minimax["value"]["components"]["cost_per_task"]["value"], bad)
            self.assertIsNone(minimax["value"]["value"], bad)

    def test_the_release_date_adds_no_bonus(self):
        first = self._records()
        second = [dict(record) for record in first]
        for record in first:
            record["release_date"] = "2026-12-01"
        for record in second:
            record["release_date"] = "2024-01-01"
        one = self._build(self._catalog(), self._cache(first))
        two = self._build(
            self._catalog(),
            self._cache(second),
        )
        self.assertEqual(
            one["minimax-m3.1-flash"]["value"]["value"],
            two["minimax-m3.1-flash"]["value"]["value"],
        )
