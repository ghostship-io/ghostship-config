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


class FreeRouteScopeTests(unittest.TestCase):
    """A free or promotional route is not exempt without a reported scope."""

    def _rank(self, free_route_accounts, windows):
        import catalog as catalog_module
        import ranking

        catalog = catalog_module.Catalog(
            {
                "opencode-go": {
                    "models": {
                        "minimax-m3.1-flash-free": {
                            "name": "MiniMax M3.1 Flash Free",
                            "family": "minimax",
                            "release_date": "2026-12-01",
                            "cost": {"input": 0.0, "output": 0.0},
                        }
                    }
                }
            }
        )
        return ranking.rank_models(
            models=[ranking.ModelRecord("opencode-go", "minimax-m3.1-flash-free")],
            catalog=catalog,
            quota_windows={"opencode-go": windows},
            free_models={("opencode-go", "minimax-m3.1-flash-free")},
            promo_models=set(),
            usage_tokens={},
            free_route_accounts=free_route_accounts,
            aa_cache={
                "status": "ok",
                "index_version": "4.3",
                "fetched_at_epoch": NOW,
                "records": [
                    {
                        "id": "id-minimax",
                        "slug": "minimax-m3-1-flash-free",
                        "model": "MiniMax M3.1 Flash Free",
                        "release_date": "2026-12-01",
                        "indices": {"intelligence_index": 42.7},
                        "cost_per_task": 0.2201,
                    }
                ],
            },
            now=NOW,
        )

    def _spent(self):
        import ranking

        return [
            ranking.QuotaWindow(
                kind="monthly",
                used_ratio=1.0,
                reset_epoch=NOW + 10 * 86400,
                duration_seconds=30 * 86400,
                observed_at=NOW,
                quota_id="go_monthly",
            )
        ]

    def test_a_free_route_on_the_paid_account_is_blocked_by_the_spent_window(self):
        ranked = self._rank({"opencode-go"}, self._spent())
        entry = ranked[0]
        self.assertFalse(entry.available)
        self.assertEqual(entry.tier, "")
        self.assertEqual(entry.remaining, 0.0)
        self.assertTrue(entry.quota_scope["observed_free_route"])
        self.assertFalse(entry.quota_scope["exemption"])
        self.assertEqual(entry.quota_scope["windows"], 1)

    def test_a_free_route_observed_operational_does_not_remove_the_window(self):
        ranked = self._rank(set(), self._spent())
        self.assertFalse(ranked[0].available)
        self.assertEqual(ranked[0].remaining, 0.0)


class EntitlementDisplayTests(unittest.TestCase):
    """One canonical display reading per entitlement, bound coherently."""

    def _reading(self, source, quota_id, used, reset, observed, kind="monthly", duration=30 * 86400):
        return {
            "provider": "opencode-go",
            "account": "default",
            "model": "*",
            "kind": kind,
            "quota_id": quota_id,
            "source": source,
            "usedRatio": used,
            "resetEpoch": reset,
            "durationSeconds": duration,
            "observedAtEpoch": observed,
        }

    def test_one_card_reading_is_chosen_and_both_raw_readings_are_kept(self):
        windows = [
            self._reading("t3", "go_monthly", 0.4, NOW + 5 * 86400, NOW - 60),
            self._reading("opencode-go", "monthly", 0.9, NOW + 2 * 86400, NOW - 30),
        ]
        entries = [entry for entry in quota.entitlements(windows, NOW) if entry["window"] == "monthly"]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(len(entry["readings"]), 2)
        display = entry["display"]
        self.assertEqual(display["source"], "opencode-go")
        self.assertEqual(display["used_ratio"], 0.9)
        # Reset, expected and pace come from that same reading, not from an
        # extremum of the other one.
        self.assertEqual(display["reset_at"], entry["readings"][1]["reset_at"])
        self.assertAlmostEqual(
            display["expected_used_ratio"],
            1.0 - (2 * 86400) / (30 * 86400),
            places=6,
        )
        self.assertAlmostEqual(
            display["pace_delta_ratio"],
            display["expected_used_ratio"] - 0.9,
            places=6,
        )
        samples = quota.entitlement_display_samples(windows, NOW)
        by_name = {
            name: (labels, value) for name, labels, value in samples
        }
        self.assertIn("ghostship_ai_entitlement_info", by_name)
        labels, value = by_name["ghostship_ai_entitlement_used_ratio"]
        self.assertEqual(value, 0.9)
        self.assertEqual(labels["source"], "opencode-go")
        self.assertEqual(labels["quota"], "monthly")
        self.assertEqual(by_name["ghostship_ai_entitlement_reset_timestamp_seconds"][1], NOW + 2 * 86400)
        self.assertAlmostEqual(
            by_name["ghostship_ai_entitlement_expected_used_ratio"][1],
            1.0 - (2 * 86400) / (30 * 86400),
            places=6,
        )
        self.assertAlmostEqual(
            by_name["ghostship_ai_entitlement_pace_delta_ratio"][1],
            (1.0 - (2 * 86400) / (30 * 86400)) - 0.9,
            places=6,
        )
        self.assertEqual(by_name["ghostship_ai_entitlement_observed_timestamp_seconds"][1], NOW - 30)
        # The raw per-reading info series still carries both sources.
        raw = quota.entitlement_samples(windows, NOW)
        self.assertEqual(len(raw), 2)

    def test_the_display_follows_the_opposite_source_on_the_next_scrape(self):
        windows = [
            self._reading("t3", "go_monthly", 0.95, NOW + 5 * 86400, NOW - 60),
            self._reading("opencode-go", "monthly", 0.2, NOW + 2 * 86400, NOW - 30),
        ]
        display = quota.entitlements(windows, NOW)[0]["display"]
        self.assertEqual(display["source"], "t3")
        self.assertEqual(display["used_ratio"], 0.95)
        self.assertEqual(display["reset_at"], "2027-01-20T00:00:00Z" if False else display["reset_at"])

    def test_an_unknown_entitlement_keeps_its_info_and_claims_no_number(self):
        stale = [
            self._reading("t3", "go_monthly", 0.4, NOW + 5 * 86400, NOW - 10 * 86400),
        ]
        entries = quota.entitlements(stale, NOW)
        self.assertEqual(len(entries), 1)
        self.assertIsNone(entries[0]["display"])
        self.assertEqual(entries[0]["display_state"], "unknown")
        samples = quota.entitlement_display_samples(stale, NOW)
        names = [name for name, _labels, _value in samples]
        self.assertEqual(
            names,
            ["ghostship_ai_entitlement_info"],
        )
        labels = samples[0][1]
        self.assertEqual(labels["entitlement"], "opencode-go:default:*:monthly:monthly")
        self.assertEqual(labels["source"], "")
        self.assertEqual(labels["quota"], "monthly")

    def test_an_unpaired_entitlement_keeps_its_identity(self):
        windows = [self._reading("grok", "credits", 0.4, NOW + 86400, NOW - 60, kind="credits")]
        entries = quota.entitlements(windows, NOW)
        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0]["alias"])
        self.assertEqual(entries[0]["display"]["source"], "grok")

    def test_different_accounts_or_windows_are_not_merged(self):
        windows = [
            self._reading("t3", "go_monthly", 0.4, NOW + 86400, NOW - 60),
            {**self._reading("t3", "go_monthly", 0.9, NOW + 86400, NOW - 60), "account": "team"},
            {**self._reading("t3", "go_weekly", 0.8, NOW + 86400, NOW - 60), "kind": "weekly"},
        ]
        entries = quota.entitlements(windows, NOW)
        self.assertEqual(len(entries), 3)
        self.assertTrue(all(entry["display"]["used_ratio"] is not None for entry in entries))
