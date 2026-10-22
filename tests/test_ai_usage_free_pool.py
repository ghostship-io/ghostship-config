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


def duplicate_count_of(text):
    """The number of repeated series the collection dropped.

    The count is the proof that no emitter repeated a series: the renderer
    drops a repeat and counts it, so a count of zero means the file holds
    one series per name and label set because there never was a second one.
    """
    for line in text.splitlines():
        if line.startswith("ghostship_ai_collection_duplicate_series "):
            return float(line.split(" ")[-1])
    return None


def pool_catalog(routes):
    """The pool's catalog: one provider per route, with its own limits.

    A route is a (provider, model, intelligence, headroom, last used, reset)
    tuple: the intelligence index of its measured Artificial Analysis record,
    the headroom the collector reads for it, the moment the pool last used
    it, and the moment its window resets.
    """
    providers: dict[str, dict] = {}
    for provider, model, _index, _headroom, _last_used, _reset in routes:
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
    for provider, model, _index, _headroom, _last_used, _reset in routes:
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
    for provider, model, _index, headroom, _last_used, reset in routes:
        if headroom is None:
            continue
        windows[f"{provider}/{model}"] = [
            ranking.QuotaWindow(
                kind="daily",
                used_ratio=1.0 - headroom,
                reset_epoch=NOW + (DAY if reset is None else reset),
                applies_to=(),
                quota_id="daily",
                duration_seconds=DAY,
                observed_at=NOW,
                basis="published",
                gating=True,
            )
        ]
    models = [(provider, model) for provider, model, _i, _h, _l, _r in routes]
    free = set(models) | set(native)
    cache = {
        "status": "ok",
        "index_version": "4.3",
        "fetched_at_epoch": NOW,
        "records": [
            aa_record(model.rsplit("/", 1)[-1], index)
            for _provider, model, index, _headroom, _last_used, _reset in routes
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
        ("groq", "groq/llama-3.3", 42.7, None, 0.0, None),
        ("groq", "groq/mixtral-8x7b", 41.8, None, 0.0, None),
        ("mistral", "mistral/magistral", 33.7, None, 0.0, None),
        ("ollama", "ollama/qwen3-coder", 11.6, None, 0.0, None),
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
        # The emitters published no repeat: the renderer had nothing to drop,
        # so the count is zero. Without this the test would pass even when an
        # emitter repeats, because the renderer drops the repeat.
        self.assertEqual(duplicate_count_of(text), 0.0)
        self.assertEqual(duplicates_of(text), [])

    def test_the_model_availability_is_published_once_per_model(self):
        text = render(self.ROUTES)
        availability = [
            entry for entry in series_of(text) if entry[0] == "ghostship_ai_model_available"
        ]
        # One series per model, no repeat reached the renderer, and the file
        # holds no series twice.
        self.assertEqual(len(availability), len(set(availability)))
        self.assertEqual(duplicate_count_of(text), 0.0)
        self.assertEqual(duplicates_of(text), [])
        for provider, model, _index, _headroom, _last_used, _reset in self.ROUTES:
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


class WriterGuardTests(unittest.TestCase):
    """The renderer publishes every series once, and says when it drops one."""

    def _render(self, samples):
        result = metrics.SourceResult(
            source="probe", status="ok", reason="ok", metrics=list(samples)
        )
        return main.render([result], [], NOW, 0.1, {})

    def test_a_repeated_series_is_published_once_with_the_first_value(self):
        text = self._render(
            [
                ("ghostship_ai_probe_value", {"provider": "groq"}, 1.0),
                ("ghostship_ai_probe_value", {"provider": "groq"}, 2.0),
            ]
        )
        self.assertIn('ghostship_ai_probe_value{provider="groq"} 1', text)
        self.assertNotIn("ghostship_ai_probe_value{provider=\"groq\"} 2", text)
        self.assertEqual(
            len(
                [
                    line
                    for line in text.splitlines()
                    if line.startswith("ghostship_ai_probe_value{")
                ]
            ),
            1,
            "the series is published once",
        )
        # The drop is counted, so the repeat is never silent.
        self.assertEqual(duplicate_count_of(text), 1.0)

    def test_two_series_with_different_labels_are_not_a_repeat(self):
        text = self._render(
            [
                ("ghostship_ai_probe_value", {"provider": "groq"}, 1.0),
                ("ghostship_ai_probe_value", {"provider": "mistral"}, 2.0),
            ]
        )
        self.assertIn('ghostship_ai_probe_value{provider="groq"} 1', text)
        self.assertIn('ghostship_ai_probe_value{provider="mistral"} 2', text)
        self.assertEqual(duplicate_count_of(text), 0.0)


class FreeTierOrderTests(unittest.TestCase):
    """The free tier is ordered by the routing policy."""

    # The worked case of the policy: 42.7 and 41.8 are within five points of
    # the best route and form the band, 33.7 and 11.6 follow by intelligence.
    # The routes are named so that the order of the policy is not the order of
    # the names.
    WORKED = [
        ("groq", "groq/llama-3.3", 42.7, None, 0.0, None),
        ("cohere", "cohere/command", 41.8, None, 0.0, None),
        ("mistral", "mistral/magistral", 33.7, None, 0.0, None),
        ("ollama", "ollama/qwen3-coder", 11.6, None, 0.0, None),
    ]

    def test_the_band_comes_first_and_the_rest_follows_by_intelligence(self):
        data = free_tier(self.WORKED)["snapshot"]
        self.assertEqual(
            free_winners(data),
            [
                ("groq", "groq/llama-3.3"),
                ("cohere", "cohere/command"),
                ("mistral", "mistral/magistral"),
                ("ollama", "ollama/qwen3-coder"),
            ],
        )
        bands = {
            (winner["provider"], winner["model"]): winner.get("band")
            for winner in (data.get("tier_winners") or {}).get("free") or []
        }
        self.assertEqual(
            bands,
            {
                ("groq", "groq/llama-3.3"): "true",
                ("cohere", "cohere/command"): "true",
                ("mistral", "mistral/magistral"): "false",
                ("ollama", "ollama/qwen3-coder"): "false",
            },
        )

    def test_the_headroom_of_a_band_route_decides_before_its_intelligence(self):
        # The negative case of the policy: both routes are in the band, and
        # the route with the most remaining headroom goes first. Both windows
        # draw the same line, so the pace of the two routes is the same and
        # the headroom is what decides.
        routes = [
            ("groq", "groq/llama-3.3", 42.7, 0.10, 0.0, 0.1 * DAY),
            ("mistral", "mistral/mixtral-8x7b", 41.8, 0.90, 0.0, 0.9 * DAY),
        ]
        data = free_tier(routes)["snapshot"]
        self.assertEqual(
            free_winners(data),
            [
                ("mistral", "mistral/mixtral-8x7b"),
                ("groq", "groq/llama-3.3"),
            ],
        )
        self.assertEqual(
            [
                winner.get("band")
                for winner in (data.get("tier_winners") or {}).get("free") or []
            ],
            ["true", "true"],
        )

    def test_the_least_recently_used_route_breaks_the_tie(self):
        # Both routes are in the band with the same headroom, and the route
        # the pool used least recently goes first.
        routes = [
            ("groq", "groq/llama-3.3", 42.7, 0.50, NOW - 10.0, None),
            ("mistral", "mistral/mixtral-8x7b", 41.8, 0.50, NOW - 3600.0, None),
        ]
        data = free_tier(routes)["snapshot"]
        self.assertEqual(
            free_winners(data),
            [
                ("mistral", "mistral/mixtral-8x7b"),
                ("groq", "groq/llama-3.3"),
            ],
        )

    def test_a_route_without_an_intelligence_record_comes_last(self):
        # A route without an Artificial Analysis match is the lower band: it
        # is used only when no ranked route has headroom, so it comes after
        # every ranked route of the tier.
        rows = [
            free_row("groq", "groq/llama-3.3", 42.7, 0.50, 0.0),
            free_row("mistral", "mistral/mixtral-8x7b", 41.8, 0.50, 0.0),
            free_row("openrouter", "openrouter/zeta-free", None, 0.50, 0.0),
        ]
        winners, _coverage = snapshot._winners(
            rows, {"free": [f"{row['provider']}:{row['model']}" for row in rows]}
        )
        self.assertEqual(
            [(winner["provider"], winner["model"]) for winner in winners["free"]],
            [
                ("groq", "groq/llama-3.3"),
                ("mistral", "mistral/mixtral-8x7b"),
                ("openrouter", "openrouter/zeta-free"),
            ],
        )
        self.assertEqual(
            [winner.get("band") for winner in winners["free"]],
            ["true", "true", "false"],
        )

    def test_the_band_is_published_with_the_position_of_the_free_tier(self):
        data = free_tier(self.WORKED)["snapshot"]
        samples = snapshot.decision_samples(data)
        positions = {
            (labels["provider"], labels["model"]): (value, labels.get("band"))
            for name, labels, value in samples
            if name == "ghostship_ai_model_winner_position"
            and labels.get("tier") == "free"
        }
        self.assertEqual(
            positions,
            {
                ("groq", "groq/llama-3.3"): (1.0, "true"),
                ("cohere", "cohere/command"): (2.0, "true"),
                ("mistral", "mistral/magistral"): (3.0, "false"),
                ("ollama", "ollama/qwen3-coder"): (4.0, "false"),
            },
        )

    def test_only_the_free_tier_changes(self):
        # The band is a rule of the free tier: the other tiers keep their own
        # order and carry no band.
        routes = [
            ("groq", "groq/llama-3.3", 42.7, 0.90, 0.0, None),
            ("mistral", "mistral/mixtral-8x7b", 41.8, 0.10, 0.0, None),
        ]
        data = free_tier(routes, native=[("mistral", "mistral/mixtral-8x7b")])["snapshot"]
        winners = data.get("tier_winners") or {}
        bulk = winners.get("bulk") or []
        free = winners.get("free") or []
        self.assertTrue(bulk, "the bulk tier has its own winners")
        self.assertTrue(
            all("band" not in winner for winner in bulk),
            "the bulk tier is not banded",
        )
        self.assertEqual(
            [winner.get("band") for winner in free],
            ["true", "true"],
        )
        self.assertEqual(
            free_winners(data),
            [
                ("groq", "groq/llama-3.3"),
                ("mistral", "mistral/mixtral-8x7b"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
