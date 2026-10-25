"""The reusable public-safe provider quota contract matrix."""
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "modules/self-hosted/ai-usage/collector"
FIXTURE = ROOT / "tests/fixtures/ai-usage/provider-quota-contract.json"
if str(COLLECTOR) not in sys.path:
    sys.path.insert(0, str(COLLECTOR))

import main
import snapshot

NOW = 1_800_000_000.0


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


class ProviderQuotaContractFixtureTests(unittest.TestCase):
    def test_configured_readers_hold_their_fixture_state_and_named_gap(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        accounts = {}
        expected = {}
        for account in fixture["accounts"]:
            provider = account["provider"]
            expected[provider] = (account["state"], account["reason"])
            accounts[provider] = []
            for window in account["windows"]:
                accounts[provider].append({
                    "source": window["source"],
                    "kind": window["kind"],
                    "quota_id": window["quota_id"],
                    "remaining_ratio": window["left_ratio"],
                    "check_at": iso(NOW - window["age_seconds"]),
                    "reset_at": iso(NOW + window["reset_in_seconds"]),
                    "duration_seconds": window["duration_seconds"],
                    "applies_to": window["applies_to"],
                    "reset_source": window["reset_source"],
                    "reset_label": {
                        "custom": "custom reset",
                        "announced": "announced reset",
                    }.get(window["reset_source"], ""),
                    "evidence": window.get(
                        "evidence",
                        "provider_reported" if window["left_ratio"] is not None else "unknown",
                    ),
                })
        sources = [
            {
                "id": source["id"],
                "status": source["status"],
                "reason": source["reason"],
                "observed_at_epoch": (
                    None if source["age_seconds"] is None
                    else NOW - source["age_seconds"]
                ),
            }
            for source in fixture["sources"]
        ]
        self.assertEqual(set(expected), {provider for provider, _source in main.QUOTA_COVERAGE})

        samples = snapshot.provider_quota_evidence_samples(
            {"quota": {"accounts": accounts}}, main.QUOTA_COVERAGE, sources, NOW
        )
        observed = {
            labels["provider"]: (labels["state"], labels["reason"])
            for name, labels, _value in samples
            if name == "ghostship_ai_provider_quota_evidence"
        }
        self.assertEqual(observed, expected)
        ages = {
            labels["provider"]: value
            for name, labels, value in samples
            if name == "ghostship_ai_provider_quota_source_age_seconds"
        }
        self.assertEqual(ages["codex"], 20)
        self.assertEqual(ages["opencode-go"], 3600)

        # The fixture pins the scope and reset provenance carried by the
        # normalized account records, including one model-scoped window.
        claude_window = accounts["claude"][0]
        self.assertEqual(claude_window["applies_to"], ["claude"])
        self.assertEqual(claude_window["reset_source"], "announced")
        antigravity_scopes = {tuple(window["applies_to"]) for window in accounts["antigravity"]}
        self.assertEqual(antigravity_scopes, {("claude", "gpt"), ("gemini",)})
        self.assertEqual(accounts["pi"][0]["evidence"], "inferred")
        window_labels = {
            labels["label"]
            for _name, labels, _value in snapshot.account_window_samples(
                {"quota": {"accounts": accounts}}
            )
            if labels.get("account") in ("claude", "antigravity")
        }
        self.assertIn("Weekly · announced reset · Claude", window_labels)
        self.assertIn("Weekly · Claude & GPT", window_labels)
        self.assertIn("Quota · Gemini", window_labels)

    def test_a_successful_reader_without_a_window_is_not_called_measured(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cursor = next(account for account in fixture["accounts"] if account["provider"] == "cursor")
        self.assertEqual(cursor["windows"], [])
        self.assertEqual((cursor["state"], cursor["reason"]), ("unknown", "no_quota_window"))


if __name__ == "__main__":
    unittest.main()
