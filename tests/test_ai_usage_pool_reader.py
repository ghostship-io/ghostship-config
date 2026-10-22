"""The free inference pool's ledger: the usage events the reader produces.

Every row in the fixtures under `tests/fixtures/ai-usage` is synthetic. No
live row is copied, and the tests never read a path outside the repository
or the temporary directory they build themselves.
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

REPOSITORY = Path(__file__).resolve().parents[1]
COLLECTOR = REPOSITORY / "modules/self-hosted/ai-usage/collector"
FIXTURES = REPOSITORY / "tests/fixtures/ai-usage"
if str(COLLECTOR) not in sys.path:
    sys.path.insert(0, str(COLLECTOR))


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, COLLECTOR / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pool_reader = load("ai_usage_pool_reader", "pool_reader.py")

# The instant the fixtures are read at. The fixture files name it as well.
NOW = 1800000000


def build_ledger(path, *, wal=False):
    """Build a pool ledger from the committed fixtures."""
    schema = (FIXTURES / "pool_schema.sql").read_text(encoding="utf-8")
    jobs = json.loads((FIXTURES / "pool_jobs.json").read_text(encoding="utf-8"))
    reservations = json.loads((FIXTURES / "pool_reservations.json").read_text(encoding="utf-8"))
    connection = sqlite3.connect(path)
    try:
        if wal:
            connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(schema)
        connection.executemany(
            "INSERT INTO jobs (id, kind, identity, status, progress, result, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    job["id"],
                    "inference.task",
                    "agent",
                    job["status"],
                    "{}",
                    json.dumps(job["result"]),
                    job["created_at"],
                    job["updated_at"],
                )
                for job in jobs["jobs"]
            ],
        )
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
                for row in reservations["reservations"]
            ],
        )
        connection.commit()
    finally:
        connection.close()


class PoolReaderTestCase(unittest.TestCase):
    """The base of the reading tests."""

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="pool-reader-")
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.path = os.path.join(self.directory, "jobs.sqlite")
        build_ledger(self.path)

    def read(self, path=None, **keywords):
        """Read the fixture ledger."""
        return pool_reader.read_events(path or self.path, NOW, **keywords)

    def event(self, reading, at):
        """The one event of the reading at an instant."""
        found = [event for event in reading["events"] if event["at"] == at]
        self.assertEqual(len(found), 1, f"expected one event at {at}, got {found}")
        return found[0]


class OutcomeMappingTests(PoolReaderTestCase):
    """The category of an attempt decides the outcome of its event."""

    def test_success_attempt_is_a_success_event_with_its_settled_usage(self):
        reading = self.read()
        event = self.event(reading, 1799996400)
        self.assertEqual(event["provider"], "acme-free")
        self.assertEqual(event["model"], "small-model")
        self.assertEqual(event["outcome"], "success")
        self.assertEqual(event["usage"], 150)
        self.assertIsNone(event["window_hint"])

    def test_quota_exhausted_is_a_limit_without_a_window(self):
        reading = self.read()
        event = self.event(reading, 1799996200)
        self.assertEqual(event["outcome"], "limit")
        self.assertIsNone(event["window_hint"])

    def test_free_daily_exhausted_is_a_limit_of_the_day(self):
        reading = self.read()
        event = self.event(reading, 1799996000)
        self.assertEqual(event["outcome"], "limit")
        self.assertEqual(event["window_hint"], "1d")

    def test_rate_limited_is_not_a_limit(self):
        event = self.event(self.read(), 1799995800)
        self.assertEqual(event["outcome"], "other")
        self.assertIsNone(event["window_hint"])

    def test_upstream_error_is_not_a_limit(self):
        event = self.event(self.read(), 1799995600)
        self.assertEqual(event["outcome"], "other")
        self.assertIsNone(event["window_hint"])

    def test_model_unavailable_is_not_a_limit(self):
        event = self.event(self.read(), 1799995400)
        self.assertEqual(event["outcome"], "other")
        self.assertIsNone(event["window_hint"])

    def test_context_limit_is_not_a_limit(self):
        event = self.event(self.read(), 1799995200)
        self.assertEqual(event["outcome"], "other")
        self.assertIsNone(event["window_hint"])

    def test_credentials_or_access_is_not_a_limit(self):
        event = self.event(self.read(), 1799995000)
        self.assertEqual(event["outcome"], "other")
        self.assertIsNone(event["window_hint"])

    def test_unexpected_tool_is_not_a_limit(self):
        event = self.event(self.read(), 1799994800)
        self.assertEqual(event["outcome"], "other")
        self.assertIsNone(event["window_hint"])


if __name__ == "__main__":
    unittest.main()
