"""The reason a route the free pool parked is unusable.

A free pool route the pool reports as unavailable reads `available: false` in
`routing.json`, and the reason used to be empty: the ranking says the route
is parked by its own source, but the snapshot rebuilt the reason from the
quota windows alone, and a route whose quota is available has no unknown
headroom to explain. The live example was the 23 candidates of the pool
providers that the Providers page could not explain.

The pool publishes no reason of its own. It marks a route unavailable for a
future cooldown, or when the account's policy does not let it serve
development work. The snapshot names the two: a route whose cooldown has not
run out says when it cools down, and a route without a cooldown says that
the pool does not offer it for development work.

The tests drive the real ranking inputs, the real ranking and the real
snapshot builder. A helper-only test would pass while routing.json is wrong.
"""

import importlib.util
import sys
import unittest
from datetime import datetime, timezone
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


metrics = load("pool_reason_metrics", "metrics.py")
main = load("pool_reason_main", "main.py")
catalog_module = load("pool_reason_catalog", "catalog.py")
ranking = load("pool_reason_ranking", "ranking.py")
snapshot = load("pool_reason_snapshot", "snapshot.py")

NOW = 1_800_000_000.0
HOUR = 3600.0
DAY = 86400.0

POLICY = {
    "frontierPrimeModels": (),
    "allowedGptModels": (),
    "backgroundProviderInstances": (),
}

# The free pool's own provider and the routes it serves. The names are
# invented: the test says what the pool says, not which route the pool
# happens to serve today.
POOL_PROVIDER = "example-pool"
COOLING_MODEL = "example-org/cooling-model:free"
PARKED_MODEL = "example-org/parked-model:free"
AVAILABLE_MODEL = "example-org/available-model:free"

# The other three kinds of unavailable route. They are the reasons the
# change must leave alone.
PAID_PROVIDER = "example-paid"
PAID_MODEL = "example-org/paid-model"
FREE_PROVIDER = "example-free"
FREE_MODEL = "example-org/retired-model:free"
FLAKY_PROVIDER = "example-flaky"
FLAKY_MODEL = "example-org/flaky-model"

# The label an observed failure of a route carries. It is the reason of a
# route that is not usable right now.
FAILURE_LABEL = "the route failed and is not usable right now"


def iso(epoch):
    """The UTC moment of an epoch, as the snapshot publishes it."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def catalog_document():
    """The catalog of the routes the test uses."""
    return {
        FREE_PROVIDER: {
            "models": {
                FREE_MODEL: {
                    "id": FREE_MODEL,
                    "name": "Retired Model",
                    "cost": {"input": 0, "output": 0},
                }
            }
        },
        PAID_PROVIDER: {
            "models": {
                PAID_MODEL: {
                    "id": PAID_MODEL,
                    "name": "Paid Model",
                    "cost": {"input": 1.0, "output": 3.0},
                }
            }
        },
    }


def window(provider, used_ratio):
    """The measured window of one account, at the given used share."""
    return {
        "provider": provider,
        "account": "default",
        "model": "*",
        "kind": "monthly",
        "quotaId": "monthly",
        "usedRatio": used_ratio,
        "resetEpoch": NOW + 10 * DAY,
        "durationSeconds": 30 * DAY,
        "source": "t3",
        "observedAtEpoch": NOW,
    }


def pool_samples(routes):
    """The pool's own readings of its routes.

    A route is a (provider, model, available, cooldown) tuple: whether the
    pool says the route can be used, and the moment its cooldown ends.
    """
    samples = []
    for provider, model, available, cooldown in routes:
        labels = {"provider": provider, "model": model}
        samples.append(
            (
                "ghostship_ai_pool_model_info",
                {
                    "provider": provider,
                    "model": model,
                    "family": "",
                    "developer_country": "",
                    "operator_country": "",
                },
                1.0,
            )
        )
        samples.append(
            (
                "ghostship_ai_pool_model_available",
                labels,
                1.0 if available else 0.0,
            )
        )
        if cooldown is not None:
            samples.append(
                (
                    "ghostship_ai_pool_model_cooldown_until_seconds",
                    labels,
                    float(cooldown),
                )
            )
    return samples


class SnapshotFixture:
    """The real pipeline of one reading: inputs, ranking and snapshot."""

    def build(self, *, pool_routes=(), offered=(), measured=(), failures=()):
        catalog = catalog_module.Catalog(catalog_document())
        samples = list(pool_samples(pool_routes))
        # The free list of the catalog: a route the instance does not offer.
        samples.append(
            (
                "ghostship_ai_free_model",
                {
                    "provider": FREE_PROVIDER,
                    "model": FREE_MODEL,
                    "tier": "free_tier",
                    "source": "model_catalog",
                },
                1.0,
            )
        )
        results = [
            metrics.SourceResult(
                source="free_pool",
                status="ok",
                metrics=samples,
                observed_at=NOW,
            )
        ]
        context = {"offered_models": list(offered)}
        inputs = main.ranking_inputs(results, catalog, context, list(measured), now=NOW)
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
            observed_failures=list(failures),
            now=NOW,
        )
        data = snapshot.build_snapshot(
            now=NOW,
            sources=[],
            ranked=ranked,
            native_models={},
            policy=POLICY,
            measured_windows=list(measured),
            catalog=catalog,
            facts={},
            free_models=inputs["free"],
            promo_models=inputs["promo"],
            pool_evidence=inputs["pool_evidence"],
        )
        return data

    def row(self, data, provider, model):
        for row in data["candidates"]:
            if (row["provider"], row["model"]) == (provider, model):
                return row
        raise AssertionError(f"the snapshot has no row for {provider}/{model}")


class PoolUnavailableReasonTests(unittest.TestCase, SnapshotFixture):
    """A route the free pool parked says why it is unusable."""

    def test_a_parked_route_with_a_cooldown_names_the_moment_it_ends(self):
        cooldown = NOW + HOUR
        data = self.build(
            pool_routes=[(POOL_PROVIDER, COOLING_MODEL, False, cooldown)],
            measured=[window(POOL_PROVIDER, 0.2)],
        )
        row = self.row(data, POOL_PROVIDER, COOLING_MODEL)
        self.assertFalse(row["available"])
        self.assertEqual(row["availability"]["state"], "unavailable")
        self.assertEqual(
            row["availability"]["reason"],
            f"cooling down in the free pool until {iso(cooldown)}",
        )
        # The change is the reason alone.
        self.assertEqual(row["quota_state"], "available")
        self.assertEqual(row["capacity"]["remaining_ratio"], 0.8)
        self.assertEqual(row["free_pool"]["cooldown_until"], cooldown)

    def test_a_parked_route_without_a_cooldown_says_the_pool_does_not_offer_it(self):
        data = self.build(
            pool_routes=[(POOL_PROVIDER, PARKED_MODEL, False, 0)],
            measured=[window(POOL_PROVIDER, 0.2)],
        )
        row = self.row(data, POOL_PROVIDER, PARKED_MODEL)
        self.assertFalse(row["available"])
        self.assertEqual(row["availability"]["state"], "unavailable")
        self.assertEqual(
            row["availability"]["reason"],
            "the free pool does not offer the route for development work",
        )
        # The change is the reason alone.
        self.assertEqual(row["quota_state"], "available")
        self.assertEqual(row["capacity"]["remaining_ratio"], 0.8)

    def test_a_parked_route_with_a_cooldown_that_has_run_out_is_not_offered(self):
        data = self.build(
            pool_routes=[(POOL_PROVIDER, PARKED_MODEL, False, NOW - HOUR)],
            measured=[window(POOL_PROVIDER, 0.2)],
        )
        row = self.row(data, POOL_PROVIDER, PARKED_MODEL)
        self.assertFalse(row["available"])
        self.assertEqual(row["availability"]["state"], "unavailable")
        self.assertEqual(
            row["availability"]["reason"],
            "the free pool does not offer the route for development work",
        )
        self.assertEqual(row["quota_state"], "available")
        self.assertEqual(row["capacity"]["remaining_ratio"], 0.8)


class UnchangedReasonTests(unittest.TestCase, SnapshotFixture):
    """The reasons the snapshot already gave are unchanged."""

    def test_an_available_pool_route_keeps_its_reason(self):
        data = self.build(
            pool_routes=[(POOL_PROVIDER, AVAILABLE_MODEL, True, None)],
            measured=[window(POOL_PROVIDER, 0.2)],
        )
        row = self.row(data, POOL_PROVIDER, AVAILABLE_MODEL)
        self.assertTrue(row["available"])
        self.assertEqual(row["availability"]["state"], "available")
        # The route is usable, and it says why: it is the headroom it has.
        self.assertEqual(
            row["availability"]["reason"], "every applicable window has headroom"
        )
        self.assertEqual(row["quota_state"], "available")
        self.assertEqual(row["capacity"]["remaining_ratio"], 0.8)

    def test_a_route_the_instance_does_not_offer_keeps_its_reason(self):
        data = self.build(measured=[window(POOL_PROVIDER, 0.2)])
        row = self.row(data, FREE_PROVIDER, FREE_MODEL)
        self.assertFalse(row["available"])
        self.assertEqual(row["availability"]["state"], "unavailable")
        self.assertEqual(
            row["availability"]["reason"], "not offered by the T3 instance"
        )

    def test_a_route_with_a_spent_window_keeps_its_reason(self):
        data = self.build(
            offered=[(PAID_PROVIDER, PAID_MODEL)],
            measured=[window(PAID_PROVIDER, 1.0)],
        )
        row = self.row(data, PAID_PROVIDER, PAID_MODEL)
        self.assertFalse(row["available"])
        self.assertEqual(row["availability"]["state"], "unavailable")
        self.assertEqual(row["availability"]["reason"], "a window is spent")
        self.assertEqual(row["quota_state"], "exhausted")

    def test_an_observed_failure_keeps_its_label_as_the_reason(self):
        data = self.build(
            offered=[(FLAKY_PROVIDER, FLAKY_MODEL)],
            measured=[window(FLAKY_PROVIDER, 0.2)],
            failures=[
                {
                    "scope": "model",
                    "target": FLAKY_MODEL,
                    "reason": "rate_limited",
                    "label": FAILURE_LABEL,
                    "observed_at": NOW,
                }
            ],
        )
        row = self.row(data, FLAKY_PROVIDER, FLAKY_MODEL)
        self.assertFalse(row["available"])
        self.assertEqual(row["availability"]["state"], "unavailable")
        self.assertEqual(row["availability"]["reason"], FAILURE_LABEL)


class MixedSnapshotTests(unittest.TestCase, SnapshotFixture):
    """Every unavailable row of a mixed snapshot says why it is unusable."""

    def test_every_unavailable_candidate_says_why(self):
        data = self.build(
            pool_routes=[
                (POOL_PROVIDER, AVAILABLE_MODEL, True, None),
                (POOL_PROVIDER, COOLING_MODEL, False, NOW + HOUR),
                (POOL_PROVIDER, PARKED_MODEL, False, 0),
            ],
            offered=[
                (PAID_PROVIDER, PAID_MODEL),
                (FLAKY_PROVIDER, FLAKY_MODEL),
            ],
            measured=[
                window(POOL_PROVIDER, 0.2),
                window(PAID_PROVIDER, 1.0),
                window(FLAKY_PROVIDER, 0.2),
            ],
            failures=[
                {
                    "scope": "model",
                    "target": FLAKY_MODEL,
                    "reason": "rate_limited",
                    "label": FAILURE_LABEL,
                    "observed_at": NOW,
                }
            ],
        )
        unavailable = [
            row
            for row in data["candidates"]
            if row["availability"]["state"] != "available"
        ]
        # The mix holds every kind of unavailable route the snapshot knows:
        # the two parked pool routes, the route the instance does not offer,
        # the route whose window is spent and the route that failed.
        self.assertEqual(len(unavailable), 5)
        for row in unavailable:
            with self.subTest(route=f"{row['provider']}/{row['model']}"):
                self.assertTrue(
                    str(row["availability"]["reason"] or "").strip(),
                    f"{row['provider']}/{row['model']} is unavailable without a reason",
                )


if __name__ == "__main__":
    unittest.main()
