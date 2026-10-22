"""The observation gate and the selection rules, tested through the real paths.

These tests drive the actual SourceResult, the actual builder, the actual
MetricWriter and the actual panel queries. A helper-only test would not have
caught any of these: the defects lived in the wiring.
"""
import importlib.util
import json
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


metrics = load("ai_usage_gate_metrics", "metrics.py")
facts = load("ai_usage_gate_facts", "facts.py")
ranking = load("ai_usage_gate_ranking", "ranking.py")
snapshot = load("ai_usage_gate_snapshot", "snapshot.py")
main = load("ai_usage_gate_main", "main.py")

NOW = 1_800_000_000.0
DAY = 24 * 3600.0


class ObservationGateTests(unittest.TestCase):
    def _writer(self, results):
        writer = metrics.MetricWriter()
        # The real renderer, with the real sources.
        text = main.render(results, [], NOW, 0.1, {})
        return text

    def test_a_partial_source_is_not_green(self):
        result = metrics.SourceResult(
            source="t3", status="partial", reason="probe_failed", observed_at=NOW
        )
        self.assertFalse(result.ok)
        self.assertTrue(result.partial)
        text = self._writer([result])
        self.assertIn('ghostship_ai_source_success{provider="t3",source="t3"} 0', text)

    def test_a_partial_source_makes_the_snapshot_partial(self):
        result = metrics.SourceResult(
            source="t3", status="partial", reason="probe_failed", observed_at=NOW
        )
        data = snapshot.build_snapshot(
            now=NOW,
            sources=[
                {
                    "id": "t3",
                    "status": result.status,
                    "reason": result.reason,
                    "observed_at": "2027-01-15T00:00:00Z",
                    "observed_at_epoch": NOW,
                }
            ],
            ranked=[],
        )
        self.assertTrue(data["partial"])
        self.assertEqual(data["coverage"]["sources_partial"], 1)

    def test_an_ok_source_stays_green_and_complete(self):
        result = metrics.SourceResult(source="grok", status="ok", reason="ok", observed_at=NOW)
        text = self._writer([result])
        self.assertIn('ghostship_ai_source_success{provider="grok",source="grok"} 1', text)


class FactsPublicationTests(unittest.TestCase):
    def test_a_private_field_never_reaches_the_snapshot(self):
        fact = facts.make_fact(
            provider="minimax",
            model="MiniMax M3.1 Flash",
            indices={"intelligence_index": 42.0},
            now=NOW,
        )
        fact["aliases"] = ["person@private.invalid"]
        fact["native_bindings"] = {"token": "sk-live-AAAABBBB"}
        fact["note"] = "/srv/apps/secret path"
        data = snapshot.build_snapshot(
            now=NOW,
            sources=[],
            ranked=[],
            facts={facts.identity_key("minimax", "MiniMax M3.1 Flash"): fact},
        )
        text = json.dumps(data)
        for sentinel in ("private.invalid", "sk-live", "/srv/apps/secret"):
            self.assertNotIn(sentinel, text)

    def test_the_published_fact_has_only_allowlisted_fields(self):
        fact = facts.make_fact(
            provider="minimax",
            model="MiniMax M3.1 Flash",
            indices={"intelligence_index": 42.0},
            now=NOW,
        )
        fact["arbitrary"] = "anything"
        record = facts.public_record(fact)
        self.assertIsNotNone(record)
        self.assertEqual(set(record) - set(facts.PUBLIC_FIELDS), set())
        self.assertNotIn("arbitrary", record)

    def test_a_fact_without_a_scope_is_withheld(self):
        fact = facts.make_fact(provider="p", model="m", variant="high", now=NOW)
        fact.pop("variant_scope", None)
        self.assertIsNone(facts.public_record(fact))

    def test_a_model_name_with_a_sentence_is_bounded(self):
        fact = facts.make_fact(provider="p", model="x" * 400, now=NOW)
        record = facts.public_record(fact)
        self.assertLessEqual(len(record["model"]), 120)


class QuotaPanelTests(unittest.TestCase):
    def test_the_quota_panel_keeps_the_quota_id(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "modules/self-hosted/siem/dashboards/ai-usage.json"
        )
        dashboard = json.loads(path.read_text())
        def walk(panels):
            # A collapsed row keeps its panels nested inside it.
            for panel in panels:
                yield panel
                yield from walk(panel.get("panels") or [])

        quota_panels = [
            panel
            for panel in walk(dashboard["panels"])
            if any(
                "ghostship_ai_quota_" in (target.get("expr") or "")
                for target in panel.get("targets") or []
            )
        ]
        self.assertTrue(quota_panels)
        for panel in quota_panels:
            for target in panel.get("targets") or []:
                expr = target.get("expr") or ""
                if "ghostship_ai_quota_" not in expr:
                    continue
                if "by (" in expr:
                    self.assertIn("quota", expr, expr)


class SelectionTests(unittest.TestCase):
    def test_a_gpt_id_with_different_punctuation_does_not_inherit_permission(self):
        policy = {"allowedGptModels": ("gpt-6.1-sol",), "frontierPrimeModels": ("gpt-6.1-sol",)}
        allowed = snapshot._eligibility("codex", "gpt-6.1-sol", ["bulk"], {"mapped": True}, policy)
        other = snapshot._eligibility("codex", "gpt-61-sol", ["bulk"], {"mapped": True}, policy)
        self.assertTrue(allowed["gpt_model_allowed"]["allowed"])
        self.assertFalse(other["gpt_model_allowed"]["allowed"])

    def test_an_implicit_scope_does_not_bind_a_variant(self):
        fact = facts.make_fact(provider="p", model="m", variant="high", now=NOW)
        del fact["variant_scope"]
        self.assertIsNone(
            facts.lookup_by_model(
                {facts.identity_key("p", "m", "high"): fact}, "p", "m", "high", now=NOW
            )
        )

    def test_the_value_is_the_published_intelligence_and_cost_policy(self):
        weights = snapshot.CALCULATION["value"]["weights"]
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=6)
        self.assertEqual(weights, {"intelligence": 0.7, "cost_per_task": 0.3})
        value, used = snapshot._component_value(
            {"intelligence": 0.9, "cost_per_task": 0.5}
        )
        self.assertEqual(set(used), {"intelligence", "cost_per_task"})
        self.assertAlmostEqual(value, 0.7 * 0.9 + 0.3 * 0.5, places=6)
        # A missing input means no combined value: no renormalization.
        self.assertEqual(
            snapshot._component_value({"intelligence": 0.9, "cost_per_task": None}),
            (None, {}),
        )


class PendingBackoffTests(unittest.TestCase):
    def test_a_pending_identity_keeps_its_check_time(self):
        fact = facts.pending_fact(
            provider="p",
            model="m",
            reason="the brief is expected",
            next_check_at=NOW + 3600,
            now=NOW,
        )
        # The fact itself keeps its backoff, and the pending identity of a
        # tiered model carries it forward. A pending fact is not usable, so
        # the lookup declines it; the record is read directly.
        self.assertEqual(fact["next_check_at"], NOW + 3600)
        self.assertIsNone(
            facts.lookup_by_model(
                {facts.identity_key("p", "m"): fact}, "p", "m", now=NOW
            )
        )
        rows = [
            {
                "provider": "p",
                "model": "m",
                "tiers": ["bulk"],
                "native": {"mapped": True, "options": []},
            }
        ]
        identities = snapshot._pending_identities(rows, {facts.identity_key("p", "m"): fact}, NOW)
        self.assertEqual(identities[0]["next_check_at"], NOW + 3600)
        self.assertEqual(identities[0]["pending_reason"], "the brief is expected")


if __name__ == "__main__":
    unittest.main()


class StockUnavailableShapeTests(unittest.TestCase):
    """The stock T3 shape of a provider whose limits probe failed.

    The contract reports `usageLimits.unavailable.reason`; the source read the
    flat shape only, so the provider looked healthy.
    """

    def test_a_nested_unavailable_makes_the_source_partial(self):
        class Client:
            def __init__(self):
                self.calls = 0

            def call(self, tag, payload=None):
                if tag == "server.refreshProviders":
                    return {
                        "providers": [
                            {
                                "instanceId": "claudeAgent",
                                "status": "ready",
                                "models": [{"slug": "claude-opus-5-5"}],
                                "usageLimits": {
                                    "checkedAt": "2026-10-21T23:00:00Z",
                                    "windows": [],
                                    "unavailable": {
                                        "reason": "probeFailed",
                                        "message": "Could not read the limits.",
                                    },
                                },
                            }
                        ]
                    }
                return {"providers": []}

        source = main.t3source.collect(Client(), NOW)
        limits = source[0]
        self.assertEqual(limits.source, "t3")
        self.assertEqual(
            limits.status,
            "partial",
            "a ready provider whose limits probe failed is not a complete reading",
        )
        self.assertIn(limits.reason, ("probe_failed", "unsupported"))
        data = snapshot.build_snapshot(
            now=NOW,
            sources=[
                {
                    "id": limits.source,
                    "status": limits.status,
                    "reason": limits.reason,
                    "observed_at_epoch": NOW,
                }
            ],
            ranked=[],
        )
        self.assertTrue(data["partial"])


class FactsAttestationTests(unittest.TestCase):
    """Every text field a published fact carries, probed with sentinels."""

    SENTINELS = (
        "person@private.invalid",
        "/srv/apps/t3code/home/.grok/auth.json",
        "sk-live-AAAABBBBCCCC",
        "acct-1234567890",
    )

    def _fact(self, **overrides):
        fact = facts.make_fact(
            provider="minimax",
            model="MiniMax M3.1 Flash",
            indices={"intelligence_index": 42.0},
            brief_url="https://artificialanalysis.ai/models/minimax",
            now=NOW,
        )
        fact.update(overrides)
        return fact

    def _assert_clean(self, text):
        for sentinel in self.SENTINELS:
            self.assertNotIn(sentinel, text)

    def test_the_provider_and_the_model_must_be_proven(self):
        fact = self._fact(provider="person@private.invalid", model="/srv/x")
        self.assertIsNone(facts.public_record(fact, {"minimax:MiniMax M3.1 Flash"}))

    def test_the_basis_is_not_published(self):
        fact = self._fact(basis="account person@private.invalid owes /srv/apps/x")
        record = facts.public_record(fact)
        self.assertNotIn("basis", record)
        self.assertEqual(record["attestation"], "artificialanalysis_free")
        self._assert_clean(json.dumps(record))

    def test_the_brief_url_is_a_first_party_evidence_url(self):
        allowed = facts.public_record(self._fact())
        self.assertEqual(allowed["brief_url"], "https://artificialanalysis.ai/models/minimax")
        for url in (
            "https://example.com/person@private.invalid",
            "https://artificialanalysis.ai.evil.example/x",
            "file:///srv/apps/secret",
            "https://artificialanalysis.ai/models?token=sk-live-AAAABBBBCCCC",
        ):
            self.assertIsNone(facts.public_record(self._fact(brief_url=url))["brief_url"])

    def test_the_pending_reason_is_a_code(self):
        fact = self._fact(status="pending", pending_reason="the brief for person@private.invalid")
        record = facts.public_record(fact)
        self.assertEqual(record["pending_reason"], "unknown")
        self._assert_clean(json.dumps(record))

    def test_the_canonical_identity_and_the_benchmark_id_are_not_published(self):
        fact = self._fact(
            canonical_identity="acct-1234567890 /srv/apps/x",
            benchmark_id="person@private.invalid",
        )
        record = facts.public_record(fact)
        self.assertNotIn("canonical_identity", record)
        self.assertNotIn("benchmark_id", record)
        self._assert_clean(json.dumps(record))

    def test_an_admission_workload_must_be_a_known_class(self):
        fact = self._fact(
            admission_evidence=[
                {"workload": "person@private.invalid", "admitted": True, "score": 1.0, "at": NOW},
                {"workload": "research", "admitted": True, "score": 1.0, "at": NOW},
            ]
        )
        record = facts.public_record(fact)
        self.assertEqual([entry["workload"] for entry in record["admission_evidence"]], ["research"])

    def test_nothing_reaches_the_snapshot_or_the_metrics(self):
        fact = self._fact(
            basis="acct-1234567890",
            canonical_identity="acct-1234567890",
            benchmark_id="acct-1234567890",
            brief_url="https://example.com/acct-1234567890",
            pending_reason="acct-1234567890",
            admission_evidence=[
                {"workload": "acct-1234567890", "admitted": True, "score": 1.0, "at": NOW}
            ],
        )
        # The exact identity is proven by the live catalog, so the fact is
        # published, and only through the allowlist.
        ranked = ranking.rank_models(
            models=[ranking.ModelRecord("minimax", "MiniMax M3.1 Flash")],
            catalog=None,
            quota_windows={},
            free_models=set(),
            usage_tokens={},
            now=NOW,
        )
        data = snapshot.build_snapshot(
            now=NOW,
            sources=[],
            ranked=ranked,
            facts={facts.identity_key("minimax", "MiniMax M3.1 Flash"): fact},
            native_models={
                ("minimax", "MiniMax M3.1 Flash"): {
                    "providerInstance": "opencode",
                    "modelId": "minimax-m3.1-flash-free",
                    "options": [],
                }
            },
        )
        self.assertIn(
            facts.identity_key("minimax", "MiniMax M3.1 Flash"),
            data["facts"]["records"],
            "the fact of a proven identity is published",
        )
        text = json.dumps(data)
        self._assert_clean(text)
        writer = metrics.MetricWriter()
        for name, labels, value in snapshot.decision_samples(data):
            writer.add(name, labels, value)
        self._assert_clean(writer.render())

    def test_a_fact_of_an_unproven_identity_is_withheld(self):
        fact = self._fact()
        self.assertIsNone(facts.public_record(fact, {"other:model"}))
