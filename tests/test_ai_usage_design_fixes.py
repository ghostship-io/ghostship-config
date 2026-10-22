"""The design fixes of the routing collector.

Every test here names the defect it catches. The defects are the findings of
the routing design audit: F1 account attribution, F2 the dedicated free tier,
F3 the access classification, F4 the limits of the free pool, F5 the missing
decision metrics, F7 the honest score, F8 the stale text, F9 the duplicated
policy lists, and the observed runtime availability of a route.
"""

import importlib.util
import json
import tempfile
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


def aa_record(slug, name, index=80.0, cost=0.2):
    """One measured Artificial Analysis record."""
    return {
        "id": f"id-{slug}",
        "slug": slug,
        "model": name,
        "release_date": "2026-01-20",
        "indices": {"intelligence_index": index},
        "cost_per_task": cost,
        "median_performance": 100.0,
        "prices": {},
    }


def build_free_snapshot(models, records, *, native=(), free=(), pool_evidence=None):
    """Build a snapshot of the free routes and their tiers."""
    document = {}
    for provider, model in models:
        for key in {provider, *catalog_module.PROVIDER_ALIASES.get(provider, ())}:
            document.setdefault(key, {"models": {}})["models"][model] = {
                "id": model,
                "name": model,
                "family": model,
                "release_date": "2026-01-20",
                "limit": {"context": 200000},
                "cost": {"input": 0.0, "output": 0.0},
            }
    catalog = catalog_module.Catalog(document)
    cache = {
        "status": "ok",
        "index_version": "4.3",
        "fetched_at_epoch": NOW,
        "records": records,
    }
    ranked = ranking.rank_models(
        models=[ranking.ModelRecord(provider, model) for provider, model in models],
        catalog=catalog,
        quota_windows={},
        free_models=set(free),
        promo_models=set(),
        usage_tokens={},
        aa_cache=cache,
        now=NOW,
    )
    return snapshot.build_snapshot(
        now=NOW,
        sources=[{"id": "t3", "status": "ok", "reason": "ok", "observed_at_epoch": NOW}],
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
        free_models=set(free),
        promo_models=set(),
        pool_evidence=pool_evidence or {},
    )


class SnapshotWriteTests(unittest.TestCase):
    """The snapshot and its projections are written on every run."""

    def test_every_run_writes_the_snapshot_and_both_projections(self):
        import tempfile

        main = _load("ai_usage_design_main_write", "main")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "ai-usage.prom"
            canonical = root / "routing.json"
            first = root / "one" / "model-routing.json"
            second = root / "two" / "model-routing.json"
            code = main.main(
                [
                    "--output",
                    str(output),
                    "--snapshot",
                    str(canonical),
                    "--projection",
                    str(first),
                    "--projection",
                    str(second),
                    "--state",
                    str(root / "state.json"),
                    "--facts",
                    str(root / "facts.json"),
                    "--aa-cache",
                    str(root / "missing-aa.json"),
                    "--aa-3d-cache",
                    str(root / "missing-aa3d.json"),
                    "--now",
                    str(NOW),
                ]
            )
            self.assertEqual(code, 0)
            for path in (output, canonical, first, second):
                self.assertTrue(path.exists(), f"{path} was not written")
                self.assertGreater(path.stat().st_size, 0)
            document = json.loads(canonical.read_text(encoding="utf-8"))
            self.assertEqual(document["schema"], snapshot.SCHEMA)
            # The evidence is missing, and every tier says so.
            for tier in snapshot.TIER_NAMES:
                state = document["coverage"]["tiers"][tier]["state"]
                self.assertEqual(state, "pending_aa_evidence")
                self.assertIn("Artificial Analysis", document["coverage"]["tiers"][tier]["reason"])

    def test_a_write_failure_is_not_swallowed(self):
        with tempfile.TemporaryDirectory() as folder:
            blocked = Path(folder) / "blocked"
            blocked.write_text("not a directory", encoding="utf-8")
            with self.assertRaises(OSError):
                snapshot.write_snapshot(blocked / "routing.json", {"schema": "x"})


class ValuePolicyTests(unittest.TestCase):
    """The value formula comes from one policy constant."""

    def _policy(self):
        return _load("ai_usage_design_value_policy", "value_policy")

    def test_the_weights_come_from_one_place(self):
        policy = self._policy()
        self.assertEqual(policy.VALUE_WEIGHTS, {"intelligence": 0.70, "cost_per_task": 0.30})
        self.assertEqual(
            policy.VALUE_3D_WEIGHTS,
            {"intelligence": 0.45, "three_d": 0.25, "cost_per_task": 0.30},
        )
        self.assertAlmostEqual(sum(policy.VALUE_WEIGHTS.values()), 1.0, places=6)
        self.assertAlmostEqual(sum(policy.VALUE_3D_WEIGHTS.values()), 1.0, places=6)

    def test_the_snapshot_publishes_the_weights_and_the_transform(self):
        document = snapshot.value_policy.policy_document()
        self.assertEqual(document["value"]["weights"], {"intelligence": 0.70, "cost_per_task": 0.30})
        self.assertEqual(
            document["value_3d"]["weights"],
            {"intelligence": 0.45, "three_d": 0.25, "cost_per_task": 0.30},
        )
        self.assertIn("inverse", document["cost_transforms"])
        self.assertIn("minmax", document["cost_transforms"])
        self.assertIn("median_relative", document["cost_transforms"])
        self.assertEqual(document["cost_transform_in_force"], "inverse")
        self.assertFalse(document["renormalized"])

    def test_the_weights_are_published_as_a_metric(self):
        data = snapshot.build_snapshot(
            now=NOW,
            sources=[{"id": "t3", "status": "ok", "reason": "ok", "observed_at_epoch": NOW}],
            ranked=[],
        )
        samples = snapshot.decision_samples(data)
        found = {
            (labels["component"], labels["weight"]): value
            for name, labels, value in samples
            if name == "ghostship_ai_calculation_weight"
        }
        self.assertAlmostEqual(found[("value", "intelligence")], 0.70, places=6)
        self.assertAlmostEqual(found[("value", "cost_per_task")], 0.30, places=6)
        self.assertAlmostEqual(found[("value_3d", "three_d")], 0.25, places=6)

    def test_the_transform_is_published_as_a_metric(self):
        data = snapshot.build_snapshot(
            now=NOW,
            sources=[{"id": "t3", "status": "ok", "reason": "ok", "observed_at_epoch": NOW}],
            ranked=[],
        )
        samples = snapshot.decision_samples(data)
        transforms = {
            labels["transform"]
            for name, labels, _value in samples
            if name == "ghostship_ai_calculation_transform"
        }
        self.assertIn("inverse", transforms)
        self.assertIn("minmax", transforms)
        self.assertIn("median_relative", transforms)

    def test_the_default_transform_is_the_reciprocal(self):
        policy = self._policy()
        value, evidence = policy.cost_transform(1.5, [0.1, 5.0], "inverse")
        self.assertAlmostEqual(value, 1.0 / 2.5, places=6)
        self.assertEqual(evidence["transform"], "inverse")

    def test_the_minmax_transform_is_relative_to_the_cohort(self):
        policy = self._policy()
        # The dearest model of the cohort has no efficiency, the cheapest
        # has all of it, and the one in the middle has half.
        dearest, evidence = policy.cost_transform(9.0, [1.0, 5.0, 9.0], "minmax")
        self.assertAlmostEqual(dearest, 0.0, places=6)
        self.assertEqual(evidence["cohort_min"], 1.0)
        self.assertEqual(evidence["cohort_max"], 9.0)
        middle, _evidence = policy.cost_transform(5.0, [1.0, 5.0, 9.0], "minmax")
        self.assertAlmostEqual(middle, 0.5, places=6)

    def test_the_median_relative_transform_is_relative_to_the_median(self):
        policy = self._policy()
        # A model that costs the median has the same efficiency as a model
        # that costs twice the median: the scale is relative.
        value, evidence = policy.cost_transform(1.0, [1.0, 2.0, 3.0], "median_relative")
        self.assertAlmostEqual(value, 2.0 / 3.0, places=6)
        self.assertEqual(evidence["cohort_median"], 2.0)

    def test_a_missing_input_leaves_the_value_unknown(self):
        policy = self._policy()
        value, missing = policy.combine(
            {"intelligence": 0.9, "cost_per_task": None}, policy.VALUE_WEIGHTS
        )
        self.assertIsNone(value)
        self.assertEqual(missing, ["cost_per_task"])

    def test_the_3d_value_combines_the_capability_with_the_intelligence(self):
        policy = self._policy()
        value, missing = policy.combine(
            {"intelligence": 0.518, "three_d": 0.6, "cost_per_task": 0.9},
            policy.VALUE_3D_WEIGHTS,
        )
        self.assertEqual(missing, [])
        self.assertAlmostEqual(
            value, 0.45 * 0.518 + 0.25 * 0.6 + 0.30 * 0.9, places=6
        )


class PoolLimitTests(unittest.TestCase):
    """F4: the pool's limits reach the decision and carry their basis."""

    def _result(self, samples):
        metrics = _load("ai_usage_design_metrics", "metrics")
        return metrics.SourceResult(
            source="free_pool", status="ok", reason="ok", metrics=samples
        )

    def _inputs(self, samples, now=NOW):
        main = _load("ai_usage_design_main_limits", "main")
        results = [self._result(samples)]
        return main, main.ranking_inputs(results, catalog_module.Catalog({}), {}, [], now=now)

    def test_every_limit_is_published_with_its_basis(self):
        main, inputs = self._inputs(
            [
                (
                    "ghostship_ai_pool_model_info",
                    {"provider": "kilo", "model": "cohere/north-mini-code:free"},
                    1.0,
                ),
                (
                    "ghostship_ai_pool_limit",
                    {"provider": "kilo", "model": "*", "limit": "rpm", "scope": "account"},
                    2.0,
                ),
                (
                    "ghostship_ai_pool_observed_limit",
                    {"provider": "kilo", "model": "*", "limit": "rpd", "scope": "account"},
                    200.0,
                ),
            ]
        )
        samples = main.provider_limit_samples(inputs)
        found = {
            (labels["limit"], labels["basis"]): value
            for name, labels, value in samples
            if name == "ghostship_ai_provider_limit"
        }
        self.assertEqual(found[("rpm", "configured")], 2.0)
        self.assertEqual(found[("rpd", "observed")], 200.0)
        # The provider's own published limit is a third, separate reading.
        self.assertIn(("rph", "published"), found)
        self.assertEqual(found[("rph", "published")], 200.0)

    def test_a_documented_limit_without_a_number_is_unknown(self):
        main = _load("ai_usage_design_main_limits", "main")
        published = _load("ai_usage_design_pool_published", "pool_published")
        limits = dict(
            (name, (value, basis))
            for name, value, basis in published.published_limits("google")
        )
        self.assertEqual(limits["rpm"][1], "unknown")
        self.assertEqual(limits["rpm"][0], published.UNKNOWN_LIMIT_VALUE)

    def test_an_implausible_cooldown_is_an_issue_and_never_blocks(self):
        # kilo-keyed's cooldown is a millisecond timestamp read as seconds.
        impossible = 1001792618529
        samples = [
            (
                "ghostship_ai_pool_model_info",
                {"provider": "kilo-keyed", "model": "cohere/north-mini-code:free"},
                1.0,
            ),
            (
                "ghostship_ai_pool_model_available",
                {"provider": "kilo-keyed", "model": "cohere/north-mini-code:free"},
                0.0,
            ),
            (
                "ghostship_ai_pool_model_cooldown_until_seconds",
                {"provider": "kilo-keyed", "model": "*"},
                float(impossible),
            ),
        ]
        main, inputs = self._inputs(samples)
        route = ("kilo-keyed", "cohere/north-mini-code:free")
        self.assertEqual(inputs["pool_issues"].get(route), ["invalid_cooldown"])
        # The route is not blocked by a cooldown that cannot be true.
        self.assertTrue(inputs["external"].get(route))
        evidence = inputs["pool_evidence"][route]
        self.assertIn("invalid_cooldown", evidence["issues"])

    def test_a_real_cooldown_still_blocks_the_route(self):
        samples = [
            (
                "ghostship_ai_pool_model_info",
                {"provider": "kilo", "model": "cohere/north-mini-code:free"},
                1.0,
            ),
            (
                "ghostship_ai_pool_model_available",
                {"provider": "kilo", "model": "cohere/north-mini-code:free"},
                0.0,
            ),
            (
                "ghostship_ai_pool_model_cooldown_until_seconds",
                {"provider": "kilo", "model": "cohere/north-mini-code:free"},
                float(NOW + 3600),
            ),
        ]
        _main, inputs = self._inputs(samples)
        route = ("kilo", "cohere/north-mini-code:free")
        self.assertFalse(inputs["external"].get(route))
        self.assertNotIn(route, inputs["pool_issues"])

    def test_the_admission_of_a_route_reaches_the_snapshot(self):
        samples = [
            (
                "ghostship_ai_pool_model_info",
                {"provider": "kilo", "model": "cohere/north-mini-code:free"},
                1.0,
            ),
            (
                "ghostship_ai_pool_model_admission",
                {"provider": "kilo", "model": "cohere/north-mini-code:free", "workload": "light"},
                1.0,
            ),
        ]
        _main, inputs = self._inputs(samples)
        route = ("kilo", "cohere/north-mini-code:free")
        self.assertEqual(
            inputs["pool_evidence"][route]["admission"],
            [{"workload": "light", "admitted": True}],
        )


class FreeTierTests(unittest.TestCase):

    POOL_MODEL = ("kilo", "cohere/north-mini-code:free")
    RECORDS = [aa_record("north-mini-code", "North Mini Code")]

    def _free_winners(self, data):
        return [
            winner
            for winner in (data.get("tier_winners") or {}).get("free") or []
        ]

    def test_a_pool_route_with_an_admission_wins_the_free_tier(self):
        data = build_free_snapshot(
            [self.POOL_MODEL],
            self.RECORDS,
            free=[self.POOL_MODEL],
            pool_evidence={
                self.POOL_MODEL: {
                    "admission": [{"workload": "light", "admitted": True}],
                    "limits": [],
                    "issues": [],
                }
            },
        )
        winners = self._free_winners(data)
        self.assertEqual([(w["provider"], w["model"]) for w in winners], [self.POOL_MODEL])
        samples = snapshot.decision_samples(data)
        self.assertIn(
            (
                "ghostship_ai_model_winner",
                {"tier": "free", "provider": "kilo", "model": "cohere/north-mini-code:free"},
                1.0,
            ),
            samples,
        )

    def test_a_pool_route_without_an_admission_never_wins_the_free_tier(self):
        data = build_free_snapshot(
            [self.POOL_MODEL],
            self.RECORDS,
            free=[self.POOL_MODEL],
            pool_evidence={self.POOL_MODEL: {"admission": [], "limits": [], "issues": []}},
        )
        self.assertEqual(self._free_winners(data), [])

    def test_a_native_free_route_wins_the_free_tier_and_is_delegatable(self):
        route = ("openrouter", "cohere/north-mini-code:free")
        data = build_free_snapshot(
            [route],
            self.RECORDS,
            native=[route],
            free=[route],
        )
        winners = self._free_winners(data)
        self.assertEqual([(w["provider"], w["model"]) for w in winners], [route])
        research = data["recommendations"]["research"]
        self.assertEqual((research["provider"], research["model"]), route)
        self.assertTrue(research["delegate"])
        self.assertEqual(research["tier"], "free")

    def test_a_pool_route_is_never_a_delegate(self):
        data = build_free_snapshot(
            [self.POOL_MODEL],
            self.RECORDS,
            free=[self.POOL_MODEL],
            pool_evidence={
                self.POOL_MODEL: {
                    "admission": [{"workload": "light", "admitted": True}],
                    "limits": [],
                    "issues": [],
                }
            },
        )
        research = data["recommendations"]["research"]
        self.assertEqual((research["provider"], research["model"]), self.POOL_MODEL)
        self.assertFalse(research["delegate"])
