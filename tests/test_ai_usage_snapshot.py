"""The routing snapshot: the contract a consumer may rely on."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage" / "collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("ai_usage_snapshot", ROOT / "snapshot.py")
snapshot = importlib.util.module_from_spec(spec)
sys.modules["ai_usage_snapshot"] = snapshot
spec.loader.exec_module(snapshot)

NOW = 1_800_000_000.0
HOUR = 3600.0


class Ranked:
    """A ranked model, shaped like the ranking engine's own entry."""

    def __init__(self, **kwargs):
        self.tier = kwargs.get("tier", "frontier")
        self.provider = kwargs.get("provider", "claude")
        self.model = kwargs.get("model", "claude-opus-5-5")
        self.rank = kwargs.get("rank", 1)
        self.score = kwargs.get("score", 100.0)
        self.quality = kwargs.get("quality", 100.0)
        self.remaining = kwargs.get("remaining", 0.5)
        self.expires_in_seconds = kwargs.get("expires_in_seconds", 3600.0)
        self.available = kwargs.get("available", True)
        self.quota_state_available = kwargs.get("quota_state_available", True)
        self.reasons = kwargs.get("reasons", ("quality 100 (a prior, not a measurement)",))
        self.windows = kwargs.get("windows", ())
        self.settled = kwargs.get("settled", True)
        self.pending_reason = kwargs.get("pending_reason", "")
        self.used_tokens = kwargs.get("used_tokens", 0.0)
        self.three_d_prior = kwargs.get("three_d_prior", None)
        self.three_d_tokens = kwargs.get("three_d_tokens", 0.0)
        self.account = kwargs.get("account", "claude")
        self.pace = kwargs.get("pace", None)


class Window:
    def __init__(self, used=0.4, reset=None, duration=7 * 86400.0, kind="weekly"):
        self.kind = kind
        self.used_ratio = used
        self.reset_epoch = NOW + 6 * HOUR if reset is None else reset
        self.duration_seconds = duration
        self.quota_id = "primary"
        self.applies_to = ()
        self.observed_at = NOW


POLICY = {
    "frontierPrimeModels": ("claude-opus-5-5", "gpt-6.1-sol"),
    "allowedGptModels": ("gpt-6.1-sol",),
    "backgroundProviderInstances": ("opencode",),
    "frontierReviewAuthority": {
        "provider_instance_id": "codex",
        "model_id": "gpt-6.1-sol",
    },
    "basis": "owner direction",
}


def build(entries, native=None, sources=None):
    return snapshot.build_snapshot(
        now=NOW,
        sources=sources
        or [
            {
                "id": "t3",
                "status": "ok",
                "detail": "",
                "observed_at": "2026-10-21T00:00:00Z",
                "observed_at_epoch": NOW,
                "last_success_at": "2026-10-21T00:00:00Z",
            }
        ],
        ranked=entries,
        native_models=native or {},
        policy=POLICY,
    )


class SnapshotContractTests(unittest.TestCase):
    def test_the_header_carries_the_version_and_the_freshness(self):
        data = build([Ranked()])
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["schema"], "ghostship.ai-usage.routing")
        self.assertEqual(data["generated_at"], "2027-01-15T08:00:00Z")
        self.assertEqual(data["max_age_seconds"], 900)
        self.assertIn("coverage", data)
        self.assertFalse(data["partial"])

    def test_a_failed_source_makes_the_snapshot_partial(self):
        data = build(
            [Ranked()],
            sources=[
                {"id": "grok", "status": "error", "detail": "boom", "observed_at_epoch": None}
            ],
        )
        self.assertTrue(data["partial"])
        self.assertEqual(data["coverage"]["sources_failed"], 1)

    def test_the_native_identity_comes_from_the_instance_catalog(self):
        data = build(
            [Ranked()],
            native={
                ("claude", "claude-opus-5-5"): {
                    "providerInstance": "claudeAgent",
                    "modelId": "claude-opus-5-5",
                    "options": [{"id": "effort", "currentValue": "high"}],
                }
            },
        )
        row = data["candidates"][0]
        self.assertEqual(row["native"]["provider_instance_id"], "claudeAgent")
        self.assertEqual(row["native"]["model_id"], "claude-opus-5-5")
        self.assertEqual(row["native"]["options"][0]["id"], "effort")
        self.assertTrue(row["native"]["mapped"])

    def test_a_model_without_a_native_instance_is_unmapped_and_ineligible(self):
        data = build([Ranked(provider="kilo", model="kimi-k3", account="kilo")])
        row = data["candidates"][0]
        self.assertFalse(row["native"]["mapped"])
        self.assertIsNone(row["native"]["provider_instance_id"])
        self.assertFalse(row["eligibility"]["delegate"]["allowed"])
        self.assertFalse(row["eligibility"]["frontier_prime"]["allowed"])

    def test_the_quota_state_is_explicit(self):
        available = build([Ranked(tier="bulk", windows=(Window(),))])
        self.assertEqual(available["candidates"][0]["quota_state"], "available")
        exhausted = build([Ranked(tier="bulk", windows=(Window(used=1.0),), remaining=0.0)])
        self.assertEqual(exhausted["candidates"][0]["quota_state"], "exhausted")
        unknown = build([Ranked(tier="bulk", remaining=None, windows=())])
        self.assertEqual(unknown["candidates"][0]["quota_state"], "unknown")

    def test_the_quality_is_labelled_as_a_prior(self):
        data = build([Ranked()])
        quality = data["candidates"][0]["quality"]
        self.assertEqual(quality["source"], "prior")
        self.assertFalse(quality["measured"])
        self.assertTrue(quality["basis"])

    def test_the_windows_carry_their_provenance(self):
        data = build([Ranked(windows=(Window(),))])
        window = data["candidates"][0]
        self.assertEqual(window["quota_state"], "available")

    def test_the_frontier_review_is_required_and_fails_closed(self):
        data = build([Ranked()])
        review = data["policy"]["frontier_review"]
        self.assertTrue(review["required"])
        self.assertTrue(review["fail_closed"])
        self.assertEqual(review["authority"]["model_id"], "gpt-6.1-sol")

    def test_the_coverage_says_whether_a_frontier_is_available(self):
        data = build([Ranked(tier="frontier", windows=(Window(),))])
        self.assertTrue(data["coverage"]["frontier"]["available"])
        blocked = build(
            [
                Ranked(
                    tier="frontier",
                    windows=(Window(used=1.0),),
                    remaining=0.0,
                )
            ]
        )
        self.assertFalse(blocked["coverage"]["frontier"]["available"])
        self.assertTrue(blocked["coverage"]["frontier"]["reason"])

    def test_a_prime_row_says_that_it_needs_the_frontier(self):
        data = build([Ranked(tier="frontier")])
        self.assertTrue(data["candidates"][0]["frontier_required"])
        self.assertEqual(data["candidates"][0]["role"], "prime")
        delegate = build([Ranked(tier="bulk", model="kimi-k3")])
        self.assertFalse(delegate["candidates"][0]["frontier_required"])
        self.assertEqual(delegate["candidates"][0]["role"], "delegate")

    def test_the_policy_is_kept_apart_from_the_readings(self):
        data = build([Ranked()])
        self.assertEqual(data["policy"]["frontier_prime_models"], ["claude-opus-5-5", "gpt-6.1-sol"])
        self.assertEqual(data["policy"]["allowed_gpt_models"], ["gpt-6.1-sol"])

    def test_the_snapshot_holds_no_secret(self):
        data = build([Ranked()])
        text = json.dumps(data)
        for forbidden in ("@", "Bearer", "sk-", "password", "/home/", "/srv/"):
            self.assertNotIn(forbidden, text)

    def test_the_file_is_written_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "routing.json"
            snapshot.write_snapshot(path, build([Ranked()]))
            self.assertTrue(path.exists())
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            self.assertFalse(path.with_name(path.name + ".new").exists())
            data = json.loads(path.read_text())
            self.assertEqual(data["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
