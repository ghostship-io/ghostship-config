"""The tier names the redesigned pages read: worker and orchestrator.

The tiers were renamed for the redesigned pages: `bulk` is `worker`,
`frontier` is `orchestrator`, and `free` and `3d` stay as they were. For one
release every published name keeps its old name beside it, so the page
dashboard that still reads the old names keeps working.

The tests also pin the member position of every member of a tier, and the
reservation of a provider that is kept for another workload. Every test is
synthetic: no host, no provider and no real ledger is read.
"""

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage/collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ranking  # noqa: E402
import snapshot  # noqa: E402

NOW = 1_800_000_000.0

# The owner's direction, as the policy carries it.
OWNER = {
    "frontierPrimeModels": ("gpt-6.1-sol",),
    "allowedGptModels": ("gpt-6.1-sol",),
    "backgroundProviderInstances": ("opencode",),
    "provider_reservations": [
        {
            "provider": "claudeAgent",
            "workload": "review-roles",
            "status": "active",
        }
    ],
}

# The names a published tier may carry in this release: the canonical name
# and its old alias, and nothing else.
PUBLISHED_TIERS = {
    "orchestrator",
    "worker",
    "free",
    "3d",
    "frontier",
    "bulk",
}


class Catalog:
    """The public catalog of the providers the tests use."""

    def __init__(self, routes):
        self.entries = {
            (route["provider"], route["model"]): {
                "name": route["model"],
                "family": route.get("family") or "test",
                "release_date": "2026-12-01",
                "cost": {"input": 1.0, "output": 2.0},
            }
            for route in routes
        }
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


def aa_record(route):
    """The Artificial Analysis record of one route."""
    return {
        "id": f"id-{route['provider']}-{route['model']}",
        "slug": route["model"],
        "model": route["model"],
        "release_date": "2026-12-01",
        "indices": {"intelligence_index": route["intelligence"]},
        "cost_per_task": route.get("cost", 0.2),
        "median_performance": 100.0,
        "prices": {},
    }


def build(routes):
    """The routing snapshot of the given routes."""
    feed = {
        "status": "ok",
        "index_version": "4.3",
        "fetched_at": "2026-01-20T00:00:00Z",
        "fetched_at_epoch": NOW,
        "records": [aa_record(route) for route in routes],
    }
    catalog = Catalog(routes)
    native = {
        (route["provider"], route["model"]): {
            "providerInstance": "opencode",
            "modelId": route["model"],
            "options": [],
        }
        for route in routes
    }
    extra = {}
    if "frontier_workhorses" in inspect.signature(ranking.rank_models).parameters:
        extra["frontier_workhorses"] = ("gpt-6.1-sol",)
    ranked = ranking.rank_models(
        models=[
            ranking.ModelRecord(route["provider"], route["model"]) for route in routes
        ],
        catalog=catalog,
        quota_windows={},
        free_models=set(),
        promo_models=set(),
        usage_tokens={},
        aa_cache=feed,
        native_models=native,
        now=NOW,
        **extra,
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
        free_models=set(),
        promo_models=set(),
        outcomes={
            "identities": {},
            "policy": {
                "model_trust": {"entries": []},
                "provider_reservations": OWNER["provider_reservations"],
            },
            "rounds": [],
            "backfill": [],
        },
    )


def samples(data):
    """The decision samples of the snapshot, keyed by name and labels."""
    result = {}
    for name, labels, value in snapshot.decision_samples(data):
        result[(name, tuple(sorted(labels.items())))] = value
    return result


def positions(data, name):
    """The member positions of a published tier name, by route."""
    return {
        (dict(labels)["provider"], dict(labels)["model"]): value
        for (sample, labels), value in samples(data).items()
        if sample == "ghostship_ai_model_member_position"
        and dict(labels)["tier"] == name
    }


def workers():
    """The two members of the worker tier: one winner and one member."""
    return [
        {"provider": "ollama", "model": "minimax-m3.1-flash", "intelligence": 60.0},
        {
            "provider": "ollama",
            "model": "deepseek-v4.1-flash:1017",
            "intelligence": 45.0,
        },
    ]


def reserved():
    """An orchestrator route, and a worker route its provider is reserved for."""
    return [
        {"provider": "codex", "model": "gpt-6.1-sol", "intelligence": 58.0},
        {"provider": "claude", "model": "claude-sonnet-5", "intelligence": 55.0},
    ]


class TierNameTests(unittest.TestCase):
    """The canonical names, and the old ones beside them for one release."""

    def test_every_tier_keeps_its_old_name_with_the_same_content(self):
        data = build(workers() + reserved())
        for canonical, alias in (("worker", "bulk"), ("orchestrator", "frontier")):
            self.assertEqual(
                data["tier_winners"][canonical], data["tier_winners"][alias]
            )
            self.assertEqual(
                data["tier_members"].get(canonical),
                data["tier_members"].get(alias),
            )
            self.assertEqual(data["tiers"][canonical], data["tiers"][alias])
            self.assertEqual(
                data["coverage"]["tiers"][canonical],
                data["coverage"]["tiers"][alias],
            )

    def test_the_winner_position_is_published_under_both_names(self):
        data = build(workers())
        found = samples(data)
        canonical = [
            (labels, value)
            for (name, labels), value in found.items()
            if name == "ghostship_ai_model_winner_position"
            and dict(labels)["tier"] == "worker"
        ]
        alias = [
            (labels, value)
            for (name, labels), value in found.items()
            if name == "ghostship_ai_model_winner_position"
            and dict(labels)["tier"] == "bulk"
        ]
        self.assertTrue(canonical, "the worker winner position is published")

        def route(labels):
            found = dict(labels)
            return (
                found["provider"],
                found["model"],
                found.get("band", ""),
                value_of[labels],
            )

        value_of = dict(canonical + alias)
        self.assertEqual(
            sorted(route(labels) for labels, _value in canonical),
            sorted(route(labels) for labels, _value in alias),
        )

    def test_a_worker_winner_is_the_first_member_and_the_rest_follow(self):
        data = build(workers())
        # The order of the tier did not change: the value decides, and the
        # winner is the best value of its provider.
        self.assertEqual(
            data["tier_members"]["worker"],
            ["ollama:minimax-m3.1-flash", "ollama:deepseek-v4.1-flash:1017"],
        )
        by_route = positions(data, "worker")
        self.assertEqual(by_route[("ollama", "minimax-m3.1-flash")], 1.0)
        self.assertEqual(by_route[("ollama", "deepseek-v4.1-flash:1017")], 2.0)
        # The old name reads the same positions.
        self.assertEqual(positions(data, "bulk"), by_route)

    def test_a_member_reserved_for_another_workload_is_published_with_its_role(self):
        data = build(reserved())
        found = samples(data)
        reserved_for = {
            labels: value
            for (name, labels), value in found.items()
            if name == "ghostship_ai_model_reserved_for"
        }
        self.assertEqual(
            reserved_for[
                (
                    ("model", "claude-sonnet-5"),
                    ("provider", "claude"),
                    ("role", "review-roles"),
                    ("tier", "worker"),
                )
            ],
            1.0,
        )
        self.assertEqual(
            [
                labels
                for labels in reserved_for
                if dict(labels)["tier"] == "orchestrator"
            ],
            [],
        )

    def test_no_tier_is_named_activation_or_deploy(self):
        data = build(workers() + reserved())
        self.assertEqual(set(data["tiers"]), PUBLISHED_TIERS)
        self.assertEqual(set(data["tier_winners"]), PUBLISHED_TIERS)
        self.assertLessEqual(set(data["tier_members"]), PUBLISHED_TIERS)
        self.assertEqual(set(data["coverage"]["tiers"]), PUBLISHED_TIERS)
        for (name, labels), _value in samples(data).items():
            if "tier" in dict(labels):
                self.assertNotIn(dict(labels)["tier"], ("activation", "deploy"), name)

    def test_a_spent_member_is_last_and_a_winner_never_follows_a_non_winner(self):
        data = {
            "tier_members": {"worker": ["p:spent", "p:non", "p:winner"]},
            "tier_winners": {
                "worker": [{"provider": "p", "model": "winner", "key": "p:winner"}]
            },
            "candidates": [
                {
                    "provider": "p",
                    "model": "spent",
                    "availability": {"state": "unavailable"},
                    "quota_state": "exhausted",
                },
                {
                    "provider": "p",
                    "model": "non",
                    "availability": {"state": "available"},
                    "quota_state": "available",
                },
                {
                    "provider": "p",
                    "model": "winner",
                    "availability": {"state": "available"},
                    "quota_state": "available",
                },
            ],
        }
        self.assertEqual(
            snapshot._member_positions(data, "worker"),
            [("p:winner", 1), ("p:non", 2), ("p:spent", 3)],
        )

    def test_the_order_of_the_orchestrator_did_not_change(self):
        data = build(reserved())
        members = data["tier_members"]["orchestrator"]
        self.assertEqual(members, data["tier_members"]["frontier"])
        self.assertIn("codex:gpt-6.1-sol", members)
        # The orchestrator holds the owner's workhorse, and the worker holds
        # the route whose provider is reserved for the review.
        self.assertEqual(
            [winner["key"] for winner in data["tier_winners"]["orchestrator"]],
            [winner["key"] for winner in data["tier_winners"]["frontier"]],
        )
        self.assertIn(
            "claude:claude-sonnet-5", data["tier_members"]["worker"]
        )


if __name__ == "__main__":
    unittest.main()
