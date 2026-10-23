"""The scope of a capacity window: the account record and the label.

A window the provider reports for one model family is not a window of the
whole account. The account record keeps the scope the ranking gives the
window, and the label of the row of the card names it: the session window
of the third-party group reads 'Session · Claude & GPT', and the quota of
one model family reads 'Quota · Gemini'.

A reading of one model that names no family is not a route of the account
but an internal name of the provider, and it is not a window of the
account at all.

The records in this file are invented. They hold no live value.
"""

import importlib.util
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


catalog = load("ai_usage_window_scope_catalog", "catalog.py")
ranking = load("ai_usage_window_scope_ranking", "ranking.py")
snapshot = load("ai_usage_window_scope_snapshot", "snapshot.py")

# The moment the readings were taken.
NOW = 1_800_000_000.0
HOUR = 3600.0
DAY = 24 * HOUR
WEEK = 7 * DAY

# The catalog the ranking reads. One model of one provider is enough.
CATALOG = catalog.Catalog(
    {
        "anthropic": {
            "models": {
                "claude-opus-5-5": {
                    "name": "Claude Opus 5.5",
                    "family": "claude-opus",
                    "release_date": "2026-12-01",
                    "modalities": {"input": ["text"]},
                    "cost": {"input": 4.0, "output": 20.0},
                },
                "claude-fable-5-1": {
                    "name": "Claude Fable 5.1",
                    "family": "claude-fable",
                    "release_date": "2026-12-01",
                    "modalities": {"input": ["text"]},
                    "cost": {"input": 1.0, "output": 5.0},
                },
            }
        }
    }
)

POLICY = {
    "frontierPrimeModels": ("claude-opus-5-5",),
    "allowedGptModels": (),
    "backgroundProviderInstances": ("opencode",),
}


def reading(provider, quota_id, kind, used, model="*", check=NOW, reset=None, duration=None):
    """One measured window, in the shape the collector reads it in."""
    return {
        "provider": provider,
        "account": "default",
        "model": model,
        "kind": kind,
        "quotaId": quota_id,
        "usedRatio": used,
        "resetEpoch": reset,
        "durationSeconds": duration,
        "source": "t3",
        "observedAtEpoch": check,
    }


def inferred(provider, model, quota_id, kind, used, scope):
    """One learned window, in the shape the collector infers it in."""
    return {
        "provider": provider,
        "model": model,
        "applies_to": (model,) if scope == "model" else (),
        "window": {
            "kind": kind,
            "quota_id": quota_id,
            "used_ratio": used,
            "reset_epoch": NOW + 5 * HOUR,
            "duration_seconds": 5 * HOUR,
            "observed_at": NOW,
            "inference": {
                "window": "5h",
                "budget": 200000.0,
                "unit": "tokens",
                "scope": scope,
                "weights": {},
                "weights_basis": "",
                "episodes": 3,
                "state": "exhausted",
            },
        },
    }


def build(measured=(), learned=(), ranked=()):
    """The routing snapshot of the readings."""
    return snapshot.build_snapshot(
        now=NOW,
        sources=[],
        ranked=list(ranked),
        policy=POLICY,
        catalog=CATALOG,
        measured_windows=list(measured),
        inferred_windows=list(learned),
    )


def records(data, account):
    """The account records of the snapshot."""
    accounts = (data.get("quota") or {}).get("accounts") or {}
    return accounts.get(account) or []


def rows(data, account):
    """The rows of the card of the account, with the share that is left."""
    return [
        (labels, value)
        for metric, labels, value in snapshot.account_window_samples(data)
        if metric == "ghostship_ai_account_window_remaining_ratio"
        and labels.get("account") == account
    ]


def capacity(data, account):
    """The capacity of the account, as the snapshot holds it."""
    return ((data.get("quota") or {}).get("provider_capacity") or {}).get(account) or {}


class ThirdPartyGroupScopeTests(unittest.TestCase):
    """The session and the weekly window of the third-party group."""

    def test_the_session_window_of_the_third_party_group_names_its_models(self):
        data = build([reading("antigravity", "3p-5h", "session", 0.5)])
        account = records(data, "antigravity")
        self.assertEqual(len(account), 1)
        # The window covers the Claude and the GPT models of the group, and
        # not the whole account.
        self.assertEqual(account[0]["applies_to"], ["claude", "gpt"])
        labels, value = rows(data, "antigravity")[0]
        self.assertEqual(labels["label"], "Session · Claude & GPT")
        self.assertEqual(value, 0.5)

    def test_the_weekly_window_of_the_third_party_group_names_its_models(self):
        data = build([reading("antigravity", "3p-weekly", "weekly", 0.4)])
        account = records(data, "antigravity")
        self.assertEqual(account[0]["applies_to"], ["claude", "gpt"])
        labels, value = rows(data, "antigravity")[0]
        self.assertEqual(labels["label"], "Weekly · Claude & GPT")
        self.assertEqual(value, 0.6)


class PerModelQuotaTests(unittest.TestCase):
    """The readings the provider reports for one model."""

    def test_the_per_model_readings_are_one_row_per_model_family(self):
        data = build(
            [
                reading("antigravity", "quotaInfo", "quota", 0.2, model="gemini-3-flash"),
                reading("antigravity", "quotaInfo", "quota", 0.4, model="gemini-2.5-pro"),
                reading("antigravity", "quotaInfo", "quota", 0.3, model="claude-opus-5-5-high"),
                reading("antigravity", "quotaInfo", "quota", 0.5, model="gpt-oss-120b-medium"),
            ]
        )
        found = {labels["label"]: value for labels, value in rows(data, "antigravity")}
        # Two readings of the Gemini models are one row, and the row holds
        # the least that is left of them.
        self.assertEqual(
            found,
            {"Quota · Gemini": 0.6, "Quota · Claude": 0.7, "Quota · GPT": 0.5},
        )

    def test_an_internal_model_id_is_not_a_window_of_the_account(self):
        data = build(
            [
                reading("antigravity", "quotaInfo", "quota", 0.2, model="chat_20706"),
                reading("antigravity", "quotaInfo", "quota", 0.3, model="tab_flash_lite_preview"),
            ]
        )
        self.assertEqual(records(data, "antigravity"), [])
        self.assertEqual(rows(data, "antigravity"), [])
        self.assertNotIn("antigravity", (data.get("quota") or {}).get("provider_capacity") or {})


class FableWindowTests(unittest.TestCase):
    """The week of one model family of the Claude account."""

    def test_the_fable_week_is_scoped_to_the_fable_family(self):
        data = build([reading("claude", "seven_day_fable", "weekly", 0.0)])
        account = records(data, "claude")
        self.assertEqual(account[0]["applies_to"], ["fable"])
        labels, _value = rows(data, "claude")[0]
        # The label names the family already, and it is not named twice.
        self.assertEqual(labels["label"], "Weekly · Fable")

    def test_a_spent_fable_week_does_not_block_the_claude_account(self):
        data = build(
            [
                reading("claude", "five_hour", "session", 0.2),
                reading("claude", "seven_day", "weekly", 0.3),
                reading("claude", "seven_day_fable", "weekly", 1.0),
            ]
        )
        account = capacity(data, "claude")
        self.assertEqual(account["remaining_ratio"], 0.7)
        self.assertEqual(account["binding"]["kind"], "weekly")


class UnchangedAccountTests(unittest.TestCase):
    """The accounts that publish no window of its own scope."""

    def test_the_accounts_without_a_scoped_window_are_unchanged(self):
        data = build(
            [
                reading("opencode-go", "rolling", "session", 0.1),
                reading("opencode-go", "weekly", "weekly", 0.2),
                reading("opencode-go", "monthly", "monthly", 0.3),
                reading("ollama", "session", "session", 0.4),
                reading("ollama", "weekly", "weekly", 0.5),
                reading("codex", "primary", "weekly", 0.6),
                reading("grok", "subscription", "weekly", 0.7),
            ]
        )
        for account in ("opencode-go", "ollama", "codex", "grok"):
            for record in records(data, account):
                self.assertNotIn("applies_to", record)
        self.assertEqual(
            {labels["label"] for labels, _value in rows(data, "opencode-go")},
            {"Session", "Weekly", "Monthly"},
        )
        self.assertEqual(
            {labels["label"] for labels, _value in rows(data, "grok")},
            {"Weekly"},
        )
        self.assertEqual(capacity(data, "grok")["remaining_ratio"], 0.3)

    def test_an_inferred_record_is_unchanged(self):
        data = build(
            learned=[inferred("claude", "claude-fable-5-1", "inferred:5h", "weekly", 1.0, "model")]
        )
        account = records(data, "claude")
        self.assertEqual(account[0]["applies_to"], ["claude-fable-5-1"])
        self.assertEqual(account[0]["evidence"], "inferred")
        labels, _value = rows(data, "claude")[0]
        # The row of an inferred window names the window it was learned
        # over, and the scope is not added to it.
        self.assertEqual(labels["label"], "Inferred · 5h")


class CandidateWindowTests(unittest.TestCase):
    """The candidate rows of a route keep the windows the ranking gave them."""

    def test_the_candidate_rows_keep_their_windows_and_their_capacity(self):
        ranked = ranking.rank_models(
            models=[
                ranking.ModelRecord("claude", "claude-opus-5-5"),
                ranking.ModelRecord("claude", "claude-fable-5-1"),
            ],
            catalog=CATALOG,
            quota_windows={
                "claude": [
                    ranking.QuotaWindow(
                        kind="weekly",
                        used_ratio=0.3,
                        reset_epoch=NOW + 5 * DAY,
                        duration_seconds=WEEK,
                        observed_at=NOW,
                        quota_id="seven_day",
                    ),
                    ranking.QuotaWindow(
                        kind="weekly",
                        used_ratio=1.0,
                        reset_epoch=NOW + 5 * DAY,
                        duration_seconds=WEEK,
                        observed_at=NOW,
                        quota_id="seven_day_fable",
                        applies_to=("fable",),
                    ),
                ]
            },
            free_models=set(),
            usage_tokens={},
            now=NOW,
        )
        data = snapshot.build_snapshot(
            now=NOW,
            sources=[],
            ranked=ranked,
            policy=POLICY,
            catalog=CATALOG,
        )
        rows = {row["model"]: row for row in data["candidates"]}
        scopes = {
            window["quota"]: window["scope"]
            for window in rows["claude-opus-5-5"]["quota_windows_applied"]
        }
        # The week of the Fable models is not a window of the Opus route.
        self.assertEqual(scopes, {"seven_day": "shared"})
        # The spent week of the Fable models does not take the headroom of
        # the Opus route with it.
        self.assertEqual(rows["claude-opus-5-5"]["capacity"]["remaining_ratio"], 0.7)
        scopes = {
            window["quota"]: window["scope"]
            for window in rows["claude-fable-5-1"]["quota_windows_applied"]
        }
        self.assertEqual(scopes, {"seven_day": "shared", "seven_day_fable": "model"})
        self.assertEqual(rows["claude-fable-5-1"]["capacity"]["remaining_ratio"], 0.0)


if __name__ == "__main__":
    unittest.main()
