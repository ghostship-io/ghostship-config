"""The free pool: the series it publishes, and the order of the free tier.

Two rules of the owner are under test here:

* no metrics output holds the same series, the same name with the same
  labels, twice; and
* the free tier is ordered by the routing policy: the quality band first,
  then the rest by intelligence.

The tests drive the real pool emitter, the real ranking, the real snapshot
builder and the real renderer. A helper-only test would pass while the
published file is broken.
"""
import importlib.util
import re
import sys
import unittest
from collections import Counter
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


metrics = load("free_pool_metrics", "metrics.py")
main = load("free_pool_main", "main.py")
pool = load("free_pool_pool", "pool.py")
ranking = load("free_pool_ranking", "ranking.py")
snapshot = load("free_pool_snapshot", "snapshot.py")
catalog_module = load("free_pool_catalog", "catalog.py")

NOW = 1_800_000_000.0
DAY = 24 * 3600.0


def aa_record(slug, index):
    """One measured Artificial Analysis record."""
    return {
        "id": f"id-{slug}",
        "slug": slug,
        "model": slug,
        "release_date": "2026-01-20",
        "indices": {"intelligence_index": index},
        "cost_per_task": 0.2,
        "median_performance": 100.0,
        "prices": {},
    }


def series_of(text):
    """Every series of a rendered textfile: its name and its label set."""
    found = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        name, _, rest = line.partition("{")
        labels = rest.partition("}")[0]
        found.append((name.strip(), labels))
    return found


def duplicates_of(text):
    """The series a textfile holds twice."""
    counts = Counter(series_of(text))
    return sorted(key for key, count in counts.items() if count > 1)


def pool_catalog(routes):
    """The pool's catalog: one provider per route, with its own limits.

    A route is a (provider, model) pair with the intelligence index of its
    measured Artificial Analysis record, the headroom the collector reads for
    it, and the moment the pool last used it.
    """
    providers: dict[str, dict] = {}
    for provider, model, _index, _headroom, _last_used in routes:
        entry = providers.setdefault(
            provider, {"selected_model": model, "candidates": []}
        )
        entry["candidates"].append(
            {
                "model": model,
                "geography": {
                    "family": model.rsplit("/", 1)[-1],
                    "developer_country": "US",
                    "operator_country": "US",
                },
                "available": True,
                "admissions": {"light": {"admitted": True, "score": 0.8}},
                "account_limits": {"rpm": 30},
                "model_limits": {},
                "last_used": _last_used,
            }
        )
    return {"providers": providers}


def catalog_document(routes):
    """The public catalog of the routes, with their release dates."""
    document: dict[str, dict] = {}
    for provider, model, _index, _headroom, _last_used in routes:
        for key in {provider, *catalog_module.PROVIDER_ALIASES.get(provider, ())}:
            document.setdefault(key, {"models": {}})["models"][model] = {
                "id": model,
                "name": model,
                "family": model,
                "release_date": "2026-01-20",
                "limit": {"context": 200000},
                "cost": {"input": 0.0, "output": 0.0},
            }
    return document


def free_tier(routes, *, native=()):
    """The collector's own readings for a set of free routes.

    The routes are (provider, model, intelligence, headroom, last used). The
    headroom is the remaining share of the window that applies to the route,
    and the last use is the moment the pool sent a job to it.

    The result holds the snapshot, the samples of the pool source and the
    samples of the ranking, which is what the renderer publishes.
    """
    samples = []
    pool._emit_catalog(samples, pool_catalog(routes))
    result = metrics.SourceResult(
        source="free_pool", status="ok", reason="ok", metrics=samples
    )
    catalog = catalog_module.Catalog(catalog_document(routes))
    inputs = main.ranking_inputs([result], catalog, {}, [], now=NOW)
    windows = dict(inputs["windows"])
    for provider, model, _index, headroom, _last_used in routes:
        if headroom is None:
            continue
        windows[f"{provider}/{model}"] = [
            ranking.QuotaWindow(
                kind="daily",
                used_ratio=1.0 - headroom,
                reset_epoch=NOW + DAY,
                applies_to=(),
                quota_id="daily",
                duration_seconds=DAY,
                observed_at=NOW,
                basis="published",
                gating=True,
            )
        ]
    models = [(provider, model) for provider, model, _i, _h, _l in routes]
    free = set(models) | set(native)
    cache = {
        "status": "ok",
        "index_version": "4.3",
        "fetched_at_epoch": NOW,
        "records": [
            aa_record(model.rsplit("/", 1)[-1], index)
            for _provider, model, index, _headroom, _last_used in routes
            if index is not None
        ],
    }
    ranked = ranking.rank_models(
        models=[ranking.ModelRecord(provider, model) for provider, model in models],
        catalog=catalog,
        quota_windows=windows,
        free_models=free,
        promo_models=set(),
        usage_tokens={},
        aa_cache=cache,
        now=NOW,
    )
    data = snapshot.build_snapshot(
        now=NOW,
        sources=[
            {"id": "free_pool", "status": "ok", "reason": "ok", "observed_at_epoch": NOW}
        ],
        ranked=ranked,
        native_models={
            key: {"providerInstance": "opencode", "modelId": key[1], "options": []}
            for key in native
        },
        policy={
            "frontierPrimeModels": ("gpt-6.1-sol", "claude-opus-5-5"),
            "allowedGptModels": ("gpt-6.1-sol",),
            "backgroundProviderInstances": ("opencode",),
        },
        catalog=catalog,
        aa_cache=cache,
        free_models=free,
        pool_evidence=inputs["pool_evidence"],
    )
    return {
        "snapshot": data,
        "pool": samples,
        "extra": ranking.rank_samples(ranked, now=NOW),
    }


def render(routes, *, native=()):
    """The published textfile of a set of free routes."""
    collected = free_tier(routes, native=native)
    return main.render(
        [
            metrics.SourceResult(
                source="free_pool",
                status="ok",
                reason="ok",
                metrics=collected["pool"],
            )
        ],
        collected["extra"],
        NOW,
        0.1,
        collected["snapshot"],
    )


def free_winners(data):
    """The winners of the free tier, in their order."""
    return [
        (winner["provider"], winner["model"])
        for winner in (data.get("tier_winners") or {}).get("free") or []
    ]


def free_row(provider, model, strength, headroom, last_used):
    """One candidate row of the free tier, as the tier order reads it.

    A route without an Artificial Analysis match is not ranked by the
    collector, so it is built here: the rule that it comes last is the rule
    of the tier order itself.
    """
    return {
        "provider": provider,
        "model": model,
        "availability": {"state": "available"},
        "admission": {"state": "settled", "reason": ""},
        "aa": {"state": "measured", "reference": {"intelligence_index": strength}},
        "selection": {"excluded": False},
        "eligibility": {
            "frontier_prime": {"allowed": False},
            "delegate": {"allowed": True},
        },
        "access": {"kind": "dedicated_free"},
        "native": {"mapped": False},
        "reserve": {"3d": False},
        "free_pool": {
            "admission": [{"workload": "light", "admitted": True}],
            "last_used": last_used,
        },
        "value": {"strength": strength, "value": 0.5 if strength is not None else None},
        "quality": {"value": strength},
        "capacity": {"remaining_ratio": headroom, "pace_delta": None},
        "quota_state": "ok",
        "role": "delegate",
    }


class DuplicateSeriesTests(unittest.TestCase):
    """No metrics output holds the same series twice."""

    ROUTES = [
        ("groq", "groq/llama-3.3", 42.7, None, 0.0),
        ("groq", "groq/mixtral-8x7b", 41.8, None, 0.0),
        ("mistral", "mistral/magistral", 33.7, None, 0.0),
        ("ollama", "ollama/qwen3-coder", 11.6, None, 0.0),
    ]

    def test_an_account_limit_is_published_once_for_a_provider_with_two_models(self):
        samples = []
        pool._emit_catalog(
            samples,
            {
                "providers": {
                    "groq": {
                        "selected_model": "groq/llama-3.3",
                        "candidates": [
                            {
                                "model": model,
                                "available": True,
                                "admissions": {"light": {"admitted": True, "score": 0.8}},
                                "account_limits": {"rpm": 30, "rpd": 1000},
                                "model_limits": {},
                            }
                            for model in ("groq/llama-3.3", "groq/mixtral-8x7b")
                        ],
                    }
                }
            },
        )
        account = [
            sample
            for sample in samples
            if sample[0] == "ghostship_ai_pool_limit"
            and sample[1].get("scope") == "account"
        ]
        # The limits of an account belong to the account: one series per
        # limit, not one per model of the provider.
        self.assertEqual(
            sorted((sample[1]["limit"], sample[2]) for sample in account),
            [("rpd", 1000.0), ("rpm", 30.0)],
        )
        # Every model of the provider keeps its own series.
        for model in ("groq/llama-3.3", "groq/mixtral-8x7b"):
            for name in (
                "ghostship_ai_pool_model_info",
                "ghostship_ai_pool_model_available",
                "ghostship_ai_pool_model_selected",
            ):
                self.assertEqual(
                    len([s for s in samples if s[0] == name and s[1].get("model") == model]),
                    1,
                    f"{name} is published once for {model}",
                )

    def test_the_published_file_holds_no_series_twice(self):
        text = render(self.ROUTES)
        self.assertEqual(duplicates_of(text), [])

    def test_the_model_availability_is_published_once_per_model(self):
        text = render(self.ROUTES)
        availability = [
            entry for entry in series_of(text) if entry[0] == "ghostship_ai_model_available"
        ]
        # One series per model, and the file holds no series twice.
        self.assertEqual(len(availability), len(set(availability)))
        self.assertEqual(duplicates_of(text), [])
        for provider, model, _index, _headroom, _last_used in self.ROUTES:
            self.assertEqual(
                len(
                    [
                        entry
                        for entry in availability
                        if f'model="{metrics.label_value(model)}"' in entry[1]
                        and f'provider="{metrics.label_value(provider)}"' in entry[1]
                    ]
                ),
                1,
                f"the availability of {provider}/{model} is published once",
            )


if __name__ == "__main__":
    unittest.main()
