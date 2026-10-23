"""The availability of every account: can it serve right now, and why not.

A provider whose account publishes no limit of its own used to reach the
Providers page as a bare "learning window" chip: the page could not say
whether the account could serve a request at all. The collector now
publishes, per account, whether it can serve right now, why it cannot when
it cannot, whether its limit is unpublished or still being learned, and when
that was observed.

Every value is read from the routing snapshot, and nothing is recomputed.
The routes of an account that count are its free or promotional routes when
it holds any, and all of its routes otherwise. The state is available when
one of the routes that count is available. The reason of an account that
cannot serve is the reason its routes carry most often, and a route in
cooldown names the moment it cools down. The basis says where the limit of
the account comes from: an account that never saw a limit failure is
learning, an account that publishes no number has an unpublished limit, and
every other account publishes one. The check time is the newest observation
of the routes that count.

The records in this file are a copy of the live set of 2026-10-23. They
hold invented values only.
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
    account_availability = load(
        "ai_usage_account_availability_module", "account_availability.py"
    )
except FileNotFoundError:
    # The collector does not publish the account availability yet. Every
    # test below says so, and says which reading is missing.
    account_availability = None

main = load("ai_usage_account_availability_main", "main.py")

# The moment the live snapshot was written.
SNAPSHOT_AT = datetime(2026, 10, 23, 4, 23, 0, tzinfo=timezone.utc)
NOW = SNAPSHOT_AT.timestamp()


def moment(text):
    """The epoch of an ISO-8601 moment."""
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


# The observations of the live set, in the order the collector wrote them.
KILO_OBSERVED = [
    "2026-10-23T04:16:00Z",
    "2026-10-23T04:17:00Z",
    "2026-10-23T04:18:00Z",
    "2026-10-23T04:19:00Z",
    "2026-10-23T04:20:00Z",
    "2026-10-23T04:21:00Z",
    "2026-10-23T04:22:00Z",
    "2026-10-23T04:23:00Z",
]


def candidate(
    provider,
    model,
    billing="free",
    available=True,
    reason="",
    observed_at="2026-10-23T04:23:00Z",
    cooldown=None,
):
    """One candidate row of the routing snapshot."""
    kinds = {
        "free": "dedicated_free",
        "promotion": "provider_promo",
        "subscription": "provider_paid",
        "pay_per_token": "provider_paid",
    }
    return {
        "provider": provider,
        "model": model,
        "available": available,
        "access": {"kind": kinds.get(billing, "unknown"), "billing": billing},
        "availability": {
            "state": "available" if available else "unavailable",
            "reason": reason,
        },
        "capacity": {},
        "free_pool": {"state": "not_a_pool_route", "cooldown_until": cooldown},
        "provenance": {"source": "collector", "observed_at": observed_at},
    }


def window(quota_id, kind="quota", remaining=None, state=None):
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
        "label": "",
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


def live_candidates():
    """The candidate rows of the live snapshot, as the collector wrote them."""
    rows = []
    # Kilo: eight free routes, all of them usable, and every one of them
    # says that the windows of the account have headroom.
    for index, observed in enumerate(KILO_OBSERVED, start=1):
        rows.append(
            candidate(
                "kilo",
                f"kilo-free-model-{index:02d}",
                available=True,
                reason="every applicable window has headroom",
                observed_at=observed,
            )
        )
    # Requesty: seven free routes, none of them usable, and every one of
    # them says nothing. Five of them are in cooldown for the same moment,
    # one for a later one, and one for a moment that has passed.
    cooldowns = [NOW + 1500] * 5 + [NOW + 3600, NOW - 600]
    for index, cooldown in enumerate(cooldowns, start=1):
        rows.append(
            candidate(
                "requesty",
                f"requesty-free-{index:02d}",
                available=False,
                reason="",
                observed_at="2026-10-23T04:22:00Z",
                cooldown=cooldown,
            )
        )
    # OpenCode Go: five free routes, two of them usable, two of them the
    # instance does not offer, and one of them retired. The paid routes of
    # the same account are not counted.
    rows.append(
        candidate(
            "opencode-go",
            "beam-free",
            available=True,
            reason="every applicable window has headroom",
            observed_at="2026-10-23T04:22:00Z",
        )
    )
    rows.append(
        candidate(
            "opencode-go",
            "beam-lite-free",
            available=True,
            reason="every applicable window has headroom",
            observed_at="2026-10-23T04:21:00Z",
        )
    )
    for model, observed in (
        ("cat-jam-free", "2026-10-23T04:20:00Z"),
        ("step-5-preview-free", "2026-10-23T04:19:00Z"),
    ):
        rows.append(
            candidate(
                "opencode-go",
                model,
                available=False,
                reason="not offered by the T3 instance (deprecated in the catalog)",
                observed_at=observed,
            )
        )
    rows.append(
        candidate(
            "opencode-go",
            "beam-max-free",
            available=False,
            reason="model_retired",
            observed_at="2026-10-23T04:18:00Z",
        )
    )
    # The paid routes of the Go account. The monthly allowance of the
    # account is spent, and they are not free routes.
    for index, observed in enumerate(
        ("2026-10-23T04:23:30Z", "2026-10-23T04:23:45Z"), start=1
    ):
        rows.append(
            candidate(
                "opencode-go",
                f"beam-subscription-{index:02d}",
                billing="subscription",
                available=False,
                reason="a window is spent",
                observed_at=observed,
            )
        )
    # OpenRouter: two free routes the instance does not offer, and a paid
    # route that works.
    for index, observed in enumerate(
        ("2026-10-23T04:20:00Z", "2026-10-23T04:19:00Z"), start=1
    ):
        rows.append(
            candidate(
                "openrouter",
                f"openrouter-free-{index:02d}",
                available=False,
                reason="not offered by the T3 instance",
                observed_at=observed,
            )
        )
    rows.append(
        candidate(
            "openrouter",
            "openrouter-paid",
            billing="pay_per_token",
            available=True,
            reason="every applicable window has headroom",
            observed_at="2026-10-23T04:23:20Z",
        )
    )
    # Claude: paid routes only, and the windows of the account are
    # published.
    for index, observed in enumerate(
        ("2026-10-23T04:21:00Z", "2026-10-23T04:20:30Z"), start=1
    ):
        rows.append(
            candidate(
                "claude",
                f"claude-paid-{index:02d}",
                billing="subscription",
                available=True,
                reason="every applicable window has headroom",
                observed_at=observed,
            )
        )
    # An account that holds a free route and a paid route. The paid route
    # works, and the account is counted by its free route alone.
    rows.append(
        candidate(
            "sample-mixed",
            "sample-mixed-free",
            available=False,
            reason="a window is spent",
            observed_at="2026-10-23T04:17:00Z",
        )
    )
    rows.append(
        candidate(
            "sample-mixed",
            "sample-mixed-paid",
            billing="subscription",
            available=True,
            reason="every applicable window has headroom",
            observed_at="2026-10-23T04:23:45Z",
        )
    )
    # An account whose routes carry two reasons. The one the routes carry
    # most often is the reason of the account.
    rows.append(
        candidate(
            "sample-counted",
            "sample-counted-free-01",
            available=False,
            reason="model_retired",
            observed_at="2026-10-23T04:15:00Z",
        )
    )
    rows.append(
        candidate(
            "sample-counted",
            "sample-counted-free-02",
            available=False,
            reason="model_retired",
            observed_at="2026-10-23T04:15:30Z",
        )
    )
    rows.append(
        candidate(
            "sample-counted",
            "sample-counted-free-03",
            available=False,
            reason="a window is spent",
            observed_at="2026-10-23T04:16:00Z",
        )
    )
    return rows


SNAPSHOT = {
    "schema": "ghostship.ai-usage.routing",
    "schema_version": "1",
    "generated_at": "2026-10-23T04:23:00Z",
    "candidates": live_candidates(),
    "quota": {
        "accounts": {
            # Kilo: the account never saw a limit failure, so it is still
            # learning its window.
            "kilo": [
                window(
                    "inferred:no-limit-seen",
                    kind="inferred",
                    remaining=None,
                    state="no_failure",
                )
            ],
            # Requesty publishes a window of its own.
            "requesty": [window("quota", kind="quota", remaining=0.4)],
            # The Go account: the monthly allowance is spent, and the
            # window is published.
            "opencode-go": [window("monthly", kind="monthly", remaining=0.0)],
            "openrouter": [window("limit", kind="quota", remaining=0.6)],
            "claude": [window("five_hour", kind="session", remaining=0.7)],
            # The account of a window that carries no number.
            "sample-mixed": [window("quota", kind="quota", remaining=None)],
            # The OpenCode Zen account: it learned a window and saw no
            # limit failure, and it holds no route at all.
            "opencode": [
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

# The accounts the snapshot holds.
ACCOUNTS = (
    "claude",
    "kilo",
    "opencode",
    "opencode-go",
    "openrouter",
    "requesty",
    "sample-counted",
    "sample-mixed",
)


def availability_rows(samples):
    """The availability of every account, by account."""
    return {
        labels["account"]: labels
        for name, labels, _value in samples
        if name == "ghostship_ai_account_availability"
    }


def check_times(samples):
    """The check time of every account, by account."""
    return {
        labels["account"]: value
        for name, labels, value in samples
        if name == "ghostship_ai_account_availability_check_timestamp_seconds"
    }


class AccountAvailabilityTests(unittest.TestCase):
    def samples(self, snapshot=None, now=None):
        """The published samples of the account availability."""
        self.assertIsNotNone(
            account_availability,
            "the collector does not publish the account availability yet",
        )
        return account_availability.samples(
            SNAPSHOT if snapshot is None else snapshot,
            NOW if now is None else now,
        )

    def test_kilo_is_available_and_learning(self):
        """Kilo serves now, and its limit is still being learned."""
        rows = availability_rows(self.samples())
        self.assertEqual(rows["kilo"]["state"], "available")
        self.assertEqual(rows["kilo"]["basis"], "learning")

    def test_the_check_time_of_an_account_is_its_newest_observation(self):
        samples = self.samples()
        self.assertAlmostEqual(
            check_times(samples)["kilo"], moment("2026-10-23T04:23:00Z")
        )

    def test_requesty_is_unavailable_and_cooling_down(self):
        """Its routes say nothing, and the pool cools them down."""
        rows = availability_rows(self.samples())
        self.assertEqual(rows["requesty"]["state"], "unavailable")
        self.assertEqual(rows["requesty"]["reason"], "cooling down until 04:48 UTC")

    def test_an_account_whose_routes_are_not_offered_is_unavailable(self):
        """The reason of the routes is the reason of the account."""
        rows = availability_rows(self.samples())
        self.assertEqual(rows["openrouter"]["state"], "unavailable")
        self.assertEqual(rows["openrouter"]["reason"], "not offered by the T3 instance")

    def test_opencode_go_counts_its_free_routes_only(self):
        """The paid routes of the account are not counted."""
        samples = self.samples()
        rows = availability_rows(samples)
        self.assertEqual(rows["opencode-go"]["state"], "available")
        self.assertEqual(rows["opencode-go"]["basis"], "published")
        # The paid routes of the account were observed later than its free
        # routes, and they are not one of the routes that count.
        self.assertAlmostEqual(
            check_times(samples)["opencode-go"], moment("2026-10-23T04:22:00Z")
        )

    def test_claude_is_available_and_publishes_its_limit(self):
        """A paid account with no free route is counted by all its routes."""
        samples = self.samples()
        rows = availability_rows(samples)
        self.assertEqual(rows["claude"]["state"], "available")
        self.assertEqual(rows["claude"]["basis"], "published")
        self.assertAlmostEqual(
            check_times(samples)["claude"], moment("2026-10-23T04:21:00Z")
        )

    def test_an_account_without_a_route_says_it_has_none(self):
        """The OpenCode account holds no route at all."""
        samples = self.samples()
        rows = availability_rows(samples)
        self.assertEqual(rows["opencode"]["state"], "unavailable")
        self.assertEqual(rows["opencode"]["reason"], "no route available")
        self.assertEqual(rows["opencode"]["basis"], "learning")
        self.assertNotIn("opencode", check_times(samples))

    def test_a_paid_route_is_not_counted_for_an_account_with_free_routes(self):
        """The paid route of the account works, and the account cannot."""
        samples = self.samples()
        rows = availability_rows(samples)
        self.assertEqual(rows["sample-mixed"]["state"], "unavailable")
        self.assertEqual(rows["sample-mixed"]["reason"], "a window is spent")
        self.assertAlmostEqual(
            check_times(samples)["sample-mixed"], moment("2026-10-23T04:17:00Z")
        )

    def test_an_account_without_a_number_has_an_unpublished_limit(self):
        rows = availability_rows(self.samples())
        self.assertEqual(rows["sample-mixed"]["basis"], "unpublished")

    def test_the_reason_the_routes_carry_most_often_is_the_reason(self):
        rows = availability_rows(self.samples())
        self.assertEqual(rows["sample-counted"]["state"], "unavailable")
        self.assertEqual(rows["sample-counted"]["reason"], "model_retired")

    def test_every_account_holds_one_series(self):
        samples = self.samples()
        series = [
            labels
            for name, labels, _value in samples
            if name == "ghostship_ai_account_availability"
        ]
        self.assertEqual(len(series), len(ACCOUNTS))
        self.assertEqual(
            sorted(labels["account"] for labels in series), sorted(ACCOUNTS)
        )

    def test_an_available_account_carries_no_reason(self):
        for account, labels in availability_rows(self.samples()).items():
            if labels["state"] == "available":
                self.assertEqual(labels["reason"], "", account)

    def test_an_unavailable_account_carries_a_reason(self):
        for account, labels in availability_rows(self.samples()).items():
            if labels["state"] == "unavailable":
                self.assertNotEqual(labels["reason"], "", account)


class AccountAvailabilityWiringTests(unittest.TestCase):
    def test_the_collector_publishes_the_availability(self):
        text = main.render([], [], NOW, 0.0, SNAPSHOT)
        self.assertIn(
            'ghostship_ai_account_availability{account="kilo",basis="learning",reason="",state="available"} 1',
            text,
        )
        self.assertIn(
            'ghostship_ai_account_availability{account="requesty",basis="published",reason="cooling down until 04:48 UTC",state="unavailable"} 1',
            text,
        )
        self.assertIn(
            'ghostship_ai_account_availability_check_timestamp_seconds{account="kilo"} '
            f"{moment('2026-10-23T04:23:00Z'):.0f}",
            text,
        )

    def test_the_help_text_names_the_new_series(self):
        text = main.render([], [], NOW, 0.0, SNAPSHOT)
        for name in (
            "ghostship_ai_account_availability",
            "ghostship_ai_account_availability_check_timestamp_seconds",
        ):
            self.assertIn(f"# HELP {name} ", text)

    def test_the_rendering_holds_no_repeated_series(self):
        text = main.render([], [], NOW, 0.0, SNAPSHOT)
        self.assertIn("ghostship_ai_account_availability{", text)
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
