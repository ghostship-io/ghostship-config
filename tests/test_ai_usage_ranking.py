"""Tests for the AI usage model ranking engine."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

COLLECTOR = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage/collector"
if str(COLLECTOR) not in sys.path:
    sys.path.append(str(COLLECTOR))

import catalog as catalog_module  # noqa: E402
import ranking  # noqa: E402

# A fixed clock, so the release dates below are stable.
NOW = 1_760_000_000.0
DAY = 86400.0

# The ranking reads quality from the measured Artificial Analysis record.
# These tests inject one measured record per model, so no prior is involved.
AA_INDEX = 80.0


def aa_cache_for(models):
    records = []
    seen = set()
    for record in models or ():
        provider = getattr(record, "provider", "")
        model = getattr(record, "model", "")
        key = (provider, model)
        if key in seen:
            continue
        seen.add(key)
        records.append(
            {
                "id": f"id-{provider}-{model}",
                "slug": model,
                "model": model,
                "release_date": "2025-09-20",
                "indices": {"intelligence_index": AA_INDEX},
                "cost_per_task": 0.2,
                "median_performance": 100.0,
                "prices": {},
            }
        )
    return {
        "status": "ok",
        "index_version": "4.3",
        "fetched_at": "2025-09-20T00:00:00Z",
        "fetched_at_epoch": NOW,
        "records": records,
    }


_rank_models = ranking.rank_models


def _rank_with_feed(**kwargs):
    if "aa_cache" not in kwargs:
        kwargs["aa_cache"] = aa_cache_for(kwargs.get("models") or ())
    return _rank_models(**kwargs)


ranking.rank_models = _rank_with_feed


def entry(
    model_id,
    family,
    *,
    released="2025-09-20",
    context=200000,
    reasoning=True,
    tool_call=True,
    cost=None,
    name=None,
    description="",
):
    """One synthetic catalog entry."""
    found = {
        "id": model_id,
        "name": name or model_id,
        "family": family,
        "release_date": released,
        "limit": {"context": context},
        "reasoning": reasoning,
        "tool_call": tool_call,
        "description": description,
    }
    if cost is not None:
        found["cost"] = cost
    return found


def make_catalog(document):
    """A catalog built from {provider: {"models": {model id: entry}}}."""
    return catalog_module.Catalog(dict(document))


def tiers_of(ranked):
    """The (provider, model, tier) triples of a ranking."""
    return {(item.provider, item.model, item.tier) for item in ranked}


def tier_members(ranked, tier):
    """The ranked models of one tier, in rank order."""
    return [item for item in ranked if item.tier == tier]


class FrontierTierTests(unittest.TestCase):
    def setUp(self):
        self.catalog = make_catalog(
            {
                "anthropic": {
                    "models": {
                        "claude-opus-5-5": entry("claude-opus-5-5", "claude-opus"),
                        "claude-opus-5-5-flash": entry(
                            "claude-opus-5-5-flash", "claude-opus"
                        ),
                    }
                },
                "openai": {
                    "models": {"gpt-6.1-sol": entry("gpt-6.1-sol", "gpt-sol")}
                },
            }
        )
        self.models = [
            ranking.ModelRecord("anthropic", "claude-opus-5-5"),
            ranking.ModelRecord("anthropic", "claude-opus-5-5-flash"),
            ranking.ModelRecord("openai", "gpt-6.1-sol"),
        ]

    def rank(self):
        return ranking.rank_models(
            models=self.models,
            catalog=self.catalog,
            quota_windows={},
            free_models=set(),
            usage_tokens={},
            now=NOW,
        )

    def test_the_best_models_are_frontier(self):
        ranked = self.rank()
        tiers = tiers_of(ranked)
        self.assertIn(("anthropic", "claude-opus-5-5", "frontier"), tiers)
        self.assertIn(("openai", "gpt-6.1-sol", "frontier"), tiers)

    def test_a_flash_variant_of_a_frontier_family_is_not_frontier(self):
        ranked = self.rank()
        tiers = tiers_of(ranked)
        self.assertNotIn(("anthropic", "claude-opus-5-5-flash", "frontier"), tiers)
        self.assertIn(("anthropic", "claude-opus-5-5-flash", "bulk"), tiers)

    def test_frontier_ranks_start_at_one(self):
        ranked = self.rank()
        frontier = tier_members(ranked, "frontier")
        self.assertEqual([item.model for item in frontier], ["claude-opus-5-5", "gpt-6.1-sol"])
        self.assertEqual([item.rank for item in frontier], [1, 2])


class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.catalog = make_catalog(
            {
                "anthropic": {"models": {"claude-opus-5-5": entry("claude-opus-5-5", "claude-opus")}},
                "openai": {"models": {"gpt-6.1-sol": entry("gpt-6.1-sol", "gpt-sol")}},
            }
        )
        self.models = [
            ranking.ModelRecord("anthropic", "claude-opus-5-5"),
            ranking.ModelRecord("openai", "gpt-6.1-sol"),
        ]

    def test_an_account_that_frees_up_soon_outranks_one_that_stays_used_up(self):
        # The order across the providers comes from the pace of their own
        # window: the account behind the line its window draws is the one
        # that is used first. The score is the measured value and carries no
        # capacity term, so the two models of equal measurement score the
        # same.
        ranked = ranking.rank_models(
            models=self.models,
            catalog=self.catalog,
            quota_windows={
                "claude": [
                    ranking.QuotaWindow(
                        kind="weekly",
                        used_ratio=0.5,
                        reset_epoch=NOW + 3600.0,
                        duration_seconds=2 * 3600.0,
                        observed_at=NOW,
                    )
                ],
                "codex": [
                    ranking.QuotaWindow(
                        kind="weekly",
                        used_ratio=0.8,
                        reset_epoch=NOW + 5 * DAY,
                        duration_seconds=10 * DAY,
                        observed_at=NOW,
                    )
                ],
            },
            free_models=set(),
            usage_tokens={},
            now=NOW,
        )
        frontier = tier_members(ranked, "frontier")
        self.assertEqual([item.model for item in frontier], ["claude-opus-5-5", "gpt-6.1-sol"])
        claude = frontier[0]
        codex = frontier[1]
        self.assertEqual(claude.remaining, 0.5)
        self.assertAlmostEqual(codex.remaining, 0.2, places=6)
        # The score is the value: the capacity is reported beside the rank,
        # never folded into it.
        self.assertAlmostEqual(claude.score, codex.score, places=6)
        self.assertGreater(claude.pace, codex.pace)

    def test_an_exhausted_account_makes_its_models_unavailable(self):
        ranked = ranking.rank_models(
            models=self.models,
            catalog=self.catalog,
            quota_windows={
                "claude": [
                    ranking.QuotaWindow(
                        kind="weekly", used_ratio=1.0, reset_epoch=NOW + 3600.0
                    , observed_at=NOW
                    )
                ]
            },
            free_models=set(),
            usage_tokens={},
            now=NOW,
        )
        claude = [item for item in ranked if item.model == "claude-opus-5-5"]
        self.assertTrue(claude)
        self.assertFalse(claude[0].available)
        self.assertEqual(claude[0].rank, 0)
        self.assertNotIn("frontier", {item.tier for item in claude})


class FreeTierTests(unittest.TestCase):
    def setUp(self):
        self.catalog = make_catalog(
            {
                "opencode-go": {
                    "models": {
                        "minimax-m3.1-flash-free": entry(
                            "minimax-m3.1-flash-free",
                            "minimax",
                            cost={"input": 0, "output": 0},
                        ),
                        "gpt-5.1-codex": entry(
                            "gpt-5.1-codex",
                            "gpt-sol",
                            cost={"input": 3.0, "output": 15.0},
                        ),
                    }
                }
            }
        )
        self.models = [
            ranking.ModelRecord("opencode-go", "minimax-m3.1-flash-free"),
            ranking.ModelRecord("opencode-go", "gpt-5.1-codex"),
        ]
        self.free = {("opencode-go", "minimax-m3.1-flash-free")}

    def rank(self):
        return ranking.rank_models(
            models=self.models,
            catalog=self.catalog,
            quota_windows={},
            free_models=self.free,
            usage_tokens={},
            now=NOW,
        )

    def test_a_model_with_a_zero_catalog_price_is_free(self):
        catalog_free = {
            (row["provider"], row["model"])
            for row in self.catalog.free_models("opencode-go")
        }
        self.assertIn(("opencode-go", "minimax-m3.1-flash-free"), catalog_free)
        tiers = tiers_of(self.rank())
        self.assertIn(("opencode-go", "minimax-m3.1-flash-free", "free"), tiers)

    def test_a_promotional_free_model_is_bulk_and_free(self):
        tiers = tiers_of(self.rank())
        self.assertIn(("opencode-go", "minimax-m3.1-flash-free", "free"), tiers)
        self.assertIn(("opencode-go", "minimax-m3.1-flash-free", "bulk"), tiers)

    def test_a_paid_model_is_not_free(self):
        tiers = tiers_of(self.rank())
        self.assertNotIn(("opencode-go", "gpt-5.1-codex", "free"), tiers)


class ThreeDTests(unittest.TestCase):
    def setUp(self):
        self.catalog = make_catalog(
            {
                "deepseek": {
                    "models": {
                        "deepseek-pro-v3": entry("deepseek-pro-v3", "deepseek-pro"),
                        "deepseek-thinking-v3": entry(
                            "deepseek-thinking-v3", "deepseek-thinking"
                        ),
                    }
                },
                "anthropic": {
                    "models": {"claude-opus-5-5": entry("claude-opus-5-5", "claude-opus")}
                },
                "openai": {
                    "models": {"gpt-6.1-sol": entry("gpt-6.1-sol", "gpt-sol")}
                },
            }
        )
        self.models = [
            ranking.ModelRecord("deepseek", "deepseek-pro-v3"),
            ranking.ModelRecord("deepseek", "deepseek-thinking-v3"),
            ranking.ModelRecord("anthropic", "claude-opus-5-5"),
            ranking.ModelRecord("openai", "gpt-6.1-sol"),
        ]
        self.three_d = {
            ("deepseek", "deepseek-pro-v3"): {
                "elo": 1150.0,
                "usage_tokens": 250000,
                "eligible": True,
            }
        }

    def rank(self, three_d=None):
        return ranking.rank_models(
            models=self.models,
            catalog=self.catalog,
            quota_windows={},
            free_models=set(),
            usage_tokens={},
            three_d_scores=three_d,
            now=NOW,
        )

    def test_three_d_eligibility_does_not_change_the_bulk_order(self):
        with_3d = [item.model for item in tier_members(self.rank(self.three_d), "bulk")]
        without = [item.model for item in tier_members(self.rank(), "bulk")]
        self.assertEqual(with_3d, without)

    def test_a_three_d_member_needs_explicit_eligibility(self):
        self.assertIn(
            ("deepseek", "deepseek-pro-v3", "3d"),
            tiers_of(self.rank(self.three_d)),
        )
        self.assertNotIn(
            ("deepseek", "deepseek-pro-v3", "3d"),
            tiers_of(self.rank()),
        )

    def test_the_frontier_rank_is_untouched(self):
        three_d = dict(self.three_d)
        three_d[("anthropic", "claude-opus-5-5")] = {
            "score": 0.95,
            "usage_tokens": 500000,
            "eligible": True,
        }
        with_three_d = tier_members(self.rank(three_d), "frontier")
        without_three_d = tier_members(self.rank(), "frontier")
        self.assertEqual(
            [(item.model, item.rank) for item in with_three_d],
            [(item.model, item.rank) for item in without_three_d],
        )

    def test_an_eligible_three_d_model_joins_the_three_d_tier(self):
        tiers = tiers_of(self.rank(self.three_d))
        self.assertIn(("deepseek", "deepseek-pro-v3", "3d"), tiers)
        self.assertNotIn(("deepseek", "deepseek-thinking-v3", "3d"), tiers)

    def test_an_ineligible_model_stays_out_of_the_three_d_tier(self):
        tiers = tiers_of(
            self.rank(
                {
                    ("deepseek", "deepseek-pro-v3"): {
                        "score": 0.9,
                        "usage_tokens": 250000,
                        "eligible": False,
                    }
                }
            )
        )
        self.assertNotIn(("deepseek", "deepseek-pro-v3", "3d"), tiers)


class StateFileTests(unittest.TestCase):
    def setUp(self):
        self.catalog = make_catalog(
            {
                "anthropic": {"models": {"claude-opus-5-5": entry("claude-opus-5-5", "claude-opus")}}
            }
        )
        self.models = [ranking.ModelRecord("anthropic", "claude-opus-5-5")]

    def rank(self, path, now, models=None):
        return ranking.rank_models(
            models=self.models if models is None else models,
            catalog=self.catalog,
            quota_windows={},
            free_models=set(),
            usage_tokens={},
            now=now,
            state_path=path,
        )

    def test_a_new_model_is_evaluated_and_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ranking.json"
            self.rank(path, NOW)
            state = json.loads(path.read_text(encoding="utf-8"))
            found = state["anthropic/claude-opus-5-5"]
            self.assertEqual(found["first_seen"], NOW)
            self.assertEqual(found["last_evaluated"], NOW)
            self.assertEqual(found["evaluations"], 1)
            self.assertFalse(found["stale"])

    def test_a_second_evaluation_keeps_the_first_seen_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ranking.json"
            self.rank(path, NOW)
            self.rank(path, NOW + 600.0)
            state = json.loads(path.read_text(encoding="utf-8"))
            found = state["anthropic/claude-opus-5-5"]
            self.assertEqual(found["first_seen"], NOW)
            self.assertEqual(found["last_evaluated"], NOW + 600.0)
            self.assertEqual(found["evaluations"], 2)

    def test_a_model_that_disappears_is_kept_as_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ranking.json"
            self.rank(path, NOW)
            self.rank(path, NOW + 600.0, models=[])
            state = json.loads(path.read_text(encoding="utf-8"))
            found = state["anthropic/claude-opus-5-5"]
            self.assertTrue(found["stale"])
            self.assertEqual(found["first_seen"], NOW)


class UnknownModelTests(unittest.TestCase):
    def test_a_model_the_catalog_does_not_know_still_gets_a_score_and_a_rank(self):
        catalog = make_catalog({"anthropic": {"models": {}}})
        models = [ranking.ModelRecord("anthropic", "claude-opus-9-9")]
        ranked = ranking.rank_models(
            models=models,
            catalog=catalog,
            quota_windows={},
            free_models=set(),
            usage_tokens={},
            now=NOW,
        )
        found = [item for item in ranked if item.model == "claude-opus-9-9"]
        self.assertTrue(found)
        self.assertEqual(found[0].quality, AA_INDEX)
        self.assertEqual(found[0].tier, "bulk")
        self.assertEqual(found[0].rank, 1)

    def test_the_samples_carry_the_ranking_metrics(self):
        catalog = make_catalog({"anthropic": {"models": {}}})
        models = [ranking.ModelRecord("anthropic", "claude-opus-9-9")]
        ranked = ranking.rank_models(
            models=models,
            catalog=catalog,
            quota_windows={},
            free_models=set(),
            usage_tokens={},
            now=NOW,
        )
        samples = ranking.rank_samples(ranked, now=NOW)
        names = {name for name, _labels, _value in samples}
        self.assertIn("ghostship_ai_model_rank", names)
        self.assertIn("ghostship_ai_model_score", names)
        self.assertIn("ghostship_ai_model_quality", names)
        self.assertIn("ghostship_ai_model_available", names)
        self.assertIn("ghostship_ai_model_tier", names)
        # No quota window was reported, so the headroom is unknown and no
        # headroom is claimed.
        self.assertNotIn("ghostship_ai_model_capacity_remaining", names)
        self.assertIn("ghostship_ai_model_evaluated_timestamp_seconds", names)

        quality = [
            (labels, value)
            for name, labels, value in samples
            if name == "ghostship_ai_model_quality"
        ]
        self.assertEqual(len(quality), 1)
        self.assertEqual(quality[0][0]["provider"], "anthropic")
        self.assertEqual(quality[0][0]["model"], "claude-opus-9-9")
        self.assertEqual(quality[0][1], AA_INDEX)

        ranks = [
            (labels, value)
            for name, labels, value in samples
            if name == "ghostship_ai_model_rank"
        ]
        self.assertEqual(ranks[0][0]["tier"], "bulk")
        self.assertEqual(ranks[0][1], 1.0)

    def test_an_unavailable_model_is_reported_but_not_ranked(self):
        catalog = make_catalog({"anthropic": {"models": {}}})
        models = [ranking.ModelRecord("anthropic", "claude-opus-9-9")]
        ranked = ranking.rank_models(
            models=[],
            catalog=catalog,
            quota_windows={},
            free_models={("anthropic", "claude-opus-9-9")},
            usage_tokens={},
            now=NOW,
        )
        found = [item for item in ranked if item.model == "claude-opus-9-9"]
        self.assertTrue(found)
        self.assertFalse(found[0].available)
        samples = ranking.rank_samples(ranked, now=NOW)
        names = {name for name, _labels, _value in samples}
        # The model is not in a tier, so it holds no tier of its own. It
        # keeps its rank and its availability, so a consumer can list it at
        # the bottom with the reason it is not usable.
        self.assertNotIn("ghostship_ai_model_tier", names)
        ranks = [
            (labels, value)
            for name, labels, value in samples
            if name == "ghostship_ai_model_rank"
        ]
        self.assertEqual(len(ranks), 1)
        self.assertEqual(ranks[0][1], 0.0)
        available = [
            (labels, value)
            for name, labels, value in samples
            if name == "ghostship_ai_model_available"
        ]
        self.assertEqual([value for _labels, value in available], [0.0])
        self.assertTrue(available[0][0]["reason"])


class LineageFrontierTests(unittest.TestCase):
    """Only the newest model of a lineage may hold the frontier."""

    def setUp(self):
        self.catalog = make_catalog(
            {
                "anthropic": {
                    "models": {
                        "claude-opus-4-8": entry(
                            "claude-opus-4-8", "claude-opus", released="2025-05-01"
                        ),
                        "claude-opus-5": entry(
                            "claude-opus-5", "claude-opus", released="2025-07-01"
                        ),
                        "claude-opus-5-5": entry(
                            "claude-opus-5-5", "claude-opus", released="2025-09-20"
                        ),
                    }
                },
                "openai": {
                    "models": {
                        "gpt-5.6-sol": entry(
                            "gpt-5.6-sol", "gpt-sol", released="2025-06-01"
                        ),
                        "gpt-6.1-sol": entry(
                            "gpt-6.1-sol", "gpt-sol", released="2025-09-20"
                        ),
                    }
                },
            }
        )
        self.models = [
            ranking.ModelRecord("anthropic", "claude-opus-4-8"),
            ranking.ModelRecord("anthropic", "claude-opus-5"),
            ranking.ModelRecord("anthropic", "claude-opus-5-5"),
            ranking.ModelRecord("openai", "gpt-5.6-sol"),
            ranking.ModelRecord("openai", "gpt-6.1-sol"),
        ]

    def rank(self):
        return ranking.rank_models(
            models=self.models,
            catalog=self.catalog,
            quota_windows={},
            free_models=set(),
            usage_tokens={},
            now=NOW,
        )

    def test_only_the_newest_model_of_a_lineage_is_a_frontier_model(self):
        ranked = self.rank()
        frontier = {item.model for item in tier_members(ranked, "frontier")}
        self.assertEqual(frontier, {"claude-opus-5-5", "gpt-6.1-sol"})

    def test_the_older_models_of_a_lineage_stay_in_the_bulk_tier(self):
        ranked = self.rank()
        tiers = tiers_of(ranked)
        for model in ("claude-opus-4-8", "claude-opus-5", "gpt-5.6-sol"):
            self.assertNotIn(("anthropic" if model.startswith("claude") else "openai", model, "frontier"), tiers)
            self.assertIn(("anthropic" if model.startswith("claude") else "openai", model, "bulk"), tiers)

    def test_a_new_release_takes_the_frontier_over_on_its_own(self):
        catalog = make_catalog(
            {
                "anthropic": {
                    "models": {
                        "claude-opus-5-5": entry(
                            "claude-opus-5-5", "claude-opus", released="2025-09-20"
                        ),
                        "claude-opus-6": entry(
                            "claude-opus-6", "claude-opus", released="2025-10-01"
                        ),
                    }
                }
            }
        )
        ranked = ranking.rank_models(
            models=[
                ranking.ModelRecord("anthropic", "claude-opus-5-5"),
                ranking.ModelRecord("anthropic", "claude-opus-6"),
            ],
            catalog=catalog,
            quota_windows={},
            free_models=set(),
            usage_tokens={},
            now=NOW,
        )
        frontier = {item.model for item in tier_members(ranked, "frontier")}
        # The frontier is the owner's explicit workhorse list; a newer
        # release does not take it over.
        self.assertEqual(frontier, {"claude-opus-5-5"})
        self.assertNotIn(
            ("anthropic", "claude-opus-6", "frontier"), tiers_of(ranked)
        )

    def test_the_version_of_the_id_decides_when_the_dates_are_missing(self):
        catalog = make_catalog(
            {
                "anthropic": {
                    "models": {
                        "claude-opus-4-8": entry("claude-opus-4-8", "claude-opus", released=None),
                        "claude-opus-5-5": entry("claude-opus-5-5", "claude-opus", released=None),
                    }
                }
            }
        )
        ranked = ranking.rank_models(
            models=[
                ranking.ModelRecord("anthropic", "claude-opus-4-8"),
                ranking.ModelRecord("anthropic", "claude-opus-5-5"),
            ],
            catalog=catalog,
            quota_windows={},
            free_models=set(),
            usage_tokens={},
            now=NOW,
        )
        # Without a release date no model is fresh enough for the frontier,
        # but the newer version of the id is still the newer one.
        self.assertEqual(tier_members(ranked, "frontier"), [])
        self.assertEqual(
            ranking._newness(None, "claude-opus-5-5", "anthropic")
            > ranking._newness(None, "claude-opus-4-8", "anthropic"),
            True,
        )
        self.assertEqual(ranking._newness(None, "claude-opus-5-5", "anthropic")[2], (5, 5))
        self.assertEqual(ranking._newness(None, "claude-opus-4-8", "anthropic")[2], (4, 8))


class HonestScoreTests(unittest.TestCase):
    """The published score is the measured value, and nothing else.

    A name suffix, a catalog price, a capacity term and a pace term are
    all guesses. They are not in the score, and a model of equal measured
    value keeps its place whatever it is called.
    """

    def setUp(self):
        # Both models share a family, so both have the same quality and only
        # the economy weighting of the bulk tier used to separate them.
        self.catalog = make_catalog(
            {
                "deepseek": {
                    "models": {
                        "deepseek-v4.1-flash": entry(
                            "deepseek-v4.1-flash", "deepseek-pro"
                        ),
                        "deepseek-v4-pro": entry("deepseek-v4-pro", "deepseek-pro"),
                    }
                }
            }
        )
        self.models = [
            ranking.ModelRecord("deepseek", "deepseek-v4.1-flash"),
            ranking.ModelRecord("deepseek", "deepseek-v4-pro"),
        ]

    def rank(self):
        return ranking.rank_models(
            models=self.models,
            catalog=self.catalog,
            quota_windows={},
            free_models=set(),
            usage_tokens={},
            now=NOW,
        )

    def test_a_name_suffix_does_not_change_the_score(self):
        bulk = tier_members(self.rank(), "bulk")
        self.assertEqual(len(bulk), 2)
        self.assertEqual(bulk[0].quality, bulk[1].quality)
        # The measured value is the same, so the score is the same: the
        # "flash" suffix buys nothing.
        self.assertAlmostEqual(bulk[0].score, bulk[1].score, places=6)
        self.assertAlmostEqual(
            bulk[0].score,
            bulk[0].value if bulk[0].value is not None else bulk[0].score,
            places=6,
        )

    def test_a_catalog_price_does_not_change_the_score(self):
        catalog = make_catalog(
            {
                "kimi": {
                    "models": {
                        "kimi-k2": entry(
                            "kimi-k2", "kimi-k2", cost={"input": 3.0, "output": 15.0}
                        ),
                        "kimi-k3": entry(
                            "kimi-k3", "kimi-k2", cost={"input": 0.3, "output": 1.2}
                        ),
                    }
                }
            }
        )
        ranked = ranking.rank_models(
            models=[
                ranking.ModelRecord("kimi", "kimi-k2"),
                ranking.ModelRecord("kimi", "kimi-k3"),
            ],
            catalog=catalog,
            quota_windows={},
            free_models=set(),
            usage_tokens={},
            now=NOW,
        )
        bulk = {item.model: item for item in tier_members(ranked, "bulk")}
        self.assertAlmostEqual(
            bulk["kimi-k2"].score, bulk["kimi-k3"].score, places=6
        )

    def test_a_capacity_or_pace_term_is_not_in_the_score(self):
        without = {
            (item.provider, item.model): item
            for item in tier_members(self.rank(), "bulk")
        }
        ranked = ranking.rank_models(
            models=self.models,
            catalog=self.catalog,
            quota_windows={
                "deepseek": [
                    ranking.QuotaWindow(
                        kind="weekly",
                        used_ratio=0.1,
                        reset_epoch=NOW + 5 * DAY,
                        observed_at=NOW,
                    )
                ]
            },
            free_models=set(),
            usage_tokens={},
            now=NOW,
        )
        with_window = {
            item.model: item for item in tier_members(ranked, "bulk")
        }
        for model, item in with_window.items():
            self.assertAlmostEqual(
                item.score,
                without[(item.provider, item.model)].score,
                places=6,
            )

    def test_a_promotional_free_model_leads_the_bulk_tier(self):
        # The free route leads because its measured cost per task is zero,
        # which the value formula turns into the full efficiency. Nothing in
        # the score knows that the model is called "-free".
        catalog = make_catalog(
            {
                "opencode-go": {
                    "models": {
                        "minimax-m3.1-flash-free": entry(
                            "minimax-m3.1-flash-free",
                            "minimax",
                            cost={"input": 0, "output": 0},
                        ),
                        "deepseek-v4-pro": entry(
                            "deepseek-v4-pro", "deepseek-pro", cost={"input": 3.0, "output": 15.0}
                        ),
                    }
                }
            }
        )
        models = [
            ranking.ModelRecord("opencode-go", "minimax-m3.1-flash-free"),
            ranking.ModelRecord("opencode-go", "deepseek-v4-pro"),
        ]
        cache = aa_cache_for(models)
        for record in cache["records"]:
            if record["model"] == "minimax-m3.1-flash-free":
                record["cost_per_task"] = 0.0
        ranked = ranking.rank_models(
            models=models,
            catalog=catalog,
            quota_windows={},
            free_models={("opencode-go", "minimax-m3.1-flash-free")},
            usage_tokens={},
            aa_cache=cache,
            now=NOW,
        )
        bulk = tier_members(ranked, "bulk")
        self.assertEqual(bulk[0].model, "minimax-m3.1-flash-free")
        self.assertGreater(bulk[0].score, bulk[1].score)


class RecencyBonusTests(unittest.TestCase):
    """Release age does not add a quality number: the index is measured."""

    def test_a_new_release_does_not_score_higher_than_an_old_one(self):
        today = "2025-09-20"
        a_year_ago = "2024-09-20"
        cache = aa_cache_for(
            [
                ranking.ModelRecord("p", "m-today"),
                ranking.ModelRecord("p", "m-old"),
            ]
        )
        ranked = ranking.rank_models(
            models=[
                ranking.ModelRecord("p", "m-today"),
                ranking.ModelRecord("p", "m-old"),
            ],
            catalog=make_catalog(
                {
                    "p": {
                        "models": {
                            "m-today": entry("m-today", "f", released=today),
                            "m-old": entry("m-old", "f", released=a_year_ago),
                        }
                    }
                }
            ),
            quota_windows={},
            free_models=set(),
            usage_tokens={},
            aa_cache=cache,
            now=NOW,
        )
        quality = {item.model: item.quality for item in ranked}
        self.assertEqual(quality["m-today"], quality["m-old"])

    def test_the_measured_index_reaches_the_free_tier(self):
        cache = aa_cache_for([ranking.ModelRecord("p", "free-model")])
        ranked = ranking.rank_models(
            models=[ranking.ModelRecord("p", "free-model")],
            catalog=make_catalog(
                {
                    "p": {
                        "models": {
                            "free-model": entry("free-model", "f", cost={"input": 0, "output": 0})
                        }
                    }
                }
            ),
            quota_windows={},
            free_models={("p", "free-model")},
            usage_tokens={},
            aa_cache=cache,
            now=NOW,
        )
        free = tier_members(ranked, "free")
        self.assertEqual(free[0].quality, AA_INDEX)


class ThreeDLimitTests(unittest.TestCase):
    """The 3D tier stays small."""

    def setUp(self):
        self.count = 25
        models = {}
        records = []
        three_d = {}
        for number in range(self.count):
            model_id = f"print-model-{number:02d}"
            models[model_id] = entry(model_id, "printing")
            records.append(ranking.ModelRecord("printer", model_id))
            three_d[("printer", model_id)] = {
                "elo": 1000.0 + number,
                "usage_tokens": 0,
                "eligible": True,
            }
        self.catalog = make_catalog({"printer": {"models": models}})
        self.models = records
        self.three_d = three_d

    def rank(self):
        # The tier orders by the measured index: give every model its own.
        cache = aa_cache_for(self.models)
        for position, record in enumerate(cache["records"]):
            record["indices"]["intelligence_index"] = 50.0 + position
        return ranking.rank_models(
            models=self.models,
            catalog=self.catalog,
            quota_windows={},
            free_models=set(),
            usage_tokens={},
            three_d_scores=self.three_d,
            aa_cache=cache,
            now=NOW,
        )

    def test_the_three_d_tier_holds_at_most_twenty_models(self):
        three_d = tier_members(self.rank(), "3d")
        self.assertEqual(len(three_d), 20)

    def test_the_three_d_tier_keeps_the_best_models(self):
        three_d = tier_members(self.rank(), "3d")
        self.assertEqual(three_d[0].model, "print-model-24")
        self.assertEqual(three_d[-1].model, "print-model-05")
        self.assertEqual([item.rank for item in three_d], list(range(1, 21)))

    def test_a_model_that_does_not_fit_is_still_reported(self):
        ranked = self.rank()
        cut = [
            item
            for item in ranked
            if item.model == "print-model-00" and item.tier == ""
        ]
        self.assertTrue(cut)
        self.assertEqual(cut[0].rank, 0)
        self.assertTrue(cut[0].available)


class ModelQuotaWindowTests(unittest.TestCase):
    """A model may have its own quota windows."""

    def setUp(self):
        self.catalog = make_catalog(
            {
                "google": {
                    "models": {
                        "gemini-3.8-pro": entry("gemini-3.8-pro", "gemini"),
                        "gemini-3.8-flash": entry("gemini-3.8-flash", "gemini"),
                    }
                }
            }
        )
        self.models = [
            ranking.ModelRecord("antigravity", "gemini-3.8-pro"),
            ranking.ModelRecord("antigravity", "gemini-3.8-flash"),
        ]

    def rank(self):
        return ranking.rank_models(
            models=self.models,
            catalog=self.catalog,
            quota_windows={
                "antigravity": [
                    ranking.QuotaWindow(
                        kind="daily", used_ratio=0.9, reset_epoch=NOW + 3600.0
                    , observed_at=NOW
                    )
                ],
                "antigravity/gemini-3.8-pro": [
                    ranking.QuotaWindow(
                        kind="model", used_ratio=0.1, reset_epoch=NOW + 3600.0
                    , observed_at=NOW
                    )
                ],
            },
            free_models=set(),
            usage_tokens={},
            now=NOW,
        )

    def test_a_model_window_combines_with_the_shared_account_window(self):
        ranked = self.rank()
        found = {
            item.model: item
            for item in ranked
            if item.model in ("gemini-3.8-pro", "gemini-3.8-flash")
        }
        # Every applicable limit gates the model: the shared daily window has
        # 0.1 left and the model window 0.9, so the model is bound at 0.1.
        self.assertAlmostEqual(found["gemini-3.8-pro"].remaining, 0.1)
        self.assertEqual(found["gemini-3.8-pro"].quota_scope["parent_windows"], 1)
        self.assertEqual(found["gemini-3.8-pro"].quota_scope["model_windows"], 1)
        # The other model of the account is gated only by the shared window.
        self.assertAlmostEqual(found["gemini-3.8-flash"].remaining, 0.1)

    def test_an_exhausted_parent_blocks_a_model_with_room_of_its_own(self):
        ranked = ranking.rank_models(
            models=self.models,
            catalog=self.catalog,
            quota_windows={
                "antigravity": [
                    ranking.QuotaWindow(
                        kind="weekly",
                        used_ratio=1.0,
                        reset_epoch=NOW + 3600.0,
                        observed_at=NOW,
                    )
                ],
                "antigravity/gemini-3.8-pro": [
                    ranking.QuotaWindow(
                        kind="model",
                        used_ratio=0.05,
                        reset_epoch=NOW + 3600.0,
                        observed_at=NOW,
                    )
                ],
            },
            free_models=set(),
            usage_tokens={},
            now=NOW,
        )
        found = {
            item.model: item
            for item in ranked
            if item.model in ("gemini-3.8-pro", "gemini-3.8-flash")
        }
        self.assertEqual(found["gemini-3.8-pro"].remaining, 0.0)
        self.assertFalse(found["gemini-3.8-pro"].available)
        self.assertEqual(found["gemini-3.8-flash"].remaining, 0.0)
        self.assertFalse(found["gemini-3.8-flash"].available)

    def test_a_single_model_with_a_window_ranks_without_an_unbound_name(self):
        instance = ModelQuotaWindowTests("test_a_model_window_combines_with_the_shared_account_window")
        instance.setUp()
        instance.models = [instance.models[0]]
        ranked = instance.rank()
        self.assertTrue(ranked)
        self.assertEqual(ranked[0].quota_scope["model_windows"], 1)

    def test_a_model_window_decides_the_availability_of_the_model(self):
        ranked = ranking.rank_models(
            models=self.models,
            catalog=self.catalog,
            quota_windows={
                "antigravity": [
                    ranking.QuotaWindow(
                        kind="daily", used_ratio=0.99, reset_epoch=NOW + 3600.0
                    , observed_at=NOW
                    )
                ],
                "antigravity/gemini-3.8-pro": [
                    ranking.QuotaWindow(
                        kind="model", used_ratio=0.99, reset_epoch=NOW + 3600.0
                    , observed_at=NOW
                    )
                ],
            },
            free_models=set(),
            usage_tokens={},
            now=NOW,
        )
        found = {
            item.model: item
            for item in ranked
            if item.model in ("gemini-3.8-pro", "gemini-3.8-flash")
        }
        self.assertFalse(found["gemini-3.8-pro"].available)
        self.assertFalse(found["gemini-3.8-flash"].available)


class ExcludedProviderTests(unittest.TestCase):
    """A tier can exclude a provider."""

    def setUp(self):
        self.catalog = make_catalog(
            {
                "google": {
                    "models": {
                        "gemini-3.8-flash": entry("gemini-3.8-flash", "gemini"),
                    }
                },
                "anthropic": {
                    "models": {
                        "claude-opus-5-5": entry("claude-opus-5-5", "claude-opus"),
                        "claude-haiku-4-5": entry("claude-haiku-4-5", "claude-haiku"),
                    }
                },
            }
        )
        self.models = [
            ranking.ModelRecord("pool", "gemini-3.8-flash"),
            ranking.ModelRecord("anthropic", "claude-opus-5-5"),
            ranking.ModelRecord("anthropic", "claude-haiku-4-5"),
        ]
        self.free = {("pool", "gemini-3.8-flash")}

    def rank(self, exclude_providers=None):
        return ranking.rank_models(
            models=self.models,
            catalog=self.catalog,
            quota_windows={},
            free_models=self.free,
            usage_tokens={},
            exclude_providers=exclude_providers,
            now=NOW,
        )

    def test_an_excluded_provider_leaves_the_tier(self):
        ranked = self.rank({"bulk": ["pool"]})
        tiers = tiers_of(ranked)
        self.assertNotIn(("pool", "gemini-3.8-flash", "bulk"), tiers)

    def test_an_excluded_provider_keeps_the_other_tiers(self):
        ranked = self.rank({"bulk": ["pool"]})
        tiers = tiers_of(ranked)
        self.assertIn(("pool", "gemini-3.8-flash", "free"), tiers)
        self.assertIn(("anthropic", "claude-haiku-4-5", "bulk"), tiers)
        self.assertIn(("anthropic", "claude-opus-5-5", "frontier"), tiers)

    def test_the_default_keeps_every_provider_in_every_tier(self):
        ranked = self.rank()
        tiers = tiers_of(ranked)
        self.assertIn(("pool", "gemini-3.8-flash", "bulk"), tiers)
        self.assertIn(("pool", "gemini-3.8-flash", "free"), tiers)

    def test_an_excluded_model_is_still_reported(self):
        ranked = self.rank({"bulk": ["pool"], "free": ["pool"]})
        found = [item for item in ranked if item.model == "gemini-3.8-flash"]
        self.assertTrue(found)
        self.assertTrue(found[0].available)
        self.assertEqual(found[0].tier, "")


if __name__ == "__main__":
    unittest.main()
