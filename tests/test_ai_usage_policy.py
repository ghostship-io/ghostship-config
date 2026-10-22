"""The owner's selection, capacity and 3D policy contracts."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage" / "collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import aa_3d  # noqa: E402
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


def build(models, records, *, windows=None, facts_map=None, policy=None, aa_3d=None):
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
        aa_3d_cache=aa_3d,
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
    def _aa_3d(self, records):
        return {
            "status": "ok",
            "source": "artificialanalysis",
            "benchmark": "aa-3d",
            "conditions": "interactive Three.js scenes; not CAD",
            "fetched_at_epoch": NOW,
            "records": records,
        }

    def test_without_a_measured_aa_3d_elo_the_row_is_pending(self):
        models = visual_model("codex", "gpt-6.1-sol")
        data = build(models, [record("gpt-6-1-sol", 51.8, 0.4)])
        row = data["candidates"][0]
        self.assertEqual(row["three_d"]["state"], "pending")
        self.assertIsNone(row["three_d"]["elo"])
        self.assertNotIn("3d", row["tiers"])
        self.assertEqual(data["tiers"].get("3d", []), [])

    def test_the_measured_elo_is_the_3d_rank_and_the_index_is_not(self):
        models = visual_model("codex", "gpt-6.1-sol")
        data = build(
            models,
            [record("gpt-6-1-sol", 51.8, 0.4)],
            aa_3d=self._aa_3d(
                [
                    {
                        "id": "aa3d-1",
                        "slug": "gpt-6-1-sol",
                        "model": "gpt-6.1-sol",
                        "elo": 1218.4,
                        "source": "https://artificialanalysis.ai/evaluations/aa-3d",
                        "observed_at": "2026-10-20T00:00:00Z",
                        "task_count": 55,
                        "conditions": {"benchmark": "aa-3d", "tasks": 55},
                    }
                ]
            ),
        )
        row = data["candidates"][0]
        self.assertEqual(row["three_d"]["state"], "measured")
        self.assertEqual(row["three_d"]["elo"], 1218.4)
        self.assertEqual(row["three_d"]["authority"], "artificialanalysis-aa-3d")
        self.assertEqual(row["three_d"]["task_count"], 55)
        self.assertIn("3d", row["tiers"])
        self.assertIn("codex:gpt-6.1-sol", data["tiers"].get("3d", []))
        # The general intelligence index is published beside it, never as the
        # 3D score.
        self.assertEqual(row["aa"]["indices"]["intelligence"], 51.8)
        three_d_entry = [entry for entry in data["tier_winners"].get("3d", [])]
        self.assertTrue(three_d_entry)
        self.assertEqual(three_d_entry[0]["value"], row["value"]["value"])

    def test_a_text_only_record_can_never_be_ranked_for_3d(self):
        models = visual_model("ollama", "beam")
        data = build(
            models,
            [record("reflection-beam", 30.3, 0.2, name="Beam 1.0")],
            aa_3d=self._aa_3d(
                [
                    {
                        "id": "aa3d-beam",
                        "slug": "reflection-beam",
                        "model": "Beam 1.0",
                        "elo": 1100.0,
                        "source": "https://artificialanalysis.ai/evaluations/aa-3d",
                        "observed_at": "2026-10-20T00:00:00Z",
                    }
                ]
            ),
        )
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


class AA3DContractTests(unittest.TestCase):
    """The AA-3D reader and the cost-aware 3D value."""

    def _document(self, records, normalization=None):
        document = {
            "status": "ok",
            "source": "artificialanalysis",
            "benchmark": "aa-3d",
            "conditions": "interactive Three.js scenes; not CAD",
            "fetched_at_epoch": NOW,
            "records": records,
        }
        if normalization is not None:
            document["normalization"] = normalization
        return document

    def _record(self, **overrides):
        base = {
            "id": "aa3d-1",
            "slug": "gpt-6-1-sol",
            "model": "gpt-6.1-sol",
            "elo": 1200.0,
            "elo_interval": {"low": 1180.0, "high": 1220.0},
            "cost_per_task": 0.5,
            "source": "https://artificialanalysis.ai/evaluations/aa-3d",
            "observed_at": "2026-10-20T00:00:00Z",
            "task_count": 55,
            "conditions": {"benchmark": "aa-3d", "tasks": 55},
        }
        base.update(overrides)
        return base

    def _load(self, document):
        import tempfile, json as json_module

        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        handle.write(json_module.dumps(document))
        handle.close()
        try:
            return aa_3d.load_cache(handle.name, NOW)
        finally:
            Path(handle.name).unlink()

    def test_the_reader_keeps_the_measurement_and_refuses_bad_values(self):
        cache = self._load(
            {
                "status": "ok",
                "source": "artificialanalysis",
                "fetched_at_epoch": NOW,
                "records": [
                    self._record(),
                    self._record(id="bad-negative", slug="x", model="x", elo=-1.0),
                    self._record(id="bad-inf", slug="y", model="y", elo=float("inf")),
                ],
            }
        )
        self.assertEqual(cache["status"], "ok")
        self.assertEqual(len(cache["records"]), 1)
        record = cache["records"][0]
        self.assertEqual(record["elo"], 1200.0)
        self.assertEqual(record["elo_interval"], {"low": 1180.0, "high": 1220.0})
        self.assertEqual(record["cost_per_task"], 0.5)
        self.assertEqual(record["task_count"], 55)
        self.assertTrue(record["source"].startswith("https://"))

    def test_a_stale_snapshot_is_not_measured(self):
        cache = self._load(
            {
                "status": "ok",
                "fetched_at_epoch": NOW - 60 * DAY,
                "records": [self._record()],
            }
        )
        self.assertEqual(cache["status"], "stale")
        self.assertEqual(aa_3d.lookup(cache, "codex", "gpt-6.1-sol")["state"], "stale")

    def test_the_elo_is_normalized_only_by_the_published_transform(self):
        self.assertIsNone(aa_3d.normalize(1200.0, None))
        normalization = {"kind": "min-max", "floor": 1000.0, "ceiling": 1400.0}
        self.assertAlmostEqual(aa_3d.normalize(1200.0, normalization), 0.5)
        self.assertIsNone(aa_3d.normalize(1200.0, {"kind": "min-max", "floor": 1400.0, "ceiling": 1400.0}))

    def test_the_3d_value_uses_the_aa_3d_cost_not_the_language_cost(self):
        models = visual_model("codex", "gpt-6.1-sol")
        # The language record says 0.10; the AA-3D record says 0.5.
        data = build(
            models,
            [record("gpt-6-1-sol", 51.8, 0.10)],
            aa_3d=self._load(
                self._document(
                    [self._record()],
                    normalization={"kind": "min-max", "floor": 1000.0, "ceiling": 1400.0},
                )
            ),
        )
        row = data["candidates"][0]
        value_3d = row["value_3d"]
        self.assertAlmostEqual(value_3d["value"], round(0.8 * 0.5 + 0.2 * (1 / 1.5), 6), places=6)
        self.assertEqual(value_3d["raw"]["cost_per_task"], 0.5)
        self.assertEqual(value_3d["raw"]["elo"], 1200.0)
        self.assertEqual(value_3d["raw"]["elo_interval"]["low"], 1180.0)
        self.assertEqual(value_3d["raw"]["normalization_state"], "applied")
        # The language value stays separate and uses the language cost.
        self.assertEqual(row["aa"]["cost_per_task"], 0.10)

    def test_without_the_normalization_the_3d_value_is_unknown_and_the_elo_visible(self):
        models = visual_model("codex", "gpt-6.1-sol")
        data = build(models, [record("gpt-6-1-sol", 51.8, 0.10)], aa_3d=self._load(self._document([self._record()])))
        row = data["candidates"][0]
        self.assertIsNone(row["value_3d"]["value"])
        self.assertEqual(row["value_3d"]["missing"], ["elo"])
        self.assertEqual(row["three_d"]["elo"], 1200.0)
        self.assertEqual(row["three_d"]["normalization_state"], "unknown")

    def test_without_the_3d_cost_the_value_is_unknown_and_the_raw_stays(self):
        models = visual_model("codex", "gpt-6.1-sol")
        data = build(
            models,
            [record("gpt-6-1-sol", 51.8, 0.10)],
            aa_3d=self._load(
                self._document(
                    [self._record(cost_per_task=None)],
                    normalization={"kind": "min-max", "floor": 1000.0, "ceiling": 1400.0},
                )
            ),
        )
        row = data["candidates"][0]
        self.assertIsNone(row["value_3d"]["value"])
        self.assertEqual(row["value_3d"]["missing"], ["cost_per_task"])
        self.assertEqual(row["three_d"]["elo"], 1200.0)
        self.assertIsNone(row["three_d"]["cost_per_task"])

    def test_an_explicit_source_normalized_value_is_used(self):
        models = visual_model("codex", "gpt-6.1-sol")
        data = build(
            models,
            [record("gpt-6-1-sol", 51.8, 0.10)],
            aa_3d=self._load(
                self._document([self._record(normalized=0.75)])
            ),
        )
        row = data["candidates"][0]
        self.assertEqual(row["value_3d"]["raw"]["normalization_state"], "source")
        self.assertAlmostEqual(row["value_3d"]["value"], round(0.8 * 0.75 + 0.2 * (1 / 1.5), 6), places=6)
