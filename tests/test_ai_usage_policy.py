"""The owner's selection, capacity and 3D policy contracts."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage" / "collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import aa_bind  # noqa: E402
import facts  # noqa: E402
import ranking  # noqa: E402
import snapshot  # noqa: E402

NOW = 1_800_000_000.0
HOUR = 3600.0
DAY = 24 * HOUR
WEEK = 7 * DAY


def record(slug, index, cost, name=None):
    return {
        "id": f"id-{slug}",
        "slug": slug,
        "model": name or slug,
        "release_date": "2026-12-01",
        "indices": {"intelligence_index": index},
        "cost_per_task": cost,
        "median_performance": 100.0,
        "prices": {},
    }


def cache(records):
    return {
        "status": "ok",
        "index_version": "4.3",
        "fetched_at_epoch": NOW,
        "records": records,
    }


import catalog as catalog_module


def Catalog(models):
    """The real catalog class, from the {(provider, model): entry} map."""
    document = {}
    for (provider, model), entry in models.items():
        for key in {provider, *catalog_module.PROVIDER_ALIASES.get(provider, ())}:
            document.setdefault(key, {"models": {}})["models"][model] = entry
    return catalog_module.Catalog(document)


def build(models, records, *, windows=None, facts_map=None, policy=None):
    catalog = Catalog(models)
    pairs = list(models)
    ranked = ranking.rank_models(
        models=[ranking.ModelRecord(provider, model) for provider, model in pairs],
        catalog=catalog,
        quota_windows=windows or {},
        free_models=set(),
        promo_models=set(pairs),
        usage_tokens={},
        aa_cache=cache(records),
        now=NOW,
    )
    return snapshot.build_snapshot(
        now=NOW,
        sources=[{"id": "t3", "status": "ok", "reason": "ok", "observed_at_epoch": NOW}],
        ranked=ranked,
        native_models={
            key: {
                "providerInstance": key[0],
                "modelId": key[1],
                "options": [],
            }
            for key in pairs
        },
        policy=policy
        or {
            "frontierPrimeModels": ("gpt-6.1-sol", "claude-opus-5-5"),
            "allowedGptModels": ("gpt-6.1-sol",),
            "backgroundProviderInstances": tuple({key[0] for key in pairs}),
        },
        catalog=catalog,
        facts=facts_map or {},
        aa_cache=cache(records),
        free_models=set(),
        promo_models=set(pairs),
        measured_windows=[
            {
                "provider": provider,
                **{
                    "kind": item.kind,
                    "used_ratio": item.used_ratio,
                    "reset_epoch": item.reset_epoch,
                    "duration_seconds": item.duration_seconds,
                    "observed_at": item.observed_at,
                    "quota_id": item.quota_id,
                },
            }
            for provider, items in (windows or {}).items()
            for item in items
        ],
    )


def text_model(provider, model, **extra):
    entry = {
        "name": model,
        "family": model.rsplit("-", 1)[0],
        "release_date": "2026-12-01",
        "modalities": {"input": ["text"]},
        "cost": {"input": 1.0, "output": 2.0},
    }
    entry.update(extra)
    return {(provider, model): entry}


def visual_model(provider, model):
    return {
        (provider, model): {
            "name": model,
            "family": "gpt-sol",
            "release_date": "2026-12-01",
            "modalities": {"input": ["text", "image"]},
            "cost": {"input": 1.0, "output": 2.0},
        }
    }


def window(used, reset, kind="weekly", quota="primary"):
    return ranking.QuotaWindow(
        kind=kind,
        used_ratio=used,
        reset_epoch=NOW + reset,
        duration_seconds=WEEK,
        observed_at=NOW,
        quota_id=quota,
    )


class FrontierAndExclusionTests(unittest.TestCase):
    def test_only_the_two_workhorses_hold_the_frontier(self):
        models = {}
        models.update(text_model("codex", "gpt-6.1-sol"))
        models.update(text_model("claude", "claude-opus-5-5"))
        models.update(text_model("codex", "gpt-6-astra"))
        models.update(text_model("claude", "claude-fable-5-1"))
        data = build(
            models,
            [
                record("gpt-6-1-sol", 51.8, 0.4),
                record("claude-opus-5-5", 57.6, 0.5),
                record("gpt-6-astra", 60.0, 0.3),
                record("claude-fable-5-1", 61.0, 0.2),
            ],
        )
        frontier = {key for key in data["tiers"].get("frontier", [])}
        self.assertEqual(frontier, {"codex:gpt-6.1-sol", "claude:claude-opus-5-5"})

    def test_astra_and_fable_are_never_a_winner_or_a_recommendation(self):
        models = {}
        models.update(text_model("codex", "gpt-6.1-sol"))
        models.update(text_model("codex", "gpt-6-astra"))
        models.update(text_model("claude", "claude-fable-5"))
        data = build(
            models,
            [
                record("gpt-6-1-sol", 51.8, 0.4),
                record("gpt-6-astra", 60.0, 0.3),
                record("claude-fable-5", 61.0, 0.2),
            ],
        )
        winners = {
            entry["model"]
            for entries in data["tier_winners"].values()
            for entry in entries
        }
        self.assertNotIn("gpt-6-astra", winners)
        self.assertNotIn("claude-fable-5", winners)
        recommended = {
            entry["model"]
            for entry in data["recommendations"].values()
            if entry.get("model")
        }
        self.assertNotIn("gpt-6-astra", recommended)
        self.assertNotIn("claude-fable-5", recommended)
        # Their usage rows stay visible.
        rows = {row["model"]: row for row in data["candidates"]}
        self.assertIn("gpt-6-astra", rows)
        self.assertIn("claude-fable-5", rows)


class ProviderCapacityTests(unittest.TestCase):
    def test_a_spent_window_blocks_the_provider_even_with_room_elsewhere(self):
        models = text_model("claude", "claude-opus-5-5")
        data = build(
            models,
            [record("claude-opus-5-5", 57.6, 0.5)],
            windows={
                "claude": [
                    window(1.0, 10 * HOUR, "weekly"),
                    window(0.1, 2 * HOUR, "session"),
                ]
            },
        )
        capacity = data["quota"]["provider_capacity"]["claude"]
        self.assertEqual(capacity["remaining_ratio"], 0.0)
        self.assertEqual(capacity["binding"]["kind"], "weekly")
        row = data["candidates"][0]
        self.assertEqual(row["capacity"]["remaining_ratio"], 0.0)
        self.assertEqual(row["capacity"]["capacity_binding_id"], "weekly:primary")

    def test_the_lowest_applicable_window_is_the_provider_capacity(self):
        models = text_model("claude", "claude-opus-5-5")
        data = build(
            models,
            [record("claude-opus-5-5", 57.6, 0.5)],
            windows={
                "claude": [
                    window(0.9, 6 * DAY, "weekly"),
                    window(0.2, 2 * HOUR, "session"),
                ]
            },
        )
        capacity = data["quota"]["provider_capacity"]["claude"]
        self.assertAlmostEqual(capacity["remaining_ratio"], 0.1, places=4)
        self.assertEqual(capacity["binding"]["kind"], "weekly")

    def test_the_binding_record_names_both_windows_when_they_differ(self):
        row = {
            "capacity": {
                "capacity_binding_id": "weekly:primary",
                "pace_binding_id": "session:primary",
            }
        }
        self.assertTrue(snapshot._bindings_differ(row))
        row["capacity"]["pace_binding_id"] = "weekly:primary"
        self.assertFalse(snapshot._bindings_differ(row))


class ThreeDAdmissionTests(unittest.TestCase):
    def test_without_an_admission_the_row_is_pending_and_not_in_the_tier(self):
        models = visual_model("codex", "gpt-6.1-sol")
        data = build(models, [record("gpt-6-1-sol", 51.8, 0.4)])
        row = data["candidates"][0]
        self.assertEqual(row["three_d"]["state"], "pending")
        self.assertTrue(row["three_d"]["visual"])
        self.assertFalse(row["three_d"]["admitted"])
        self.assertNotIn("3d", row["tiers"])
        self.assertEqual(data["tiers"].get("3d", []), [])

    def test_a_verified_admission_and_an_image_input_admit_the_model(self):
        models = visual_model("codex", "gpt-6.1-sol")
        admission = facts.make_fact(
            provider="codex",
            model="gpt-6.1-sol",
            indices={"intelligence_index": 51.8},
            benchmark_id="gpt-6.1-sol",
            brief_url="https://artificialanalysis.ai/models",
            now=NOW,
        )
        admission["admission_evidence"] = [
            {"workload": "3d", "admitted": True, "at": NOW}
        ]
        data = build(
            models,
            [record("gpt-6-1-sol", 51.8, 0.4)],
            facts_map={facts.identity_key("codex", "gpt-6.1-sol"): admission},
        )
        row = data["candidates"][0]
        self.assertEqual(row["three_d"]["state"], "admitted")
        self.assertIn("3d", row["tiers"])
        self.assertIn("codex:gpt-6.1-sol", data["tiers"].get("3d", []))

    def test_a_text_only_record_can_never_be_admitted(self):
        models = visual_model("ollama", "beam")
        data = build(models, [record("reflection-beam", 30.3, 0.2, name="Beam 1.0")])
        row = data["candidates"][0]
        self.assertEqual(row["three_d"]["state"], "ineligible")
        self.assertNotIn("3d", row["tiers"])


if __name__ == "__main__":
    unittest.main()


class AlignmentTests(unittest.TestCase):
    """The alignment uses the option id and the value the model publishes."""

    def test_the_native_record_keeps_the_descriptor_values(self):
        record = snapshot._native_record(
            "claude",
            "claude-opus-5-5",
            {
                "providerInstance": "claudeAgent",
                "modelId": "claude-opus-5-5",
                "options": [
                    {
                        "id": "effort",
                        "currentValue": "high",
                        "allowedValues": ["low", "medium", "high", "max"],
                    },
                    {"id": "thinking", "currentValue": True},
                ],
            },
        )
        self.assertEqual(record["options"][0]["id"], "effort")
        self.assertEqual(
            record["options"][0]["values"], ["low", "medium", "high", "max"]
        )

    def test_the_alignment_names_the_actual_option_key(self):
        for key, condition, listed, expected in (
            ("effort", "high", "High", ("effort", "High")),
            ("variant", "max", "max", ("variant", "max")),
            ("reasoningEffort", "high", "high", ("reasoningEffort", "high")),
        ):
            options = [{"id": key, "current_value": "low", "values": ["low", listed]}]
            self.assertEqual(aa_bind.alignment_option(options, condition), expected)

    def test_an_option_without_a_descriptor_cannot_align(self):
        self.assertIsNone(
            aa_bind.alignment_option(
                [{"id": "effort", "current_value": "high"}], "high"
            )
        )

    def test_a_descriptor_that_does_not_list_the_condition_cannot_align(self):
        self.assertIsNone(
            aa_bind.alignment_option(
                [{"id": "effort", "values": ["low", "medium"]}], "max"
            )
        )

    def test_the_snapshot_emits_the_alignment_under_the_actual_key(self):
        models = visual_model("claude", "claude-opus-5-5")
        catalog = Catalog(models)
        cache_doc = cache([record("claude-opus-5-5-high", 55.0, 0.5, name="Claude Opus 5.5 (High)")])
        ranked = ranking.rank_models(
            models=[ranking.ModelRecord("claude", "claude-opus-5-5")],
            catalog=catalog,
            quota_windows={},
            free_models=set(),
            promo_models={("claude", "claude-opus-5-5")},
            usage_tokens={},
            aa_cache=cache_doc,
            now=NOW,
        )
        data = snapshot.build_snapshot(
            now=NOW,
            sources=[{"id": "t3", "status": "ok", "reason": "ok", "observed_at_epoch": NOW}],
            ranked=ranked,
            native_models={
                ("claude", "claude-opus-5-5"): {
                    "providerInstance": "claudeAgent",
                    "modelId": "claude-opus-5-5",
                    "options": [
                        {
                            "id": "effort",
                            "currentValue": "high",
                            "allowedValues": ["low", "medium", "high", "max"],
                        }
                    ],
                }
            },
            policy={
                "frontierPrimeModels": ("claude-opus-5-5",),
                "allowedGptModels": (),
                "backgroundProviderInstances": ("claude",),
            },
            catalog=catalog,
            facts={},
            aa_cache=cache_doc,
            free_models=set(),
            promo_models={("claude", "claude-opus-5-5")},
        )
        row = data["candidates"][0]
        self.assertEqual(row["aa"]["condition"]["variant_match"], "exact")
        self.assertTrue(row["aa"]["selectable"])
        self.assertEqual(row["aa"]["alignment"], {})
