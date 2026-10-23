"""The pace state: the band of a route on the line of its own window.

The owner's rule is that a route whose binding window is more than twenty
points behind the pace goes to the back of the pool. The collector publishes
one state per route and per account window, and the Providers page colours
amber (behind) and red (far_behind, spent) from that state instead of
drawing its own band, so the page and the ranking cannot disagree.

The delta is the Paced Availability of the most constraining window in
points, the share left minus the expected share left, rounded to six
decimals only to remove the noise of the subtraction: 100 * (0.50 - 0.55) is
-5.000000000000004 and must read -5.

Every test here is synthetic. The Artificial Analysis records, the model
identities, the trust of the routes and the quota windows are built inside
the test, and no host, no provider and no real ledger is read.
"""

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

# The owner's direction, as the policy carries it.
OWNER = {
    "frontierPrimeModels": ("gpt-6.1-sol", "claude-opus-5-5"),
    "allowedGptModels": ("gpt-6.1-sol",),
    "backgroundProviderInstances": ("opencode",),
}

# The owner's trust, as the runtime policy carries it: the untrusted route is
# the one the "stays last" case needs.
TRUST = {
    "model_trust": {
        "entries": [
            {
                "model": "beam",
                "level": "untrusted",
                "task_types": ["implementation"],
                "reason": "placeholder tests reported as passing",
                "evidence": [],
            },
        ]
    }
}

IDENTITIES = {
    "schema": "ghostship.model-identities/v1",
    "models": {
        "beam": {
            "label": "Beam",
            "routes": ["opencode-go/beam-free"],
        },
    },
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

    def __init__(self, provider, model, intelligence, cost=0.2, pace=None, free=False):
        self.provider = provider
        self.model = model
        self.intelligence = intelligence
        self.cost = cost
        self.pace = pace
        self.free = free

    @property
    def key(self):
        return f"{self.provider}:{self.model}"


def window_for(pace):
    """A window whose Paced Availability is the number asked for.

    The line of the window is half of its life, and the share left is the
    line plus the pace: a positive pace is ahead of the line, a negative one
    is behind it.
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


def build(routes, *, trust=TRUST):
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
    windows = {}
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
        retired_routes={},
        now=NOW,
    )
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
        outcomes={
            "identities": IDENTITIES,
            "policy": trust,
            "rounds": [],
            "backfill": [],
        },
    )


def bulk_winners(data):
    """The bulk tier, in the order the snapshot holds it."""
    return [winner["key"] for winner in data["tier_winners"]["bulk"]]


def row_of(data, key):
    """The candidate row of one route."""
    for row in data["candidates"]:
        if f"{row['provider']}:{row['model']}" == key:
            return row
    raise AssertionError(f"no candidate row for {key}")


def winner_of(data, key):
    """The winner row of one route, from any tier."""
    for tier in data["tier_winners"].values():
        for winner in tier:
            if winner["key"] == key:
                return winner
    raise AssertionError(f"no winner row for {key}")


class PaceStateBandTests(unittest.TestCase):
    """The band of one window, at every edge the owner named."""

    def test_ahead_when_the_share_left_is_more_than_five_points_over_the_line(self):
        self.assertEqual(value_policy.pace_state(0.50, 0.40), "ahead")

    def test_on_pace_at_five_points_behind_the_line(self):
        # 100 * (0.50 - 0.55) is -5.000000000000004 in floating point, and the
        # six-decimal rounding is what makes it read -5 and not behind.
        self.assertEqual(value_policy.pace_state(0.50, 0.55), "on_pace")

    def test_behind_when_more_than_five_points_behind_the_line(self):
        self.assertEqual(value_policy.pace_state(0.50, 0.551), "behind")
        # The far edge of the band is still behind: -20 is not far behind.
        self.assertEqual(value_policy.pace_state(0.30, 0.50), "behind")

    def test_far_behind_beyond_twenty_points_behind_the_line(self):
        self.assertEqual(value_policy.pace_state(0.30, 0.501), "far_behind")

    def test_spent_when_nothing_is_left_whatever_the_line(self):
        self.assertEqual(value_policy.pace_state(0.0, 0.2), "spent")
        self.assertEqual(value_policy.pace_state(0.0, 0.0), "spent")

    def test_unknown_without_a_window_or_without_a_line(self):
        self.assertEqual(value_policy.pace_state(0.5, None), "unknown")
        self.assertEqual(value_policy.pace_state(None, 0.5), "unknown")


class PaceStateOrderTests(unittest.TestCase):
    """The far_behind route goes to the back of its trust group."""

    def test_a_far_behind_route_follows_an_on_pace_route_of_lower_value(self):
        # Route A is worth more (0.93 against 0.55) and is 25 points behind
        # its line; route B is on the pace and worth less. The owner's rule
        # puts B first.
        routes = [
            Route("ollama", "deepseek-v4.1-flash:1017", 50.0, cost=0.0, pace=-0.25),
            Route("openrouter", "slow-model", 30.0, cost=0.5, pace=0.0),
        ]
        data = build(routes, trust={})
        a = row_of(data, "ollama:deepseek-v4.1-flash:1017")
        b = row_of(data, "openrouter:slow-model")
        self.assertEqual(a["capacity"]["pace_state"], "far_behind")
        self.assertEqual(b["capacity"]["pace_state"], "on_pace")
        # A is worth more, so today's order alone would lead it.
        self.assertGreater(
            winner_of(data, "ollama:deepseek-v4.1-flash:1017")["value"],
            winner_of(data, "openrouter:slow-model")["value"],
        )
        order = bulk_winners(data)
        self.assertLess(order.index("openrouter:slow-model"), order.index("ollama:deepseek-v4.1-flash:1017"))

    def test_an_untrusted_route_stays_last_behind_a_trusted_far_behind_route(self):
        # The untrusted route is on the pace and the trusted one is far
        # behind. The far_behind element sits inside the trust group, so it
        # never lifts an untrusted route above a trusted one.
        routes = [
            Route("ollama", "deepseek-v4.1-flash:1017", 50.0, cost=0.0, pace=-0.25),
            Route("opencode-go", "beam-free", 30.0, cost=0.0, free=True, pace=0.0),
        ]
        data = build(routes)
        trusted = row_of(data, "ollama:deepseek-v4.1-flash:1017")
        untrusted = row_of(data, "opencode-go:beam-free")
        self.assertEqual(trusted["capacity"]["pace_state"], "far_behind")
        self.assertEqual(untrusted["capacity"]["pace_state"], "on_pace")
        self.assertEqual(untrusted["trust"]["bulk"]["level"], "untrusted")
        order = bulk_winners(data)
        self.assertLess(order.index("ollama:deepseek-v4.1-flash:1017"), order.index("opencode-go:beam-free"))
        self.assertEqual(order[-1], "opencode-go:beam-free")

    def test_a_behind_route_keeps_its_value_order_against_an_on_pace_route(self):
        # A route that is merely behind (15 points) is not moved: the more
        # valuable route still leads the less valuable one on the pace.
        routes = [
            Route("ollama", "deepseek-v4.1-flash:1017", 50.0, cost=0.0, pace=-0.15),
            Route("openrouter", "slow-model", 30.0, cost=0.5, pace=0.0),
        ]
        data = build(routes, trust={})
        a = row_of(data, "ollama:deepseek-v4.1-flash:1017")
        b = row_of(data, "openrouter:slow-model")
        self.assertEqual(a["capacity"]["pace_state"], "behind")
        self.assertEqual(b["capacity"]["pace_state"], "on_pace")
        self.assertGreater(
            winner_of(data, "ollama:deepseek-v4.1-flash:1017")["value"],
            winner_of(data, "openrouter:slow-model")["value"],
        )
        order = bulk_winners(data)
        self.assertLess(order.index("ollama:deepseek-v4.1-flash:1017"), order.index("openrouter:slow-model"))


class PaceStatePublicationTests(unittest.TestCase):
    """The state is published by the collector, so the page reads one band."""

    def test_every_candidate_row_and_winner_publishes_the_pace_state(self):
        routes = [
            Route("ollama", "deepseek-v4.1-flash:1017", 50.0, cost=0.0, pace=-0.25),
            Route("openrouter", "slow-model", 30.0, cost=0.5, pace=0.0),
        ]
        data = build(routes, trust={})
        row = row_of(data, "ollama:deepseek-v4.1-flash:1017")
        winner = winner_of(data, "ollama:deepseek-v4.1-flash:1017")
        self.assertEqual(row["capacity"]["pace_state"], "far_behind")
        self.assertEqual(winner["pace_state"], "far_behind")
        # The row's state is the band of the published number: the Paced
        # Availability in points, rounded only by its four decimals.
        self.assertEqual(
            value_policy.pace_state(
                row["capacity"]["remaining_ratio"],
                row["capacity"]["remaining_ratio"] - row["capacity"]["paced_availability"],
            ),
            row["capacity"]["pace_state"],
        )

    def test_every_account_window_publishes_its_pace_state(self):
        def window(quota_id, remaining, seconds, duration):
            return {
                "quota_id": quota_id,
                "kind": "weekly",
                "evidence": "provider_reported",
                "remaining_ratio": remaining,
                "seconds_to_reset": seconds,
                "duration_seconds": duration,
            }

        data = {
            "quota": {
                "accounts": {
                    "claude": [
                        window("ahead", 0.80, 40.0, 100.0),
                        window("behind", 0.30, 50.0, 100.0),
                        window("spent", 0.0, 50.0, 100.0),
                        window("unknown", 0.5, None, None),
                    ]
                },
                "provider_capacity": {},
            }
        }
        samples = snapshot.account_window_samples(data)
        states = {
            labels["quota_id"]: labels["state"]
            for name, labels, value in samples
            if name == "ghostship_ai_account_window_pace_state"
        }
        self.assertEqual(
            states,
            {
                "ahead": "ahead",
                "behind": "behind",
                "spent": "spent",
                "unknown": "unknown",
            },
        )
        for name, labels, value in samples:
            if name != "ghostship_ai_account_window_pace_state":
                continue
            self.assertEqual(value, 1.0)
            # The state carries the labels of the remaining series plus its
            # own state, and nothing else.
            self.assertEqual(
                set(labels),
                {"account", "kind", "quota_id", "label", "evidence", "state"},
            )
        self.assertIn("ghostship_ai_account_window_pace_state", main.METRIC_HELP)
        text = main.render([], [], NOW, 0.1, data)
        self.assertIn("# HELP ghostship_ai_account_window_pace_state ", text)


if __name__ == "__main__":
    unittest.main()
