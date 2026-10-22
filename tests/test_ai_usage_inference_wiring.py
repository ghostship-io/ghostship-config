"""The wiring between the request records and the capacity they imply.

The providers that report no usage, and every free route, showed "Limits
unknown" on the Providers page. The owner rule (`ghostship-agent`'s
`config/agents/routing-policy.md`, section "Usage measurement") reads their
capacity from the limit failures instead.

These tests pin the wiring: the two records are read, their events are put
on the routes of the collector's inventory, and the inference becomes the
window the ranking reads. A route that reports its usage keeps its
reported window, and a record that cannot be read never fails the run.

Every record in this file is synthetic and lives in a temporary directory.
No live database is opened, and the only repository file that is read is
the committed fixture of the pool ledger.
"""
import importlib.util
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
FIXTURES = ROOT / "tests" / "fixtures" / "ai-usage"
if str(COLLECTOR) not in sys.path:
    sys.path.insert(0, str(COLLECTOR))

import catalog as catalog_module  # noqa: E402
import main  # noqa: E402
from metrics import SourceResult  # noqa: E402

_MODULES: dict[str, object] = {}


def load(name, file):
    """A collector module, loaded on demand.

    The module is loaded inside the test, so a checkout without it fails
    every test with the same clear error instead of hiding the whole file
    behind one import failure.
    """
    if name not in _MODULES:
        spec = importlib.util.spec_from_file_location(name, COLLECTOR / file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        _MODULES[name] = module
    return _MODULES[name]


def usage():
    """The wiring between the records and the inference."""
    return load("ai_usage_wiring_usage", "usage_inference.py")

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


def record(when, provider="openrouter", model="example-model", usage=None, limit=False):
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


def build_ledger(directory, reservations):
    """Build a pool ledger with the given reservations."""
    schema = (FIXTURES / "pool_schema.sql").read_text(encoding="utf-8")
    path = Path(directory) / "jobs.sqlite"
    connection = sqlite3.connect(path)
    try:
        connection.executescript(schema)
        connection.executemany(
            "INSERT INTO inference_reservations (id, job, provider, model, at, input, output, usd, neurons) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)",
            [
                (
                    row["id"],
                    row["job"],
                    row["provider"],
                    row["model"],
                    row["at"],
                    row["input"],
                    row["output"],
                )
                for row in reservations
            ],
        )
        connection.commit()
    finally:
        connection.close()
    return str(path)


class WiringTestCase(unittest.TestCase):
    """The base of the wiring tests."""

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="usage-inference-")
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.cache = os.path.join(self.directory, "events.json")

    def infer(self, records=(), routes=(), ledger=None, now=NOW):
        """Read the records, put them on the routes, and infer."""
        database = build_database(self.directory, list(records))
        return usage().read_and_infer(
            now,
            opencode_db=database,
            events_cache=self.cache,
            pool_ledger=ledger,
            routes=set(routes),
        )

    def windows(self, inferred, routes=(), measured=(), now=NOW):
        """The windows the ranking reads, with the inferred ones in them."""
        context = {
            "offered_models": list(routes),
            "inferred_capacity": inferred.capacities,
        }
        inputs = main.ranking_inputs([], catalog_module.Catalog({}), context, list(measured), now=now)
        return inputs["windows"]

    def rank(self, inferred, routes=(), measured=(), now=NOW):
        """The ranking of the routes, and the samples it publishes."""
        context = {
            "offered_models": list(routes),
            "inferred_capacity": inferred.capacities,
        }
        results = [
            SourceResult(source="measured", status="ok", reason="ok", observed_at=now, windows=list(measured))
        ]
        return main.ranking_samples(
            results, catalog_module.Catalog({}), context, now, t3_home=self.directory
        )

    def sample(self, samples, name, provider=None, model=None):
        """The one sample of a name, for a route."""
        found = [
            (labels, value)
            for metric, labels, value in samples
            if metric == name
            and (provider is None or labels.get("provider") == provider)
            and (model is None or labels.get("model") == model)
        ]
        self.assertEqual(len(found), 1, f"expected one {name} sample, got {found}")
        return found[0]


class NoFailureTests(WiringTestCase):
    """A route that was never refused has all of its allowance."""

    def setUp(self):
        super().setUp()
        self.routes = [("openrouter", "example-model")]
        self.records = [
            record(at(13, 0), usage=1000),
            record(at(13, 30), usage=2000),
            record(at(14, 0), usage=3000),
        ]
        self.inferred = self.infer(self.records, self.routes)

    def test_the_route_is_matched_and_the_state_is_no_failure(self):
        capacity = self.inferred.capacities[("openrouter", "example-model")]
        self.assertEqual(capacity["state"], "no_failure")
        self.assertEqual(capacity["basis"], "inferred")
        self.assertEqual(capacity["left"], 1.0)
        self.assertIsNone(capacity["window"])
        self.assertIsNone(capacity["reset_at"])
        self.assertEqual(self.inferred.unmatched["opencode_events"], 0)

    def test_the_window_reads_like_the_published_unlimited_window(self):
        windows = self.windows(self.inferred, self.routes)
        # The scope of a limit with no other model in its span is the
        # account, so the window is filed under the provider.
        window = windows["openrouter"][0]
        self.assertEqual(window.kind, "inferred")
        self.assertEqual(window.quota_id, "inferred:no-limit-seen")
        self.assertEqual(window.used_ratio, 0.0)
        self.assertIsNone(window.reset_epoch)
        self.assertIsNone(window.duration_seconds)
        self.assertEqual(window.basis, "inferred: no limit failure in the records")

    def test_the_route_has_its_full_allowance_and_no_pace(self):
        samples, ranked = self.rank(self.inferred, self.routes)
        entry = ranked[0]
        self.assertEqual(entry.remaining, 1.0)
        self.assertIsNone(entry.pace)
        self.assertEqual(entry.capacity_basis, "inferred")
        self.assertEqual(entry.capacity_inference["state"], "no_failure")

    def test_the_headroom_is_never_unknown(self):
        samples, _ranked = self.rank(self.inferred, self.routes)
        unknown = [
            labels
            for metric, labels, _value in samples
            if metric == "ghostship_ai_model_quota_unknown"
        ]
        self.assertEqual(unknown, [])
        remaining = self.sample(samples, "ghostship_ai_model_capacity_remaining")
        self.assertEqual(remaining[1], 1.0)

    def test_the_basis_is_published_with_the_state(self):
        samples, _ranked = self.rank(self.inferred, self.routes)
        labels, value = self.sample(samples, "ghostship_ai_model_capacity_basis")
        self.assertEqual(value, 1.0)
        self.assertEqual(labels["basis"], "inferred")
        self.assertEqual(labels["state"], "no_failure")
        self.assertEqual(labels["scope"], "unknown")
        self.assertEqual(labels["unit"], "tokens")

    def test_the_snapshot_holds_no_pace(self):
        samples, ranked = self.rank(self.inferred, self.routes)
        snapshot = main.build_snapshot(
            [], ranked, {}, NOW, catalog=catalog_module.Catalog({})
        )
        row = snapshot["candidates"][0]
        self.assertEqual(row["capacity"]["remaining_ratio"], 1.0)
        self.assertIsNone(row["capacity"]["paced_availability"])
        self.assertIsNone(row["capacity"]["pace_delta"])
        self.assertEqual(row["capacity"]["capacity_basis"], "inferred")


class ModelIdRuleTests(WiringTestCase):
    """The rule that puts an event on the route of the inventory."""

    def test_a_model_id_that_differs_only_in_its_case_is_the_same_route(self):
        routes = [("ovh", "Meta-Llama-3_3-70B-Instruct")]
        records = [record(at(13, 0), provider="ovh", model="meta-llama-3_3-70b-instruct", usage=1000)]
        inferred = self.infer(records, routes)
        self.assertEqual(inferred.unmatched["opencode_events"], 0)
        self.assertEqual(
            sorted(inferred.capacities), [("ovh", "Meta-Llama-3_3-70B-Instruct")]
        )

    def test_a_model_id_that_is_not_in_the_inventory_is_unmatched(self):
        routes = [("openrouter", "example-model")]
        records = [record(at(13, 0), model="other-model", usage=1000)]
        inferred = self.infer(records, routes)
        self.assertEqual(inferred.unmatched["opencode_events"], 1)
        self.assertEqual(inferred.capacities, {})

    def test_a_provider_that_is_not_in_the_inventory_is_unmatched(self):
        routes = [("openrouter", "example-model")]
        # The reader knows the provider, so the event is emitted, and the
        # inventory does not know the route.
        records = [record(at(13, 0), provider="nvidia", model="example-model", usage=1000)]
        inferred = self.infer(records, routes)
        self.assertEqual(inferred.unmatched["opencode_events"], 1)
        self.assertEqual(inferred.capacities, {})

    def test_two_routes_that_differ_only_in_their_case_are_not_guessed(self):
        routes = [("openrouter", "Example-Model"), ("openrouter", "example-model")]
        records = [record(at(13, 0), model="EXAMPLE-MODEL", usage=1000)]
        inferred = self.infer(records, routes)
        self.assertEqual(inferred.unmatched["opencode_events"], 1)
        self.assertEqual(inferred.capacities, {})


class VendorPrefixedModelTests(WiringTestCase):
    """A model id that carries a vendor prefix finds its route.

    OpenCode records a request of Requesty as "vendor/model", while the
    inventory of the collector knows the route as the model alone. The
    event is placed on the route when the model alone is a route of the
    same provider, and it stays unmatched when it is not: the prefix is
    never taken from another provider, never added, and only ever one
    segment of it is stripped.
    """

    def mapped(self, provider, model, routes):
        """The events of one request, put on the routes."""
        events = [{"provider": provider, "model": model, "at": 1.0, "outcome": "limit"}]
        return usage().map_events(events, set(routes))

    def test_a_vendor_prefixed_model_id_is_matched_to_its_route(self):
        mapped, unmatched = self.mapped(
            "requesty", "examplevendor/example-model-it", {("requesty", "example-model-it")}
        )
        self.assertEqual(unmatched, 0)
        self.assertEqual(
            [(event["provider"], event["model"]) for event in mapped],
            [("requesty", "example-model-it")],
        )

    def test_a_vendor_prefixed_model_id_is_matched_by_its_case(self):
        mapped, unmatched = self.mapped(
            "requesty", "examplevendor/Example-Model-It", {("requesty", "example-model-it")}
        )
        self.assertEqual(unmatched, 0)
        self.assertEqual(
            [(event["provider"], event["model"]) for event in mapped],
            [("requesty", "example-model-it")],
        )

    def test_an_exact_route_wins_over_the_stripped_one(self):
        mapped, unmatched = self.mapped(
            "openrouter",
            "examplevendor/example-x",
            {("openrouter", "examplevendor/example-x"), ("openrouter", "example-x")},
        )
        self.assertEqual(unmatched, 0)
        self.assertEqual(
            [(event["provider"], event["model"]) for event in mapped],
            [("openrouter", "examplevendor/example-x")],
        )

    def test_the_limit_failures_of_a_prefixed_model_reach_its_route(self):
        routes = [("requesty", "example-model-it")]
        model = "examplevendor/example-model-it"
        records = [
            record(at(8), provider="requesty", model=model, usage=200000),
            record(at(10, 30), provider="requesty", model=model, limit=True),
            record(at(13, 2), provider="requesty", model=model, usage=0),
            record(at(13, 5), provider="requesty", model=model, usage=150000),
        ]
        inferred = self.infer(records, routes)
        self.assertEqual(inferred.unmatched["opencode_events"], 0)
        capacity = inferred.capacities[("requesty", "example-model-it")]
        self.assertNotEqual(capacity["state"], "no_failure")

    def test_a_prefix_is_never_taken_from_another_provider(self):
        mapped, unmatched = self.mapped(
            "requesty", "examplevendor/example-model-it", {("otherprov", "example-model-it")}
        )
        self.assertEqual(unmatched, 1)
        self.assertEqual(mapped, [])

    def test_only_the_first_segment_of_the_prefix_is_stripped(self):
        mapped, unmatched = self.mapped("requesty", "a/b/example-x", {("requesty", "example-x")})
        self.assertEqual(unmatched, 1)
        self.assertEqual(mapped, [])

    def test_a_prefix_is_never_added_to_a_model_id(self):
        mapped, unmatched = self.mapped(
            "requesty", "example-model-it", {("requesty", "examplevendor/example-model-it")}
        )
        self.assertEqual(unmatched, 1)
        self.assertEqual(mapped, [])


class PolicyExampleTests(WiringTestCase):
    """The worked example of the owner rule, through the wiring."""

    def setUp(self):
        super().setUp()
        self.routes = [("openrouter", "example-model")]
        self.records = [
            record(at(8), usage=200000),
            record(at(9), usage=400000),
            record(at(10, 30), limit=True),
            record(at(13, 2), usage=0),
            record(at(13, 5), usage=150000),
        ]
        self.inferred = self.infer(self.records, self.routes)

    def test_the_window_and_the_budget_are_the_worked_ones(self):
        capacity = self.inferred.capacities[("openrouter", "example-model")]
        self.assertEqual(capacity["state"], "in_window")
        self.assertEqual(capacity["window"], "5h")
        self.assertEqual(capacity["budget"], 600000.0)
        self.assertEqual(capacity["unit"], "tokens")
        self.assertEqual(capacity["episodes"], 1)
        self.assertAlmostEqual(capacity["left"], 0.75)

    def test_the_window_carries_the_share_and_the_reset(self):
        windows = self.windows(self.inferred, self.routes)
        window = windows["openrouter"][0]
        self.assertEqual(window.quota_id, "inferred:5h")
        self.assertAlmostEqual(window.used_ratio, 0.25)
        self.assertEqual(window.reset_epoch, at(18, 5))
        self.assertEqual(window.duration_seconds, 18000)
        self.assertEqual(window.basis, "inferred from 1 limit episodes")

    def test_the_route_has_three_quarters_left_and_is_on_pace(self):
        samples, ranked = self.rank(self.inferred, self.routes)
        entry = ranked[0]
        self.assertAlmostEqual(entry.remaining, 0.75)
        self.assertAlmostEqual(entry.pace, 0.0)
        self.assertEqual(entry.capacity_basis, "inferred")
        self.assertEqual(entry.capacity_inference["window"], "5h")

    def test_the_budget_and_the_episodes_are_published(self):
        samples, _ranked = self.rank(self.inferred, self.routes)
        budget = self.sample(samples, "ghostship_ai_model_capacity_budget")
        self.assertEqual(budget[0]["unit"], "tokens")
        self.assertEqual(budget[1], 600000.0)
        episodes = self.sample(samples, "ghostship_ai_model_capacity_episodes")
        self.assertEqual(episodes[1], 1.0)

    def test_the_snapshot_carries_the_inference(self):
        samples, ranked = self.rank(self.inferred, self.routes)
        snapshot = main.build_snapshot(
            [], ranked, {}, NOW, catalog=catalog_module.Catalog({})
        )
        row = snapshot["candidates"][0]
        self.assertEqual(row["capacity"]["capacity_basis"], "inferred")
        self.assertAlmostEqual(row["capacity"]["remaining_ratio"], 0.75)
        self.assertAlmostEqual(row["capacity"]["paced_availability"], 0.0)
        inference = row["capacity"]["inference"]
        self.assertEqual(inference["window"], "5h")
        self.assertEqual(inference["budget"], 600000.0)
        self.assertEqual(inference["unit"], "tokens")
        self.assertEqual(inference["episodes"], 1)
        self.assertEqual(inference["state"], "in_window")


class ExhaustedTests(WiringTestCase):
    """A route whose last request was refused has nothing left."""

    def setUp(self):
        super().setUp()
        self.routes = [("openrouter", "example-model")]
        self.records = [
            record(at(8), usage=200000),
            record(at(10, 30), limit=True),
            record(at(13, 2), usage=0),
            record(at(13, 5), usage=150000),
            record(at(14, 0), limit=True),
        ]
        self.inferred = self.infer(self.records, self.routes)

    def test_the_route_is_spent(self):
        capacity = self.inferred.capacities[("openrouter", "example-model")]
        self.assertEqual(capacity["state"], "exhausted")
        self.assertEqual(capacity["left"], 0.0)
        self.assertEqual(capacity["reset_at"], at(18, 5))

    def test_the_window_states_the_spent_allowance(self):
        windows = self.windows(self.inferred, self.routes)
        window = windows["openrouter"][0]
        self.assertEqual(window.quota_id, "inferred:exhausted")
        self.assertEqual(window.used_ratio, 1.0)
        self.assertEqual(window.reset_epoch, at(18, 5))

    def test_the_route_has_no_headroom_left(self):
        samples, ranked = self.rank(self.inferred, self.routes)
        entry = ranked[0]
        self.assertEqual(entry.remaining, 0.0)
        self.assertFalse(entry.available)
        self.assertEqual(entry.capacity_basis, "inferred")
        self.assertEqual(entry.capacity_inference["state"], "exhausted")


class ReportedWindowTests(WiringTestCase):
    """A route that reports its usage keeps its reported window."""

    def setUp(self):
        super().setUp()
        self.routes = [("opencode-go", "example-model")]
        self.records = [
            record(at(8), provider="opencode-go", usage=200000),
            record(at(10, 30), provider="opencode-go", limit=True),
            record(at(13, 2), provider="opencode-go", usage=0),
            record(at(13, 5), provider="opencode-go", usage=150000),
        ]
        self.measured = [
            {
                "provider": "opencode-go",
                "account": "default",
                "model": "*",
                "kind": "monthly",
                "quotaId": "go_monthly",
                "usedRatio": 0.5,
                "resetEpoch": at(20),
                "durationSeconds": 2592000,
                "source": "t3",
                "observedAtEpoch": NOW,
            }
        ]
        self.inferred = self.infer(self.records, self.routes)

    def test_the_reported_window_is_kept(self):
        windows = self.windows(self.inferred, self.routes, self.measured)
        self.assertEqual(len(windows["opencode-go"]), 1)
        self.assertEqual(windows["opencode-go"][0].quota_id, "go_monthly")
        self.assertNotIn("opencode-go/example-model", windows)

    def test_the_basis_of_the_route_is_the_reported_reading(self):
        samples, ranked = self.rank(self.inferred, self.routes, self.measured)
        entry = ranked[0]
        self.assertEqual(entry.remaining, 0.5)
        self.assertEqual(entry.capacity_basis, "reported")
        self.assertEqual(entry.capacity_inference, {})
        labels, _value = self.sample(samples, "ghostship_ai_model_capacity_basis")
        self.assertEqual(labels["basis"], "reported")
        self.assertEqual(labels["state"], "")


class AccountScopeTests(WiringTestCase):
    """A limit that belongs to the account is filed under the provider."""

    def setUp(self):
        super().setUp()
        self.routes = [("openrouter", "example-model"), ("openrouter", "other-model")]
        self.records = [
            record(at(8), model="example-model", usage=200000),
            record(at(9), model="other-model", usage=100000),
            record(at(10, 30), model="example-model", limit=True),
            record(at(10, 35), model="other-model", limit=True),
            record(at(13, 2), model="example-model", usage=0),
        ]
        self.inferred = self.infer(self.records, self.routes)

    def test_the_scope_of_the_limit_is_the_account(self):
        capacity = self.inferred.capacities[("openrouter", "example-model")]
        self.assertEqual(capacity["scope"], "account")

    def test_the_window_is_filed_under_the_provider(self):
        windows = self.windows(self.inferred, self.routes)
        self.assertIn("openrouter", windows)
        self.assertNotIn("openrouter/example-model", windows)
        window = windows["openrouter"][0]
        self.assertEqual(window.kind, "inferred")
        self.assertEqual(window.quota_id, "inferred:5h")

    def test_the_account_window_reaches_every_model_of_the_account(self):
        samples, ranked = self.rank(self.inferred, self.routes)
        for entry in ranked:
            self.assertEqual(entry.capacity_basis, "inferred")
            self.assertIsNotNone(entry.remaining)


class UnreadableTests(WiringTestCase):
    """A record that cannot be read never fails the run."""

    def test_both_records_unreadable_leave_the_routes_unknown(self):
        inferred = usage().read_and_infer(
            NOW,
            opencode_db=os.path.join(self.directory, "absent.db"),
            events_cache=self.cache,
            pool_ledger=os.path.join(self.directory, "absent.sqlite"),
            routes={("openrouter", "example-model")},
        )
        self.assertEqual(inferred.capacities, {})
        statuses = {result.source: (result.status, result.reason) for result in inferred.results}
        self.assertEqual(statuses["opencode_events"], ("unreadable", "database_missing"))
        self.assertEqual(statuses["pool_events"], ("unreadable", "ledger_missing"))

        samples, ranked = self.rank(inferred, [("openrouter", "example-model")])
        entry = ranked[0]
        self.assertIsNone(entry.remaining)
        self.assertEqual(entry.capacity_basis, "unknown")
        unknown = self.sample(samples, "ghostship_ai_model_quota_unknown")
        self.assertEqual(unknown[0]["reason"], "no_window")

    def test_the_source_status_is_published_with_the_readers_reason(self):
        inferred = usage().read_and_infer(
            NOW,
            opencode_db=os.path.join(self.directory, "absent.db"),
            events_cache=self.cache,
            pool_ledger=os.path.join(self.directory, "absent.sqlite"),
            routes=set(),
        )
        text = main.render(inferred.results, [], NOW, 1.0, {})
        self.assertIn(
            'ghostship_ai_source_status{provider="opencode_events",'
            'reason="database_missing",source="opencode_events",status="unreadable"} 1',
            text,
        )
        self.assertIn(
            'ghostship_ai_source_status{provider="pool_events",'
            'reason="ledger_missing",source="pool_events",status="unreadable"} 1',
            text,
        )

    def test_the_collector_exits_zero_without_the_records(self):
        code = main.main(
            [
                "--stdout",
                "--output",
                os.path.join(self.directory, "ai-usage.prom"),
                "--snapshot",
                os.path.join(self.directory, "routing.json"),
                "--state",
                os.path.join(self.directory, "state.json"),
                "--events-cache",
                os.path.join(self.directory, "events.json"),
                "--facts",
                "/dev/null",
                "--aa-cache",
                os.path.join(self.directory, "aa.json"),
                "--aa-3d-cache",
                os.path.join(self.directory, "aa3d.json"),
                "--now",
                str(NOW),
            ]
        )
        self.assertEqual(code, 0)


class UnmatchedTests(WiringTestCase):
    """An event of a route the collector does not know is counted."""

    def setUp(self):
        super().setUp()
        self.routes = [("openrouter", "example-model")]
        self.records = [
            record(at(13, 0), model="example-model", usage=1000),
            record(at(13, 30), model="other-model", usage=1000),
        ]

    def test_the_event_of_an_unknown_route_is_counted(self):
        inferred = self.infer(self.records, self.routes)
        self.assertEqual(inferred.unmatched["opencode_events"], 1)
        self.assertEqual(sorted(inferred.capacities), [("openrouter", "example-model")])

    def test_the_unknown_route_gets_no_window(self):
        inferred = self.infer(self.records, self.routes)
        windows = self.windows(inferred, self.routes)
        self.assertNotIn("openrouter/other-model", windows)

    def test_the_count_is_published(self):
        inferred = self.infer(self.records, self.routes)
        text = main.render(inferred.results, [], NOW, 1.0, {})
        self.assertIn(
            'ghostship_ai_inference_unmatched_events{source="opencode_events"} 1', text
        )


class PoolRecordTests(WiringTestCase):
    """The ledger of the free pool is read the same way."""

    def test_a_pool_route_is_measured_from_its_ledger(self):
        ledger = build_ledger(
            self.directory,
            [
                {
                    "id": "reservation-1",
                    "job": None,
                    "provider": "acme-free",
                    "model": "small-model",
                    "at": int(at(13, 0)),
                    "input": 1000,
                    "output": 200,
                },
                {
                    "id": "reservation-2",
                    "job": None,
                    "provider": "acme-free",
                    "model": "small-model",
                    "at": int(at(13, 30)),
                    "input": 1000,
                    "output": 200,
                },
            ],
        )
        inferred = self.infer(
            (), [("acme-free", "small-model")], ledger=ledger
        )
        self.assertEqual(inferred.unmatched["pool_events"], 0)
        capacity = inferred.capacities[("acme-free", "small-model")]
        self.assertEqual(capacity["state"], "no_failure")
        self.assertEqual(capacity["left"], 1.0)


class RenderedFileTests(WiringTestCase):
    """The rendered file holds one series per name and label set."""

    def test_the_file_has_no_duplicate_series(self):
        records = [record(at(13, 0), usage=1000), record(at(13, 30), usage=1000)]
        routes = [("openrouter", "example-model")]
        inferred = self.infer(records, routes)
        samples, _ranked = self.rank(inferred, routes)
        text = main.render(inferred.results, samples, NOW, 1.0, {})
        self.assertIn("ghostship_ai_collection_duplicate_series 0", text)


if __name__ == "__main__":
    unittest.main()
