"""The inferred windows the ranking and the snapshot publish.

A provider that never reports its usage shows its capacity from the limit
failures of its routes. Two gaps made that capacity invisible: a route of
the same provider that was never refused filed its own "no limit seen"
window under the provider key, and the refused route's learned window was
skipped as a duplicate; and the account section of the snapshot was filled
from the reported windows only, so no inferred window ever reached it.

These tests pin the publication: the learned window of a refused route is
the provider's capacity in the ranking and in `quota.accounts`, a route
that was never refused never stands in for a refused one, a refused route
outside the ranking keeps its record, and a reported window is never
replaced by an inference.

Every record in this file is synthetic and lives in a temporary directory.
No live database is opened.
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "modules" / "self-hosted" / "ai-usage" / "collector"
if str(COLLECTOR) not in sys.path:
    sys.path.insert(0, str(COLLECTOR))

import catalog as catalog_module  # noqa: E402
import main  # noqa: E402
import usage_inference  # noqa: E402
from metrics import SourceResult  # noqa: E402

# Monday 2026-01-05 00:00 UTC. Every case of a day uses this clock.
DAY0 = 1767571200.0
HOUR = 3600.0
MINUTE = 60.0

# The instant the readings are taken at: 14:20 on the first day.
NOW = DAY0 + 14 * HOUR + 20 * MINUTE

# The words a provider uses when the account's allowance is spent. The
# reader reads them in memory and never keeps them.
LIMIT_MESSAGE = "Your account has reached its usage limit"


def at(hour=0, minute=0, day=0):
    """An instant on the clock of the cases."""
    return DAY0 + day * 86400.0 + hour * HOUR + minute * MINUTE


def record(when, provider="google", model="example-flash-a", usage=None, limit=False):
    """One request record, shaped the way OpenCode writes it."""
    data = {
        "model": {"providerID": provider, "id": model},
        "time": {"created": int(when * 1000)},
    }
    if limit:
        data["error"] = {"type": "provider.quota", "data": {"message": LIMIT_MESSAGE}}
    else:
        data["finish"] = "stop"
        if usage is not None:
            data["tokens"] = {"input": usage, "output": 0, "reasoning": 0}
    return {"at": when, "data": data}


def build_database(directory, records):
    """Build an OpenCode database with the given request records."""
    path = Path(directory) / "opencode.db"
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE session_message ("
            "id TEXT PRIMARY KEY, session_id TEXT, type TEXT, "
            "time_created INTEGER, data TEXT)"
        )
        for index, entry in enumerate(records):
            connection.execute(
                "INSERT INTO session_message (id, session_id, type, time_created, data) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    f"msg_{index}",
                    "ses_synthetic",
                    "assistant",
                    int(entry["at"] * 1000),
                    json.dumps(entry["data"]),
                ),
            )
        connection.commit()
    finally:
        connection.close()
    return str(path)


# The worked record of the owner rule: a route uses its budget from 08:00,
# is refused at 10:30, and its next success is at 13:02. Another route of
# the same provider is never refused.
REFUSED_ROUTE = "example-flash-z"
QUIET_ROUTE = "example-flash-a"
MATHS = [
    record(at(9), model=QUIET_ROUTE, usage=1000),
    record(at(12), model=QUIET_ROUTE, usage=2000),
    record(at(8), model=REFUSED_ROUTE, usage=200000),
    record(at(10, 30), model=REFUSED_ROUTE, limit=True),
    record(at(13, 2), model=REFUSED_ROUTE, usage=0),
]


class PublicationTestCase(unittest.TestCase):
    """The base of the publication cases."""

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="usage-inferred-publication-")
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.cache = os.path.join(self.directory, "events.json")
        self.catalog = catalog_module.Catalog({})

    def infer(self, records=(), routes=(), now=NOW):
        """Read the records, put them on the routes, and infer."""
        database = build_database(self.directory, list(records))
        return usage_inference.read_and_infer(
            now,
            opencode_db=database,
            events_cache=self.cache,
            pool_ledger=None,
            routes=set(routes),
        )

    def windows(self, inferred, routes=(), measured=(), now=NOW):
        """The windows the ranking reads, with the inferred ones in them."""
        context = {
            "offered_models": list(routes),
            "inferred_capacity": inferred.capacities,
        }
        return main.ranking_inputs(
            [], self.catalog, context, list(measured), now=now
        )["windows"]

    def rank(self, inferred, routes=(), measured=(), now=NOW):
        """The ranking of the routes, and the samples it publishes."""
        context = {
            "offered_models": list(routes),
            "inferred_capacity": inferred.capacities,
        }
        results = [
            SourceResult(
                source="measured",
                status="ok",
                reason="ok",
                observed_at=now,
                windows=list(measured),
            )
        ]
        return main.ranking_samples(
            results, self.catalog, context, now, t3_home=self.directory
        )

    def snapshot(self, inferred, routes=(), ranked=(), measured=(), now=NOW):
        """The routing snapshot, with the inferred windows in its accounts."""
        context = {
            "offered_models": list(routes),
            "ranking_inventory": list(routes),
            "inferred_capacity": inferred.capacities,
        }
        return main.build_snapshot(
            [],
            list(ranked),
            context,
            now,
            measured_windows=list(measured),
            catalog=self.catalog,
        )


class RefusedRouteWindowTests(PublicationTestCase):
    """A never-refused route never hides the window of a refused one."""

    def setUp(self):
        super().setUp()
        self.routes = [("google", QUIET_ROUTE), ("google", REFUSED_ROUTE)]
        self.inferred = self.infer(MATHS, self.routes)

    def test_the_quiet_route_does_not_take_the_provider_key(self):
        windows = self.windows(self.inferred, self.routes)
        self.assertIn("google", windows)
        self.assertEqual(
            [window.quota_id for window in windows["google"]], ["inferred:5h"]
        )

    def test_the_learned_window_is_the_one_published(self):
        windows = self.windows(self.inferred, self.routes)
        window = windows["google"][0]
        self.assertEqual(window.kind, "inferred")
        self.assertEqual(window.quota_id, "inferred:5h")
        self.assertEqual(window.duration_seconds, 5 * HOUR)
        self.assertEqual(window.inference["budget"], 200000.0)
        self.assertEqual(window.inference["episodes"], 1)
        self.assertEqual(window.inference["state"], "in_window")

    def test_both_routes_are_read_as_inferred(self):
        _samples, ranked = self.rank(self.inferred, self.routes)
        self.assertEqual(
            sorted(
                (entry.model, entry.capacity_basis, entry.capacity_inference.get("window"))
                for entry in ranked
            ),
            [
                (QUIET_ROUTE, "inferred", "5h"),
                (REFUSED_ROUTE, "inferred", "5h"),
            ],
        )


class AccountSectionTests(PublicationTestCase):
    """The learned window reaches the account section of the snapshot."""

    def test_the_inferred_window_is_published_once_per_account(self):
        routes = [("google", QUIET_ROUTE), ("google", REFUSED_ROUTE)]
        inferred = self.infer(MATHS, routes)
        _samples, ranked = self.rank(inferred, routes)
        snapshot = self.snapshot(inferred, routes, ranked)
        records = snapshot["quota"]["accounts"]["google"]
        self.assertEqual(len(records), 1)
        found = records[0]
        self.assertEqual(found["kind"], "inferred")
        self.assertEqual(found["quota_id"], "inferred:5h")
        self.assertEqual(found["evidence"], "inferred")
        self.assertTrue(found["basis"].startswith("inferred"))
        self.assertEqual(found["inference"]["window"], "5h")
        self.assertEqual(found["inference"]["budget"], 200000.0)
        self.assertEqual(found["inference"]["episodes"], 1)

    def test_a_refused_route_outside_the_ranking_keeps_its_record(self):
        # The route was in the record the inference read, and the ranking
        # does not hold a row for it any more.
        routes = [("example-zen", "example-zen-a")]
        inferred = self.infer(
            [
                record(at(8), provider="example-zen", model="example-zen-a", usage=200000),
                record(at(10, 30), provider="example-zen", model="example-zen-a", limit=True),
                record(at(13, 2), provider="example-zen", model="example-zen-a", usage=0),
            ],
            routes,
        )
        # The ranking is built over an inventory that no longer offers it.
        _samples, ranked = self.rank(inferred, [])
        self.assertEqual(ranked, [])
        snapshot = self.snapshot(inferred, [])
        records = snapshot["quota"]["accounts"]["example-zen"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["quota_id"], "inferred:5h")
        self.assertEqual(records[0]["evidence"], "inferred")
        self.assertEqual(records[0]["inference"]["budget"], 200000.0)

    def test_a_provider_never_refused_publishes_its_no_failure_record(self):
        routes = [("example-quiet", "example-quiet-a")]
        inferred = self.infer(
            [
                record(at(9), provider="example-quiet", model="example-quiet-a", usage=1000),
                record(at(12), provider="example-quiet", model="example-quiet-a", usage=2000),
            ],
            routes,
        )
        _samples, ranked = self.rank(inferred, routes)
        snapshot = self.snapshot(inferred, routes, ranked)
        records = snapshot["quota"]["accounts"]["example-quiet"]
        self.assertEqual(len(records), 1)
        found = records[0]
        self.assertEqual(found["quota_id"], "inferred:no-limit-seen")
        self.assertEqual(found["inference"]["state"], "no_failure")
        self.assertIsNone(found["inference"]["budget"])
        self.assertEqual(found["remaining_ratio"], 1.0)

    def test_a_model_scoped_limit_carries_its_model(self):
        # Another model of the provider succeeds between the refusal and the
        # recovery, so the limit belongs to the refused route's model.
        routes = [("google", QUIET_ROUTE), ("google", REFUSED_ROUTE)]
        inferred = self.infer(
            [
                record(at(8), model=REFUSED_ROUTE, usage=200000),
                record(at(10, 30), model=REFUSED_ROUTE, limit=True),
                record(at(11), model=QUIET_ROUTE, usage=1000),
                record(at(13, 2), model=REFUSED_ROUTE, usage=0),
            ],
            routes,
        )
        self.assertEqual(
            inferred.capacities[("google", REFUSED_ROUTE)]["scope"], "model"
        )
        _samples, ranked = self.rank(inferred, routes)
        snapshot = self.snapshot(inferred, routes, ranked)
        records = snapshot["quota"]["accounts"]["google"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["applies_to"], [REFUSED_ROUTE])
        self.assertEqual(records[0]["quota_id"], "inferred:5h")

    def test_a_reported_window_is_never_replaced(self):
        routes = [("openrouter", "example-model")]
        inferred = self.infer(
            [
                record(at(8), provider="openrouter", usage=200000),
                record(at(10, 30), provider="openrouter", limit=True),
                record(at(13, 2), provider="openrouter", usage=0),
            ],
            routes,
        )
        measured = [
            {
                "provider": "openrouter",
                "account": "default",
                "model": "*",
                "kind": "monthly",
                "quotaId": "example_monthly",
                "usedRatio": 0.5,
                "resetEpoch": at(20),
                "durationSeconds": 2592000,
                "source": "t3",
                "observedAtEpoch": NOW,
            }
        ]
        _samples, ranked = self.rank(inferred, routes, measured)
        snapshot = self.snapshot(inferred, routes, ranked, measured)
        records = snapshot["quota"]["accounts"]["openrouter"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["quota_id"], "example_monthly")
        self.assertEqual(records[0]["evidence"], "provider_reported")
        self.assertNotIn("inference", records[0])
        windows = self.windows(inferred, routes, measured)
        self.assertEqual(
            [window.quota_id for window in windows["openrouter"]],
            ["example_monthly"],
        )


class ProviderKeyTests(PublicationTestCase):
    """A no-failure capacity never occupies the provider key."""

    def test_the_provider_key_stays_empty_for_a_model_scoped_refusal(self):
        routes = [("google", QUIET_ROUTE), ("google", REFUSED_ROUTE)]
        inferred = self.infer(
            [
                record(at(8), model=REFUSED_ROUTE, usage=200000),
                record(at(10, 30), model=REFUSED_ROUTE, limit=True),
                record(at(11), model=QUIET_ROUTE, usage=1000),
                record(at(13, 2), model=REFUSED_ROUTE, usage=0),
            ],
            routes,
        )
        # The quiet route carries its no-failure capacity.
        self.assertEqual(
            inferred.capacities[("google", QUIET_ROUTE)]["state"], "no_failure"
        )
        windows = self.windows(inferred, routes)
        self.assertNotIn("google", windows)
        self.assertEqual(
            [window.quota_id for window in windows[f"google/{REFUSED_ROUTE}"]],
            ["inferred:5h"],
        )
        self.assertNotIn("inferred:no-limit-seen", [w.quota_id for w in windows[f"google/{REFUSED_ROUTE}"]])


if __name__ == "__main__":
    unittest.main()
