"""The reason a route the T3 instance does not offer is unusable.

A route the live instance does not offer reads `available: false` in
`routing.json`, and the reason used to be empty: the ranking says the route
is not offered, but the snapshot rebuilt the reason from the quota windows
alone, and a route with a known free window has no unknown headroom to
explain. A reader saw an unavailable route with no reason at all.

The live examples are the Go free routes `cat-jam-free` and
`step-5-preview-free`, whose catalog entries are marked deprecated: the
catalog is the source that says why the model behind the route is gone, so
the reason names it. A route without a catalog status keeps the bare fact.

The tests drive the real ranking inputs, the real ranking and the real
snapshot builder. A helper-only test would pass while routing.json is wrong.
"""

import importlib.util
import sys
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


metrics = load("not_offered_metrics", "metrics.py")
main = load("not_offered_main", "main.py")
catalog_module = load("not_offered_catalog", "catalog.py")
ranking = load("not_offered_ranking", "ranking.py")
snapshot = load("not_offered_snapshot", "snapshot.py")

NOW = 1_800_000_000.0
DAY = 86400.0

POLICY = {
    "frontierPrimeModels": (),
    "allowedGptModels": (),
    "backgroundProviderInstances": (),
}

# The two routes the live catalog marks deprecated. Neither is offered by
# the instance in these tests: the free list is what carries them.
DEPRECATED_ROUTES = ("cat-jam-free", "step-5-preview-free")

# A paid route of the same subscription, offered by the instance.
PAID_ROUTE = "glm-5.3"


def catalog_with(status):
    """The Go catalog, with `status` on the deprecated free routes."""
    models = {
        "cat-jam-free": {
            "name": "Cat Jam Free",
            "cost": {"input": 0, "output": 0},
        },
        "step-5-preview-free": {
            "name": "Step 5 Preview Free",
            "cost": {"input": 0, "output": 0},
        },
        PAID_ROUTE: {
            "name": "GLM 5.3",
            "cost": {"input": 1.0, "output": 3.0},
        },
    }
    if status is not None:
        for model in DEPRECATED_ROUTES:
            models[model]["status"] = status
    return {"opencode-go": {"models": models}}


def go_monthly(used_ratio):
    """The monthly window of the Go account, at the given used share."""
    return {
        "provider": "opencode-go",
        "account": "default",
        "model": "*",
        "kind": "monthly",
        "quotaId": "go_monthly",
        "usedRatio": used_ratio,
        "resetEpoch": NOW + 10 * DAY,
        "durationSeconds": 30 * DAY,
        "source": "t3",
        "observedAtEpoch": NOW,
    }


class SnapshotFixture:
    """The real pipeline of one reading: inputs, ranking and snapshot."""

    def build(self, offered, measured, *, status=None, failures=()):
        catalog = catalog_module.Catalog(catalog_with(status))
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
            observed_failures=failures,
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
        return data

    def row(self, data, model):
        for row in data["candidates"]:
            if (row["provider"], row["model"]) == ("opencode-go", model):
                return row
        raise AssertionError(f"the snapshot has no row for opencode-go/{model}")


class NotOfferedReasonTests(unittest.TestCase, SnapshotFixture):
    """A route the instance does not offer says why it is unusable."""

    def test_a_deprecated_route_the_instance_does_not_offer_names_the_catalog(self):
        # The live case: the route is in the free list, not in the inventory,
        # and the catalog marks the model behind it deprecated.
        data = self.build(
            [], [go_monthly(1.0)], status="deprecated"
        )
        for model in DEPRECATED_ROUTES:
            with self.subTest(model=model):
                row = self.row(data, model)
                self.assertFalse(row["available"])
                self.assertEqual(row["availability"]["state"], "unavailable")
                self.assertEqual(
                    row["availability"]["reason"],
                    "not offered by the T3 instance (deprecated in the catalog)",
                )
                # The fix changes the reason alone.
                self.assertEqual(row["quota_state"], "available")
                self.assertEqual(row["capacity"]["remaining_ratio"], 1.0)

    def test_a_route_the_instance_does_not_offer_says_so_without_a_catalog_status(self):
        data = self.build([], [go_monthly(1.0)])
        for model in DEPRECATED_ROUTES:
            with self.subTest(model=model):
                row = self.row(data, model)
                self.assertFalse(row["available"])
                self.assertEqual(row["availability"]["state"], "unavailable")
                self.assertEqual(
                    row["availability"]["reason"], "not offered by the T3 instance"
                )
                self.assertEqual(row["quota_state"], "available")
                self.assertEqual(row["capacity"]["remaining_ratio"], 1.0)


class UnchangedReasonTests(unittest.TestCase, SnapshotFixture):
    """The reasons the snapshot already gave are unchanged."""

    def test_an_available_route_keeps_the_headroom_reason(self):
        data = self.build([("opencode-go", PAID_ROUTE)], [go_monthly(0.2)])
        row = self.row(data, PAID_ROUTE)
        self.assertTrue(row["available"])
        self.assertEqual(row["availability"]["state"], "available")
        self.assertEqual(
            row["availability"]["reason"], "every applicable window has headroom"
        )
        self.assertEqual(row["quota_state"], "available")

    def test_an_offered_route_with_a_spent_window_keeps_the_spent_reason(self):
        data = self.build([("opencode-go", PAID_ROUTE)], [go_monthly(1.0)])
        row = self.row(data, PAID_ROUTE)
        self.assertFalse(row["available"])
        self.assertEqual(row["availability"]["state"], "unavailable")
        self.assertEqual(row["availability"]["reason"], "a window is spent")
        self.assertEqual(row["quota_state"], "exhausted")

    def test_an_observed_failure_keeps_its_label_as_the_reason(self):
        label = "the route failed and is not usable right now"
        data = self.build(
            [("opencode-go", PAID_ROUTE)],
            [go_monthly(0.2)],
            failures=[
                {
                    "scope": "model",
                    "target": PAID_ROUTE,
                    "reason": "rate_limited",
                    "label": label,
                    "observed_at": NOW,
                }
            ],
        )
        row = self.row(data, PAID_ROUTE)
        self.assertFalse(row["available"])
        self.assertEqual(row["availability"]["state"], "unavailable")
        self.assertEqual(row["availability"]["reason"], label)
        self.assertEqual(
            (row["availability"]["observed_failure"] or {}).get("label"), label
        )


if __name__ == "__main__":
    unittest.main()
