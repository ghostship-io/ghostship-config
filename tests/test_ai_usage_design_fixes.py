"""The design fixes of the routing collector.

Every test here names the defect it catches. The defects are the findings of
the routing design audit: F1 account attribution, F2 the dedicated free tier,
F3 the access classification, F4 the limits of the free pool, F5 the missing
decision metrics, F7 the honest score, F8 the stale text, F9 the duplicated
policy lists, and the observed runtime availability of a route.
"""

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage/collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import catalog as catalog_module  # noqa: E402
import ranking  # noqa: E402

NOW = 1_800_000_000.0
DAY = 86400.0


def _load(name: str, filename: str | None = None):
    """Load one collector module under its own name."""
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{filename or name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


snapshot = _load("ai_usage_design_snapshot", "snapshot")


def aa_cache_for(models, index=80.0, cost=0.2):
    """A measured Artificial Analysis cache for the given models."""
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
                "release_date": "2026-01-20",
                "indices": {"intelligence_index": index},
                "cost_per_task": cost,
                "median_performance": 100.0,
                "prices": {},
            }
        )
    return {
        "status": "ok",
        "index_version": "4.3",
        "fetched_at": "2026-01-20T00:00:00Z",
        "fetched_at_epoch": NOW,
        "records": records,
    }


def catalog_entry(model_id, family="family", released="2026-01-20", cost=None):
    """One synthetic catalog entry."""
    found = {
        "id": model_id,
        "name": model_id,
        "family": family,
        "release_date": released,
        "limit": {"context": 200000},
    }
    if cost is not None:
        found["cost"] = cost
    return found


class AccountAttributionTests(unittest.TestCase):
    """F1: a model id prefix is a name, not an account."""

    def test_a_free_pool_model_keeps_its_own_account(self):
        self.assertEqual(ranking.account_for("kilo", "gpt-4o-mini"), "kilo")
        self.assertEqual(ranking.account_for("ovh", "gpt-oss-120b"), "ovh")
        self.assertEqual(ranking.account_for("google", "gemini-3.8-flash"), "google")
        self.assertEqual(ranking.account_for("requesty", "gemini-3-pro"), "requesty")

    def test_the_opencode_route_keeps_its_own_account(self):
        self.assertEqual(ranking.account_for("opencode", "grok-4.7"), "opencode")
        self.assertEqual(ranking.account_for("opencode", "gpt-5"), "opencode")

    def test_a_known_account_stays_itself(self):
        self.assertEqual(ranking.account_for("codex", "gpt-6.1-sol"), "codex")
        self.assertEqual(ranking.account_for("claude", "claude-opus-5-5"), "claude")
        self.assertEqual(ranking.account_for("opencode-go", "grok-4.7"), "opencode-go")

    def test_an_exhausted_codex_never_hides_a_pool_route(self):
        catalog = catalog_module.Catalog(
            {
                "openai": {"models": {"gpt-6.1-sol": catalog_entry("gpt-6.1-sol")}},
                "kilo": {"models": {"gpt-4o-mini": catalog_entry("gpt-4o-mini")}},
                "opencode": {"models": {"grok-4.7": catalog_entry("grok-4.7")}},
            }
        )
        models = [
            ranking.ModelRecord("codex", "gpt-6.1-sol"),
            ranking.ModelRecord("kilo", "gpt-4o-mini"),
            ranking.ModelRecord("opencode", "grok-4.7"),
        ]
        ranked = ranking.rank_models(
            models=models,
            catalog=catalog,
            quota_windows={
                "codex": [
                    ranking.QuotaWindow(
                        kind="weekly",
                        used_ratio=1.0,
                        reset_epoch=NOW + 3 * DAY,
                        observed_at=NOW,
                    )
                ]
            },
            free_models=set(),
            usage_tokens={},
            aa_cache=aa_cache_for(models),
            now=NOW,
        )
        available = {
            (item.provider, item.model)
            for item in ranked
            if item.available and item.tier
        }
        self.assertNotIn(("codex", "gpt-6.1-sol"), available)
        self.assertIn(("kilo", "gpt-4o-mini"), available)
        self.assertIn(("opencode", "grok-4.7"), available)
        # The pool model is not gated by the Codex allowance at all.
        pool = [item for item in ranked if item.provider == "kilo"][0]
        self.assertEqual(pool.account, "kilo")
        self.assertEqual(pool.quota_scope["parent_windows"], 0)


class AccessClassificationTests(unittest.TestCase):
    """F3: a promotional zero price is not a dedicated free route."""

    def test_a_promotional_zero_price_wins_over_the_free_class(self):
        record = snapshot._access_record(
            "openrouter",
            "cohere/north-mini-code:free",
            {("openrouter", "cohere/north-mini-code:free")},
            {("openrouter", "cohere/north-mini-code:free")},
            {"input": 0.0, "output": 0.0},
        )
        self.assertEqual(record["kind"], snapshot.ACCESS_PROVIDER_PROMO)
        self.assertIn("paid provider route", record["basis"])

    def test_a_free_route_of_the_free_pool_is_a_dedicated_free_route(self):
        record = snapshot._access_record(
            "kilo",
            "cohere/north-mini-code:free",
            {("kilo", "cohere/north-mini-code:free")},
            set(),
            {"input": 0.0, "output": 0.0},
        )
        self.assertEqual(record["kind"], snapshot.ACCESS_DEDICATED_FREE)
        self.assertEqual(record["execution"], "inference_job")

    def test_a_t3_route_free_by_listing_is_a_dedicated_free_route(self):
        record = snapshot._access_record(
            "openrouter",
            "cohere/north-mini-code:free",
            {("openrouter", "cohere/north-mini-code:free")},
            set(),
            {"input": 0.0, "output": 0.0},
            native_mapped=True,
        )
        self.assertEqual(record["kind"], snapshot.ACCESS_DEDICATED_FREE)
        self.assertEqual(record["execution"], "provider_native")

    def test_a_paid_route_with_a_price_is_not_free(self):
        record = snapshot._access_record(
            "codex", "gpt-6.1-sol", set(), set(), {"input": 1.0, "output": 2.0}
        )
        self.assertEqual(record["kind"], snapshot.ACCESS_PROVIDER_PAID)

    def test_a_route_without_a_price_is_unknown(self):
        record = snapshot._access_record("kilo", "gpt-4o-mini", set(), set(), None)
        self.assertEqual(record["kind"], snapshot.ACCESS_UNKNOWN)


class FreeSetTests(unittest.TestCase):
    """The collector keeps the free routes and the promotional routes apart."""

    def _catalog(self):
        return catalog_module.Catalog(
            {
                "openrouter": {
                    "models": {
                        "cohere/north-mini-code:free": {
                            "id": "cohere/north-mini-code:free",
                            "name": "North Mini Code (free)",
                            "cost": {"input": 0, "output": 0},
                        }
                    }
                },
                "opencode-go": {
                    "models": {
                        "minimax-m3.1-flash-free": {
                            "id": "minimax-m3.1-flash-free",
                            "name": "MiniMax M3.1 Flash Free",
                            "cost": {"input": 0, "output": 0},
                        }
                    }
                },
                "opencode": {
                    "models": {
                        "big-pickle": {
                            "id": "big-pickle",
                            "name": "Big Pickle",
                            "cost": {"input": 0, "output": 0},
                        }
                    }
                },
            }
        )

    def test_the_free_route_providers_are_free_and_the_rest_is_promotional(self):
        main = _load("ai_usage_design_main", "main")
        catalog = self._catalog()
        inputs = main.ranking_inputs([], catalog, {}, [])
        free = inputs["free"]
        promo = inputs["promo"]
        self.assertIn(("openrouter", "cohere/north-mini-code:free"), free)
        self.assertIn(("opencode-go", "minimax-m3.1-flash-free"), free)
        self.assertIn(("opencode", "big-pickle"), promo)
        self.assertNotIn(("opencode", "big-pickle"), free)
        self.assertNotIn(("openrouter", "cohere/north-mini-code:free"), promo)
