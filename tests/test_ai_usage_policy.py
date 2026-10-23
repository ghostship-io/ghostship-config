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


def build(models, records, *, windows=None, facts_map=None, policy=None, aa_3d=None, native_options=None):
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
                "options": (native_options or {}).get(key, []),
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
        frontier = {key for key in data["tiers"].get("orchestrator", [])}
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
        # The winner of the 3D tier publishes the 3D value (intelligence, the
        # AA-3D Elo and the cost) under the trust of the model, never the
        # general value; the general Artificial Analysis value is beside it.
        self.assertEqual(three_d_entry[0]["value_aa"], row["value"]["value"])
        self.assertEqual(three_d_entry[0]["value"], row["value_3d"]["value"])
        self.assertEqual(
            three_d_entry[0]["value"], row["outcome"]["3d"]["published"]
        )

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
        self.assertEqual(row["aa"]["condition"]["variant_match"], "reference")
        self.assertTrue(row["aa"]["selectable"])
        self.assertEqual(row["aa"]["alignment"], {"effort": "medium"})
        self.assertEqual(row["aa"]["alignment_meta"]["escalation"], {"effort": "high"})
        self.assertEqual(row["aa"]["execution"]["state"], "selectable")


class AA3DContractTests(unittest.TestCase):
    """The strict AA-3D reader: the whole board or nothing."""

    def _record(self, **overrides):
        base = {
            "model": "GPT-6.1 Sol (Max)",
            "elo": 1200,
            "rank": 1,
            "rank_range": "1",
            "ci95_low": 1180,
            "ci95_high": 1220,
            "anchor": False,
            "cost_per_task": 0.5,
        }
        base.update(overrides)
        return base

    def _document(self, records, **overrides):
        document = {
            "schema": "ghostship.aa3d.evidence",
            "schema_version": 1,
            "benchmark": "AA-3D",
            "benchmark_version": "1.0",
            "source": "public_web",
            "source_url": "https://artificialanalysis.ai/evaluations/aa-3d",
            "observed_at": "2026-10-22T01:29:46+00:00",
            "completeness": {
                "complete": True,
                "records": len(records),
                "scope": "entire_displayed_leaderboard",
            },
            "records": records,
        }
        document.update(overrides)
        return document

    def _now(self):
        from datetime import datetime

        return datetime.fromisoformat("2026-10-22T02:00:00+00:00").timestamp()

    def _load(self, document, now=None):
        import tempfile, json as json_module

        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        handle.write(json_module.dumps(document))
        handle.close()
        try:
            return aa_3d.load_cache(handle.name, self._now() if now is None else now)
        finally:
            Path(handle.name).unlink()

    def _now(self):
        from datetime import datetime

        return datetime.fromisoformat("2026-10-22T02:00:00+00:00").timestamp()

    def test_the_valid_board_is_accepted_with_one_normalization(self):
        cache = self._load(self._document([self._record()]), now=self._now())
        self.assertEqual(cache["status"], "ok")
        self.assertEqual(cache["source_url"], "https://artificialanalysis.ai/evaluations/aa-3d")
        self.assertEqual(cache["benchmark"], "AA-3D")
        self.assertEqual(cache["benchmark_version"], "1.0")
        self.assertEqual(cache["bounds"], {"min_elo": 1200.0, "max_elo": 1200.0, "count": 1})
        self.assertEqual(cache["records"][0]["normalized"], 1.0)
        self.assertIsInstance(cache["normalization"], dict)
        self.assertEqual(cache["normalization"]["kind"], "relative-minmax")
        self.assertTrue(cache["fingerprint"])
        # The record's own source and arbitrary conditions are not forwarded.
        self.assertEqual(cache["records"][0]["source"], aa_3d.SOURCE_URL)
        self.assertEqual(set(cache["records"][0]["conditions"]), {"benchmark", "scope"})

    def test_a_truncated_or_incomplete_snapshot_is_rejected(self):
        two = [self._record(model="A"), self._record(model="B", rank=2)]
        truncated = self._document(
            two,
            completeness={"complete": False, "records": 22, "scope": "entire_displayed_leaderboard"},
        )
        self.assertEqual(self._load(truncated)["status"], "invalid")
        mismatch = self._document(
            two,
            completeness={"complete": True, "records": 22, "scope": "entire_displayed_leaderboard"},
        )
        self.assertEqual(self._load(mismatch)["status"], "invalid")
        wrong_scope = self._document(
            two,
            completeness={"complete": True, "records": 2, "scope": "top_10"},
        )
        self.assertEqual(self._load(wrong_scope)["status"], "invalid")

    def test_a_future_or_missing_observation_is_rejected(self):
        from datetime import datetime, timezone

        future = datetime.fromtimestamp(self._now() + 86400, tz=timezone.utc).isoformat()
        self.assertEqual(
            self._load(self._document([self._record()], observed_at=future), now=self._now())["status"],
            "invalid",
        )
        self.assertEqual(
            self._load(self._document([self._record()], observed_at=None))["status"], "invalid"
        )

    def test_a_foreign_source_or_schema_is_rejected(self):
        self.assertEqual(
            self._load(
                self._document([self._record()], source_url="https://example.com/leaderboard")
            )["status"],
            "invalid",
        )
        self.assertEqual(
            self._load(self._document([self._record()], benchmark="other"))["status"], "invalid"
        )
        self.assertEqual(
            self._load(self._document([self._record()], benchmark_version=""))["status"], "invalid"
        )
        self.assertEqual(
            self._load(self._document([self._record()], schema="other"))["status"], "invalid"
        )

    def test_a_bad_record_rejects_the_whole_snapshot(self):
        for bad in (
            self._record(elo=-1),
            self._record(elo=float("inf")),
            self._record(ci95_low=1180, ci95_high=None),
            self._record(ci95_low=1220, ci95_high=1180),
            self._record(cost_per_task=-0.5),
            self._record(model=""),
        ):
            self.assertEqual(
                self._load(self._document([self._record(model="A"), bad]))["status"],
                "invalid",
                bad,
            )
        duplicate = [self._record(model="A"), self._record(model="a", rank=2)]
        self.assertEqual(self._load(self._document(duplicate))["status"], "invalid")

    def test_an_oversized_file_is_rejected_without_slicing(self):
        import tempfile

        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        handle.write(" " * (aa_3d.MAX_BYTES + 10))
        handle.close()
        try:
            self.assertIsNone(aa_3d.load_cache(handle.name, NOW))
        finally:
            Path(handle.name).unlink()

    def test_the_policy_is_the_relative_minmax_over_the_board(self):
        cache = self._load(
            self._document(
                [
                    self._record(model="Low", elo=1000, rank=2, ci95_low=980, ci95_high=1020),
                    self._record(model="High", elo=1200, rank=1),
                ]
            )
        )
        self.assertEqual(cache["bounds"], {"min_elo": 1000.0, "max_elo": 1200.0, "count": 2})
        self.assertEqual(cache["records"][0]["normalized"], 0.0)
        self.assertEqual(cache["records"][1]["normalized"], 1.0)
        self.assertEqual(cache["records"][0]["elo_interval"]["low"], 980.0)
        self.assertEqual(cache["records"][0]["source"], aa_3d.SOURCE_URL)

    def test_no_record_normalized_or_linear_transform_is_accepted(self):
        # The old free-form fields are ignored: the board policy decides.
        cache = self._load(
            self._document(
                [self._record(model="A", elo=1000, ci95_low=980, ci95_high=1020, normalized=0.2)],
                normalization={"kind": "linear", "offset": 10, "scale": 100},
            )
        )
        self.assertEqual(cache["status"], "ok")
        self.assertEqual(cache["normalization"]["kind"], "relative-minmax")
        self.assertEqual(cache["records"][0]["normalized"], 1.0)

    def test_duplicate_ranks_are_rejected(self):
        dup = [
            self._record(model="A", rank=1),
            self._record(model="B", rank=1, elo=1100, ci95_low=1080, ci95_high=1120),
        ]
        self.assertEqual(self._load(self._document(dup))["status"], "invalid")

    def test_an_interval_that_does_not_contain_the_point_is_rejected(self):
        bad = self._record(elo=1197, ci95_low=1, ci95_high=2)
        self.assertEqual(self._load(self._document([bad]))["status"], "invalid")

    def test_a_non_finite_rank_rejects_without_raising(self):
        bad = self._record(rank=float("inf"))
        self.assertEqual(self._load(self._document([bad]))["status"], "invalid")

    def test_the_published_attribution_is_fixed_and_raw_fields_are_not_forwarded(self):
        cache = self._load(
            self._document(
                [
                    self._record(
                        model="GPT-6.1 Sol (Max)",
                        id="private-id",
                        slug="private-slug",
                        source="https://private.example/leaderboard",
                        normalization="private",
                        released_at="PRIVATE",
                    )
                ],
                attribution="PRIVATE_SENTINEL",
            )
        )
        self.assertEqual(cache["status"], "ok")
        self.assertEqual(cache["attribution"], "Artificial Analysis (https://artificialanalysis.ai/)")
        record = cache["records"][0]
        self.assertEqual(
            set(record),
            {
                "model",
                "elo",
                "elo_interval",
                "rank",
                "rank_range",
                "anchor",
                "cost_per_task",
                "normalized",
                "source_normalized",
                "conditions",
                "source",
            },
        )
        self.assertEqual(record["source"], aa_3d.SOURCE_URL)
        self.assertEqual(record["conditions"], {"benchmark": "AA-3D", "scope": aa_3d.PUBLIC_CONDITION})

    def test_the_3d_value_is_cost_aware_with_the_explicit_proxy(self):
        models = visual_model("codex", "gpt-6.1-sol")
        data = build(
            models,
            [record("gpt-6-1-sol", 51.8, 0.10)],
            aa_3d=self._load(
                self._document([self._record(model="GPT-6.1 Sol (Max)", cost_per_task=None)])
            ),
        )
        row = data["candidates"][0]
        value_3d = row["value_3d"]
        self.assertEqual(value_3d["cost_source"], "artificialanalysis_intelligence")
        self.assertTrue(value_3d["proxy"])
        self.assertIn("not a measured 3D cost", value_3d["cost_basis"])
        # 0.45 * intelligence + 0.25 * the normalized Elo + 0.30 * efficiency.
        self.assertAlmostEqual(
            value_3d["value"],
            round(0.45 * (51.8 / 100.0) + 0.25 * 1.0 + 0.3 * (1 / 1.1), 6),
            places=6,
        )
        self.assertEqual(row["three_d"]["elo"], 1200.0)
        normalization = row["three_d"]["normalization"]
        self.assertEqual(normalization["kind"], "relative-minmax")
        self.assertEqual(normalization["bounds"], {"min_elo": 1200.0, "max_elo": 1200.0, "count": 1})
        self.assertTrue(normalization["fingerprint"])
        self.assertEqual(row["three_d"]["normalization_state"], "relative-minmax")

    def test_missing_both_costs_leaves_no_full_value(self):
        models = visual_model("codex", "gpt-6.1-sol")
        data = build(
            models,
            [record("gpt-6-1-sol", 51.8, None)],
            aa_3d=self._load(
                self._document([self._record(model="GPT-6.1 Sol (Max)", cost_per_task=None)])
            ),
        )
        row = data["candidates"][0]
        self.assertIsNone(row["value_3d"]["value"])
        self.assertEqual(row["value_3d"]["missing"], ["cost_per_task"])
        self.assertIsNone(row["value_3d"]["cost_source"])
        self.assertEqual(row["three_d"]["elo"], 1200.0)


class RealAA3DSnapshotTests(unittest.TestCase):
    """The root-acquired 22-row AA-3D snapshot, through the reader."""

    def _now(self):
        from datetime import datetime

        return datetime.fromisoformat("2026-10-22T02:00:00+00:00").timestamp()

    def test_the_real_board_reads_and_normalizes_over_every_row(self):
        path = Path(__file__).resolve().parent / "fixtures" / "ai-usage" / "aa-3d-measured.json"
        cache = aa_3d.load_cache(str(path), self._now())
        self.assertEqual(cache["status"], "ok")
        self.assertEqual(cache["benchmark"], "AA-3D")
        self.assertEqual(cache["benchmark_version"], "1.0")
        self.assertEqual(len(cache["records"]), 22)
        elos = [record["elo"] for record in cache["records"]]
        self.assertEqual(cache["bounds"]["min_elo"], min(elos))
        self.assertEqual(cache["bounds"]["max_elo"], max(elos))
        self.assertEqual(cache["bounds"]["count"], 22)
        self.assertTrue(cache["fingerprint"])
        normalized = [record["normalized"] for record in cache["records"]]
        self.assertEqual(max(normalized), 1.0)
        self.assertEqual(min(normalized), 0.0)
        # The source publishes a 95% interval for every row but one; that
        # row keeps its raw Elo and the interval stays absent, never invented.
        with_interval = [
            record
            for record in cache["records"]
            if record["elo_interval"]["low"] is not None
        ]
        self.assertGreaterEqual(len(with_interval), 21)
        for record in cache["records"]:
            self.assertIsNone(record["cost_per_task"])

    def test_the_actual_measurement_names_bind_to_the_provider_models(self):
        path = Path(__file__).resolve().parent / "fixtures" / "ai-usage" / "aa-3d-measured.json"
        cache = aa_3d.load_cache(str(path), self._now())
        found = aa_3d.lookup(cache, "codex", "gpt-6.1-sol")
        self.assertEqual(found["state"], "measured")
        self.assertEqual(found["elo"], 1118.0)
        self.assertEqual(found["normalization_state"], "relative-minmax")
        self.assertEqual(found["aa_name"], "GPT-6.1 Sol (Max)")
        self.assertEqual(found["elo_interval"], {"low": 1085.0, "high": 1150.0})
        self.assertIsNone(found["cost_per_task"])
        expected = (1118.0 - min(r["elo"] for r in cache["records"])) / (
            max(r["elo"] for r in cache["records"]) - min(r["elo"] for r in cache["records"])
        )
        self.assertAlmostEqual(found["normalized"], expected, places=9)


class ProviderCapacityUnknownTests(unittest.TestCase):
    def test_an_unknown_window_suppresses_a_positive_capacity(self):
        models = text_model("claude", "claude-opus-5-5")
        data = build(
            models,
            [record("claude-opus-5-5", 57.6, 0.5)],
            windows={
                "claude": [
                    window(0.1, 2 * HOUR, "session"),
                    ranking.QuotaWindow(
                        kind="monthly",
                        used_ratio=None,
                        reset_epoch=NOW + 20 * DAY,
                        duration_seconds=30 * DAY,
                        observed_at=NOW,
                        quota_id="monthly",
                    ),
                ]
            },
        )
        capacity = data["quota"]["provider_capacity"]["claude"]
        # The known window has room, but the account also has an unknown one:
        # no positive capacity is published.
        self.assertIsNone(capacity["remaining_ratio"])
        self.assertGreaterEqual(capacity["unknown_windows"], 1)

    def test_a_model_scoped_window_does_not_constrain_the_provider(self):
        rows = {
            "provider_capacity": {"claude": {"remaining_ratio": 0.8, "binding": {"kind": "weekly"}, "windows": 1, "unknown_windows": 0}}
        }
        samples = snapshot.provider_capacity_samples({"quota": rows})
        values = {
            (name, labels.get("binding"), labels.get("evidence")): value
            for name, labels, value in samples
        }
        self.assertEqual(
            values[("ghostship_ai_provider_capacity_remaining_ratio", "weekly", None)],
            0.8,
        )


class StockDescriptorTests(unittest.TestCase):
    """The stock orchestrator option descriptors, end to end."""

    def _source_options(self):
        import t3source

        return t3source._model_options(
            {
                "capabilities": {
                    "optionDescriptors": [
                        {
                            "id": "effort",
                            "options": [
                                {"id": "low", "label": "Low"},
                                {"id": "medium", "label": "Medium"},
                                {"id": "high", "label": "High"},
                                {"id": "xhigh", "label": "Xhigh"},
                                {"id": "max", "label": "Max"},
                                {"id": "ultracode", "label": "Ultracode"},
                                {"id": "ultrathink", "label": "Ultrathink"},
                            ],
                        },
                        {"id": "thinking", "options": [{"id": "on"}, {"id": "off"}]},
                    ]
                }
            }
        )

    def test_a_descriptor_without_a_current_value_is_kept_with_its_choices(self):
        options = self._source_options()
        effort = [option for option in options if option["id"] == "effort"][0]
        self.assertNotIn("currentValue", effort)
        self.assertEqual(
            effort["values"],
            ["low", "medium", "high", "xhigh", "max", "ultracode", "ultrathink"],
        )
        native = snapshot._native_record(
            "claude", "claude-opus-5-5", {"providerInstance": "claudeAgent", "modelId": "claude-opus-5-5", "options": options}
        )
        self.assertFalse(native["options"][0]["current_published"])
        self.assertIsNone(native["options"][0]["current_value"])
        self.assertEqual(native["options"][0]["values"][4], "max")

    def test_the_measured_condition_aligns_through_the_stock_option(self):
        self.assertEqual(aa_bind.alignment_option(self._source_options(), "max"), ("effort", "max"))
        models = visual_model("claude", "claude-opus-5-5")
        data = build(
            models,
            [record("claude-opus-5-5", 57.6, 0.5, name="Claude Opus 5.5 (Max)")],
            native_options={("claude", "claude-opus-5-5"): self._source_options()},
        )
        row = data["candidates"][0]
        self.assertEqual(row["aa"]["condition"]["variant_match"], "reference")
        # The AA condition stays Max, visible; our run is Medium.
        self.assertEqual(row["aa"]["condition"]["measured_variant"], "max")
        self.assertEqual(row["aa"]["condition"]["execution_default"], "medium")
        self.assertTrue(row["aa"]["selectable"])
        self.assertEqual(row["aa"]["alignment"], {"effort": "medium"})
        self.assertEqual(row["aa"]["alignment_meta"]["option"], "effort")
        self.assertTrue(row["aa"]["alignment_meta"]["recommended"])
        self.assertFalse(row["aa"]["alignment_meta"]["applied"])
        self.assertIsNone(row["aa"]["alignment_meta"]["actual"])
        self.assertEqual(row["aa"]["alignment_meta"]["escalation"], {"effort": "high"})
        self.assertEqual(row["aa"]["runtime_policy"]["state"], "selectable")

    def test_the_minimax_flash_options_support_the_default_and_the_escalation(self):
        options = [{"id": "variant", "values": ["low", "medium", "high", "xhigh", "max"]}]
        models = visual_model("opencode-go", "minimax-m3.1-flash")
        data = build(
            models,
            [record("minimax-m3-1-flash", 42.7, 0.2201, name="MiniMax-M3.1-Flash")],
            native_options={("opencode-go", "minimax-m3.1-flash"): options},
        )
        row = data["candidates"][0]
        self.assertTrue(row["aa"]["selectable"])
        self.assertEqual(row["aa"]["alignment"], {"variant": "medium"})
        self.assertEqual(row["aa"]["alignment_meta"]["escalation"], {"variant": "high"})
        self.assertEqual(row["aa"]["runtime_policy"]["state"], "selectable")

    def test_deepseek_v41_flash_uses_the_approved_high_default(self):
        options = [{"id": "variant", "values": ["low", "high", "max"]}]
        for provider, model, aa_slug, aa_name in (
            ("ollama", "deepseek-v4.1-flash:1017", "deepseek-v4-1-flash-1017", "DeepSeek V4.1 Flash 1017 (Max)"),
            ("deepseek", "deepseek/deepseek-v4.1-flash", "deepseek-v4-1-flash", "DeepSeek V4.1 Flash (Max)"),
        ):
            data = build(
                visual_model(provider, model),
                [record(aa_slug, 45.1, 0.262, name=aa_name)],
                native_options={(provider, model): options},
            )
            row = data["candidates"][0]
            self.assertTrue(row["aa"]["selectable"], model)
            self.assertEqual(row["aa"]["alignment"], {"variant": "high"}, model)
            self.assertEqual(row["aa"]["alignment_meta"]["value"], "high")
            self.assertEqual(row["aa"]["alignment_meta"]["escalation"], {"variant": "high"})
            self.assertEqual(row["aa"]["condition"]["execution_default"], "high", model)
            self.assertTrue(row["aa"]["condition"]["execution_exception"], model)
            self.assertEqual(row["aa"]["runtime_policy"]["default"], "high")
            self.assertTrue(row["aa"]["runtime_policy"]["exception"])
            # The AA reference is still the best measured 80/20, unchanged.
            self.assertEqual(row["aa"]["reference"]["condition"], "max", model)

    def test_the_high_exception_does_not_inherit(self):
        options = [{"id": "variant", "values": ["low", "high", "max"]}]
        for model in (
            "deepseek-v4-flash",
            "deepseek-v4.1-flash-extra",
            "my-deepseek-v4.1-flash-clone",
        ):
            data = build(
                visual_model("ollama", model),
                [record("deepseek-v4-1-flash", 39.5, 0.4, name="DeepSeek V4.1 Flash (Max)")],
                native_options={("ollama", model): options},
            )
            row = data["candidates"][0]
            self.assertFalse(row["aa"]["selectable"], model)
            self.assertFalse(row["aa"]["condition"]["execution_exception"], model)
            self.assertEqual(row["aa"]["runtime_policy"]["default"], "medium", model)
            self.assertEqual(row["aa"]["runtime_policy"]["state"], "capability_mismatch", model)

    def test_the_minimax_flash_keeps_the_medium_default(self):
        options = [{"id": "variant", "values": ["low", "medium", "high", "xhigh", "max"]}]
        data = build(
            visual_model("opencode-go", "minimax-m3.1-flash"),
            [record("minimax-m3-1-flash", 42.7, 0.2201, name="MiniMax-M3.1-Flash")],
            native_options={("opencode-go", "minimax-m3.1-flash"): options},
        )
        row = data["candidates"][0]
        self.assertEqual(row["aa"]["runtime_policy"]["default"], "medium")
        self.assertFalse(row["aa"]["condition"]["execution_exception"])
        self.assertEqual(row["aa"]["alignment"], {"variant": "medium"})

    def test_a_flash_without_high_fails_closed(self):
        options = [{"id": "variant", "values": ["low", "medium"]}]
        data = build(
            visual_model("ollama", "deepseek-v4.1-flash:1017"),
            [record("deepseek-v4-1-flash-1017", 45.1, 0.262, name="DeepSeek V4.1 Flash 1017 (Max)")],
            native_options={("ollama", "deepseek-v4.1-flash:1017"): options},
        )
        row = data["candidates"][0]
        self.assertFalse(row["aa"]["selectable"])
        self.assertEqual(row["aa"]["alignment"], {})
        self.assertEqual(row["aa"]["runtime_policy"]["state"], "capability_mismatch")
        self.assertEqual(row["aa"]["runtime_policy"]["supported"], ["low", "medium"])

    def test_a_model_without_a_reasoning_option_is_not_subject_to_the_policy(self):
        models = visual_model("claude", "claude-opus-5-5")
        data = build(
            models,
            [record("claude-opus-5-5", 57.6, 0.5, name="Claude Opus 5.5 (High)")],
        )
        row = data["candidates"][0]
        self.assertTrue(row["aa"]["selectable"])
        self.assertEqual(row["aa"]["alignment"], {})
        self.assertEqual(row["aa"]["runtime_policy"]["state"], "not_applicable")
        # The benchmark condition remains visible.
        self.assertEqual(row["aa"]["condition"]["measured_variant"], "high")

    def test_the_codex_actual_current_value_is_distinguished_from_the_recommendation(self):
        import t3source

        options = t3source._model_options(
            {
                "capabilities": {
                    "optionDescriptors": [
                        {
                            "id": "reasoningEffort",
                            "currentValue": "low",
                            "options": [
                                {"id": "low"},
                                {"id": "medium"},
                                {"id": "high"},
                                {"id": "xhigh"},
                                {"id": "max"},
                                {"id": "ultra"},
                            ],
                        }
                    ]
                }
            }
        )
        models = visual_model("codex", "gpt-6.1-sol")
        # The snapshot receives the raw stock options.
        data = build(
            models,
            [record("gpt-6-1-sol", 51.8, 0.4, name="GPT-6.1 Sol (Max)")],
            native_options={("codex", "gpt-6.1-sol"): options},
        )
        row = data["candidates"][0]
        self.assertEqual(row["aa"]["alignment"], {"reasoningEffort": "medium"})
        self.assertEqual(row["aa"]["alignment_meta"]["escalation"], {"reasoningEffort": "high"})
        self.assertTrue(row["aa"]["alignment_meta"]["recommended"])
        self.assertFalse(row["aa"]["alignment_meta"]["applied"])
        # The actual low is still published beside the recommendation.
        self.assertEqual(row["native"]["options"][0]["current_value"], "low")
        self.assertEqual(row["aa"]["runtime_policy"]["current"], "low")


class CatalogCoverageReconciliationTests(unittest.TestCase):
    def test_the_inventory_and_the_excluded_models_are_published(self):
        models = text_model("codex", "gpt-6.1-sol")
        catalog = Catalog(models)
        cache_doc = cache([record("gpt-6-1-sol", 51.8, 0.4)])
        ranked = ranking.rank_models(
            models=[ranking.ModelRecord("codex", "gpt-6.1-sol")],
            catalog=catalog,
            quota_windows={},
            free_models=set(),
            promo_models={("codex", "gpt-6.1-sol")},
            usage_tokens={},
            aa_cache=cache_doc,
            now=NOW,
        )
        data = snapshot.build_snapshot(
            now=NOW,
            sources=[{"id": "t3", "status": "ok", "reason": "ok", "observed_at_epoch": NOW}],
            ranked=ranked,
            native_models={},
            policy={"frontierPrimeModels": (), "allowedGptModels": (), "backgroundProviderInstances": ("codex",)},
            catalog=catalog,
            facts={},
            aa_cache=cache_doc,
            free_models=set(),
            promo_models={("codex", "gpt-6.1-sol")},
            inventory=[("codex", "gpt-6.1-sol"), ("codex", "not-offered")],
        )
        ranking_coverage = data["coverage"]["ranking"]
        self.assertEqual(ranking_coverage["inventory"], 2)
        self.assertEqual(ranking_coverage["candidates"], 1)
        self.assertEqual(ranking_coverage["excluded"], 1)
        self.assertEqual(ranking_coverage["excluded_models"], [["codex", "not-offered"]])


class AAReferenceIndependenceTests(unittest.TestCase):
    """The AA reference is independent of the native runtime setting."""

    def _records(self):
        return [
            record("gpt-6-1-sol", 51.8, 0.5, name="GPT-6.1 Sol (Max)"),
            record("gpt-6-1-sol-high", 50.2, 0.1, name="GPT-6.1 Sol (High)"),
        ]

    def _options(self, current):
        return [
            {
                "id": "reasoningEffort",
                "currentValue": current,
                "options": [{"id": "low"}, {"id": "medium"}, {"id": "high"}, {"id": "max"}],
            }
        ]

    def _build(self, current):
        models = visual_model("codex", "gpt-6.1-sol")
        return build(
            models,
            self._records(),
            native_options={("codex", "gpt-6.1-sol"): self._options(current)},
        )

    def test_changing_only_the_current_value_does_not_change_the_reference(self):
        low = self._build("low")["candidates"][0]
        medium = self._build("medium")["candidates"][0]
        for key in ("id", "slug", "name", "reference", "alternatives"):
            self.assertEqual(low["aa"][key], medium["aa"][key], key)
        self.assertEqual(low["aa"]["indices"], medium["aa"]["indices"])
        self.assertEqual(low["value"]["value"], medium["value"]["value"])
        self.assertEqual(low["quality"]["value"], medium["quality"]["value"])

    def test_the_best_measured_value_is_the_reference_not_max(self):
        row = self._build("medium")["candidates"][0]
        # High: 0.70 * 0.502 + 0.30 / 1.1 = 0.624... beats Max:
        # 0.70 * 0.518 + 0.30 / 1.5 = 0.563...
        self.assertEqual(row["aa"]["condition"]["measured_variant"], "high")
        self.assertEqual(row["aa"]["reference"]["condition"], "high")
        self.assertEqual(len(row["aa"]["alternatives"]), 2)
        self.assertEqual(
            {entry["condition"] for entry in row["aa"]["alternatives"]}, {"max", "high"}
        )
        self.assertAlmostEqual(
            row["aa"]["reference"]["value"], row["value"]["value"], places=4
        )

    def test_duplicate_conflicting_same_condition_records_are_ambiguous(self):
        records = [
            record("gpt-6-1-sol", 51.8, 0.5, name="GPT-6.1 Sol (Max)"),
            record("gpt-6-1-sol-dup", 52.0, 0.4, name="GPT-6.1 Sol (Max)"),
        ]
        models = visual_model("codex", "gpt-6.1-sol")
        data = build(
            models,
            records,
            native_options={("codex", "gpt-6.1-sol"): self._options("medium")},
        )
        row = data["candidates"][0]
        self.assertEqual(row["aa"]["state"], "ambiguous")
        self.assertIsNone(row["aa"]["reference"])
        self.assertIsNone(row["value"]["value"])
        self.assertEqual(row["rank"], {})

    def test_a_record_without_a_cost_has_no_reference_but_stays_visible(self):
        models = visual_model("codex", "gpt-6.1-sol")
        data = build(
            models,
            [record("gpt-6-1-sol", 51.8, None, name="GPT-6.1 Sol (Max)")],
            native_options={("codex", "gpt-6.1-sol"): self._options("medium")},
        )
        row = data["candidates"][0]
        self.assertIsNone(row["aa"]["reference"])
        self.assertEqual(row["aa"]["indices"]["intelligence"], 51.8)
        self.assertIsNone(row["value"]["value"])
        self.assertEqual(row["rank"], {})
