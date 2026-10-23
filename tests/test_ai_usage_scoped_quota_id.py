"""The quota id of a published window series: one id for one scope.

The card of a provider keys its rows by the account, the kind and the
quota id. A provider that publishes one quota id for several model
families therefore draws one row of the card for all of them: the
Antigravity account publishes `quotaInfo` for the Gemini, the Claude and
the GPT models, and the card showed one of the three.

Every published series of an account carries a quota id of its own. The
scope of the window is named after the id when the id does not name it
already, so the quota of the Gemini models is `quotaInfo@gemini`. A
window whose id already names its scope keeps it: `3p-5h` names the
Claude and the GPT models of the third-party group, and
`seven_day_fable` names the Fable models of the Claude account.

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


snapshot = load("ai_usage_scoped_quota_id_snapshot", "snapshot.py")

# The moment the readings were taken.
NOW = 1_800_000_000.0
HOUR = 3600.0
DAY = 24 * HOUR
WEEK = 7 * DAY


def reading(
    provider,
    quota_id,
    kind,
    used,
    model="*",
    check=NOW,
    reset=None,
    duration=None,
    applies_to=(),
):
    """One measured window, in the shape the collector reads it in."""
    measured = {
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
    if applies_to:
        measured["applies_to"] = list(applies_to)
    return measured


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


def build(measured=(), learned=()):
    """The routing snapshot of the readings."""
    return snapshot.build_snapshot(
        now=NOW,
        sources=[],
        ranked=[],
        measured_windows=list(measured),
        inferred_windows=list(learned),
    )


def series(data, account=None):
    """The published series of every window, by their labels."""
    return [
        labels
        for metric, labels, value in snapshot.account_window_samples(data)
        if metric == "ghostship_ai_account_window_remaining_ratio"
        and (account is None or labels.get("account") == account)
    ]


def ids_of(data, account=None):
    """The quota id of every published series."""
    return [labels["quota_id"] for labels in series(data, account)]


def records(data, account):
    """The account records of the snapshot."""
    accounts = (data.get("quota") or {}).get("accounts") or {}
    return accounts.get(account) or []


class ScopedQuotaIdTests(unittest.TestCase):
    """The quota id of a window that names a scope of its own."""

    def test_the_quota_of_a_model_family_carries_its_scope(self):
        data = build(
            [
                reading("antigravity", "quotaInfo", "quota", 0.2, model="gemini-3-flash"),
                reading("antigravity", "quotaInfo", "quota", 0.3, model="claude-opus-5-5-high"),
                reading("antigravity", "quotaInfo", "quota", 0.4, model="gpt-oss-120b-medium"),
            ]
        )
        published = {
            labels["quota_id"]: labels["label"] for labels in series(data, "antigravity")
        }
        # The three windows of the account are three series of their own,
        # and the row of each names the family it belongs to.
        self.assertEqual(
            published,
            {
                "quotaInfo@gemini": "Quota · Gemini",
                "quotaInfo@claude": "Quota · Claude",
                "quotaInfo@gpt": "Quota · GPT",
            },
        )

    def test_a_scope_of_two_families_names_both_of_them(self):
        data = build(
            [
                reading(
                    "antigravity",
                    "quotaInfo",
                    "quota",
                    0.2,
                    applies_to=("claude", "gpt"),
                ),
            ]
        )
        account = records(data, "antigravity")
        self.assertEqual(account[0]["applies_to"], ["claude", "gpt"])
        # The window covers the Claude and the GPT models, and the id
        # names the two of them.
        self.assertEqual(ids_of(data, "antigravity"), ["quotaInfo@claude+gpt"])

    def test_a_window_whose_id_names_its_scope_keeps_its_id(self):
        data = build([reading("antigravity", "3p-5h", "session", 0.5)])
        account = records(data, "antigravity")
        self.assertEqual(account[0]["applies_to"], ["claude", "gpt"])
        # The id names the Claude and the GPT models already, so it is
        # kept as it is.
        self.assertEqual(ids_of(data, "antigravity"), ["3p-5h"])

    def test_the_week_of_the_fable_models_keeps_its_id(self):
        data = build([reading("claude", "seven_day_fable", "weekly", 0.0)])
        account = records(data, "claude")
        self.assertEqual(account[0]["applies_to"], ["fable"])
        # The id names the Fable models already, so it is kept as it is.
        self.assertEqual(ids_of(data, "claude"), ["seven_day_fable"])

    def test_no_two_series_of_an_account_share_a_kind_and_an_id(self):
        data = build(
            [
                reading("antigravity", "quotaInfo", "quota", 0.2, model="gemini-3-flash"),
                reading("antigravity", "quotaInfo", "quota", 0.3, model="claude-opus-5-5-high"),
                reading("antigravity", "quotaInfo", "quota", 0.4, model="gpt-oss-120b-medium"),
                reading("antigravity", "3p-5h", "session", 0.5),
                reading("antigravity", "3p-weekly", "weekly", 0.6),
            ]
        )
        published = [
            (labels["kind"], labels["quota_id"]) for labels in series(data, "antigravity")
        ]
        # The card keys its rows by the account, the kind and the quota id,
        # so two series of one account may not share a kind and an id.
        self.assertEqual(len(set(published)), len(published))
        self.assertEqual(
            set(published),
            {
                ("quota", "quotaInfo@gemini"),
                ("quota", "quotaInfo@claude"),
                ("quota", "quotaInfo@gpt"),
                ("session", "3p-5h"),
                ("weekly", "3p-weekly"),
            },
        )


class UnchangedQuotaIdTests(unittest.TestCase):
    """The windows that name no scope of their own."""

    def test_a_window_without_a_scope_keeps_its_id(self):
        data = build(
            [
                reading("claude", "five_hour", "session", 0.2),
                reading("ollama", "session", "session", 0.4),
                reading("opencode-go", "go_monthly", "monthly", 0.3),
            ],
            learned=[
                inferred("claude", "claude-fable-5-1", "inferred:5h", "weekly", 1.0, "model")
            ],
        )
        # A window of the whole account, and an inferred window, keep the
        # id they have.
        self.assertEqual(ids_of(data, "claude"), ["five_hour", "inferred:5h"])
        self.assertEqual(ids_of(data, "ollama"), ["session"])
        self.assertEqual(ids_of(data, "opencode-go"), ["go_monthly"])

    def test_the_account_records_of_the_snapshot_keep_their_quota_id(self):
        data = build(
            [
                reading("antigravity", "quotaInfo", "quota", 0.2, model="gemini-3-flash"),
                reading("antigravity", "quotaInfo", "quota", 0.3, model="claude-opus-5-5-high"),
            ]
        )
        account = records(data, "antigravity")
        # The records of the routing snapshot keep the quota id of the
        # provider: the scope is named in the published series, and the
        # snapshot itself is unchanged.
        self.assertEqual(
            [record["quota_id"] for record in account],
            ["quotaInfo", "quotaInfo"],
        )
        self.assertEqual(
            [record["applies_to"] for record in account],
            [["gemini"], ["claude"]],
        )


if __name__ == "__main__":
    unittest.main()
