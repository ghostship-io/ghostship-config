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
import json
import re
import sqlite3
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

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


def observation(model, *, observed, rpd=None, tpm=None, rph=None, scope="model_in_organization"):
    """One synthetic reading of a provider's own rate-limit headers."""
    windows = {}
    if rpd is not None:
        windows["rpd"] = rpd
    if tpm is not None:
        windows["tpm"] = tpm
    if rph is not None:
        windows["rph"] = rph
    return {
        "provider": "groq",
        "model": model,
        "observed_at": observed,
        "data": {"scope": scope, "windows": windows},
    }


class ReportedHeaderCapacityTests(unittest.TestCase):
    """A provider's own reported headers are that model's capacity.

    The free pool records the rate-limit headers of a provider's answer as
    observations. Those observations are the provider's capacity for the
    model it answered, filed per model, with the moment the provider said
    the window refills. The pool's own admission caps are a local policy
    and never stand in for it.
    """

    MODEL = "qwen/qwen3-32b"
    MOMENT = 1001.0

    def collect(self, status, *, now=None, catalog=None):
        """Run the real pool collector against a synthetic bridge."""
        with tempfile.TemporaryDirectory(prefix="reported-headers-") as directory:
            root = Path(directory)
            server = root / "server.json"
            server.write_text(json.dumps({"socket": str(root / "inference.sock")}), encoding="utf-8")
            token = root / "token"
            token.write_text("synthetic-token", encoding="utf-8")
            ledger = root / "ledger.sqlite"
            connection = sqlite3.connect(ledger)
            try:
                connection.execute(
                    "CREATE TABLE inference_reservations ("
                    "id TEXT, job TEXT, provider TEXT, model TEXT, at REAL, "
                    "input INTEGER, output INTEGER, usd REAL, neurons INTEGER)"
                )
                connection.commit()
            finally:
                connection.close()

            def bridge(_socket, _token, _surface, arguments):
                if arguments.get("op") == "models":
                    return catalog or {"providers": {}}
                return status

            with mock.patch.object(pool, "bridge_call", side_effect=bridge):
                results = pool.collect(
                    server, token, ledger, self.MOMENT if now is None else now
                )
        self.assertEqual(len(results), 1)
        return results[0]

    def test_the_reported_headers_publish_the_daily_and_minute_window(self):
        status = {
            "quota_observations": [
                observation(
                    self.MODEL,
                    observed=1000.0,
                    rpd={"limit": 1000, "remaining": 999, "reset": "1m26.4s"},
                    tpm={"limit": 8000, "remaining": 7703, "reset": "2.227s"},
                )
            ]
        }
        result = self.collect(status)
        windows = {(window["kind"], window["quotaId"]): window for window in result.windows}

        self.assertEqual(set(windows), {("daily", "rpd"), ("minute", "tpm")})
        daily = windows[("daily", "rpd")]
        self.assertEqual(daily["provider"], "groq")
        self.assertEqual(daily["model"], self.MODEL)
        self.assertEqual(daily["durationSeconds"], 86400.0)
        self.assertAlmostEqual(daily["usedRatio"], 0.001)
        # The reset is the one the provider reported, counted from the
        # moment it observed the reading, and never from the collection.
        self.assertAlmostEqual(daily["resetEpoch"], 1086.4)
        self.assertEqual(daily["observedAtEpoch"], 1000.0)
        self.assertEqual(daily["basis"], "provider_reported")
        self.assertEqual(tuple(daily["applies_to"]), (self.MODEL,))

        minute = windows[("minute", "tpm")]
        self.assertEqual(minute["durationSeconds"], 60.0)
        self.assertAlmostEqual(minute["usedRatio"], 0.037125)
        self.assertAlmostEqual(minute["resetEpoch"], 1002.227)

        # The observation is still a diagnostic: the amounts, the reset and
        # the observation keep their series and their values.
        amounts = {
            (labels["kind"], labels["unit"]): value
            for name, labels, value in result.metrics
            if name == "ghostship_ai_pool_quota_amount"
        }
        self.assertEqual(amounts[("limit", "rpd")], 1000.0)
        self.assertEqual(amounts[("remaining", "rpd")], 999.0)
        self.assertEqual(amounts[("limit", "tpm")], 8000.0)
        self.assertEqual(amounts[("remaining", "tpm")], 7703.0)
        resets = {
            labels["unit"]: value
            for name, labels, value in result.metrics
            if name == "ghostship_ai_pool_quota_reset_seconds"
        }
        self.assertAlmostEqual(resets["rpd"], 1086.4)
        self.assertAlmostEqual(resets["tpm"], 1002.227)
        observed_limit = [
            labels
            for name, labels, _value in result.metrics
            if name == "ghostship_ai_pool_observed_limit"
        ]
        # The provider reported the limit for one model, and the diagnostic
        # keeps that scope instead of filing it as the account's limit.
        self.assertEqual({labels["scope"] for labels in observed_limit}, {"model"})

    def test_a_spent_model_does_not_lock_out_its_sibling(self):
        spent = "llama-3.3-70b-versatile"
        room = self.MODEL
        status = {
            "quota_observations": [
                observation(
                    spent,
                    observed=1000.0,
                    rpd={"limit": 100, "remaining": 0, "reset": "1m"},
                ),
                observation(
                    room,
                    observed=1000.0,
                    rpd={"limit": 100, "remaining": 50, "reset": "1m"},
                ),
            ]
        }
        result = self.collect(status)
        catalog = catalog_module.Catalog(
            catalog_document(
                [
                    ("groq", spent, 42.0, None, 0.0, None),
                    ("groq", room, 41.0, None, 0.0, None),
                ]
            )
        )
        inputs = main.ranking_inputs(
            [result], catalog, {}, result.windows, now=self.MOMENT
        )
        # The windows are filed by the model, never by the account: one
        # spent model has no window at the provider key.
        self.assertEqual(
            sorted(inputs["windows"]), [f"groq/{spent}", f"groq/{room}"]
        )
        self.assertNotIn("groq", inputs["windows"])
        self.assertAlmostEqual(
            inputs["windows"][f"groq/{spent}"][0].used_ratio, 1.0
        )
        self.assertAlmostEqual(
            inputs["windows"][f"groq/{room}"][0].used_ratio, 0.5
        )

        cache = {
            "status": "ok",
            "index_version": "4.3",
            "fetched_at_epoch": self.MOMENT,
            "records": [
                aa_record(spent.rsplit("/", 1)[-1], 42.0),
                aa_record(room.rsplit("/", 1)[-1], 41.0),
            ],
        }
        ranked = ranking.rank_models(
            models=[
                ranking.ModelRecord("groq", spent),
                ranking.ModelRecord("groq", room),
            ],
            catalog=catalog,
            quota_windows=inputs["windows"],
            free_models={("groq", spent), ("groq", room)},
            promo_models=set(),
            usage_tokens={},
            aa_cache=cache,
            now=self.MOMENT,
        )
        remaining = {(entry.provider, entry.model): entry.remaining for entry in ranked}
        self.assertEqual(remaining[("groq", spent)], 0.0)
        self.assertEqual(remaining[("groq", room)], 0.5)

        snapshot_data = snapshot.build_snapshot(
            now=self.MOMENT,
            sources=[],
            ranked=ranked,
            catalog=catalog,
            measured_windows=result.windows,
        )
        accounts = snapshot_data["quota"]["accounts"]["groq"]
        self.assertEqual(
            sorted(tuple(record["applies_to"]) for record in accounts),
            sorted([(spent,), (room,)]),
        )
        # No window applies to the whole account, so the provider keeps no
        # account-wide capacity and neither model locks the other out.
        self.assertEqual(
            snapshot_data["quota"]["provider_capacity"]["groq"]["windows"], 0
        )

        text = main.render([result], [], self.MOMENT, 0.1, snapshot_data)
        remaining_published = {}
        for line in text.splitlines():
            if not line.startswith("ghostship_ai_account_window_remaining_ratio{"):
                continue
            for model in (spent, room):
                if f'quota_id="rpd@{model}"' in line:
                    remaining_published[model] = float(line.rsplit(" ", 1)[-1])
        self.assertEqual(remaining_published, {spent: 0.0, room: 0.5})
        self.assertFalse(
            any(
                line.startswith("ghostship_ai_provider_capacity_remaining_ratio{")
                and 'provider="groq"' in line
                for line in text.splitlines()
            ),
            "a per-model window is never published as the provider's capacity",
        )

    def test_an_expired_or_stale_reading_is_not_current_capacity(self):
        expired = "llama-3.3-70b-versatile"
        stale = self.MODEL
        status = {
            "quota_observations": [
                observation(
                    expired,
                    observed=1000.0,
                    rpd={"limit": 100, "remaining": 50, "reset": "2s"},
                ),
                observation(
                    stale,
                    observed=1000.0,
                    rpd={"limit": 100, "remaining": 50, "reset": "1h"},
                ),
            ]
        }
        # The first window refilled at 1002, and the second reading is 1801
        # seconds old: neither is current headroom or a lockout.
        result = self.collect(status, now=2801.0)
        self.assertEqual(result.windows, [])
        self.assertTrue(
            [
                name
                for name, _labels, _value in result.metrics
                if name == "ghostship_ai_pool_quota_amount"
            ],
            "the observation stays a diagnostic",
        )

    def test_pool_admission_caps_are_not_provider_capacity(self):
        catalog = {
            "providers": {
                "groq": {
                    "selected_model": self.MODEL,
                    "candidates": [
                        {
                            "model": self.MODEL,
                            "available": True,
                            "admissions": {"light": {"admitted": True, "score": 0.8}},
                            "account_limits": {"rpd": 1000, "tpm": 8000},
                            "model_limits": {},
                        }
                    ],
                }
            }
        }
        result = self.collect({}, catalog=catalog)
        self.assertEqual(result.windows, [])
        self.assertTrue(
            [
                labels
                for name, labels, _value in result.metrics
                if name == "ghostship_ai_pool_limit"
                and labels.get("scope") == "account"
            ],
            "the pool's own caps stay local admission metrics",
        )

    def test_no_unusable_reading_becomes_capacity(self):
        invalid = [
            ("remaining above the limit", {"limit": 100, "remaining": 101, "reset": "1m"}),
            ("a boolean limit", {"limit": True, "remaining": 1, "reset": "1m"}),
            ("a NaN limit", {"limit": float("nan"), "remaining": 1, "reset": "1m"}),
            ("an infinite remaining", {"limit": 100, "remaining": float("inf"), "reset": "1m"}),
            ("a zero limit", {"limit": 0, "remaining": 0, "reset": "1m"}),
            ("a malformed reset", {"limit": 100, "remaining": 50, "reset": "2s garbage"}),
            ("a boolean remaining", {"limit": 100, "remaining": False, "reset": "1m"}),
            ("no reset", {"limit": 100, "remaining": 50}),
            ("a negative remaining", {"limit": 100, "remaining": -1, "reset": "1m"}),
        ]
        observations = [
            observation(f"invalid-{index}", observed=1000.0, rpd=values)
            for index, (_reason, values) in enumerate(invalid)
        ]
        observations.append(
            observation("unknown-unit", observed=1000.0, rph={"limit": 100, "remaining": 50, "reset": "1m"})
        )
        observations.append(
            observation(
                "unknown-scope",
                observed=1000.0,
                rpd={"limit": 100, "remaining": 50, "reset": "1m"},
                scope="account",
            )
        )
        missing = observation(
            "missing-observation",
            observed=1000.0,
            rpd={"limit": 100, "remaining": 50, "reset": "1m"},
        )
        missing["observed_at"] = None
        observations.append(missing)
        result = self.collect({"quota_observations": observations})
        self.assertEqual(result.windows, [])


if __name__ == "__main__":
    unittest.main()
