"""The place every provider card takes on the Providers page.

The Providers page draws one card per provider account, and the cards have
to come in the order the owner approved. A Grafana variable keeps only the
order of the query that fills it, so the page cannot sort the cards itself:
the collector publishes the place of every account, and the page reads it.

The position is 1-based and holds no gap. The approved list comes first, in
the order the owner approved it. The accounts that are not on the list
follow: the ones that publish at least one window with a number come first,
by name, and the accounts that are still learning their window come after
them, by name. An account of the approved list that the snapshot does not
hold is skipped, and the cards behind it move up.

The records in this file are a copy of the live set of 2026-10-23. They hold
invented values only.
"""

import importlib.util
import sys
import unittest
from datetime import datetime, timezone
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


try:
    card_order = load("ai_usage_card_order_module", "card_order.py")
except FileNotFoundError:
    # The collector does not publish the card order yet. Every test below
    # says so, and says which reading is missing.
    card_order = None

main = load("ai_usage_card_order_main", "main.py")

# The moment the live snapshot was written.
SNAPSHOT_AT = datetime(2026, 10, 23, 4, 23, 0, tzinfo=timezone.utc)
NOW = SNAPSHOT_AT.timestamp()

# The accounts of the live set, in the order the owner approved them.
APPROVED = (
    "claude",
    "codex",
    "ollama",
    "opencode-go",
    "antigravity",
    "grok",
    "openrouter",
)

# The accounts of the live set, and the place every one of them takes.
LIVE_POSITIONS = {
    "claude": 1,
    "codex": 2,
    "ollama": 3,
    "opencode-go": 4,
    "antigravity": 5,
    "grok": 6,
    "openrouter": 7,
    "google": 8,
    "requesty": 9,
    "kilo": 10,
    "zai": 11,
}


def candidate(provider, model, available=True, reason=""):
    """One candidate row of the routing snapshot."""
    return {
        "provider": provider,
        "model": model,
        "available": available,
        "access": {"kind": "provider_paid", "billing": "subscription"},
        "availability": {
            "state": "available" if available else "unavailable",
            "reason": reason,
        },
        "capacity": {},
        "free_pool": {"state": "not_a_pool_route", "cooldown_until": None},
        "provenance": {"source": "collector", "observed_at": "2026-10-23T04:23:00Z"},
    }


def window(quota_id, kind="quota", remaining=None, state=None, label=""):
    """One window of an account, in the shape the snapshot publishes it."""
    record = {
        "quota_id": quota_id,
        "kind": kind,
        "evidence": "inferred" if kind == "inferred" else "provider_reported",
        "used_ratio": None if remaining is None else round(1.0 - remaining, 4),
        "remaining_ratio": remaining,
        "reset_at": None,
        "seconds_to_reset": None,
        "duration_seconds": None,
        "basis": "",
        "label": label,
        "ends_at": None,
        "check_at": None,
        "provenance": "collector",
    }
    if kind == "inferred":
        record["inference"] = {
            "window": quota_id.split(":", 1)[-1],
            "budget": None,
            "unit": None,
            "scope": None,
            "weights": {},
            "weights_basis": "",
            "episodes": 0,
            "state": state,
            "rolling": False,
        }
    return record


def live_snapshot():
    """The live set of 2026-10-23, as the collector wrote it.

    Seven accounts are on the approved list of the owner. Two more publish a
    window with a number: Google learned a five hour window, and Requesty
    learned a window that is spent. Two accounts are still learning their
    window: Kilo never saw a limit failure, and neither did Zai.
    """
    return {
        "schema": "ghostship.ai-usage.routing",
        "schema_version": "1",
        "generated_at": "2026-10-23T04:23:00Z",
        "candidates": [
            candidate("claude", "claude-paid-01"),
            candidate("codex", "codex-paid-01"),
            candidate("ollama", "ollama-paid-01"),
            candidate("opencode-go", "beam-subscription-01"),
            candidate("antigravity", "antigravity-paid-01"),
            candidate("grok", "grok-paid-01"),
            candidate("openrouter", "openrouter-paid-01"),
            candidate("google", "google-free-01"),
            candidate("requesty", "requesty-free-01"),
            candidate("kilo", "kilo-free-01"),
            candidate("zai", "zai-free-01"),
        ],
        "quota": {
            "accounts": {
                "claude": [window("five_hour", kind="session", remaining=0.69)],
                "codex": [window("weekly", kind="weekly", remaining=1.0)],
                "ollama": [window("session", kind="session", remaining=0.99)],
                "opencode-go": [window("monthly", kind="monthly", remaining=0.0)],
                "antigravity": [window("weekly", kind="weekly", remaining=1.0)],
                "grok": [window("weekly", kind="weekly", remaining=0.0)],
                "openrouter": [window("daily", kind="daily", remaining=0.0)],
                # Google learned a five hour window from the limit failures
                # of its routes, and the window holds a number.
                "google": [window("inferred:5h", kind="inferred", remaining=0.42)],
                # Requesty learned a window that is spent. A spent window
                # holds a number, and the number is zero.
                "requesty": [window("inferred:5h", kind="inferred", remaining=0.0)],
                # Kilo and Zai never saw a limit failure: they are still
                # learning their window.
                "kilo": [
                    window(
                        "inferred:no-limit-seen",
                        kind="inferred",
                        remaining=None,
                        state="no_failure",
                    )
                ],
                "zai": [
                    window(
                        "inferred:no-limit-seen",
                        kind="inferred",
                        remaining=None,
                        state="no_failure",
                    )
                ],
            }
        },
    }


SNAPSHOT = live_snapshot()


def positions(samples):
    """The place of every account, by account."""
    return {
        labels["account"]: value
        for name, labels, value in samples
        if name == "ghostship_ai_account_card_order"
    }


class CardOrderTests(unittest.TestCase):
    def samples(self, snapshot=None):
        """The published samples of the card order."""
        self.assertIsNotNone(
            card_order,
            "the collector does not publish the card order yet",
        )
        return card_order.samples(SNAPSHOT if snapshot is None else snapshot)

    def test_the_approved_cards_come_first_in_the_approved_order(self):
        """The seven cards of the approved list keep their places."""
        places = positions(self.samples())
        for index, account in enumerate(APPROVED, start=1):
            self.assertEqual(places[account], index, account)

    def test_the_accounts_with_a_number_follow_by_name(self):
        """Google and Requesty publish a window with a number."""
        places = positions(self.samples())
        self.assertEqual(places["google"], 8)
        self.assertEqual(places["requesty"], 9)

    def test_the_accounts_that_are_learning_follow_by_name(self):
        """Kilo and Zai are still learning their window."""
        places = positions(self.samples())
        self.assertEqual(places["kilo"], 10)
        self.assertEqual(places["zai"], 11)

    def test_the_live_set_holds_the_place_of_every_account(self):
        self.assertEqual(positions(self.samples()), LIVE_POSITIONS)

    def test_an_approved_account_the_snapshot_does_not_hold_is_skipped(self):
        """The Grok card is gone, and the cards behind it move up."""
        snapshot = live_snapshot()
        del snapshot["quota"]["accounts"]["grok"]
        snapshot["candidates"] = [
            row for row in snapshot["candidates"] if row["provider"] != "grok"
        ]
        places = positions(self.samples(snapshot))
        self.assertNotIn("grok", places)
        self.assertEqual(places["claude"], 1)
        self.assertEqual(places["antigravity"], 5)
        self.assertEqual(places["openrouter"], 6)
        self.assertEqual(places["google"], 7)
        self.assertEqual(places["requesty"], 8)
        self.assertEqual(places["kilo"], 9)
        self.assertEqual(places["zai"], 10)

    def test_an_account_the_snapshot_knows_only_by_its_routes_is_published(self):
        """An account with a candidate and no window of its own."""
        snapshot = {
            "candidates": [candidate("cursor", "cursor-paid-01")],
            "quota": {"accounts": {}},
        }
        self.assertEqual(positions(self.samples(snapshot)), {"cursor": 1})

    def test_no_two_accounts_take_one_place(self):
        places = list(positions(self.samples()).values())
        self.assertEqual(len(places), len(set(places)))

    def test_no_place_is_zero(self):
        for account, place in positions(self.samples()).items():
            self.assertGreater(place, 0, account)

    def test_every_account_is_published_once(self):
        accounts = [
            labels["account"]
            for name, labels, _value in self.samples()
            if name == "ghostship_ai_account_card_order"
        ]
        self.assertEqual(len(accounts), len(set(accounts)))
        self.assertEqual(sorted(accounts), sorted(LIVE_POSITIONS))

    def test_the_places_hold_no_gap(self):
        places = sorted(positions(self.samples()).values())
        self.assertEqual(places, list(range(1, len(places) + 1)))


class CardOrderWiringTests(unittest.TestCase):
    def test_the_collector_publishes_the_card_order(self):
        text = main.render([], [], NOW, 0.0, SNAPSHOT)
        self.assertIn(
            'ghostship_ai_account_card_order{account="claude"} 1',
            text,
        )
        self.assertIn(
            'ghostship_ai_account_card_order{account="openrouter"} 7',
            text,
        )
        self.assertIn(
            'ghostship_ai_account_card_order{account="zai"} 11',
            text,
        )

    def test_the_help_text_names_the_new_series(self):
        text = main.render([], [], NOW, 0.0, SNAPSHOT)
        self.assertIn("# HELP ghostship_ai_account_card_order ", text)

    def test_the_rendering_holds_no_repeated_series(self):
        text = main.render([], [], NOW, 0.0, SNAPSHOT)
        self.assertIn("ghostship_ai_account_card_order{", text)
        seen = set()
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            name, _, labels = line.partition("{")
            key = (name.strip(), labels.partition("}")[0])
            self.assertNotIn(key, seen, f"the file holds {key} twice")
            seen.add(key)


if __name__ == "__main__":
    unittest.main()
