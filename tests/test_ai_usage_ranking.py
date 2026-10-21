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
        ranked = ranking.rank_models(
            models=self.models,
            catalog=self.catalog,
            quota_windows={
                "claude": [
                    ranking.QuotaWindow(
                        kind="weekly", used_ratio=0.5, reset_epoch=NOW + 3600.0
                    , observed_at=NOW
                    )
                ],
                "codex": [
                    ranking.QuotaWindow(
                        kind="weekly", used_ratio=0.5, reset_epoch=NOW + 5 * DAY
                    , observed_at=NOW
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
        self.assertEqual(codex.remaining, 0.5)
        self.assertGreater(claude.score, codex.score)

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
                "score": 0.9,
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

    def test_a_three_d_model_ranks_lower_in_the_bulk_tier(self):
        bulk = tier_members(self.rank(self.three_d), "bulk")
        self.assertEqual(
            [item.model for item in bulk],
            ["deepseek-thinking-v3", "deepseek-pro-v3"],
        )

    def test_without_a_three_d_score_the_bulk_order_is_unchanged(self):
        bulk = tier_members(self.rank(), "bulk")
        self.assertEqual(
            [item.model for item in bulk],
            ["deepseek-pro-v3", "deepseek-thinking-v3"],
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
        self.assertEqual(found[0].quality, 95.0)
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
        self.assertEqual(quality[0][1], 95.0)

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
        self.assertNotIn("ghostship_ai_model_rank", names)
        self.assertNotIn("ghostship_ai_model_tier", names)
        available = [
            value
            for name, _labels, value in samples
            if name == "ghostship_ai_model_available"
        ]
        self.assertEqual(available, [0.0])


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
        self.assertEqual(frontier, {"claude-opus-6"})

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


class EconomyBulkTests(unittest.TestCase):
    """The bulk tier prefers the economy models."""

    def setUp(self):
        # Both models share a family, so both have the same quality and only
        # the economy weighting of the bulk tier separates them.
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

    def test_an_economy_model_outranks_a_premium_model_of_the_same_quality(self):
        bulk = tier_members(self.rank(), "bulk")
        self.assertEqual(
            [item.model for item in bulk], ["deepseek-v4.1-flash", "deepseek-v4-pro"]
        )
        self.assertEqual(bulk[0].quality, bulk[1].quality)
        self.assertAlmostEqual(
            bulk[0].score / bulk[1].score,
            ranking.ECONOMY_BULK_FACTOR / ranking.PREMIUM_BULK_FACTOR,
        )

    def test_a_price_above_the_cheap_threshold_is_not_an_economy_model(self):
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
        quality = bulk["kimi-k2"].quality
        self.assertEqual(quality, bulk["kimi-k3"].quality)
        # Without a quota window the capacity is unknown, so it earns no
        # bonus: an unknown allowance is never treated as headroom.
        self.assertAlmostEqual(
            bulk["kimi-k2"].score, quality * ranking.PREMIUM_BULK_FACTOR
        )
        self.assertAlmostEqual(
            bulk["kimi-k3"].score, quality * ranking.ECONOMY_BULK_FACTOR
        )

    def test_a_promotional_free_model_leads_the_bulk_tier(self):
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
        ranked = ranking.rank_models(
            models=[
                ranking.ModelRecord("opencode-go", "minimax-m3.1-flash-free"),
                ranking.ModelRecord("opencode-go", "deepseek-v4-pro"),
            ],
            catalog=catalog,
            quota_windows={},
            free_models={("opencode-go", "minimax-m3.1-flash-free")},
            usage_tokens={},
            now=NOW,
        )
        bulk = tier_members(ranked, "bulk")
        self.assertEqual(bulk[0].model, "minimax-m3.1-flash-free")


class RecencyBonusTests(unittest.TestCase):
    """A brand new model is worth a little more."""

    def quality_of(self, released):
        catalog = make_catalog(
            {
                "google": {
                    "models": {
                        "gemini-3.8-pro": entry(
                            "gemini-3.8-pro", "gemini", released=released
                        )
                    }
                }
            }
        )
        ranked = ranking.rank_models(
            models=[ranking.ModelRecord("antigravity", "gemini-3.8-pro")],
            catalog=catalog,
            quota_windows={},
            free_models=set(),
            usage_tokens={},
            now=NOW,
        )
        found = [item for item in ranked if item.model == "gemini-3.8-pro"]
        self.assertTrue(found)
        return found[0].quality

    def test_a_model_released_today_scores_higher_than_one_released_a_year_ago(self):
        today = self.quality_of("2025-10-09")
        a_year_ago = self.quality_of("2024-10-09")
        self.assertGreater(today, a_year_ago)
        # A model of the last month gains three, a model of last year loses
        # fifteen.
        self.assertAlmostEqual(today - a_year_ago, 18.0)

    def test_the_bonus_reaches_the_free_tier(self):
        catalog = make_catalog(
            {
                "opencode-go": {
                    "models": {
                        "minimax-m3.1-flash-free": entry(
                            "minimax-m3.1-flash-free",
                            "minimax",
                            released="2025-10-01",
                            cost={"input": 0, "output": 0},
                        ),
                        "minimax-m3.1-flash": entry(
                            "minimax-m3.1-flash",
                            "minimax",
                            released="2025-01-01",
                            cost={"input": 0, "output": 0},
                        ),
                    }
                }
            }
        )
        ranked = ranking.rank_models(
            models=[
                ranking.ModelRecord("opencode-go", "minimax-m3.1-flash-free"),
                ranking.ModelRecord("opencode-go", "minimax-m3.1-flash"),
            ],
            catalog=catalog,
            quota_windows={},
            free_models={
                ("opencode-go", "minimax-m3.1-flash-free"),
                ("opencode-go", "minimax-m3.1-flash"),
            },
            usage_tokens={},
            now=NOW,
        )
        free = tier_members(ranked, "free")
        self.assertEqual(free[0].model, "minimax-m3.1-flash-free")


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
                "score": 0.5 + number / 100.0,
                "usage_tokens": 0,
                "eligible": True,
            }
        self.catalog = make_catalog({"printer": {"models": models}})
        self.models = records
        self.three_d = three_d

    def rank(self):
        return ranking.rank_models(
            models=self.models,
            catalog=self.catalog,
            quota_windows={},
            free_models=set(),
            usage_tokens={},
            three_d_scores=self.three_d,
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

    def test_a_model_window_replaces_the_account_window(self):
        ranked = self.rank()
        found = {
            item.model: item
            for item in ranked
            if item.model in ("gemini-3.8-pro", "gemini-3.8-flash")
        }
        # The model window is the precise one, so it wins over the shared
        # family window.
        self.assertAlmostEqual(found["gemini-3.8-pro"].remaining, 0.9)
        # The other model of the account keeps the account window.
        self.assertAlmostEqual(found["gemini-3.8-flash"].remaining, 0.1)

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
