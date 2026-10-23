"""The order of the tiers: the trust of a model, and the outcome it is worth.

The Providers page shows the tiers in the order the snapshot holds them, so
the order is a decision and not a display. A trusted route leads a tier, a
backup route follows it, an untrusted route comes last with the reason it
holds, and the value that decides the rest is the outcome-weighted value:
the measured intelligence inside the tier, shrunk toward the rounds that
were actually observed, and scaled by the trust of the model.

Every test here is synthetic. The Artificial Analysis records, the model
identities, the owner's trust and the rounds of the delegation ledger are
built inside the test, and no host, no provider and no real ledger is read.
"""

import inspect
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage/collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
import ranking  # noqa: E402
import snapshot  # noqa: E402
import value_policy  # noqa: E402

NOW = 1_800_000_000.0
DAY = 86_400.0

# The owner's direction, as the policy carries it.
OWNER = {
    "frontierPrimeModels": ("gpt-6.1-sol", "claude-opus-5-5"),
    "allowedGptModels": ("gpt-6.1-sol",),
    "backgroundProviderInstances": ("opencode",),
}

# The model identities: which routes serve one model. The trust of a model
# is read for its identity, not for the route that serves it.
IDENTITIES = {
    "schema": "ghostship.model-identities/v1",
    "models": {
        "deepseek-v4.1-flash-1017": {
            "label": "DeepSeek V4.1 Flash 1017",
            "routes": ["ollama-cloud/deepseek-v4.1-flash:1017"],
        },
        "minimax-m3.1-flash": {
            "label": "MiniMax M3.1 Flash",
            "routes": [
                "ollama-cloud/minimax-m3.1-flash",
                "opencode-go/minimax-m3.1-flash-free",
            ],
        },
        "beam": {
            "label": "Beam",
            "routes": ["opencode-go/beam-free"],
        },
        "gemini-3.8-flash": {
            "label": "Gemini 3.8 Flash",
            "routes": ["antigravity/gemini-3.8-flash"],
        },
        "claude-haiku-5-5": {
            "label": "Claude Haiku 5.5",
            "routes": ["claudeAgent/claude-haiku-5-5"],
        },
    },
}

# The owner's trust, as the runtime policy carries it.
TRUST = {
    "model_trust": {
        "entries": [
            {
                "model": "beam",
                "level": "untrusted",
                "task_types": ["implementation"],
                "reason": (
                    "placeholder tests reported as passing, and existing tests "
                    "listed as new coverage"
                ),
                "evidence": [
                    {
                        "date": "2026-10-22",
                        "source": "ghostship-config#211",
                        "task_type": "implementation",
                        "caught_by_review": True,
                    }
                ],
            },
            {
                "model": "gemini-3.8-flash",
                "level": "untrusted",
                "task_types": ["implementation", "cad-execution"],
                "reason": (
                    "reported a zero-overlap check its own render contradicts"
                ),
                "evidence": [
                    {
                        "date": "2026-10-22",
                        "source": "3D door-seal round 2",
                        "task_type": "cad-execution",
                        "caught_by_review": True,
                    }
                ],
            },
            {
                "model": "claude-haiku-5-5",
                "level": "backup",
                "task_types": ["*"],
                "reason": (
                    "owner: a backup route, used only when every other route "
                    "for the task is exhausted or unavailable"
                ),
                "evidence": [],
            },
        ]
    }
}


class Catalog:
    """The public catalog of the providers the tests use."""

    def __init__(self, entries):
        self.entries = dict(entries)
        self.document = {}
        for (provider, model), entry in self.entries.items():
            models = self.document.setdefault(provider, {"models": {}})["models"]
            models[model] = entry

    def model_entry(self, provider, model):
        return self.entries.get((provider, model))

    def price_for(self, provider, model):
        entry = self.model_entry(provider, model)
        return entry["cost"] if entry else None

    def model_name(self, provider, model):
        entry = self.model_entry(provider, model)
        return entry["name"] if entry else model

    def release_date(self, provider, model):
        entry = self.model_entry(provider, model)
        return entry.get("release_date") if entry else None


class Route:
    """One route of the test: a provider, a model and what was measured."""

    def __init__(
        self,
        provider,
        model,
        intelligence,
        cost=0.2,
        pace=None,
        free=False,
        retired=False,
    ):
        self.provider = provider
        self.model = model
        self.intelligence = intelligence
        self.cost = cost
        self.pace = pace
        self.free = free
        self.retired = retired

    @property
    def key(self):
        return f"{self.provider}:{self.model}"


def window_for(pace):
    """A window whose pace is the number asked for.

    The pace compares the measured usage of a window with the line the
    window of that length draws by now. The window below is half spent at
    the half of its life, and the share it has used is what makes the pace
    the number the test asks for.
    """
    duration = 100.0
    reset = NOW + 50.0
    expected = (NOW - (reset - duration)) / duration
    used = min(1.0, max(0.0, expected - pace))
    return ranking.QuotaWindow(
        kind="weekly",
        used_ratio=used,
        reset_epoch=reset,
        duration_seconds=duration,
        observed_at=NOW,
        basis=ranking.BASIS_REPORTED,
    )


def rounds_for(model, total, accepted, task_type="implementation"):
    """The rounds of a model: `total` rounds, `accepted` of them accepted."""
    rounds = []
    for index in range(total):
        verdict = "accepted" if index < accepted else "rejected"
        rounds.append(
            {
                "round_id": f"{model}-{index}",
                "model": model,
                "task_type": task_type,
                "verdict": verdict,
                "verdict_source": "ledger",
                "cause": "",
                "fabrication": 0,
                "started_at": "2026-10-20T10:00:00Z",
            }
        )
    return rounds


def aa_record(route):
    """The Artificial Analysis record of one route."""
    return {
        "id": f"id-{route.provider}-{route.model}",
        "slug": route.model,
        "model": route.model,
        "release_date": "2026-12-01",
        "indices": {"intelligence_index": route.intelligence},
        "cost_per_task": route.cost,
        "median_performance": 100.0,
        "prices": {},
    }


def build(
    routes,
    *,
    rounds=(),
    trust=TRUST,
    identities=IDENTITIES,
):
    """The routing snapshot of the given routes."""
    feed = {
        "status": "ok",
        "index_version": "4.3",
        "fetched_at": "2026-01-20T00:00:00Z",
        "fetched_at_epoch": NOW,
        "records": [aa_record(route) for route in routes],
    }
    catalog = Catalog(
        {
            (route.provider, route.model): {
                "name": route.model,
                "family": "test",
                "release_date": "2026-12-01",
                "cost": {"input": 0.0 if route.free else 1.0, "output": 0.0},
            }
            for route in routes
        }
    )
    windows: dict[str, list] = {}
    for route in routes:
        if route.pace is None:
            continue
        windows.setdefault(route.provider, []).append(window_for(route.pace))
    native = {
        (route.provider, route.model): {
            "providerInstance": "opencode",
            "modelId": route.model,
            "options": [],
        }
        for route in routes
    }
    free_pairs = {(route.provider, route.model) for route in routes if route.free}
    retired = {
        f"{route.provider}/{route.model}": {
            "route": f"{route.provider}/{route.model}",
            "provider": route.provider,
            "model": route.model,
            "first_seen": NOW - DAY,
        }
        for route in routes
        if route.retired
    }
    ranked = ranking.rank_models(
        models=[
            ranking.ModelRecord(route.provider, route.model) for route in routes
        ],
        catalog=catalog,
        quota_windows=windows,
        free_models=free_pairs,
        promo_models=set(),
        usage_tokens={},
        aa_cache=feed,
        native_models=native,
        retired_routes=retired,
        now=NOW,
    )
    # The outcomes are read by the snapshot that knows them. A snapshot that
    # does not know them yet is the one this test is written against, and
    # the test fails on the order it pins, not on a missing argument.
    extra = {}
    if "outcomes" in inspect.signature(snapshot.build_snapshot).parameters:
        extra["outcomes"] = {
            "identities": identities,
            "policy": trust,
            "rounds": list(rounds),
            "backfill": [],
        }
    return snapshot.build_snapshot(
        now=NOW,
        sources=[
            {"id": "t3", "status": "ok", "reason": "ok", "observed_at_epoch": NOW}
        ],
        ranked=ranked,
        native_models=native,
        policy=OWNER,
        aa_cache=feed,
        catalog=catalog,
        facts={},
        free_models=free_pairs,
        promo_models=set(),
        **extra,
    )


def bulk_winners(data):
    """The bulk tier, in the order the snapshot holds it."""
    return [winner["key"] for winner in data["tier_winners"]["worker"]]


def row_of(data, key):
    """The candidate row of one route."""
    for row in data["candidates"]:
        if f"{row['provider']}:{row['model']}" == key:
            return row
    raise AssertionError(f"no candidate row for {key}")


def winner_of(data, key):
    """The winner row of one route."""
    for tier in data["tier_winners"].values():
        for winner in tier:
            if winner["key"] == key:
                return winner
    raise AssertionError(f"no winner row for {key}")


class TrustOrderTests(unittest.TestCase):
    """The trust of a model decides the order of a tier."""

    def test_a_trusted_model_leads_and_an_untrusted_one_comes_last(self):
        routes = [
            Route("ollama", "deepseek-v4.1-flash:1017", 45.1, pace=-0.03),
            Route("opencode-go", "beam-free", 30.0, cost=0.0, free=True),
            Route("antigravity", "gemini-3.8-flash", 30.0),
            Route("claude", "claude-haiku-5-5", 41.2),
        ]
        data = build(routes)
        order = bulk_winners(data)
        # The trusted route leads, the backup route follows it, and the two
        # untrusted routes come last.
        self.assertEqual(order[0], "ollama:deepseek-v4.1-flash:1017")
        self.assertEqual(order[1], "claude:claude-haiku-5-5")
        self.assertEqual(
            sorted(order[2:]),
            ["antigravity:gemini-3.8-flash", "opencode-go:beam-free"],
        )

    def test_the_untrusted_route_keeps_half_of_its_value_and_its_reason(self):
        routes = [
            Route("ollama", "deepseek-v4.1-flash:1017", 45.1, pace=-0.03),
            Route("opencode-go", "beam-free", 30.0, cost=0.0, free=True),
        ]
        data = build(routes)
        winner = winner_of(data, "opencode-go:beam-free")
        outcome = row_of(data, "opencode-go:beam-free")["outcome"]["worker"]
        # The reason is the reason of the owner's policy.
        self.assertEqual(
            winner["trust_reason"],
            "placeholder tests reported as passing, and existing tests listed "
            "as new coverage",
        )
        self.assertEqual(winner["trust_level"], "untrusted")
        # The published value is half of the outcome value.
        self.assertAlmostEqual(winner["value"], outcome["value"] * 0.5, places=9)
        self.assertAlmostEqual(
            winner["value"], outcome["value"] * value_policy.UNTRUSTED_VALUE_FACTOR, places=9
        )

    def test_a_route_with_no_window_does_not_lead_a_known_pace(self):
        # A route with no window has no pace. It is not a pace of zero: it
        # waits behind every route that has one. The two routes are worth
        # the same, so the pace is what decides.
        routes = [
            Route("ollama", "deepseek-v4.1-flash:1017", 45.1, pace=-0.03),
            Route("openrouter", "some-model", 45.1),
        ]
        data = build(routes)
        order = bulk_winners(data)
        self.assertEqual(order[0], "ollama:deepseek-v4.1-flash:1017")
        self.assertEqual(order[1], "openrouter:some-model")


class OutcomeValueTests(unittest.TestCase):
    """The outcome-weighted value picks the winner of a provider."""

    ROUTES = [
        Route("ollama", "minimax-m3.1-flash", 42.7),
        Route("ollama", "deepseek-v4.1-flash:1017", 45.1),
        # The model at the bottom of the range of the tier, so the prior of
        # the two models above it is read inside that range.
        Route("antigravity", "gemini-3.8-flash", 24.7),
    ]

    def test_a_model_without_an_observed_round_leads_its_provider(self):
        rounds = rounds_for("ollama-cloud/minimax-m3.1-flash", 148, 104)
        data = build(self.ROUTES, rounds=rounds)
        # The prior of the two models of the provider is read inside the
        # range of the tier: 24.7 to 45.1.
        row = row_of(data, "ollama:deepseek-v4.1-flash:1017")
        self.assertAlmostEqual(row["outcome"]["worker"]["i_min"], 24.7, places=6)
        self.assertAlmostEqual(row["outcome"]["worker"]["i_max"], 45.1, places=6)
        self.assertAlmostEqual(row["outcome"]["worker"]["p0"], 0.9, places=6)
        # The model with no observed round keeps its prior, and it is worth
        # more than the model whose rounds were observed.
        self.assertEqual(row["outcome"]["worker"]["n"], 0)
        self.assertEqual(row["outcome"]["worker"]["s"], 0)
        self.assertAlmostEqual(row["outcome"]["worker"]["p"], 0.9, places=6)
        self.assertEqual(
            [key for key in bulk_winners(data) if key.startswith("ollama:")],
            ["ollama:deepseek-v4.1-flash:1017"],
        )

    def test_the_observed_rounds_of_a_model_can_win_its_provider(self):
        rounds = rounds_for("ollama-cloud/minimax-m3.1-flash", 148, 104)
        rounds += rounds_for("ollama-cloud/deepseek-v4.1-flash:1017", 173, 106)
        data = build(self.ROUTES, rounds=rounds)
        row = row_of(data, "ollama:deepseek-v4.1-flash:1017")
        self.assertEqual(row["outcome"]["worker"]["n"], 173)
        self.assertEqual(row["outcome"]["worker"]["s"], 106)
        self.assertAlmostEqual(row["outcome"]["worker"]["p"], 115 / 183, places=6)
        # The observed rounds shrink the quality of the model below the
        # quality of the model that was not measured, and the other model of
        # the provider wins it.
        self.assertEqual(
            [key for key in bulk_winners(data) if key.startswith("ollama:")],
            ["ollama:minimax-m3.1-flash"],
        )


class FreeRouteOrderTests(unittest.TestCase):
    """A free route leads the bulk tier while it is close enough."""

    ROUTES = [
        Route("opencode-go", "minimax-m3.1-flash-free", 42.7, cost=0.0, free=True),
        Route("ollama", "deepseek-v4.1-flash:1017", 45.1),
        Route("antigravity", "gemini-3.8-flash", 24.7),
    ]

    def test_a_free_route_leads_the_bulk_tier_while_it_is_close_enough(self):
        data = build(self.ROUTES)
        free = row_of(data, "opencode-go:minimax-m3.1-flash-free")
        paid = row_of(data, "ollama:deepseek-v4.1-flash:1017")
        # The free route is behind the paid one, but not by more than the
        # margin of the policy.
        self.assertAlmostEqual(free["outcome"]["worker"]["p"], 0.8529, places=4)
        self.assertAlmostEqual(paid["outcome"]["worker"]["p"], 0.9, places=6)
        self.assertLessEqual(
            paid["outcome"]["worker"]["p"] - free["outcome"]["worker"]["p"],
            value_policy.FREE_ROUTE_MARGIN,
        )
        self.assertEqual(bulk_winners(data)[0], "opencode-go:minimax-m3.1-flash-free")

    def test_a_retired_free_route_holds_no_tier_at_all(self):
        routes = [
            Route(
                "opencode-go",
                "minimax-m3.1-flash-free",
                42.7,
                cost=0.0,
                free=True,
                retired=True,
            ),
            self.ROUTES[1],
            self.ROUTES[2],
        ]
        data = build(routes)
        self.assertNotIn("opencode-go:minimax-m3.1-flash-free", data["tiers"]["worker"])
        self.assertNotIn(
            "opencode-go:minimax-m3.1-flash-free",
            [winner["key"] for winner in data["tier_winners"]["worker"]],
        )


class FreeRouteMarginTests(unittest.TestCase):
    """The margin of a free route is read from the best route of its level."""

    def test_a_free_route_far_behind_the_best_route_does_not_lead(self):
        # Catches a margin measured from the best paid route only: beta-free
        # is within the margin of the best paid route (gamma) but far behind
        # the best route of its trust level (alpha-free), so gamma leads it.
        routes = [
            Route("opencode-go", "alpha-free", 45.0, free=True),
            Route("openrouter", "beta:free", 35.0, free=True),
            Route("ollama", "gamma", 37.5),
            Route("claude", "low-anchor", 30.0),
        ]
        data = build(routes)
        self.assertAlmostEqual(row_of(data, "openrouter:beta:free")["outcome"]["worker"]["p"], 0.6333, places=4)
        self.assertAlmostEqual(row_of(data, "ollama:gamma")["outcome"]["worker"]["p"], 0.7, places=4)
        order = bulk_winners(data)
        self.assertEqual(order[0], "opencode-go:alpha-free")
        self.assertLess(order.index("ollama:gamma"), order.index("openrouter:beta:free"))


class NewRouteTests(unittest.TestCase):
    """A route that was never measured keeps the prior of its intelligence."""

    def test_a_new_route_with_no_observed_round_leads_the_bulk_tier(self):
        routes = [
            Route("ollama", "deepseek-v4.1-flash:1017", 45.1),
            Route("antigravity", "gemini-3.8-flash", 24.7),
            Route("ollama", "a-brand-new-model", 50.0),
        ]
        data = build(routes)
        row = row_of(data, "ollama:a-brand-new-model")
        self.assertAlmostEqual(row["outcome"]["worker"]["p0"], 0.9, places=6)
        self.assertEqual(row["outcome"]["worker"]["n"], 0)
        # The new route is the strongest of the tier, and it leads it.
        self.assertEqual(bulk_winners(data)[0], "ollama:a-brand-new-model")


class FrontierOrderTests(unittest.TestCase):
    """The frontier order does not change when no trust entry applies."""

    def test_the_frontier_order_is_the_pace_and_nothing_else(self):
        # No policy entry speaks about the two frontier models, so the
        # trust of the frontier changes nothing: the order is the pace of
        # the account window, exactly as it was.
        routes = [
            Route("codex", "gpt-6.1-sol", 60.0, pace=0.05),
            Route("claude", "claude-opus-5-5", 60.0, pace=-0.02),
        ]
        with_policy = build(routes, trust=TRUST)
        without_policy = build(routes, trust={})
        order = [
            winner["key"] for winner in with_policy["tier_winners"]["orchestrator"]
        ]
        self.assertEqual(order, ["codex:gpt-6.1-sol", "claude:claude-opus-5-5"])
        # The order is the same with a policy and without one: no trust
        # entry applies to these two models.
        self.assertEqual(
            order,
            [
                winner["key"]
                for winner in without_policy["tier_winners"]["orchestrator"]
            ],
        )


class OutcomeRecordTests(unittest.TestCase):
    """The candidate row publishes the trust and the outcome of a model."""

    def test_the_row_carries_the_trust_and_the_outcome_of_every_tier(self):
        routes = [
            Route("ollama", "deepseek-v4.1-flash:1017", 45.1, pace=-0.03),
            Route("claude", "claude-haiku-5-5", 41.2),
        ]
        data = build(routes)
        row = row_of(data, "claude:claude-haiku-5-5")
        trust = row["trust"]["worker"]
        self.assertEqual(trust["level"], "backup")
        self.assertEqual(trust["task_type"], "implementation")
        self.assertEqual(trust["source"], "policy")
        self.assertIn("backup route", trust["reason"])
        outcome = row["outcome"]["worker"]
        self.assertEqual(outcome["identity"], "claude-haiku-5-5")
        self.assertEqual(outcome["task_type"], "implementation")
        self.assertAlmostEqual(outcome["intelligence"], 41.2, places=6)
        self.assertEqual(outcome["k"], value_policy.OUTCOME_PRIOR_STRENGTH)
        self.assertEqual(outcome["n"], 0)
        self.assertEqual(outcome["s"], 0)
        # The Artificial Analysis value of the row is not the published
        # value: the published value is the outcome-weighted one.
        self.assertNotEqual(row["value"]["value"], row["outcome"]["worker"]["value"])
        winner = winner_of(data, "claude:claude-haiku-5-5")
        self.assertEqual(winner["value"], row["outcome"]["worker"]["published"])
        self.assertEqual(winner["value_aa"], row["value"]["value"])
        self.assertEqual(winner["trust_level"], "backup")
        self.assertEqual(winner["trust_reason"], trust["reason"])
        self.assertEqual(
            winner["outcome"],
            {
                "p0": outcome["p0"],
                "n": 0,
                "s": 0,
                "p": outcome["p"],
            },
        )


class MissingHistoryTests(unittest.TestCase):
    """A missing file is an empty history, and every model is trusted."""

    def test_a_model_without_a_policy_entry_and_without_a_fabrication_is_trusted(self):
        routes = [Route("ollama", "deepseek-v4.1-flash:1017", 45.1)]
        data = build(routes, trust={}, identities={})
        row = row_of(data, "ollama:deepseek-v4.1-flash:1017")
        self.assertEqual(row["trust"]["worker"]["level"], "trusted")
        self.assertEqual(row["trust"]["worker"]["source"], "default")
        self.assertEqual(row["outcome"]["worker"]["n"], 0)
        self.assertEqual(row["outcome"]["worker"]["s"], 0)


class PublishedGaugeTests(unittest.TestCase):
    """The trust and the outcome of a model are published as gauges."""

    def test_the_trust_and_the_outcome_are_published(self):
        routes = [
            Route("ollama", "deepseek-v4.1-flash:1017", 45.1, pace=-0.03),
            Route("claude", "claude-haiku-5-5", 41.2),
        ]
        data = build(routes)
        text = main.render([], [], NOW, 0.1, data)
        self.assertIn("# HELP ghostship_ai_model_trust_info", text)
        self.assertIn("# HELP ghostship_ai_model_outcome", text)
        # The trust of the route, with the level it holds and the reason it
        # holds it.
        self.assertIn(
            'ghostship_ai_model_trust_info{level="backup",model="claude-haiku-5-5",'
            'provider="claude",reason="owner:_a_backup_route__used_only_when_every_'
            'other_route_for_the_task_is_exhausted_or_unavailable",source="policy",'
            'task_type="implementation",tier="worker"} 1',
            text,
        )
        # The outcome of the route, field by field.
        for field, value in (("p0", "0.5"), ("k", "10"), ("n", "0"), ("s", "0"), ("p", "0.5")):
            self.assertIn(
                'ghostship_ai_model_outcome{field="'
                + field
                + '",model="claude-haiku-5-5",provider="claude",'
                'task_type="implementation",tier="worker"} '
                + value,
                text,
            )


class ExcludedTrustTests(unittest.TestCase):

    TRUST = {
        "model_trust": {
            "entries": [
                {
                    "model": "deepseek-v4.1-flash-1017",
                    "level": "excluded",
                    "task_types": ["implementation"],
                    "reason": "owner: the model is not used for this work",
                    "evidence": [],
                }
            ]
        }
    }

    def test_an_excluded_model_holds_no_tier_at_all(self):
        routes = [
            Route("ollama", "deepseek-v4.1-flash:1017", 45.1),
            Route("claude", "claude-haiku-5-5", 41.2),
        ]
        data = build(routes, trust=self.TRUST)
        row = row_of(data, "ollama:deepseek-v4.1-flash:1017")
        self.assertEqual(row["trust"]["worker"]["level"], "excluded")
        self.assertNotIn("ollama:deepseek-v4.1-flash:1017", data["tiers"]["worker"])
        self.assertNotIn(
            "ollama:deepseek-v4.1-flash:1017",
            [winner["key"] for winner in data["tier_winners"]["worker"]],
        )


if __name__ == "__main__":
    unittest.main()


class MainWiringTests(unittest.TestCase):
    """The collector reads the identities that ship beside the policy."""

    FIXTURES = Path(__file__).resolve().parent / "fixtures/ai-usage/outcomes"

    def test_the_identities_default_to_the_file_beside_the_policy(self):
        # Catches a default that computes the path and never uses it: with
        # no identities the routes of one model would not pool.
        policy = self.FIXTURES / "runtime-policy.json"
        path = main.model_identities_path("", str(policy))
        self.assertEqual(path, str(self.FIXTURES / "model-identities.json"))
        outcomes = main.read_outcomes(
            identities_path=path, runtime_policy=str(policy)
        )
        self.assertIn(
            "deepseek-v4.1-flash-1017",
            {record["id"] for record in outcomes["identities"]},
        )

    def test_a_named_identities_file_wins_and_none_reads_nothing(self):
        self.assertEqual(main.model_identities_path("other.json", "x/p.json"), "other.json")
        self.assertEqual(main.model_identities_path("", ""), "")


class ProviderReservationTests(unittest.TestCase):
    """A provider reserved for another workload is not a worker of a tier."""

    POLICY = dict(
        TRUST,
        provider_reservations=[
            {"provider": "claudeAgent", "workload": "review-roles", "status": "active"},
            {"provider": "grok", "workload": "3d", "status": "interim"},
            {"provider": "codex", "workload": "review-roles", "status": "released"},
        ],
    )

    ROUTES = [
        Route("claude", "claude-sonnet-5-5", 44.0, pace=0.2),
        Route("ollama", "minimax-m3.1-flash", 42.7, pace=-0.05),
        Route("opencode-go", "beam-free", 30.3, free=True),
        Route("codex", "gpt-6.1-sol", 47.8, pace=0.1),
    ]

    def test_a_reserved_provider_follows_every_unreserved_worker(self):
        # Catches the reservation being ignored: the review-role provider's
        # Sonnet outranked the bulk workers on value and pace.
        data = build(self.ROUTES, trust=self.POLICY)
        order = bulk_winners(data)
        self.assertLess(order.index("ollama:minimax-m3.1-flash"), order.index("claude:claude-sonnet-5-5"))
        # It stays ahead of an untrusted route, which is last in every tier.
        self.assertLess(order.index("claude:claude-sonnet-5-5"), order.index("opencode-go:beam-free"))
        winner = winner_of(data, "claude:claude-sonnet-5-5")
        self.assertEqual(winner["reserved_for"], "review-roles")

    def test_a_released_reservation_and_the_reserved_tier_are_unaffected(self):
        data = build(self.ROUTES, trust=self.POLICY)
        self.assertEqual(winner_of(data, "codex:gpt-6.1-sol")["reserved_for"], "")
        frontier = [w for w in data["tier_winners"].get("orchestrator", []) if w["provider"] == "claude"]
        for winner in frontier:
            self.assertEqual(winner["reserved_for"], "")
