"""The Go free routes, and the paid allowance that must not bind them.

The Go documentation lists the free routes of the subscription as unlimited,
and a live probe confirmed it: a free route answered while the paid monthly
window of the plan was spent. The free routes arrive in the collector from
two places, the live instance inventory and the catalog's free list, and a
route on either path is a free route.

The status of a window is the provider's own statement about it ("ok" or
"rate-limited"). It reaches the account section of the routing snapshot, so
a consumer reads the Go monthly state the usage endpoint reported.

The tests drive the real ranking inputs, the real ranking and the real
snapshot builder. A helper-only test would pass while routing.json is wrong.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage" / "collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


metrics = load("go_free_routes_metrics", "metrics.py")
main = load("go_free_routes_main", "main.py")
catalog_module = load("go_free_routes_catalog", "catalog.py")
ranking = load("go_free_routes_ranking", "ranking.py")
snapshot = load("go_free_routes_snapshot", "snapshot.py")
providers = load("go_free_routes_providers", "providers.py")
published = load("go_free_routes_published", "published.py")

NOW = 1_800_000_000.0
DAY = 86400.0

POLICY = {
    "frontierPrimeModels": (),
    "allowedGptModels": (),
    "backgroundProviderInstances": (),
}

CATALOG = {
    "opencode-go": {
        "models": {
            # The two free routes of the live Go account. The catalog lists
            # both of them at no cost.
            "cat-jam-free": {
                "name": "Cat Jam Free",
                "cost": {"input": 0, "output": 0},
            },
            "step-5-preview-free": {
                "name": "Step 5 Preview Free",
                "cost": {"input": 0, "output": 0},
            },
            # A free route the live instance also offers.
            "beam-free": {
                "name": "Beam Free",
                "cost": {"input": 0, "output": 0},
            },
            # A paid route of the same subscription.
            "glm-5.3": {
                "name": "GLM 5.3",
                "cost": {"input": 1.0, "output": 3.0},
            },
            # A route whose name says free while the catalog prices it.
            "trap-free": {
                "name": "Trap Free (a paid route)",
                "cost": {"input": 1.0, "output": 3.0},
            },
        }
    },
    "openrouter": {
        "models": {
            "cohere/north-mini-code:free": {
                "name": "North Mini Code (free)",
                "cost": {"input": 0, "output": 0},
            }
        }
    },
}

ALLOWANCE_QUOTAS = {
    "go_rolling",
    "go_weekly",
    "go_monthly",
    "rolling",
    "weekly",
    "monthly",
}


def spent_go_monthly():
    """The paid monthly window of the Go account, spent."""
    return {
        "provider": "opencode-go",
        "account": "default",
        "model": "*",
        "kind": "monthly",
        "quotaId": "go_monthly",
        "usedRatio": 1.0,
        "resetEpoch": NOW + 10 * DAY,
        "durationSeconds": 30 * DAY,
        "source": "t3",
        "observedAtEpoch": NOW,
    }


def spent_openrouter_daily():
    """The daily allowance of the OpenRouter free models, spent."""
    return {
        "provider": "openrouter",
        "account": "default",
        "model": "*",
        "kind": "daily",
        "quotaId": "free-models-per-day",
        "usedRatio": 1.0,
        "resetEpoch": NOW + DAY,
        "durationSeconds": DAY,
        "source": "openrouter",
        "observedAtEpoch": NOW,
        "basis": "provider_reported",
    }


class SnapshotFixture:
    """The real pipeline of one reading: inputs, ranking and snapshot."""

    def build(self, offered, measured):
        """The ranking inputs, the ranking and the snapshot of one reading."""
        catalog = catalog_module.Catalog(CATALOG)
        offered = list(offered)
        samples = main.free_model_samples(catalog, offered, (), NOW)
        results = [
            metrics.SourceResult(
                source="model_catalog",
                status="ok",
                metrics=samples,
                observed_at=NOW,
            )
        ]
        context = {"offered_models": offered}
        inputs = main.ranking_inputs(results, catalog, context, measured, now=NOW)
        ranked = ranking.rank_models(
            models=[
                ranking.ModelRecord(provider, model)
                for provider, model in inputs["inventory"]
            ],
            catalog=catalog,
            quota_windows=inputs["windows"],
            free_models=inputs["free"],
            promo_models=inputs["promo"],
            external_availability=inputs["external"],
            usage_tokens=inputs["usage"],
            now=NOW,
        )
        data = snapshot.build_snapshot(
            now=NOW,
            sources=[],
            ranked=ranked,
            native_models={},
            policy=POLICY,
            measured_windows=measured,
            catalog=catalog,
            facts={},
            free_models=inputs["free"],
            promo_models=inputs["promo"],
        )
        return inputs, data

    def rows(self, data):
        return {
            (row["provider"], row["model"]): row for row in data["candidates"]
        }


class GoFreeRouteCase(unittest.TestCase, SnapshotFixture):
    """The free route keeps its own capacity, whatever the account spent."""

    def test_a_free_route_outside_the_inventory_keeps_the_free_capacity(self):
        # The route reaches the ranking through the catalog's free list, not
        # through the instance inventory, and that is still the same route.
        inputs, data = self.build([], [spent_go_monthly()])
        rows = self.rows(data)
        for model in ("cat-jam-free", "step-5-preview-free"):
            with self.subTest(model=model):
                window = inputs["windows"][f"opencode-go/{model}"][0]
                self.assertEqual(window.quota_id, published.UNLIMITED_QUOTA_ID)
                self.assertEqual(window.kind, "unlimited")
                row = rows[("opencode-go", model)]
                self.assertEqual(row["quota_state"], "available")
                self.assertEqual(
                    row["capacity"]["capacity_binding"]["quota"],
                    published.UNLIMITED_QUOTA_ID,
                )

    def test_a_free_route_in_the_inventory_keeps_the_free_capacity(self):
        # beam-free is offered by the live instance. Its capacity is unchanged
        # by the fix: it was already exempt from the paid allowance.
        inputs, data = self.build(
            [("opencode-go", "beam-free")], [spent_go_monthly()]
        )
        window = inputs["windows"]["opencode-go/beam-free"][0]
        self.assertEqual(window.quota_id, published.UNLIMITED_QUOTA_ID)
        row = self.rows(data)[("opencode-go", "beam-free")]
        self.assertEqual(row["quota_state"], "available")
        self.assertEqual(
            row["capacity"]["capacity_binding"]["quota"],
            published.UNLIMITED_QUOTA_ID,
        )

    def test_a_paid_route_stays_bound_by_the_paid_allowance(self):
        # A paid route, and a "-free"-named route the catalog prices, are not
        # the routes the Go documentation lists as unlimited.
        _inputs, data = self.build(
            [("opencode-go", "glm-5.3"), ("opencode-go", "trap-free")],
            [spent_go_monthly()],
        )
        rows = self.rows(data)
        for model in ("glm-5.3", "trap-free"):
            with self.subTest(model=model):
                row = rows[("opencode-go", model)]
                self.assertEqual(row["quota_state"], "exhausted")
                self.assertEqual(
                    row["capacity"]["capacity_binding"]["quota"], "go_monthly"
                )

    def test_an_openrouter_free_route_is_still_gated_by_its_daily_allowance(self):
        # The OpenRouter daily allowance is the free allowance itself, and it
        # is not a Go paid allowance: no unlimited window belongs to it.
        inputs, data = self.build([], [spent_openrouter_daily()])
        route = ("openrouter", "cohere/north-mini-code:free")
        self.assertNotIn(f"openrouter/{route[1]}", inputs["windows"])
        row = self.rows(data)[route]
        self.assertEqual(row["quota_state"], "exhausted")
        self.assertEqual(
            row["capacity"]["capacity_binding"]["quota"], "free-models-per-day"
        )


class GoWindowStatusTests(unittest.TestCase):
    """The status the usage endpoint reports reaches the routing snapshot."""

    def read(self, usage):
        with tempfile.TemporaryDirectory() as home:
            share = Path(home) / ".local" / "share" / "opencode"
            share.mkdir(parents=True)
            (share / "auth.json").write_text(
                json.dumps({"opencode-go": {"type": "api", "key": "test-key"}}),
                encoding="utf-8",
            )

            class Response:
                ok = True
                status = 200

                def json(self):
                    return {"usage": usage}

            return providers.read_opencode_go(
                home,
                NOW,
                http=lambda url, **kwargs: Response(),
            )

    def test_the_status_of_each_go_window_reaches_the_account_section(self):
        result = self.read(
            {
                "rolling": {"percent": 10, "status": "ok"},
                "weekly": {"percent": 20},
                "monthly": {"percent": 100, "status": "rate-limited"},
            }
        )
        data = snapshot.build_snapshot(
            now=NOW,
            sources=[],
            ranked=[],
            native_models={},
            policy=POLICY,
            measured_windows=result.windows,
            facts={},
        )
        records = {
            record["quota_id"]: record
            for record in data["quota"]["accounts"]["opencode-go"]
        }
        self.assertEqual(records["rolling"]["status"], "ok")
        self.assertEqual(records["monthly"]["status"], "rate-limited")
        # A window whose provider published no status carries no status key.
        self.assertNotIn("status", records["weekly"])


class GoFreeRouteGuardTests(unittest.TestCase, SnapshotFixture):
    """OpenCode Go is a paid subscription: no Go route is ever free or promotional."""

    def test_every_go_route_is_a_subscription_even_when_the_catalog_lists_a_zero_price(self):
        _inputs, data = self.build([], [spent_go_monthly()])
        routes = [row for row in data["candidates"] if row["provider"] == "opencode-go"]
        self.assertTrue(routes, "the fixture must hold Go routes")
        self.assertIn("cat-jam-free", {row["model"] for row in routes})
        for row in routes:
            with self.subTest(model=row["model"]):
                self.assertEqual((row.get("access") or {}).get("billing"), "subscription")


if __name__ == "__main__":
    unittest.main()
