"""The quota entitlement reconciliation: aliases share an id, nothing drops."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage" / "collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import quota  # noqa: E402

NOW = 1_800_000_000.0


def reading(provider, source, quota_id, kind, used=0.4, account="default", model="*"):
    return {
        "provider": provider,
        "account": account,
        "model": model,
        "kind": kind,
        "quota_id": quota_id,
        "source": source,
        "used_ratio": used,
        "reset_at": "2027-01-20T00:00:00Z",
        "observed_at": "2027-01-15T08:00:00Z",
    }


class EntitlementTests(unittest.TestCase):
    def test_the_go_aliases_share_one_entitlement_and_keep_both_readings(self):
        windows = [
            reading("opencode-go", "t3", "go_monthly", "monthly"),
            reading("opencode-go", "t3", "go_rolling", "rolling"),
            reading("opencode-go", "t3", "go_weekly", "weekly"),
            reading("opencode-go", "opencode-go", "monthly", "monthly"),
            reading("opencode-go", "opencode-go", "rolling", "rolling"),
            reading("opencode-go", "opencode-go", "weekly", "weekly"),
        ]
        entries = {entry["canonical_quota"]: entry for entry in quota.entitlements(windows)}
        self.assertEqual(set(entries), {"monthly", "rolling", "weekly"})
        monthly = entries["monthly"]
        self.assertEqual(len(monthly["readings"]), 2)
        self.assertEqual(monthly["sources"], ["opencode-go", "t3"])
        self.assertEqual(monthly["relationship"], "same_entitlement_independent_readings")
        self.assertTrue(monthly["alias"])
        self.assertEqual(
            {reading["quota"] for reading in monthly["readings"]},
            {"go_monthly", "monthly"},
        )

    def test_samples_carry_the_entitlement_and_the_exact_source(self):
        samples = quota.entitlement_samples(
            [
                reading("opencode-go", "t3", "go_monthly", "monthly"),
                reading("opencode-go", "opencode-go", "monthly", "monthly"),
            ],
            NOW,
        )
        self.assertEqual(len(samples), 2)
        names = {name for name, _labels, _value in samples}
        self.assertEqual(names, {"ghostship_ai_quota_entitlement"})
        labels = [labels for _name, labels, _value in samples]
        self.assertEqual({entry["source"] for entry in labels}, {"t3", "opencode-go"})
        self.assertEqual(
            {entry["entitlement"] for entry in labels},
            {"opencode-go:default:*:monthly:monthly"},
        )
        self.assertEqual(
            {entry["relationship"] for entry in labels},
            {"same_entitlement_independent_readings"},
        )

    def test_different_accounts_or_models_stay_separate_entitlements(self):
        entries = quota.entitlements(
            [
                reading("opencode-go", "t3", "go_monthly", "monthly", account="default"),
                reading("opencode-go", "t3", "go_monthly", "monthly", account="team"),
                reading("claude", "t3", "weekly", "weekly", account="default"),
            ]
        )
        self.assertEqual(len(entries), 3)
        self.assertTrue(all(entry["relationship"] == "single_reading" for entry in entries))

    def test_an_unpaired_window_keeps_its_exact_key(self):
        entries = quota.entitlements([reading("grok", "grok", "credits", "credits")])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["canonical_quota"], "credits")
        self.assertFalse(entries[0]["alias"])


if __name__ == "__main__":
    unittest.main()
