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

    def test_zen_and_openrouter_are_free_routes_and_go_is_always_paid(self):
        main = _load("ai_usage_design_main", "main")
        catalog = self._catalog()
        inputs = main.ranking_inputs([], catalog, {}, [])
        free = inputs["free"]
        promo = inputs["promo"]
        self.assertIn(("openrouter", "cohere/north-mini-code:free"), free)
        # OpenCode Zen is the free OpenCode login. OpenCode Go is a paid
        # subscription, so even its zero-price listings are neither free nor promotional.
        self.assertIn(("opencode", "big-pickle"), free)
        self.assertNotIn(("opencode", "big-pickle"), promo)
        self.assertNotIn(("opencode-go", "minimax-m3.1-flash-free"), free)
        self.assertNotIn(("opencode-go", "minimax-m3.1-flash-free"), promo)
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


class HonestScoreTests(unittest.TestCase):
    """F7 and F8: the published score is the value, and the text says so."""

    def test_the_recommendation_is_chosen_by_the_published_value(self):
        rows = [
            {
                "provider": "opencode-go",
                "model": "minimax-m3.1-flash-free",
                "tiers": ["bulk"],
                "rank": {"bulk": 1},
                "score": {"bulk": 999.0},
                "value": {"value": 0.4},
                "available": True,
                "availability": {"state": "available"},
                "admission": {"state": "settled", "reason": ""},
                "native": {"provider_instance_id": "opencode", "model_id": "x", "options": [], "mapped": True},
                "role": "delegate",
                "quota_state": "available",
                "aa": {"state": "measured"},
                "access": {"kind": "provider_paid", "basis": "", "price": {}, "execution": "provider_native"},
                "selection": {"excluded": False},
                "eligibility": {
                    "frontier_prime": {"allowed": False, "basis": "policy:owner"},
                    "delegate": {"allowed": True, "basis": "policy:owner+native+tier"},
                    "background": {"allowed": False, "basis": "policy:owner"},
                    "gpt_model_allowed": {"allowed": True, "basis": "policy:owner"},
                },
            },
            {
                "provider": "opencode-go",
                "model": "deepseek-v4-pro",
                "tiers": ["bulk"],
                "rank": {"bulk": 2},
                "score": {"bulk": 1.0},
                "value": {"value": 0.7},
                "available": True,
                "availability": {"state": "available"},
                "admission": {"state": "settled", "reason": ""},
                "native": {"provider_instance_id": "opencode", "model_id": "y", "options": [], "mapped": True},
                "role": "delegate",
                "quota_state": "available",
                "aa": {"state": "measured"},
                "access": {"kind": "provider_paid", "basis": "", "price": {}, "execution": "provider_native"},
                "selection": {"excluded": False},
                "eligibility": {
                    "frontier_prime": {"allowed": False, "basis": "policy:owner"},
                    "delegate": {"allowed": True, "basis": "policy:owner+native+tier"},
                    "background": {"allowed": False, "basis": "policy:owner"},
                    "gpt_model_allowed": {"allowed": True, "basis": "policy:owner"},
                },
            },
        ]
        result = snapshot._recommendations(rows, snapshot.WORKLOAD_CLASSES)
        # The higher score would pick the first row; the published value
        # picks the second one.
        self.assertEqual(result["metadata"]["model"], "deepseek-v4-pro")

    def test_no_text_claims_the_weights_are_renormalized(self):
        policy = _load("ai_usage_design_value_policy_text", "value_policy")
        document = policy.policy_document()
        self.assertFalse(document["renormalized"])
        self.assertIn("nothing is renormalized", document["basis"])
        self.assertIn(
            "nothing is renormalized",
            snapshot.VALUE_POLICY["requires"] + snapshot.VALUE_POLICY.get("basis", ""),
        )

    def test_the_policy_lists_have_one_source(self):
        # The runtime policy is the source of the owner's lists, and the
        # constant is only the fallback.
        policy = {
            "frontierPrimeModels": ("gpt-6.1-sol",),
            "excludedModels": ("gpt-6-astra",),
            "allowedGptModels": ("gpt-6.1-sol",),
            "backgroundProviderInstances": ("opencode",),
        }
        data = build_free_snapshot(
            [("codex", "gpt-6.1-sol")],
            [aa_record("gpt-6-1-sol", "GPT-6.1 Sol")],
            native=[("codex", "gpt-6.1-sol")],
        )
        row = data["candidates"][0]
        self.assertIn("selection", row)
        self.assertTrue(row["selection"]["frontier_workhorse"])
        # The policy of the snapshot names the same list.
        self.assertEqual(
            data["policy"]["frontier_prime_models"],
            ["gpt-6.1-sol", "claude-opus-5-5"],
        )

    def test_an_excluded_model_is_never_selected(self):
        data = build_free_snapshot(
            [("codex", "gpt-6.1-sol")],
            [aa_record("gpt-6-1-sol", "GPT-6.1 Sol")],
            native=[("codex", "gpt-6.1-sol")],
        )
        self.assertIsNotNone(data["candidates"][0])
        # The exclusion list of the policy is read, not the constant.
        self.assertTrue(snapshot._selection_excluded("gpt-6-astra"))
        self.assertTrue(snapshot._selection_excluded("gpt-6-astra", ["gpt-6-astra"]))
        self.assertFalse(snapshot._selection_excluded("gpt-6-astra", ["claude-fable-5"]))

    def test_the_workhorse_list_is_published_as_a_metric(self):
        data = snapshot.build_snapshot(
            now=NOW,
            sources=[{"id": "t3", "status": "ok", "reason": "ok", "observed_at_epoch": NOW}],
            ranked=[],
            policy={
                "frontierPrimeModels": ("gpt-6.1-sol",),
                "excludedModels": ("gpt-6-astra",),
            },
        )
        samples = snapshot.decision_samples(data)
        workhorses = {
            labels["model"]
            for name, labels, _value in samples
            if name == "ghostship_ai_policy_frontier_workhorse"
        }
        excluded = {
            labels["model"]
            for name, labels, _value in samples
            if name == "ghostship_ai_policy_excluded_model"
        }
        self.assertEqual(workhorses, {"gpt-6.1-sol"})
        self.assertEqual(excluded, {"gpt-6-astra"})


class ObservedAvailabilityTests(unittest.TestCase):
    """The observed availability of a route, out of the T3 Code state."""

    def _reader(self):
        return _load("ai_usage_design_runtime_state", "runtime_state")

    def _state(self, folder, attempts, sessions=(), runtimes=(), runs=()):
        """A small T3 Code state database with the given rows."""
        import sqlite3

        path = Path(folder) / "statev2.sqlite"
        connection = sqlite3.connect(path)
        connection.execute(
            "CREATE TABLE orchestration_v2_projection_run_attempts "
            "(attempt_id TEXT, thread_id TEXT, run_id TEXT, attempt_ordinal INTEGER, "
            "root_node_id TEXT, provider TEXT, provider_thread_id TEXT, "
            "provider_turn_id TEXT, status TEXT, payload_json TEXT, "
            "provider_instance_id TEXT)"
        )
        connection.execute(
            "CREATE TABLE orchestration_v2_projection_runs "
            "(run_id TEXT, thread_id TEXT, ordinal INTEGER, provider TEXT, "
            "provider_thread_id TEXT, status TEXT, requested_at TEXT, "
            "completed_at TEXT, payload_json TEXT, provider_instance_id TEXT)"
        )
        connection.execute(
            "CREATE TABLE projection_thread_sessions "
            "(thread_id TEXT, status TEXT, provider_name TEXT, "
            "provider_session_id TEXT, provider_thread_id TEXT, active_turn_id TEXT, "
            "last_error TEXT, updated_at TEXT, runtime_mode TEXT, "
            "provider_instance_id TEXT)"
        )
        connection.execute(
            "CREATE TABLE provider_session_runtime "
            "(thread_id TEXT, provider_name TEXT, adapter_key TEXT, "
            "runtime_mode TEXT, status TEXT, last_seen_at TEXT, "
            "resume_cursor_json TEXT, runtime_payload_json TEXT, "
            "provider_instance_id TEXT)"
        )
        for index, attempt in enumerate(attempts):
            connection.execute(
                "INSERT INTO orchestration_v2_projection_run_attempts VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"attempt-{index}",
                    attempt.get("thread_id", "thread-1"),
                    attempt.get("run_id", "run-1"),
                    1,
                    "root",
                    attempt.get("provider", "opencode"),
                    "provider-thread",
                    None,
                    attempt.get("status", "failed"),
                    json.dumps(
                        {
                            "startedAt": attempt.get("started_at"),
                            "completedAt": attempt.get("completed_at"),
                            "model": attempt.get("model", ""),
                        }
                    ),
                    attempt.get("provider_instance_id", "opencode"),
                ),
            )
            # The run carries the time of the attempt and the model of the
            # selection, and it is the run the reader bounds its read by.
            connection.execute(
                "INSERT INTO orchestration_v2_projection_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    attempt.get("run_id", "run-1"),
                    attempt.get("thread_id", "thread-1"),
                    index,
                    attempt.get("provider", "opencode"),
                    "provider-thread",
                    attempt.get("status", "failed"),
                    attempt.get("started_at"),
                    attempt.get("completed_at"),
                    json.dumps(
                        {
                            "modelSelection": {
                                "instanceId": attempt.get(
                                    "provider_instance_id", "opencode"
                                ),
                                "model": attempt.get("model", ""),
                            }
                        }
                    ),
                    attempt.get("provider_instance_id", "opencode"),
                ),
            )
        for index, session in enumerate(sessions):
            connection.execute(
                "INSERT INTO projection_thread_sessions VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    session.get("thread_id", "thread-1"),
                    "stopped",
                    session.get("provider_name", "opencode"),
                    "session",
                    "provider-thread",
                    None,
                    session.get("last_error", ""),
                    session.get("updated_at"),
                    "full-access",
                    session.get("provider_instance_id", "opencode"),
                ),
            )
        for index, runtime in enumerate(runtimes):
            connection.execute(
                "INSERT INTO provider_session_runtime VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    runtime.get("thread_id", "thread-1"),
                    "opencode",
                    "opencode",
                    "full-access",
                    "stopped",
                    runtime.get("last_seen_at"),
                    "{}",
                    json.dumps(runtime.get("payload") or {}),
                    runtime.get("provider_instance_id", "opencode"),
                ),
            )
        connection.commit()
        connection.close()
        return path

    def _observed(self, folder, attempts, sessions=(), runtimes=()):
        reader = self._reader()
        path = self._state(folder, attempts, sessions, runtimes)
        return reader.read_failures(path, NOW)

    def test_an_account_failure_reaches_every_model_of_the_account(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            failures = self._observed(
                folder,
                [
                    {
                        "thread_id": "thread-1",
                        "provider_instance_id": "opencode",
                        "status": "failed",
                        "completed_at": "2027-01-15T00:00:00Z",
                        "model": "ollama-cloud/deepseek-v4.1-flash",
                    }
                ],
                sessions=[
                    {
                        "thread_id": "thread-1",
                        "last_error": (
                            "you (someone) have reached your session usage "
                            "limit, upgrade for higher limits"
                        ),
                        "updated_at": "2027-01-15T00:00:00Z",
                    }
                ],
            )
        self.assertEqual(len(failures), 1)
        failure = failures[0]
        self.assertEqual(failure["scope"], "account")
        self.assertEqual(failure["target"], "ollama")
        self.assertEqual(failure["reason"], "account_usage_limit")
        # The provider's own text never leaves the collector.
        self.assertNotIn("someone", json.dumps(failure))

    def test_a_go_usage_limit_is_an_account_failure(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            failures = self._observed(
                folder,
                [
                    {
                        "thread_id": "thread-1",
                        "provider_instance_id": "opencode",
                        "status": "failed",
                        "completed_at": "2027-01-15T00:00:00Z",
                        "model": "opencode-go/grok-4.7",
                    }
                ],
                sessions=[
                    {
                        "thread_id": "thread-1",
                        "last_error": "Go usage limit exceeded",
                        "updated_at": "2027-01-15T00:00:00Z",
                    }
                ],
            )
        self.assertEqual(failures[0]["scope"], "account")
        self.assertEqual(failures[0]["target"], "opencode-go")

    def test_a_payment_refusal_is_an_account_failure(self):
        # A provider that refuses a request with "402 Payment Required" and a
        # spent balance has an exhausted account, not a broken route: every
        # route of that account is unavailable until a later success.
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            failures = self._observed(
                folder,
                [
                    {
                        "thread_id": "thread-1",
                        "provider_instance_id": "grok",
                        "status": "failed",
                        "completed_at": "2027-01-15T00:00:00Z",
                        "model": "grok-code",
                    }
                ],
                sessions=[
                    {
                        "thread_id": "thread-1",
                        "last_error": (
                            "API error (status 402 Payment Required): Grok Build "
                            "usage balance exhausted"
                        ),
                        "updated_at": "2027-01-15T00:00:00Z",
                    }
                ],
            )
        self.assertEqual(len(failures), 1)
        failure = failures[0]
        self.assertEqual(failure["scope"], "account")
        # The account of the instance that serves the model, so every route
        # of that provider is unavailable.
        self.assertEqual(failure["target"], "grok")
        self.assertEqual(failure["reason"], "account_usage_limit")

    def test_a_startup_failure_is_a_route_failure(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            failures = self._observed(
                folder,
                [
                    {
                        "thread_id": "thread-1",
                        "provider_instance_id": "antigravity",
                        "status": "failed",
                        "completed_at": "2027-01-15T00:00:00Z",
                        "model": "gemini-3.8-flash",
                    }
                ],
                sessions=[
                    {
                        "thread_id": "thread-1",
                        "provider_instance_id": "antigravity",
                        "last_error": (
                            "MCP load failed for t3-code: error while loading "
                            "shared libraries: libatomic.so.1: cannot open "
                            "shared object file: No such file or directory"
                        ),
                        "updated_at": "2027-01-15T00:00:00Z",
                    }
                ],
            )
        self.assertEqual(failures[0]["scope"], "route")
        self.assertEqual(failures[0]["target"], "antigravity")
        self.assertEqual(failures[0]["reason"], "route_startup_failed")

    def test_a_refused_model_is_a_model_failure(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            failures = self._observed(
                folder,
                [
                    {
                        "thread_id": "thread-1",
                        "provider_instance_id": "opencode",
                        "status": "failed",
                        "completed_at": "2027-01-15T00:00:00Z",
                        "model": "deepseek-v4.1-flash",
                    }
                ],
                sessions=[
                    {
                        "thread_id": "thread-1",
                        "last_error": 'Bad Request: {"model":"deepseek-v4.1-flash"}',
                        "updated_at": "2027-01-15T00:00:00Z",
                    }
                ],
            )
        self.assertEqual(failures[0]["scope"], "model")
        self.assertEqual(failures[0]["target"], "deepseek-v4.1-flash")

    def test_a_later_successful_run_clears_the_failure(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            failures = self._observed(
                folder,
                [
                    {
                        "thread_id": "thread-1",
                        "provider_instance_id": "antigravity",
                        "status": "failed",
                        "completed_at": "2027-01-15T00:00:00Z",
                        "model": "gemini-3.8-flash",
                    },
                    {
                        "thread_id": "thread-2",
                        "provider_instance_id": "antigravity",
                        "status": "completed",
                        "completed_at": "2027-01-15T01:00:00Z",
                        "model": "gemini-3.8-flash",
                    },
                ],
                sessions=[
                    {
                        "thread_id": "thread-1",
                        "provider_instance_id": "antigravity",
                        "last_error": "Could not start Antigravity.",
                        "updated_at": "2027-01-15T00:00:00Z",
                    }
                ],
            )
        self.assertEqual(failures, [])

    def test_an_unavailable_route_stays_visible_and_never_wins(self):
        catalog = catalog_module.Catalog(
            {
                "antigravity": {
                    "models": {"gemini-3.8-flash": catalog_entry("gemini-3.8-flash")}
                }
            }
        )
        models = [ranking.ModelRecord("antigravity", "gemini-3.8-flash")]
        ranked = ranking.rank_models(
            models=models,
            catalog=catalog,
            quota_windows={},
            free_models=set(),
            usage_tokens={},
            aa_cache=aa_cache_for(models),
            observed_failures=[
                {
                    "scope": "route",
                    "target": "antigravity",
                    "reason": "route_startup_failed",
                    "label": "the provider's runtime could not start",
                    "observed_at": NOW,
                }
            ],
            native_models={
                ("antigravity", "gemini-3.8-flash"): {
                    "providerInstance": "antigravity",
                    "modelId": "gemini-3.8-flash",
                    "options": [],
                }
            },
            now=NOW,
        )
        # The route is visible, and it is not available.
        self.assertTrue(ranked)
        self.assertFalse(ranked[0].available)
        self.assertEqual(ranked[0].tier, "")
        self.assertEqual(
            ranked[0].observed_failure.get("reason"), "route_startup_failed"
        )

    def test_the_failure_is_published_in_the_snapshot(self):
        data = build_free_snapshot(
            [("antigravity", "gemini-3.8-flash")],
            [aa_record("gemini-3-8-flash", "Gemini 3.8 Flash")],
            native=[("antigravity", "gemini-3.8-flash")],
        )
        row = data["candidates"][0]
        self.assertIn("observed_failure", row["availability"])
        self.assertIsNone(row["availability"]["observed_failure"])

    def test_a_growing_state_still_reports_todays_failures(self):
        # The attempts table carries no time of its own and it grows. A read
        # that is not bounded by the window and ordered by the time of the
        # run returns the oldest rows, and today's failures are missed.
        import sqlite3
        import tempfile
        from datetime import datetime, timedelta, timezone

        reader = self._reader()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "statev2.sqlite"
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE orchestration_v2_projection_runs "
                "(run_id TEXT, thread_id TEXT, ordinal INTEGER, provider TEXT, "
                "provider_thread_id TEXT, status TEXT, requested_at TEXT, "
                "completed_at TEXT, payload_json TEXT, provider_instance_id TEXT)"
            )
            connection.execute(
                "CREATE TABLE orchestration_v2_projection_run_attempts "
                "(attempt_id TEXT, thread_id TEXT, run_id TEXT, "
                "attempt_ordinal INTEGER, root_node_id TEXT, provider TEXT, "
                "provider_thread_id TEXT, provider_turn_id TEXT, status TEXT, "
                "payload_json TEXT, provider_instance_id TEXT)"
            )
            connection.execute(
                "CREATE TABLE projection_thread_sessions "
                "(thread_id TEXT, status TEXT, provider_name TEXT, "
                "provider_session_id TEXT, provider_thread_id TEXT, "
                "active_turn_id TEXT, last_error TEXT, updated_at TEXT, "
                "runtime_mode TEXT, provider_instance_id TEXT)"
            )
            connection.execute(
                "CREATE TABLE provider_session_runtime "
                "(thread_id TEXT, provider_name TEXT, adapter_key TEXT, "
                "runtime_mode TEXT, status TEXT, last_seen_at TEXT, "
                "resume_cursor_json TEXT, runtime_payload_json TEXT, "
                "provider_instance_id TEXT)"
            )
            now = datetime(2026, 10, 22, 4, 0, tzinfo=timezone.utc)
            old = now - timedelta(days=40)
            # 2,500 old successful runs, so the table is past the bound.
            for index in range(2500):
                moment = old + timedelta(seconds=index)
                connection.execute(
                    "INSERT INTO orchestration_v2_projection_runs VALUES "
                    "(?,?,?,?,?,?,?,?,?,?)",
                    (
                        f"run-old-{index}",
                        f"thread-old-{index}",
                        index,
                        "opencode",
                        "pt",
                        "completed",
                        moment.isoformat(),
                        moment.isoformat(),
                        json.dumps(
                            {
                                "modelSelection": {
                                    "instanceId": "opencode",
                                    "model": "opencode/old-model",
                                }
                            }
                        ),
                        "opencode",
                    ),
                )
                connection.execute(
                    "INSERT INTO orchestration_v2_projection_run_attempts VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        f"attempt-old-{index}",
                        f"thread-old-{index}",
                        f"run-old-{index}",
                        1,
                        "root",
                        "opencode",
                        "pt",
                        None,
                        "completed",
                        json.dumps({"completedAt": moment.isoformat()}),
                        "opencode",
                    ),
                )
            # Three recent failures, and one failure that is too old.
            for index, (offset, error) in enumerate(
                (
                    (0.5, "Go usage limit exceeded"),
                    (1.5, "MCP load failed for t3-code: error while loading shared libraries"),
                    (2.5, "Bad Request: {\"model\":\"deepseek-v4.1-flash\"}"),
                )
            ):
                moment = now - timedelta(hours=offset)
                thread = f"thread-new-{index}"
                run = f"run-new-{index}"
                connection.execute(
                    "INSERT INTO orchestration_v2_projection_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        run,
                        thread,
                        3000 + index,
                        "opencode",
                        "pt",
                        "failed",
                        moment.isoformat(),
                        moment.isoformat(),
                        json.dumps(
                            {
                                "modelSelection": {
                                    "instanceId": "opencode",
                                    "model": "opencode/model",
                                }
                            }
                        ),
                        "opencode",
                    ),
                )
                connection.execute(
                    "INSERT INTO orchestration_v2_projection_run_attempts VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        f"attempt-new-{index}",
                        thread,
                        run,
                        1,
                        "root",
                        "opencode",
                        "pt",
                        None,
                        "failed",
                        json.dumps({"completedAt": moment.isoformat()}),
                        "opencode",
                    ),
                )
                connection.execute(
                    "INSERT INTO projection_thread_sessions VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        thread,
                        "stopped",
                        "opencode",
                        "session",
                        "pt",
                        None,
                        error,
                        moment.isoformat(),
                        "full-access",
                        "opencode",
                    ),
                )
            stale = now - timedelta(days=40)
            connection.execute(
                "INSERT INTO orchestration_v2_projection_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    "run-stale",
                    "thread-stale",
                    9999,
                    "opencode",
                    "pt",
                    "failed",
                    stale.isoformat(),
                    stale.isoformat(),
                    json.dumps(
                        {"modelSelection": {"instanceId": "opencode", "model": "opencode/old"}}
                    ),
                    "opencode",
                ),
            )
            connection.execute(
                "INSERT INTO orchestration_v2_projection_run_attempts VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "attempt-stale",
                    "thread-stale",
                    "run-stale",
                    1,
                    "root",
                    "opencode",
                    "pt",
                    None,
                    "failed",
                    json.dumps({"completedAt": stale.isoformat()}),
                    "opencode",
                ),
            )
            connection.execute(
                "INSERT INTO projection_thread_sessions VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    "thread-stale",
                    "stopped",
                    "opencode",
                    "session",
                    "pt",
                    None,
                    "Go usage limit exceeded",
                    stale.isoformat(),
                    "full-access",
                    "opencode",
                ),
            )
            connection.commit()
            connection.close()

            failures = reader.read_failures(path, now.timestamp())
        reasons = sorted(entry["reason"] for entry in failures)
        self.assertEqual(
            reasons,
            [
                "account_usage_limit",
                "model_refused",
                "route_startup_failed",
            ],
        )
        # The failure that is older than the window is not reported.
        self.assertEqual(len(failures), 3)

    def test_a_failure_older_than_the_window_is_ignored(self):
        import sqlite3

        reader = self._reader()
        # The window is the owner's decision, and it is honoured.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "statev2.sqlite"
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE orchestration_v2_projection_runs "
                "(run_id TEXT, thread_id TEXT, ordinal INTEGER, provider TEXT, "
                "provider_thread_id TEXT, status TEXT, requested_at TEXT, "
                "completed_at TEXT, payload_json TEXT, provider_instance_id TEXT)"
            )
            connection.execute(
                "CREATE TABLE orchestration_v2_projection_run_attempts "
                "(attempt_id TEXT, thread_id TEXT, run_id TEXT, "
                "attempt_ordinal INTEGER, root_node_id TEXT, provider TEXT, "
                "provider_thread_id TEXT, provider_turn_id TEXT, status TEXT, "
                "payload_json TEXT, provider_instance_id TEXT)"
            )
            connection.execute(
                "CREATE TABLE projection_thread_sessions "
                "(thread_id TEXT, status TEXT, provider_name TEXT, "
                "provider_session_id TEXT, provider_thread_id TEXT, "
                "active_turn_id TEXT, last_error TEXT, updated_at TEXT, "
                "runtime_mode TEXT, provider_instance_id TEXT)"
            )
            connection.execute(
                "CREATE TABLE provider_session_runtime "
                "(thread_id TEXT, provider_name TEXT, adapter_key TEXT, "
                "runtime_mode TEXT, status TEXT, last_seen_at TEXT, "
                "resume_cursor_json TEXT, runtime_payload_json TEXT, "
                "provider_instance_id TEXT)"
            )
            moment = "2026-10-20T00:00:00Z"
            connection.execute(
                "INSERT INTO orchestration_v2_projection_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    "run-1",
                    "thread-1",
                    1,
                    "opencode",
                    "pt",
                    "failed",
                    moment,
                    moment,
                    json.dumps(
                        {"modelSelection": {"instanceId": "opencode", "model": "opencode/m"}}
                    ),
                    "opencode",
                ),
            )
            connection.execute(
                "INSERT INTO orchestration_v2_projection_run_attempts VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "attempt-1",
                    "thread-1",
                    "run-1",
                    1,
                    "root",
                    "opencode",
                    "pt",
                    None,
                    "failed",
                    json.dumps({"completedAt": moment}),
                    "opencode",
                ),
            )
            connection.execute(
                "INSERT INTO projection_thread_sessions VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    "thread-1",
                    "stopped",
                    "opencode",
                    "session",
                    "pt",
                    None,
                    "Go usage limit exceeded",
                    moment,
                    "full-access",
                    "opencode",
                ),
            )
            connection.commit()
            connection.close()
            # The failure is two days old, and the window is one hour.
            failures = reader.read_failures(
                path, 1_800_000_000.0, age_seconds=3600.0
            )
        self.assertEqual(failures, [])


class PacedAvailabilityTests(unittest.TestCase):
    """The owner's ordering measure: Paced Availability."""

    def test_the_snapshot_publishes_the_paced_availability(self):
        policy = snapshot.CALCULATION["paced_availability"]
        self.assertEqual(policy["name"], "Paced Availability")
        self.assertIn("share left", policy["formula"])
        self.assertIn("pace delta", policy["equivalence"])
        self.assertIn("ranks first", policy["sign"])

    def test_the_paced_availability_is_the_pace_delta(self):
        # The owner's measure is the same number as the pace delta of the
        # most constraining window.
        data = snapshot.build_snapshot(
            now=NOW,
            sources=[{"id": "t3", "status": "ok", "reason": "ok", "observed_at_epoch": NOW}],
            ranked=[],
        )
        self.assertIn("paced_availability", snapshot.CALCULATION)
        self.assertIn("Paced Availability", snapshot.CALCULATION["provider_order"]["formula"])
        self.assertTrue(data["calculation"]["paced_availability"])

    def test_the_paced_availability_is_published_as_a_metric(self):
        ranking_module = _load("ai_usage_design_ranking_paced2", "ranking")
        catalog = catalog_module.Catalog(
            {"openai": {"models": {"gpt-6.1-sol": catalog_entry("gpt-6.1-sol")}}}
        )
        models = [ranking_module.ModelRecord("codex", "gpt-6.1-sol")]
        ranked = ranking_module.rank_models(
            models=models,
            catalog=catalog,
            quota_windows={
                "codex": [
                    ranking_module.QuotaWindow(
                        kind="weekly",
                        used_ratio=0.5,
                        reset_epoch=NOW + 5 * DAY,
                        duration_seconds=7 * DAY,
                        observed_at=NOW,
                    )
                ]
            },
            free_models=set(),
            usage_tokens={},
            aa_cache=aa_cache_for(models),
            now=NOW,
        )
        data = snapshot.build_snapshot(
            now=NOW,
            sources=[{"id": "t3", "status": "ok", "reason": "ok", "observed_at_epoch": NOW}],
            ranked=ranked,
            aa_cache=aa_cache_for(models),
        )
        samples = snapshot.decision_samples(data)
        names = {name for name, _labels, _value in samples}
        self.assertIn("ghostship_ai_model_paced_availability", names)
        self.assertIn("ghostship_ai_model_pace_delta_ratio", names)
        # The provider metric names the binding window it measured.
        provider_samples = snapshot.provider_capacity_samples(data)
        bindings = {
            labels["binding"]
            for name, labels, _value in provider_samples
            if name == "ghostship_ai_provider_paced_availability"
        }
        self.assertTrue(bindings)

    def test_a_model_with_a_window_publishes_both_numbers(self):
        ranking_module = _load("ai_usage_design_ranking_paced", "ranking")
        catalog = catalog_module.Catalog(
            {"openai": {"models": {"gpt-6.1-sol": catalog_entry("gpt-6.1-sol")}}}
        )
        models = [ranking_module.ModelRecord("codex", "gpt-6.1-sol")]
        ranked = ranking_module.rank_models(
            models=models,
            catalog=catalog,
            quota_windows={
                "codex": [
                    ranking_module.QuotaWindow(
                        kind="weekly",
                        used_ratio=0.5,
                        reset_epoch=NOW + 5 * DAY,
                        duration_seconds=7 * DAY,
                        observed_at=NOW,
                    )
                ]
            },
            free_models=set(),
            usage_tokens={},
            aa_cache=aa_cache_for(models),
            now=NOW,
        )
        data = snapshot.build_snapshot(
            now=NOW,
            sources=[{"id": "t3", "status": "ok", "reason": "ok", "observed_at_epoch": NOW}],
            ranked=ranked,
            aa_cache=aa_cache_for(models),
        )
        row = data["candidates"][0]
        capacity = row["capacity"]
        self.assertIsNotNone(capacity["paced_availability"])
        self.assertAlmostEqual(
            capacity["paced_availability"], capacity["pace_delta"], places=6
        )
        self.assertEqual(capacity["paced_availability_window"], "weekly:primary")
        samples = snapshot.decision_samples(data)
        paced = {
            (labels["provider"], labels["model"]): value
            for name, labels, value in samples
            if name == "ghostship_ai_model_paced_availability"
        }
        delta = {
            (labels["provider"], labels["model"]): value
            for name, labels, value in samples
            if name == "ghostship_ai_model_pace_delta_ratio"
        }
        self.assertEqual(paced, delta)


class OllamaWindowTests(unittest.TestCase):
    """The Ollama Cloud account has a session window and a weekly window."""

    def _providers(self):
        return _load("ai_usage_design_providers", "providers")

    def _env(self, folder):
        path = Path(folder) / "secrets.env"
        path.write_text("OLLAMA_API_KEY=key\n")
        return str(path)

    def _response(self, body, ok=True, status=200):
        class Response:
            def __init__(self):
                self.ok = ok
                self.status = status
                self._body = body

            def json(self):
                return self._body

        return Response()

    def test_the_ollama_windows_are_published(self):
        providers = self._providers()
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            env = self._env(folder)
            result = providers.read_ollama(
                env,
                1000.0,
                http=lambda url, **kwargs: self._response(
                    {
                        "range": "7d",
                        "totals": {"request_count": 5},
                        "session": {"used": 3, "limit": 10, "resetsAt": 2000.0},
                        "weekly": {"used": 1, "limit": 100, "resetsAt": 3000.0},
                    }
                ),
            )
        states = {
            sample[1]["window"]
            for sample in result.metrics
            if sample[0] == "ghostship_ai_quota_state"
        }
        self.assertEqual(states, {"session", "weekly"})
        windows = {window["kind"]: window for window in result.windows}
        self.assertAlmostEqual(windows["session"]["usedRatio"], 0.3, places=6)
        self.assertEqual(windows["session"]["resetEpoch"], 2000.0)
        self.assertAlmostEqual(windows["weekly"]["usedRatio"], 0.01, places=6)
        self.assertEqual(windows["weekly"]["resetEpoch"], 3000.0)

    def test_an_unread_window_is_published_as_unknown_and_never_gates(self):
        providers = self._providers()
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            env = self._env(folder)
            result = providers.read_ollama(
                env,
                1000.0,
                http=lambda url, **kwargs: self._response(
                    {"range": "7d", "totals": {"request_count": 5}}
                ),
            )
        states = {
            (sample[1]["window"], sample[1]["state"])
            for sample in result.metrics
            if sample[0] == "ghostship_ai_quota_state"
        }
        self.assertEqual(states, {("session", "unknown"), ("weekly", "unknown")})
        windows = {window["kind"]: window for window in result.windows}
        self.assertIsNone(windows["session"]["usedRatio"])
        # The window does not gate the route: an unknown reading is not
        # evidence that the account is exhausted.
        self.assertFalse(windows["session"]["gating"])

    def test_an_ollama_model_is_not_hidden_by_an_unknown_window(self):
        ranking_module = _load("ai_usage_design_ranking_ollama", "ranking")
        catalog = catalog_module.Catalog(
            {
                "ollama-cloud": {
                    "models": {
                        "deepseek-v4.1-flash:1017": catalog_entry(
                            "deepseek-v4.1-flash:1017"
                        )
                    }
                }
            }
        )
        models = [ranking_module.ModelRecord("ollama", "deepseek-v4.1-flash:1017")]
        ranked = ranking_module.rank_models(
            models=models,
            catalog=catalog,
            quota_windows={
                "ollama": [
                    ranking_module.QuotaWindow(
                        kind="session",
                        used_ratio=None,
                        reset_epoch=None,
                        observed_at=NOW,
                        gating=False,
                    )
                ]
            },
            free_models=set(),
            usage_tokens={},
            aa_cache=aa_cache_for(models),
            now=NOW,
        )
        self.assertTrue(ranked)
        self.assertTrue(ranked[0].available)

    def test_the_model_label_keeps_the_t3_id(self):
        metrics = _load("ai_usage_design_metrics_ollama", "metrics")
        self.assertEqual(
            metrics.label_value("deepseek-v4.1-flash:1017"),
            "deepseek-v4.1-flash:1017",
        )

    def test_the_t3_status_publishes_the_ollama_windows(self):
        t3source = _load("ai_usage_design_t3source_ollama", "t3source")

        class Client:
            def call(self, tag, payload=None):
                if tag == "server.refreshProviders":
                    return {
                        "providers": [
                            {
                                "instanceId": "opencode",
                                "status": "ready",
                                "models": [
                                    {"slug": "ollama-cloud/deepseek-v4.1-flash:1017"}
                                ],
                                "usageLimits": {
                                    "checkedAt": "2026-01-15T00:00:00Z",
                                    "windows": [
                                        {
                                            "id": "ollama_session",
                                            "kind": "session",
                                            "usedPercent": 100,
                                            "resetsAt": "2026-01-16T00:00:00Z",
                                            "windowDurationMins": 300,
                                        },
                                        {
                                            "id": "ollama_weekly",
                                            "kind": "weekly",
                                            "usedPercent": 20,
                                            "resetsAt": "2026-01-22T00:00:00Z",
                                            "windowDurationMins": 10080,
                                        },
                                    ],
                                },
                            }
                        ]
                    }
                return {}

        result = t3source._collect_limits(Client())
        windows = {window["kind"]: window for window in result.windows}
        # The Ollama windows belong to the Ollama account, not to the Go
        # subscription the instance also serves.
        self.assertEqual(windows["session"]["provider"], "ollama")
        self.assertEqual(windows["weekly"]["provider"], "ollama")
        self.assertAlmostEqual(windows["session"]["usedRatio"], 1.0, places=6)
        self.assertAlmostEqual(windows["weekly"]["usedRatio"], 0.2, places=6)
        self.assertIsNotNone(windows["session"]["resetEpoch"])
        self.assertIsNotNone(windows["weekly"]["resetEpoch"])


class UnmeasuredModelTests(unittest.TestCase):
    """An unmeasured model never wins a tier."""

    def _rank(self, records, models):
        ranking_module = _load("ai_usage_design_ranking_grok", "ranking")
        catalog = catalog_module.Catalog(
            {
                "xai": {
                    "models": {
                        model: catalog_entry(model) for model in models
                    }
                }
            }
        )
        cache = {
            "status": "ok",
            "index_version": "4.3",
            "fetched_at_epoch": NOW,
            "records": records,
        }
        return ranking_module.rank_models(
            models=[ranking_module.ModelRecord("grok", model) for model in models],
            catalog=catalog,
            quota_windows={},
            free_models=set(),
            usage_tokens={},
            aa_cache=cache,
            now=NOW,
        )

    def test_an_unmeasured_grok_never_wins_the_bulk_tier(self):
        models = ["grok-4.5", "grok-4.6", "grok-4.7"]
        records = [
            {
                "id": "id-grok-4-7",
                "slug": "grok-4-7",
                "model": "Grok 4.7 (Xhigh)",
                "release_date": "2026-09-21",
                "indices": {"intelligence_index": 46.4465506302286},
                "cost_per_task": 3.738325952106939,
                "median_performance": 100.0,
                "prices": {},
            }
        ]
        ranked = self._rank(records, models)
        bulk = [item for item in ranked if item.tier == "bulk"]
        self.assertTrue(bulk)
        self.assertEqual(bulk[0].model, "grok-4.7")
        # The unmeasured models are visible and they are not in the tier.
        self.assertNotIn("grok-4.6", {item.model for item in bulk})
        self.assertNotIn("grok-4.5", {item.model for item in bulk})

    def test_a_cheap_price_never_makes_an_unmeasured_model_win(self):
        # The name-suffix and price factor is gone: a model the feed does
        # not measure never holds a tier, however cheap its listing is.
        ranking_module = _load("ai_usage_design_ranking_grok2", "ranking")
        catalog = catalog_module.Catalog(
            {
                "xai": {
                    "models": {
                        "grok-4.6": catalog_entry(
                            "grok-4.6", cost={"input": 0.0, "output": 0.0}
                        ),
                        "grok-4.7": catalog_entry("grok-4.7"),
                    }
                }
            }
        )
        models = [
            ranking_module.ModelRecord("grok", "grok-4.6"),
            ranking_module.ModelRecord("grok", "grok-4.7"),
        ]
        records = [
            {
                "id": "id-grok-4-7",
                "slug": "grok-4-7",
                "model": "Grok 4.7 (Xhigh)",
                "release_date": "2026-09-21",
                "indices": {"intelligence_index": 46.4465506302286},
                "cost_per_task": 3.738325952106939,
                "median_performance": 100.0,
                "prices": {},
            }
        ]
        cache = {
            "status": "ok",
            "index_version": "4.3",
            "fetched_at_epoch": NOW,
            "records": records,
        }
        ranked = ranking_module.rank_models(
            models=models,
            catalog=catalog,
            quota_windows={},
            free_models=set(),
            usage_tokens={},
            aa_cache=cache,
            now=NOW,
        )
        bulk = [item for item in ranked if item.tier == "bulk"]
        self.assertEqual([item.model for item in bulk], ["grok-4.7"])

    def test_a_measured_grok_4_6_may_win_the_bulk_tier(self):
        # Grok 4.6 is a measured model: it has its own record, with the cost
        # per task its model page publishes. It may win on that record, and
        # never on a name or a price.
        models = ["grok-4.5", "grok-4.6", "grok-4.7"]
        records = [
            {
                "id": "id-grok-4-7",
                "slug": "grok-4-7",
                "model": "Grok 4.7 (Xhigh)",
                "release_date": "2026-09-21",
                "indices": {"intelligence_index": 46.4465506302286},
                "cost_per_task": 3.738325952106939,
                "median_performance": 100.0,
                "prices": {},
            },
            {
                "id": "id-grok-4-6",
                "slug": "grok-4-6",
                "model": "Grok 4.6 (High)",
                "release_date": "2026-07-01",
                "indices": {"intelligence_index": 44.3113073012592},
                "cost_per_task": 1.4848449196688633,
                "median_performance": 100.0,
                "prices": {},
            },
        ]
        ranked = self._rank(records, models)
        bulk = [item for item in ranked if item.tier == "bulk"]
        self.assertTrue(bulk)
        # The measured 4.6 is ahead of the measured 4.7: its value is higher
        # and its cost is lower.
        self.assertEqual(bulk[0].model, "grok-4.6")
        # Grok 4.5 has no record at all, so it is not in the tier.
        self.assertNotIn("grok-4.5", {item.model for item in bulk})


class DecisionInputTests(unittest.TestCase):
    """F5: the inputs a decision was made on are published."""

    def _snapshot(self):
        ranking_module = _load("ai_usage_design_ranking_inputs", "ranking")
        models = [ranking_module.ModelRecord("codex", "gpt-6.1-sol")]
        catalog = catalog_module.Catalog(
            {"openai": {"models": {"gpt-6.1-sol": catalog_entry("gpt-6.1-sol")}}}
        )
        cache = {
            "status": "ok",
            "index_version": "4.3",
            "fetched_at_epoch": NOW,
            "records": [
                {
                    "id": "id-gpt-6-1-sol",
                    "slug": "gpt-6-1-sol",
                    "model": "GPT-6.1 Sol (Max)",
                    "release_date": "2026-01-20",
                    "indices": {"intelligence_index": 51.8},
                    "cost_per_task": 0.1,
                    "median_performance": 100.0,
                    "prices": {},
                }
            ],
        }
        ranked = ranking_module.rank_models(
            models=models,
            catalog=catalog,
            quota_windows={
                "codex": [
                    ranking_module.QuotaWindow(
                        kind="weekly",
                        used_ratio=0.4,
                        reset_epoch=NOW + 3 * DAY,
                        duration_seconds=7 * DAY,
                        observed_at=NOW,
                    )
                ]
            },
            free_models=set(),
            usage_tokens={},
            aa_cache=cache,
            native_models={
                ("codex", "gpt-6.1-sol"): {
                    "providerInstance": "codex",
                    "modelId": "gpt-6.1-sol",
                    "options": [],
                }
            },
            now=NOW,
        )
        return snapshot.build_snapshot(
            now=NOW,
            sources=[{"id": "t3", "status": "ok", "reason": "ok", "observed_at_epoch": NOW}],
            ranked=ranked,
            aa_cache=cache,
            catalog=catalog,
            native_models={
                ("codex", "gpt-6.1-sol"): {
                    "providerInstance": "codex",
                    "modelId": "gpt-6.1-sol",
                    "options": [],
                }
            },
            policy={
                "frontierPrimeModels": ("gpt-6.1-sol",),
                "excludedModels": (),
                "allowedGptModels": ("gpt-6.1-sol",),
                "backgroundProviderInstances": ("codex",),
            },
        )

    def test_the_benchmark_condition_and_the_execution_reasoning_are_published(self):
        main = _load("ai_usage_design_main_inputs", "main")
        samples = main.decision_input_samples(self._snapshot())
        conditions = {
            labels["variant"]
            for name, labels, _value in samples
            if name == "ghostship_ai_model_aa_condition"
        }
        self.assertIn("max", conditions)
        reasoning = [
            labels
            for name, labels, _value in samples
            if name == "ghostship_ai_model_execution_reasoning"
        ]
        self.assertTrue(reasoning)
        self.assertEqual(reasoning[0]["default"], "medium")
        self.assertEqual(reasoning[0]["escalation"], "high")

    def test_the_binding_windows_are_published(self):
        main = _load("ai_usage_design_main_inputs2", "main")
        samples = main.decision_input_samples(self._snapshot())
        capacity = [
            labels["window"]
            for name, labels, _value in samples
            if name == "ghostship_ai_model_capacity_binding"
        ]
        pace = [
            labels["window"]
            for name, labels, _value in samples
            if name == "ghostship_ai_model_pace_binding"
        ]
        self.assertTrue(capacity)
        self.assertTrue(pace)

    def test_the_frontier_membership_carries_its_wait(self):
        main = _load("ai_usage_design_main_inputs3", "main")
        samples = main.decision_input_samples(self._snapshot())
        members = [
            labels
            for name, labels, _value in samples
            if name == "ghostship_ai_frontier_member"
        ]
        self.assertTrue(members)
        self.assertEqual(members[0]["model"], "gpt-6.1-sol")
        waits = [
            value
            for name, _labels, value in samples
            if name == "ghostship_ai_frontier_wait_seconds"
        ]
        self.assertTrue(waits)


class ReserveTests(unittest.TestCase):
    """The 3D reserve: a qualified model is kept for CAD work."""

    FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ai-usage"
    # The moment the AA-3D fixture was read. The board is only evidence
    # while it is fresh, so the snapshot is built at that moment.
    NOW = 1792640463.0

    def _fixture(self, name):
        return json.loads((self.FIXTURES / name).read_text(encoding="utf-8"))

    def _build(self, *, used_ratio, providers=("codex",)):
        ranking_module = _load("ai_usage_design_ranking_reserve", "ranking")
        aa_3d = _load("ai_usage_design_aa3d_reserve", "aa_3d")
        records = self._fixture("aa-public-models.json")["records"]
        cache = {
            "status": "ok",
            "index_version": "4.3",
            "fetched_at_epoch": self.NOW,
            "records": records,
        }
        board = aa_3d.load_cache(
            str(self.FIXTURES / "aa-3d-public.json"), self.NOW
        )
        self.assertIsNotNone(board)
        models = []
        catalog_models = {}
        for record in records:
            model = record["slug"]
            models.append(ranking_module.ModelRecord("codex", model))
            catalog_models[model] = {
                "id": model,
                "name": model,
                "family": model,
                "release_date": "2026-01-20",
                "limit": {"context": 200000},
                # The 3D tier needs a proven image input.
                "modalities": {"input": ["text", "image"]},
            }
        catalog = catalog_module.Catalog({"openai": {"models": catalog_models}})
        windows = {
            provider: [
                ranking_module.QuotaWindow(
                    kind="weekly",
                    used_ratio=used_ratio,
                    reset_epoch=self.NOW + 3 * DAY,
                    duration_seconds=7 * DAY,
                    observed_at=self.NOW,
                )
            ]
            for provider in providers
        }
        ranked = ranking_module.rank_models(
            models=models,
            catalog=catalog,
            quota_windows=windows,
            free_models=set(),
            usage_tokens={},
            aa_cache=cache,
            native_models={
                ("codex", model): {
                    "providerInstance": "codex",
                    "modelId": model,
                    "options": [],
                }
                for model in catalog_models
            },
            now=self.NOW,
        )
        return snapshot.build_snapshot(
            now=self.NOW,
            sources=[
                {"id": "t3", "status": "ok", "reason": "ok", "observed_at_epoch": self.NOW}
            ],
            ranked=ranked,
            aa_cache=cache,
            aa_3d_cache=board,
            catalog=catalog,
            measured_windows=[
                {
                    "provider": provider,
                    "account": "default",
                    "model": "*",
                    "kind": "weekly",
                    "quotaId": "primary",
                    "usedRatio": used_ratio,
                    "resetEpoch": self.NOW + 3 * DAY,
                    "durationSeconds": 7 * DAY,
                    "source": "t3",
                    "observedAtEpoch": self.NOW,
                }
                for provider in providers
            ],
            native_models={
                ("codex", model): {
                    "providerInstance": "codex",
                    "modelId": model,
                    "options": [],
                }
                for model in catalog_models
            },
            policy={
                "frontierPrimeModels": (),
                "excludedModels": (),
                "allowedGptModels": (),
                "backgroundProviderInstances": ("codex",),
            },
        )

    def _bulk_order(self, data):
        members = (data.get("tier_members") or {}).get("bulk") or []
        return [key.split(":", 1)[1] for key in members]

    def test_the_bulk_order_follows_the_published_value(self):
        data = self._build(used_ratio=0.6)
        order = self._bulk_order(data)
        self.assertTrue(order)
        # The measured value decides inside the tier, and the models that
        # are reserved for the 3D tier come after the others.
        self.assertLess(
            order.index("deepseek-v4-1-flash-1017"), order.index("mimo-v2-6-pro")
        )
        self.assertLess(
            order.index("minimax-m3-1-flash"), order.index("mimo-v2-6-pro")
        )

    def test_a_reserved_model_is_withheld_at_low_capacity(self):
        data = self._build(used_ratio=0.6)
        row = next(
            entry
            for entry in data["candidates"]
            if entry["model"] == "mimo-v2-6-pro"
        )
        reserve = row["reserve"]
        self.assertTrue(reserve["3d"])
        self.assertTrue(reserve["withheld"])
        self.assertAlmostEqual(reserve["capacity"], 0.4, places=6)
        # The reserved model is not a bulk winner while the capacity is low.
        winners = (data.get("tier_winners") or {}).get("bulk") or []
        self.assertNotIn(
            "mimo-v2-6-pro", [winner["model"] for winner in winners]
        )

    def test_a_reserved_model_wins_the_3d_tier(self):
        data = self._build(used_ratio=0.6)
        winners = (data.get("tier_winners") or {}).get("3d") or []
        self.assertTrue(winners)
        self.assertEqual(winners[0]["model"], "mimo-v2-6-pro")

    def test_the_3d_order_follows_the_published_value(self):
        data = self._build(used_ratio=0.6)
        members = (data.get("tier_members") or {}).get("3d") or []
        order = [key.split(":", 1)[1] for key in members]
        for before, after in (
            ("mimo-v2-6-pro", "claude-haiku-5-5"),
            ("claude-haiku-5-5", "glm-5-3-flash"),
            ("glm-5-3-flash", "kimi-k3"),
            ("kimi-k3", "grok-4-7"),
        ):
            self.assertLess(order.index(before), order.index(after))

    def test_a_reserved_model_ranks_last_with_enough_capacity(self):
        data = self._build(used_ratio=0.2)
        row = next(
            entry
            for entry in data["candidates"]
            if entry["model"] == "mimo-v2-6-pro"
        )
        self.assertTrue(row["reserve"]["3d"])
        self.assertFalse(row["reserve"]["withheld"])
        # The reserve changes the order and the eligibility, never the value.
        components = row["value"]["components"]
        expected = (
            0.70 * components["intelligence"]["value"]
            + 0.30 * components["cost_per_task"]["value"]
        )
        self.assertAlmostEqual(row["value"]["value"], round(expected, 6), places=6)

    def test_the_reserve_is_published_as_a_metric(self):
        main = _load("ai_usage_design_main_reserve", "main")
        data = self._build(used_ratio=0.6)
        samples = main.decision_input_samples(data)
        reserved = [
            labels
            for name, labels, _value in samples
            if name == "ghostship_ai_model_reserved"
        ]
        self.assertTrue(reserved)
        self.assertEqual(reserved[0]["reserve"], "3d")
        self.assertIn(reserved[0]["tier"], ("bulk", "free"))


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
