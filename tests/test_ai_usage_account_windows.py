"""The account window series: one card row per capacity window.

A card of a provider holds one row per capacity window of the account:
the label of the window, the share that is left, the even-spend line and
the reset. The collector publishes those rows as gauges, read straight
from the routing snapshot, so the page never recomputes a window.

One window is read more than once. The OpenCode Go status surface names
its windows `go_rolling`, `go_weekly` and `go_monthly` while the Go usage
endpoint names the same three windows `rolling`, `weekly` and `monthly`,
and two readings of one window arrive under one account. The window is
published once: the reading that carries the length of the window wins,
then the one that carries its reset, then the freshest one, then the one
with the least left, and finally the one that resets first.

The records in this file are a copy of the live ones. They hold invented
values only.
"""

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stderr
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


snapshot = load("ai_usage_account_windows_snapshot", "snapshot.py")
main = load("ai_usage_account_windows_main", "main.py")

# The moment the live readings were taken: 2026-10-22T20:40:00Z.
NOW = 1792701600.0


def iso(epoch):
    """A moment, as the snapshot publishes it."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def epoch_of(value):
    """A moment, in seconds."""
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def record(
    quota_id,
    kind,
    remaining=None,
    seconds_to_reset=None,
    duration=None,
    reset_at=None,
    check_at=None,
    evidence="provider_reported",
    inference=None,
):
    """One measured window, in the shape the snapshot publishes it in."""
    window = {
        "quota_id": quota_id,
        "kind": kind,
        "evidence": evidence,
        "used_ratio": None if remaining is None else round(1.0 - remaining, 4),
        "remaining_ratio": remaining,
        "reset_at": reset_at,
        "seconds_to_reset": seconds_to_reset,
        "duration_seconds": duration,
        "basis": "the provider reported the window",
        "label": "",
        "ends_at": None,
        "check_at": check_at,
        "provenance": "collector",
    }
    if inference is not None:
        window["inference"] = dict(inference)
    return window


# The live account windows, as the routing snapshot holds them.
LIVE_ACCOUNTS = {
    # Claude: a session window and two weekly windows, one of them for a
    # model family.
    "claude": [
        record(
            "five_hour",
            "session",
            remaining=0.67,
            seconds_to_reset=7722,
            duration=18000,
            reset_at=iso(NOW + 7722),
            check_at=iso(NOW - 60),
        ),
        record(
            "seven_day",
            "weekly",
            remaining=0.77,
            seconds_to_reset=518400,
            duration=604800,
            reset_at=iso(NOW + 518400),
            check_at=iso(NOW - 60),
        ),
        record(
            "seven_day_fable",
            "weekly",
            remaining=1.0,
            seconds_to_reset=518400,
            duration=604800,
            reset_at=iso(NOW + 518400),
            check_at=iso(NOW - 60),
        ),
    ],
    # OpenCode Go: the status surface and the usage endpoint name the
    # same three windows, and the status names the monthly one without a
    # length.
    "opencode-go": [
        record(
            "go_rolling",
            "session",
            remaining=1.0,
            seconds_to_reset=7200,
            duration=18000,
            reset_at=iso(NOW + 7200),
            check_at=iso(NOW - 120),
        ),
        record(
            "rolling",
            "session",
            remaining=1.0,
            seconds_to_reset=7200,
            duration=18000,
            reset_at=iso(NOW + 7200),
            check_at=iso(NOW - 60),
        ),
        record(
            "go_weekly",
            "weekly",
            remaining=1.0,
            seconds_to_reset=345600,
            duration=604800,
            reset_at=iso(NOW + 345600),
            check_at=iso(NOW - 120),
        ),
        record(
            "weekly",
            "weekly",
            remaining=1.0,
            seconds_to_reset=345600,
            duration=604800,
            reset_at=iso(NOW + 345600),
            check_at=iso(NOW - 60),
        ),
        record(
            "go_monthly",
            "monthly",
            remaining=0.0,
            seconds_to_reset=696789,
            duration=None,
            reset_at=iso(NOW + 696789),
            check_at=iso(NOW - 120),
        ),
        record(
            "monthly",
            "monthly",
            remaining=0.0,
            seconds_to_reset=696789,
            duration=2592000,
            reset_at=iso(NOW + 696789),
            check_at=iso(NOW - 60),
        ),
    ],
    # Grok: two readings of one subscription window, one without a length.
    "grok": [
        record(
            "subscription",
            "weekly",
            remaining=0.0,
            seconds_to_reset=241920,
            duration=None,
            reset_at=iso(NOW + 241920),
            check_at=iso(NOW - 90),
        ),
        record(
            "subscription",
            "weekly",
            remaining=0.0,
            seconds_to_reset=241920,
            duration=604800,
            reset_at=iso(NOW + 241920),
            check_at=iso(NOW - 60),
        ),
    ],
    # Antigravity: two readings of one quota window, one without a reset.
    "antigravity": [
        record(
            "quotaInfo",
            "quota",
            remaining=0.42,
            seconds_to_reset=None,
            duration=None,
            reset_at=None,
            check_at=iso(NOW - 300),
        ),
        record(
            "quotaInfo",
            "quota",
            remaining=0.42,
            seconds_to_reset=43200,
            duration=None,
            reset_at=iso(NOW + 43200),
            check_at=iso(NOW - 300),
        ),
    ],
    # Google: the account publishes no window of its own yet.
    "google": [],
    # OpenRouter: the inference saw no limit failure, so the account has
    # no period to show.
    "openrouter": [
        record(
            "inferred:no-limit-seen",
            "inferred",
            remaining=1.0,
            check_at=iso(NOW - 120),
            evidence="inferred",
        ),
    ],
    # Requesty: the inference learned a five hour window.
    "requesty": [
        record(
            "inferred:5h",
            "inferred",
            remaining=0.4,
            seconds_to_reset=9000,
            duration=18000,
            reset_at=iso(NOW + 9000),
            check_at=iso(NOW - 120),
            evidence="inferred",
        ),
    ],
    # Vercel: the reading of the window could not be read.
    "vercel": [
        record(
            "weekly",
            "weekly",
            remaining=None,
            check_at=iso(NOW - 300),
            evidence="unknown",
        ),
    ],
}


def capacity_of(accounts):
    """The provider capacity of every account, as the snapshot holds it."""
    return {
        account: {
            "remaining_ratio": None,
            "binding": None,
            "windows": len(records),
            "unknown_windows": 0,
            "basis": "the lowest applicable remaining share",
        }
        for account, records in accounts.items()
    }


def build_snapshot(accounts=None, capacity=None):
    """The routing snapshot with a copy of the live account windows in it."""
    windows = LIVE_ACCOUNTS if accounts is None else accounts
    return {
        "quota": {
            "accounts": {
                account: [dict(item) for item in records]
                for account, records in windows.items()
            },
            "provider_capacity": (
                capacity_of(windows) if capacity is None else dict(capacity)
            ),
        }
    }


def render(data):
    """The metrics file the collector writes for a snapshot."""
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        return main.render([], [], NOW, 0.5, data)


class AccountWindowTests(unittest.TestCase):
    """The rows of the cards of the Providers page."""

    def setUp(self):
        self.data = build_snapshot()
        self.samples = snapshot.account_window_samples(self.data)

    def rows(self, name, account=None):
        """The rows of one metric, by their labels."""
        return [
            (labels, value)
            for metric, labels, value in self.samples
            if metric == name and (account is None or labels.get("account") == account)
        ]

    def row(self, name, account, quota_id):
        """The one row of a window."""
        found = [
            (labels, value)
            for labels, value in self.rows(name, account)
            if labels.get("quota_id") == quota_id
        ]
        self.assertEqual(len(found), 1, f"expected one {name} for {account}/{quota_id}")
        return found[0]

    def learning(self):
        """The accounts that publish no window of their own."""
        return {
            labels["account"]: value
            for labels, value in self.rows("ghostship_ai_account_window_learning")
        }

    def test_a_session_window_publishes_the_share_the_line_and_the_reset(self):
        labels, value = self.row(
            "ghostship_ai_account_window_remaining_ratio", "claude", "five_hour"
        )
        self.assertEqual(value, 0.67)
        self.assertEqual(labels["kind"], "session")
        self.assertEqual(labels["label"], "Session")
        self.assertEqual(labels["evidence"], "provider_reported")
        # The even-spend line of the window: 7722 of the 18000 seconds it
        # has left.
        _labels, value = self.row(
            "ghostship_ai_account_window_expected_remaining_ratio", "claude", "five_hour"
        )
        self.assertEqual(value, 0.429)
        _labels, value = self.row(
            "ghostship_ai_account_window_reset_timestamp_seconds", "claude", "five_hour"
        )
        self.assertEqual(value, NOW + 7722)
        # The session window is the first row of the card.
        _labels, value = self.row("ghostship_ai_account_window_order", "claude", "five_hour")
        self.assertEqual(value, 1.0)

    def test_two_weekly_windows_of_one_account_are_two_rows(self):
        labels, value = self.row(
            "ghostship_ai_account_window_remaining_ratio", "claude", "seven_day"
        )
        self.assertEqual(value, 0.77)
        self.assertEqual(labels["label"], "Weekly")
        labels, value = self.row(
            "ghostship_ai_account_window_remaining_ratio", "claude", "seven_day_fable"
        )
        self.assertEqual(value, 1.0)
        # The window that names a model family says which one it is.
        self.assertEqual(labels["label"], "Weekly · Fable")

    def test_the_two_names_of_one_window_are_one_row(self):
        rows = self.rows("ghostship_ai_account_window_remaining_ratio", "opencode-go")
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            sorted(labels["quota_id"] for labels, _value in rows),
            ["monthly", "rolling", "weekly"],
        )

    def test_the_reading_that_carries_the_length_of_a_window_is_the_one_published(self):
        labels, value = self.row(
            "ghostship_ai_account_window_remaining_ratio", "opencode-go", "monthly"
        )
        self.assertEqual(value, 0.0)
        self.assertEqual(labels["kind"], "monthly")
        # The even-spend line of the monthly window: 696789 of its 2592000
        # seconds.
        _labels, value = self.row(
            "ghostship_ai_account_window_expected_remaining_ratio", "opencode-go", "monthly"
        )
        self.assertEqual(value, 0.269)

    def test_two_readings_of_one_subscription_window_are_one_row(self):
        rows = self.rows("ghostship_ai_account_window_remaining_ratio", "grok")
        self.assertEqual(len(rows), 1)
        # The reading that carries the length of the window is the one that
        # is published, so the even-spend line is there.
        _labels, value = self.row(
            "ghostship_ai_account_window_expected_remaining_ratio", "grok", "subscription"
        )
        self.assertEqual(value, 0.4)

    def test_a_quota_window_takes_the_reset_of_the_reading_that_has_it(self):
        rows = self.rows("ghostship_ai_account_window_order", "antigravity")
        self.assertEqual(len(rows), 1)
        _labels, value = self.row(
            "ghostship_ai_account_window_reset_timestamp_seconds", "antigravity", "quotaInfo"
        )
        self.assertEqual(value, NOW + 43200)
        # The window has no length, so it has no even-spend line.
        self.assertEqual(
            self.rows("ghostship_ai_account_window_expected_remaining_ratio", "antigravity"),
            [],
        )

    def test_an_account_with_no_window_is_learning(self):
        self.assertEqual(self.learning().get("google"), 1.0)
        self.assertEqual(self.rows("ghostship_ai_account_window_order", "google"), [])

    def test_the_mark_of_an_account_with_no_limit_is_not_a_window(self):
        self.assertEqual(self.rows("ghostship_ai_account_window_order", "openrouter"), [])
        self.assertEqual(self.learning().get("openrouter"), 1.0)

    def test_an_inferred_window_is_a_row_of_its_own(self):
        labels, value = self.row(
            "ghostship_ai_account_window_remaining_ratio", "requesty", "inferred:5h"
        )
        self.assertEqual(value, 0.4)
        self.assertEqual(labels["kind"], "inferred")
        self.assertEqual(labels["label"], "Inferred · 5h")
        self.assertEqual(labels["evidence"], "inferred")
        # An inferred window comes after every window a provider reported.
        _labels, value = self.row(
            "ghostship_ai_account_window_order", "requesty", "inferred:5h"
        )
        self.assertEqual(value, 8.0)
        self.assertNotIn("requesty", self.learning())

    def test_a_window_with_an_unknown_reading_keeps_its_row(self):
        self.assertEqual(
            self.rows("ghostship_ai_account_window_remaining_ratio", "vercel"), []
        )
        _labels, value = self.row("ghostship_ai_account_window_order", "vercel", "weekly")
        self.assertEqual(value, 3.0)
        # The account publishes a row, so it is not learning.
        self.assertNotIn("vercel", self.learning())

    def test_every_value_is_read_from_the_snapshot(self):
        for name, labels, value in self.samples:
            if name == "ghostship_ai_account_window_learning":
                continue
            windows = self.windows_of(labels["account"], labels["quota_id"])
            if name == "ghostship_ai_account_window_remaining_ratio":
                self.assertIn(
                    value,
                    [
                        item["remaining_ratio"]
                        for item in windows
                        if item["remaining_ratio"] is not None
                    ],
                )
            elif name == "ghostship_ai_account_window_expected_remaining_ratio":
                self.assertIn(
                    value,
                    [
                        round(
                            min(
                                1.0,
                                max(
                                    0.0,
                                    float(item["seconds_to_reset"])
                                    / float(item["duration_seconds"]),
                                ),
                            ),
                            3,
                        )
                        for item in windows
                        if item["seconds_to_reset"] is not None
                        and item["duration_seconds"]
                    ],
                )
            elif name == "ghostship_ai_account_window_reset_timestamp_seconds":
                self.assertIn(
                    value,
                    [
                        epoch_of(item["reset_at"])
                        for item in windows
                        if item["reset_at"]
                    ],
                )
            elif name == "ghostship_ai_account_window_check_timestamp_seconds":
                # The check time of the reading the row is drawn from.
                self.assertIn(
                    value,
                    [
                        epoch_of(item["check_at"])
                        for item in windows
                        if item["check_at"]
                    ],
                )
            elif name == "ghostship_ai_account_window_rolling":
                self.assertEqual(value, 1.0)
            else:
                self.assertIn(value, (1.0, 2.0, 3.0, 4.0, 5.0, 8.0, 9.0))

    def windows_of(self, account, quota_id):
        """The readings of a window, as the snapshot holds them."""
        found = [
            item
            for item in self.data["quota"]["accounts"][account]
            if item["quota_id"] == quota_id
        ]
        self.assertTrue(found, f"no record for {account}/{quota_id}")
        return found

    def test_the_rows_of_a_card_are_published_once(self):
        text = render(self.data)
        # The collector's own guard stays at zero: no two rows share a name
        # and a label set.
        self.assertIn("ghostship_ai_collection_duplicate_series 0", text)
        for name in (
            "ghostship_ai_account_window_remaining_ratio",
            "ghostship_ai_account_window_expected_remaining_ratio",
            "ghostship_ai_account_window_reset_timestamp_seconds",
            "ghostship_ai_account_window_check_timestamp_seconds",
            "ghostship_ai_account_window_rolling",
            "ghostship_ai_account_window_order",
            "ghostship_ai_account_window_learning",
        ):
            self.assertIn(f"# TYPE {name} gauge", text)
        self.assertEqual(
            text.count('ghostship_ai_account_window_order{account="claude"'),
            3,
        )

    def test_a_window_that_is_not_in_the_accounts_is_not_published(self):
        data = build_snapshot()
        # A model of an account carries its own capacity, and that capacity
        # is not a window of the account.
        data["candidates"] = [
            {
                "provider": "claude",
                "model": "claude-opus-5-5",
                "capacity": {"remaining_ratio": 0.5},
            }
        ]
        samples = snapshot.account_window_samples(data)
        rows = [
            (name, labels, value)
            for name, labels, value in samples
            if name.startswith("ghostship_ai_account_window")
        ]
        # The rows of the accounts are the same as they were: the capacity
        # of a model is not a window of the account.
        self.assertEqual(len(rows), len(self.samples))

    def test_an_account_that_only_has_a_capacity_is_learning(self):
        data = {
            "quota": {
                "accounts": {},
                "provider_capacity": {
                    "groq": {
                        "remaining_ratio": None,
                        "binding": None,
                        "windows": 0,
                        "unknown_windows": 0,
                    }
                },
            }
        }
        self.assertEqual(
            snapshot.account_window_samples(data),
            [("ghostship_ai_account_window_learning", {"account": "groq"}, 1.0)],
        )

    def test_the_order_of_a_row_follows_its_kind(self):
        kinds = ("session", "daily", "weekly", "monthly", "quota", "inferred", "other")
        accounts = {
            "kinded": [
                record(f"quota_{kind}", kind, remaining=0.5, check_at=iso(NOW - 60))
                for kind in kinds
            ]
        }
        data = build_snapshot(accounts=accounts)
        samples = snapshot.account_window_samples(data)
        orders = {
            labels["kind"]: value
            for name, labels, value in samples
            if name == "ghostship_ai_account_window_order"
        }
        self.assertEqual(
            orders,
            {
                "session": 1.0,
                "daily": 2.0,
                "weekly": 3.0,
                "monthly": 4.0,
                "quota": 5.0,
                "inferred": 8.0,
                "other": 9.0,
            },
        )


class AccountWindowCheckTimeTests(unittest.TestCase):
    """How old a reading is, and the rolling mark of an inferred window.

    A card is compared with the provider's own site, so the age of a
    reading has to be published: the check time of the record the row is
    drawn from, in seconds. A reading without a check time publishes no
    check time, and the other series of the row stay as they are. An
    inferred window that rolls carries the mark, so the page can say
    'rolling'.
    """

    def rows(self, data, name, account=None):
        """The rows of one metric, by their labels."""
        return [
            (labels, value)
            for metric, labels, value in snapshot.account_window_samples(data)
            if metric == name and (account is None or labels.get("account") == account)
        ]

    def declared(self, name):
        """The collector declares the series, so the page can read it."""
        self.assertIn(name, main.METRIC_HELP)

    def test_the_check_time_of_a_window_is_published(self):
        data = build_snapshot(
            accounts={
                "claude": [
                    record(
                        "five_hour",
                        "session",
                        remaining=0.67,
                        seconds_to_reset=7722,
                        duration=18000,
                        reset_at=iso(NOW + 7722),
                        check_at="2026-10-22T20:56:18Z",
                    )
                ]
            }
        )
        rows = self.rows(data, "ghostship_ai_account_window_check_timestamp_seconds")
        self.assertEqual(len(rows), 1)
        labels, value = rows[0]
        self.assertEqual(value, 1792702578)
        self.assertEqual(labels["account"], "claude")
        self.assertEqual(labels["kind"], "session")
        self.assertEqual(labels["quota_id"], "five_hour")
        self.assertEqual(labels["label"], "Session")
        self.assertEqual(labels["evidence"], "provider_reported")

    def test_two_readings_of_one_window_publish_one_check_time(self):
        # The Go status names its window go_rolling and the Go usage
        # endpoint names the same window rolling. The freshest reading is
        # the one the row is drawn from, and the check time is its own.
        data = build_snapshot(
            accounts={
                "opencode-go": [
                    record(
                        "go_rolling",
                        "session",
                        remaining=1.0,
                        seconds_to_reset=7200,
                        duration=18000,
                        reset_at=iso(NOW + 7200),
                        check_at="2026-10-22T21:01:18Z",
                    ),
                    record(
                        "rolling",
                        "session",
                        remaining=1.0,
                        seconds_to_reset=7200,
                        duration=18000,
                        reset_at=iso(NOW + 7200),
                        check_at="2026-10-22T21:01:17Z",
                    ),
                ]
            }
        )
        rows = self.rows(data, "ghostship_ai_account_window_check_timestamp_seconds")
        self.assertEqual(len(rows), 1)
        labels, value = rows[0]
        self.assertEqual(value, 1792702878)
        self.assertEqual(labels["quota_id"], "go_rolling")

    def test_a_reading_without_a_check_time_publishes_no_check_time(self):
        self.declared("ghostship_ai_account_window_check_timestamp_seconds")
        data = build_snapshot(
            accounts={
                "claude": [
                    record(
                        "five_hour",
                        "session",
                        remaining=0.67,
                        seconds_to_reset=7722,
                        duration=18000,
                        reset_at=iso(NOW + 7722),
                        check_at=None,
                    )
                ]
            }
        )
        self.assertEqual(
            self.rows(data, "ghostship_ai_account_window_check_timestamp_seconds"), []
        )
        # The other series of the row are unchanged.
        remaining = self.rows(data, "ghostship_ai_account_window_remaining_ratio")
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0][1], 0.67)
        expected = self.rows(data, "ghostship_ai_account_window_expected_remaining_ratio")
        self.assertEqual(len(expected), 1)
        self.assertEqual(expected[0][1], 0.429)
        reset = self.rows(data, "ghostship_ai_account_window_reset_timestamp_seconds")
        self.assertEqual(len(reset), 1)
        self.assertEqual(reset[0][1], NOW + 7722)
        order = self.rows(data, "ghostship_ai_account_window_order")
        self.assertEqual(len(order), 1)
        self.assertEqual(order[0][1], 1.0)

    def test_an_inferred_rolling_window_is_marked(self):
        data = build_snapshot(
            accounts={
                "learner": [
                    record(
                        "inferred:1m",
                        "inferred",
                        remaining=0.5,
                        check_at=iso(NOW - 120),
                        evidence="inferred",
                        inference={"rolling": True},
                    )
                ]
            }
        )
        rows = self.rows(data, "ghostship_ai_account_window_rolling")
        self.assertEqual(len(rows), 1)
        labels, value = rows[0]
        self.assertEqual(value, 1.0)
        self.assertEqual(labels["account"], "learner")
        self.assertEqual(labels["kind"], "inferred")
        self.assertEqual(labels["quota_id"], "inferred:1m")
        self.assertEqual(labels["evidence"], "inferred")
        # A rolling window has no reset and no even-spend line.
        self.assertEqual(
            self.rows(data, "ghostship_ai_account_window_reset_timestamp_seconds"), []
        )
        self.assertEqual(
            self.rows(data, "ghostship_ai_account_window_expected_remaining_ratio"), []
        )

    def test_a_reading_without_a_rolling_mark_publishes_no_rolling_mark(self):
        self.declared("ghostship_ai_account_window_rolling")
        data = build_snapshot(
            accounts={
                "claude": [
                    record(
                        "five_hour",
                        "session",
                        remaining=0.67,
                        seconds_to_reset=7722,
                        duration=18000,
                        reset_at=iso(NOW + 7722),
                        check_at=iso(NOW - 60),
                    )
                ]
            }
        )
        self.assertEqual(self.rows(data, "ghostship_ai_account_window_rolling"), [])

    def test_a_learning_account_publishes_no_check_time(self):
        self.declared("ghostship_ai_account_window_check_timestamp_seconds")
        self.declared("ghostship_ai_account_window_rolling")
        data = build_snapshot()
        # The account publishes no window of its own, so it has no reading
        # and no age.
        self.assertEqual(
            self.rows(data, "ghostship_ai_account_window_check_timestamp_seconds", "google"),
            [],
        )
        self.assertEqual(
            self.rows(data, "ghostship_ai_account_window_rolling", "google"), []
        )

    def test_every_series_of_a_row_carries_the_labels_of_the_row(self):
        self.declared("ghostship_ai_account_window_check_timestamp_seconds")
        data = build_snapshot()
        rows: dict[tuple, list] = {}
        for name, labels, value in snapshot.account_window_samples(data):
            if name == "ghostship_ai_account_window_learning":
                continue
            key = (labels["account"], labels["kind"], labels["quota_id"])
            rows.setdefault(key, []).append(dict(labels))
        self.assertTrue(rows)
        for key, label_sets in rows.items():
            distinct = {
                tuple(sorted((str(name), str(value)) for name, value in labels.items()))
                for labels in label_sets
            }
            self.assertEqual(
                len(distinct),
                1,
                f"the row {key} publishes series with different labels",
            )
        # Every row of the live accounts publishes the time it was read.
        self.assertEqual(
            len(self.rows(data, "ghostship_ai_account_window_check_timestamp_seconds")),
            len(rows),
        )


class InferredWindowLabelTests(unittest.TestCase):
    """The label of a row of an inferred window.

    An inferred window names the window the inference learned. A suffix
    that is a length of time is that window and the label says so: '5h'
    reads 'Inferred · 5h'. A suffix that names a state of the inference
    is not a period, so the row is named by its kind alone: 'exhausted'
    reads 'Inferred'.
    """

    def labels_of(self, records):
        """The label of the row of every window given."""
        data = build_snapshot(accounts={"learner": [dict(item) for item in records]})
        rows = [
            labels
            for name, labels, value in snapshot.account_window_samples(data)
            if name == "ghostship_ai_account_window_remaining_ratio"
        ]
        return {labels["quota_id"]: labels["label"] for labels in rows}

    def label_of(self, quota_id, kind="inferred", remaining=0.5, duration=None):
        """The label of the one row of one window."""
        labels = self.labels_of(
            [
                record(
                    quota_id,
                    kind,
                    remaining=remaining,
                    duration=duration,
                    check_at=iso(NOW - 120),
                    evidence="inferred" if kind == "inferred" else "provider_reported",
                )
            ]
        )
        self.assertEqual(len(labels), 1, f"expected one row for {quota_id}")
        return labels[quota_id]

    def test_an_inferred_window_names_the_window_it_was_learned_over(self):
        self.assertEqual(self.label_of("inferred:5h", duration=18000), "Inferred · 5h")

    def test_an_inferred_window_of_a_minute_names_the_minute(self):
        self.assertEqual(self.label_of("inferred:1m", duration=60), "Inferred · 1m")

    def test_an_inferred_window_of_twelve_days_names_the_days(self):
        self.assertEqual(self.label_of("inferred:12d", duration=1036800), "Inferred · 12d")

    def test_an_inferred_window_that_names_a_state_is_named_by_its_kind(self):
        # 'exhausted' is a state of the inference, not a period, so the
        # row is named by its kind alone.
        self.assertEqual(self.label_of("inferred:exhausted", remaining=0.0), "Inferred")

    def test_a_window_that_names_a_model_family_still_names_it(self):
        labels = self.labels_of(
            [
                record("seven_day", "weekly", remaining=0.77, check_at=iso(NOW - 60)),
                record("seven_day_fable", "weekly", remaining=1.0, check_at=iso(NOW - 60)),
            ]
        )
        self.assertEqual(labels["seven_day"], "Weekly")
        self.assertEqual(labels["seven_day_fable"], "Weekly · Fable")

    def test_the_mark_of_an_account_with_no_limit_is_not_a_row(self):
        data = build_snapshot(
            accounts={
                "learner": [
                    record(
                        "inferred:no-limit-seen",
                        "inferred",
                        remaining=1.0,
                        check_at=iso(NOW - 120),
                        evidence="inferred",
                    )
                ]
            }
        )
        samples = snapshot.account_window_samples(data)
        self.assertEqual(
            [
                labels
                for name, labels, value in samples
                if name == "ghostship_ai_account_window_remaining_ratio"
            ],
            [],
        )
        self.assertEqual(
            [
                (name, labels, value)
                for name, labels, value in samples
                if name == "ghostship_ai_account_window_learning"
            ],
            [("ghostship_ai_account_window_learning", {"account": "learner"}, 1.0)],
        )


if __name__ == "__main__":
    unittest.main()
