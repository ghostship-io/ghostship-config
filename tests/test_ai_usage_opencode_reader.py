"""The OpenCode request reader: the classification, the mapping and the read.

The reader turns OpenCode's own request records into the events the AI
usage collector infers a route's window and budget from. These tests read
only the committed fixture and the directories they build themselves.
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
FIXTURE = ROOT / "tests" / "fixtures" / "ai-usage" / "opencode-messages.json"

_MODULE = None


def reader():
    """The reader module, loaded on demand.

    The module is loaded inside the test, so a checkout without it fails
    every test with the same clear error instead of hiding the whole file
    behind one import failure.
    """
    global _MODULE
    if _MODULE is None:
        spec = importlib.util.spec_from_file_location(
            "ai_usage_opencode_reader", COLLECTOR / "opencode_reader.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["ai_usage_opencode_reader"] = module
        spec.loader.exec_module(module)
        _MODULE = module
    return _MODULE


def request(error=None, finish=None, tokens=None, provider="opencode-go", model="example-model", **extra):
    """One request record, shaped the way OpenCode writes it."""
    data = {"model": {"providerID": provider, "id": model}}
    if finish is not None:
        data["finish"] = finish
    if tokens is not None:
        data["tokens"] = tokens
    if error is not None:
        data["error"] = error
    data.update(extra)
    return data


def failure(kind, message):
    """A failed request, with the provider's own words in it."""
    return {"type": kind, "data": {"message": message}}


def fixture():
    """The committed fixture: the records and the instant they are read at."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def build_database(directory, rows):
    """Build the fixture database in WAL mode, and keep it open.

    A live writer holds the write ahead log and the shared memory file, the
    way OpenCode holds them while it runs.
    """
    path = Path(directory) / "opencode.db"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode = wal")
    connection.execute(
        "CREATE TABLE session_message ("
        "id TEXT PRIMARY KEY, session_id TEXT, type TEXT, "
        "time_created INTEGER, data TEXT)"
    )
    connection.execute(
        "CREATE INDEX session_message_time_created_idx ON session_message (time_created)"
    )
    for row in rows:
        connection.execute(
            "INSERT INTO session_message (id, session_id, type, time_created, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                row["id"],
                row["session_id"],
                row["type"],
                row["time_created"],
                json.dumps(row["data"]),
            ),
        )
    connection.commit()
    return path, connection


def event_at(result, epoch_ms):
    """The one event of a reading that happened at an instant."""
    for event in result["events"]:
        if event["at"] == epoch_ms / 1000.0:
            return event
    return None


def capture_statements(module, test):
    """The statements the reader runs, with the bounds they carry.

    The trace callback of a connection reports every statement it runs with
    its parameters inlined, so the bound the reader asked for is visible.
    """
    statements = []
    original = module.open_database

    def wrapper(target):
        connection = original(target)
        connection.set_trace_callback(statements.append)
        return connection

    module.open_database = wrapper
    test.addCleanup(setattr, module, "open_database", original)
    return statements


def synthetic_rows(count, start=1799900000000, step=1000, provider="opencode-go", prefix="synthetic"):
    """A batch of invented request records."""
    rows = []
    for index in range(count):
        moment = start + index * step
        rows.append(
            {
                "id": f"msg_{prefix}_{index}",
                "session_id": "ses_synthetic",
                "type": "assistant",
                "time_created": moment,
                "data": {
                    "model": {"providerID": provider, "id": "example/minimax-m3.1-flash"},
                    "time": {"created": moment},
                    "tokens": {"input": 10, "output": 5, "reasoning": 0},
                    "finish": "stop",
                },
            }
        )
    return rows


class ClassificationTests(unittest.TestCase):
    """Every outcome the reader can pick, one assertion each."""

    def classify(self, data):
        return reader().classify(data)

    def test_a_stop_is_a_success(self):
        self.assertEqual(self.classify(request(finish="stop")), ("success", None))

    def test_a_tool_call_stop_is_a_success(self):
        self.assertEqual(self.classify(request(finish="tool-calls")), ("success", None))

    def test_a_length_stop_is_a_success(self):
        self.assertEqual(self.classify(request(finish="length")), ("success", None))

    def test_a_content_filter_stop_is_a_success(self):
        self.assertEqual(self.classify(request(finish="content-filter")), ("success", None))

    def test_a_request_without_a_finish_is_other(self):
        self.assertEqual(self.classify(request()), ("other", None))

    def test_a_request_with_an_unknown_finish_is_other(self):
        self.assertEqual(self.classify(request(finish="unknown")), ("other", None))

    def test_the_session_usage_limit_names_a_five_hour_window(self):
        error = failure("provider.quota", "you (example-user) have reached your session usage limit")
        self.assertEqual(self.classify(request(error=error)), ("limit", "5h"))

    def test_the_weekly_usage_limit_names_a_seven_day_window(self):
        error = failure("provider.quota", "you (example-user) have reached your weekly usage limit")
        self.assertEqual(self.classify(request(error=error)), ("limit", "7d"))

    def test_the_go_usage_limit_is_a_limit_without_a_window(self):
        error = failure("provider.quota", "Go usage limit exceeded")
        self.assertEqual(self.classify(request(error=error)), ("limit", None))

    def test_the_quota_type_rate_limit_is_a_limit_without_a_window(self):
        error = failure("provider.quota", "Rate limit exceeded. Please try again later.")
        self.assertEqual(self.classify(request(error=error)), ("limit", None))

    def test_the_current_quota_refusal_is_a_limit_without_a_window(self):
        error = failure("provider.quota", "You exceeded your current quota, please check your plan")
        self.assertEqual(self.classify(request(error=error)), ("limit", None))

    def test_the_daily_limit_names_a_one_day_window(self):
        error = failure(
            "provider.rate-limit",
            "Rate limit exceeded: limit_rpd/example-model. Daily limit reached for example-model",
        )
        self.assertEqual(self.classify(request(error=error)), ("limit", "1d"))

    def test_the_free_models_daily_limit_names_a_one_day_window(self):
        error = failure("provider.rate-limit", "Rate limit exceeded: free-models-per-day")
        self.assertEqual(self.classify(request(error=error)), ("limit", "1d"))

    def test_a_payment_required_refusal_is_a_limit_without_a_window(self):
        error = failure("provider.quota", "This request requires a positive account balance")
        self.assertEqual(self.classify(request(error=error)), ("limit", None))

    def test_a_credit_card_refusal_is_a_limit_without_a_window(self):
        error = failure("provider.quota", "AI Gateway requires a valid credit card on file")
        self.assertEqual(self.classify(request(error=error)), ("limit", None))

    def test_too_many_concurrent_requests_is_not_a_limit(self):
        error = failure("provider.rate-limit", "Too Many Requests: too many concurrent requests")
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_the_organization_concurrency_refusal_is_not_a_limit(self):
        error = failure(
            "provider.rate-limit", "Your organization reached its limit of concurrent requests"
        )
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_the_worker_concurrency_refusal_is_not_a_limit(self):
        error = failure("provider.rate-limit", "Worker local total request limit reached (8/8)")
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_the_free_models_per_minute_refusal_is_not_a_limit(self):
        error = failure("provider.rate-limit", "Rate limit exceeded: free-models-per-min.")
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_a_transient_rate_limit_is_not_a_limit(self):
        error = failure("provider.rate-limit", "Rate limit exceeded: abc123def.")
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_an_upstream_refusal_is_not_a_limit(self):
        error = failure(
            "provider.rate-limit", "example-model is temporarily rate-limited upstream, retry later"
        )
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_a_request_that_is_too_large_is_not_a_limit(self):
        error = failure(
            "provider.error",
            "Request too large for model example-model on tokens per minute (TPM)",
        )
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_an_expired_key_is_not_a_limit(self):
        error = failure("provider.auth-error", "This API key has expired")
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_an_invalid_token_is_not_a_limit(self):
        error = failure("provider.auth-error", "Your authentication token is invalid")
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_an_aborted_run_is_not_a_limit(self):
        error = failure("provider.aborted", "Step interrupted")
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_a_response_timeout_is_not_a_limit(self):
        error = failure("provider.error", "Timed out waiting for response headers")
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_a_provider_error_without_budget_words_is_not_a_limit(self):
        error = failure("provider.error", "Provider returned error")
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_the_message_may_sit_at_the_top_of_the_error(self):
        error = {"type": "provider.quota", "message": "Go usage limit exceeded"}
        self.assertEqual(self.classify(request(error=error)), ("limit", None))

    def test_the_refusal_is_read_case_insensitively(self):
        error = failure("provider.quota", "GO USAGE LIMIT EXCEEDED")
        self.assertEqual(self.classify(request(error=error)), ("limit", None))

    def test_a_limit_request_still_reports_its_usage(self):
        error = failure("provider.quota", "Go usage limit exceeded")
        data = request(error=error, tokens={"input": 0, "output": 0, "reasoning": 0})
        self.assertEqual(reader().usage_tokens(data), 0)

    def test_a_request_reports_the_sum_of_its_tokens(self):
        data = request(
            finish="stop",
            tokens={"input": 1200, "output": 340, "reasoning": 60, "cache": {"read": 800, "write": 5}},
        )
        self.assertEqual(reader().usage_tokens(data), 1600)

    def test_a_request_without_tokens_reports_no_usage(self):
        self.assertIsNone(reader().usage_tokens(request(finish="stop")))

    def test_a_retry_is_one_request_with_one_outcome(self):
        data = request(finish="stop", retry={"attempt": 2})
        self.assertEqual(self.classify(data), ("success", None))


class ProviderMappingTests(unittest.TestCase):
    """The provider table is committed, and nothing is guessed."""

    def test_the_known_providers_are_mapped(self):
        expected = {
            "ollama-cloud": "ollama",
            "opencode-go": "opencode-go",
            "opencode": "opencode",
            "openrouter": "openrouter",
            "google": "google",
            "requesty": "requesty",
            "nvidia": "nvidia",
            "ovh": "ovh",
            "upstage": "upstage",
            "inception": "inception",
            "groq": "groq",
            "mistral": "mistral",
            "cohere": "cohere",
            "zai": "zai",
            "vercel": "vercel",
            "poolside": "poolside",
            "orcarouter": "orcarouter",
        }
        for provider_id, name in expected.items():
            with self.subTest(provider=provider_id):
                self.assertEqual(reader().provider_for(provider_id), name)

    def test_an_unmapped_provider_is_not_mapped(self):
        for provider_id in ("kilo", "kilo-free", "groq-free", "cf-workers", "ghm"):
            with self.subTest(provider=provider_id):
                self.assertIsNone(reader().provider_for(provider_id))

    def test_an_unknown_provider_is_not_mapped(self):
        self.assertIsNone(reader().provider_for("a-provider-nobody-knows"))


class FixtureDatabaseTests(unittest.TestCase):
    """The read of the committed fixture, in a directory the test builds."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        content = fixture()
        self.rows = content["rows"]
        self.now = content["now_epoch_ms"] / 1000.0
        self.path, self.connection = build_database(self.directory.name, self.rows)
        self.addCleanup(self.connection.close)

    def read(self):
        return reader().read_events(self.path, self.now)

    def test_the_reading_is_ok(self):
        result = self.read()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["reason"], "ok")

    def test_the_reader_counts_the_rows_it_read(self):
        result = self.read()
        self.assertEqual(result["counts"]["rows_read"], 30)

    def test_the_reader_counts_the_rows_it_cannot_map(self):
        result = self.read()
        self.assertEqual(result["counts"]["rows_unmapped"], 1)

    def test_the_reader_counts_the_events_by_outcome(self):
        result = self.read()
        self.assertEqual(
            result["counts"]["outcomes"], {"success": 6, "limit": 9, "other": 14}
        )

    def test_every_mapped_row_becomes_one_event(self):
        result = self.read()
        self.assertEqual(len(result["events"]), 29)

    def test_an_unmapped_provider_is_counted_and_not_emitted(self):
        result = self.read()
        self.assertEqual(
            [event for event in result["events"] if event["model"] == "example/kilo-model"], []
        )
        self.assertEqual(result["counts"]["rows_unmapped"], 1)

    def test_a_row_older_than_the_window_is_not_read(self):
        result = self.read()
        self.assertIsNone(event_at(result, 1796544000000))
        self.assertEqual(result["counts"]["rows_read"], 30)

    def test_a_row_that_is_not_a_model_request_is_not_read(self):
        result = self.read()
        self.assertEqual(result["counts"]["rows_read"], 30)

    def test_the_provider_is_mapped_and_the_model_is_kept(self):
        result = self.read()
        event = event_at(result, 1799989200000)
        self.assertIsNotNone(event)
        self.assertEqual(event["provider"], "openrouter")
        self.assertEqual(event["model"], "example/some-router-model")

    def test_the_event_carries_its_instant_and_its_outcome(self):
        result = self.read()
        event = event_at(result, 1799996400000)
        self.assertEqual(event["at"], 1799996400000 / 1000.0)
        self.assertEqual(event["outcome"], "success")
        self.assertEqual(event["usage"], 1600)
        self.assertIsNone(event["window_hint"])

    def test_a_limit_event_carries_the_window_it_names(self):
        result = self.read()
        self.assertEqual(event_at(result, 1799974800000)["window_hint"], "5h")
        self.assertEqual(event_at(result, 1799971200000)["window_hint"], "7d")
        self.assertEqual(event_at(result, 1799967600000)["window_hint"], "1d")
        self.assertEqual(event_at(result, 1799964000000)["window_hint"], "1d")

    def test_a_limit_without_a_window_names_none(self):
        result = self.read()
        self.assertIsNone(event_at(result, 1799956800000)["window_hint"])
        self.assertIsNone(event_at(result, 1799953200000)["window_hint"])

    def test_a_refusal_that_spends_no_window_is_other(self):
        result = self.read()
        self.assertEqual(event_at(result, 1799942400000)["outcome"], "other")
        self.assertEqual(event_at(result, 1799931600000)["outcome"], "other")
        self.assertEqual(event_at(result, 1799924400000)["outcome"], "other")
        self.assertEqual(event_at(result, 1799906400000)["outcome"], "other")

    def test_a_request_without_tokens_reports_no_usage(self):
        result = self.read()
        self.assertIsNone(event_at(result, 1799892000000)["usage"])

    def test_a_row_without_its_own_time_falls_back_to_the_row(self):
        result = self.read()
        event = event_at(result, 1799982000000)
        self.assertIsNotNone(event)
        self.assertEqual(event["at"], 1799982000000 / 1000.0)


class UnreadableTests(unittest.TestCase):
    """A database that cannot be read is reported, never raised."""

    def test_a_missing_database_is_unreadable(self):
        with tempfile.TemporaryDirectory() as directory:
            result = reader().read_events(Path(directory) / "absent.db", 1800000000.0)
        self.assertEqual(result["status"], "unreadable")
        self.assertEqual(result["reason"], "database_missing")
        self.assertEqual(result["events"], [])

    def test_a_wal_database_without_its_shared_memory_is_unreadable(self):
        content = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path, connection = build_database(directory, content["rows"])
            # The records move into the database file and one more record
            # stays in the write ahead log, the way a live database looks.
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute(
                "INSERT INTO session_message (id, session_id, type, time_created, data) "
                "VALUES (?, ?, ?, ?, ?)",
                ("msg_after_the_checkpoint", "ses_example_7", "assistant", 1799999000000, "{}"),
            )
            connection.commit()
            readonly = Path(directory) / "readonly"
            readonly.mkdir()
            shutil.copyfile(path, readonly / path.name)
            shutil.copyfile(str(path) + "-wal", readonly / (path.name + "-wal"))
            connection.close()
            os.chmod(readonly, 0o555)
            try:
                result = reader().read_events(
                    readonly / path.name, content["now_epoch_ms"] / 1000.0
                )
            finally:
                os.chmod(readonly, 0o755)
        self.assertEqual(result["status"], "unreadable")
        self.assertEqual(result["reason"], "database_unreadable")
        self.assertEqual(result["events"], [])
        self.assertEqual(result["counts"]["rows_read"], 0)

    def test_an_unreadable_reading_reports_no_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            result = reader().read_events(Path(directory) / "absent.db", 1800000000.0)
        self.assertEqual(
            result["counts"], {"rows_read": 0, "rows_unmapped": 0, "outcomes": {"success": 0, "limit": 0, "other": 0}}
        )


class PrivacyTests(unittest.TestCase):
    """The text of a provider's error never leaves the reader."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        content = fixture()
        self.now = content["now_epoch_ms"] / 1000.0
        self.path, self.connection = build_database(self.directory.name, content["rows"])
        self.addCleanup(self.connection.close)
        self.result = reader().read_events(self.path, self.now)

    def test_no_event_carries_the_error_text(self):
        rendered = json.dumps(self.result, default=str)
        self.assertNotIn("example-user", rendered)
        self.assertNotIn("usage limit", rendered)
        self.assertNotIn("Rate limit", rendered)

    def test_the_status_and_the_counts_carry_no_error_text(self):
        rendered = json.dumps(
            {"status": self.result["status"], "reason": self.result["reason"], "counts": self.result["counts"]},
            default=str,
        )
        self.assertNotIn("example-user", rendered)

    def test_the_reason_is_one_of_the_fixed_codes(self):
        self.assertIn(self.result["reason"], reader().REASONS)

    def test_the_reason_of_a_failure_is_a_code_and_not_a_message(self):
        with tempfile.TemporaryDirectory() as directory:
            result = reader().read_events(Path(directory) / "absent.db", 1800000000.0)
        self.assertIn(result["reason"], reader().REASONS)
        self.assertNotIn("/", result["reason"])


class FailingConnection:
    """A connection whose first statement fails, like a closed database."""

    def __init__(self, connection):
        self.connection = connection
        self.closed = False

    def execute(self, *args, **kwargs):
        raise sqlite3.OperationalError("injected failure after the connect")

    def close(self):
        self.closed = True
        self.connection.close()


class FailingSqlite:
    """The database module, with a connect that returns a failing connection."""

    Error = sqlite3.Error
    DatabaseError = sqlite3.DatabaseError
    OperationalError = sqlite3.OperationalError

    def __init__(self, connection):
        self.connection = connection

    def connect(self, *args, **kwargs):
        return self.connection


class ReadOnlyTests(unittest.TestCase):
    """The database is opened read only."""

    def test_the_connection_refuses_a_write(self):
        content = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path, connection = build_database(directory, content["rows"])
            try:
                readonly = reader().open_database(path)
                with self.assertRaises(sqlite3.OperationalError):
                    readonly.execute(
                        "INSERT INTO session_message (id, session_id, type, time_created, data) "
                        "VALUES ('x', 'y', 'assistant', 0, '{}')"
                    )
                readonly.close()
            finally:
                connection.close()

    def test_a_failure_after_the_connect_closes_the_connection(self):
        module = reader()
        content = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path, _connection = build_database(directory, content["rows"])
            injected = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            failing = FailingConnection(injected)
            original = module.sqlite3
            module.sqlite3 = FailingSqlite(failing)
            self.addCleanup(setattr, module, "sqlite3", original)
            with self.assertRaises(sqlite3.OperationalError):
                module.open_database(path)
            self.assertTrue(failing.closed)
            with self.assertRaises(sqlite3.ProgrammingError):
                injected.execute("SELECT 1")

    def test_the_module_never_writes_to_the_database(self):
        source = (COLLECTOR / "opencode_reader.py").read_text(encoding="utf-8").lower()
        for forbidden in (
            "immutable",
            "vacuum",
            "wal_checkpoint",
            "journal_mode",
            "attach",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_the_module_opens_the_database_with_the_read_only_uri(self):
        source = (COLLECTOR / "opencode_reader.py").read_text(encoding="utf-8")
        self.assertIn("mode=ro", source)


class BoundedReadTests(unittest.TestCase):
    """The read is bounded by the window and by the clock."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path, self.connection = build_database(self.directory.name, synthetic_rows(2000))
        self.addCleanup(self.connection.close)
        self.now = 1800000000.0

    def test_a_read_that_runs_out_of_time_is_unreadable(self):
        result = reader().read_events(self.path, self.now, timeout_s=0.0)
        self.assertEqual(result["status"], "unreadable")
        self.assertEqual(result["reason"], "timeout")
        self.assertEqual(result["events"], [])

    def test_a_read_within_the_limit_is_ok(self):
        result = reader().read_events(self.path, self.now)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["counts"]["rows_read"], 2000)

    def test_the_read_window_is_thirty_five_days(self):
        self.assertEqual(reader().READ_DAYS, 35)

    def test_the_read_limit_is_twenty_seconds(self):
        self.assertEqual(reader().READ_TIMEOUT_S, 20.0)

    def test_the_busy_timeout_is_two_seconds(self):
        self.assertLessEqual(reader().BUSY_TIMEOUT_S, 2.0)


class ExtractionTests(unittest.TestCase):
    """The query reads the fields the reader uses, not the whole record."""

    def test_the_query_never_selects_the_bare_record(self):
        statement = reader().READ_SQL
        selected = statement.split(" FROM ")[0]
        # Every mention of the record column is inside the extraction.
        outside = selected.replace("json_valid(data)", "").replace("THEN data END", "")
        self.assertNotIn("data", outside)

    def test_the_query_extracts_the_fields_the_reader_uses(self):
        statement = reader().READ_SQL
        for path in (
            "'$.model'",
            "'$.time'",
            "'$.finish'",
            "'$.error'",
            "'$.tokens'",
            "'$.retry'",
        ):
            with self.subTest(path=path):
                self.assertIn(path, statement)

    def test_the_extracted_record_classifies_like_the_whole_record(self):
        module = reader()
        content = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path, connection = build_database(directory, content["rows"])
            try:
                extracted = {}
                readonly = module.open_database(path)
                try:
                    for time_created, payload in readonly.execute(module.READ_SQL, (0,)):
                        extracted[time_created] = module.record_from_extracted(payload)
                finally:
                    readonly.close()
                for row in content["rows"]:
                    if row["type"] != "assistant":
                        continue
                    record = extracted.get(row["time_created"])
                    self.assertIsNotNone(record, row["id"])
                    with self.subTest(row=row["id"]):
                        self.assertEqual(
                            module.classify(record), module.classify(row["data"])
                        )
                        self.assertEqual(
                            module.usage_tokens(record), module.usage_tokens(row["data"])
                        )
                        self.assertEqual(module.model_of(record), module.model_of(row["data"]))
            finally:
                connection.close()

    def test_the_extracted_record_carries_the_retry(self):
        module = reader()
        content = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path, connection = build_database(directory, content["rows"])
            try:
                readonly = module.open_database(path)
                try:
                    for _time_created, payload in readonly.execute(module.READ_SQL, (0,)):
                        record = module.record_from_extracted(payload)
                        if "retry" in record:
                            self.assertEqual(record["retry"], {"attempt": 2, "last": 1799895500000})
                            return
                finally:
                    readonly.close()
                self.fail("the retry was not extracted")
            finally:
                connection.close()

    def test_a_record_that_does_not_parse_is_counted_and_not_emitted(self):
        module = reader()
        with tempfile.TemporaryDirectory() as directory:
            path, connection = build_database(directory, [])
            try:
                connection.execute(
                    "INSERT INTO session_message (id, session_id, type, time_created, data) "
                    "VALUES (?, ?, ?, ?, ?)",
                    ("msg_broken", "ses_example_1", "assistant", 1799996400000, "not json"),
                )
                connection.commit()
                result = module.read_events(path, 1800000000.0)
            finally:
                connection.close()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["counts"]["rows_read"], 1)
        self.assertEqual(result["counts"]["rows_unmapped"], 1)
        self.assertEqual(result["events"], [])


class IncrementalReadTests(unittest.TestCase):
    """A read that takes a bound reads only the rows inside it."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.now = 1800000000.0
        self.rows = synthetic_rows(
            10, start=int((self.now - 10 * 3600) * 1000), step=3600000
        )
        self.path, self.connection = build_database(self.directory.name, self.rows)
        self.addCleanup(self.connection.close)

    def test_a_read_with_a_since_bound_reads_no_older_row(self):
        result = reader().read_events(self.path, self.now, since=self.now - 7200)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["counts"]["rows_read"], 2)
        for event in result["events"]:
            self.assertGreaterEqual(event["at"], self.now - 7200)

    def test_a_read_with_an_until_bound_reads_no_newer_row(self):
        result = reader().read_events(self.path, self.now, until=self.now - 18000)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["counts"]["rows_read"], 5)
        for event in result["events"]:
            self.assertLess(event["at"], self.now - 18000)

    def test_a_read_with_both_bounds_reads_the_rows_between_them(self):
        result = reader().read_events(
            self.path, self.now, since=self.now - 18000, until=self.now - 7200
        )
        self.assertEqual(result["counts"]["rows_read"], 3)

    def test_the_read_reports_the_newest_row_it_read(self):
        result = reader().read_events(self.path, self.now)
        self.assertEqual(result["cursor"], int((self.now - 3600) * 1000))

    def test_the_query_carries_the_bound_it_was_given(self):
        module = reader()
        statements = capture_statements(module, self)
        module.read_events(self.path, self.now, since=self.now - 7200)
        bounds = [text for text in statements if "session_message" in text]
        self.assertTrue(bounds)
        for statement in bounds:
            self.assertIn(str(int((self.now - 7200) * 1000)), statement)

    def test_a_read_without_a_bound_reads_the_whole_window(self):
        result = reader().read_events(self.path, self.now)
        self.assertEqual(result["counts"]["rows_read"], 10)


class CacheTests(unittest.TestCase):
    """The event cache the collector owns."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name) / "state"
        self.state.mkdir()
        self.cache_path = self.state / "opencode-events.json"
        self.now = 1800000000.0
        self.path, self.connection = build_database(
            self.directory.name,
            synthetic_rows(10, start=int((self.now - 10 * 3600) * 1000), step=3600000),
        )
        self.addCleanup(self.connection.close)

    def run_reader(self, now=None):
        return reader().collect_events(
            self.path, self.cache_path, self.now if now is None else now
        )

    def add_rows(self, count, start_ms):
        rows = synthetic_rows(count, start=start_ms, step=1000, prefix="new")
        for row in rows:
            self.connection.execute(
                "INSERT INTO session_message (id, session_id, type, time_created, data) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    row["id"],
                    row["session_id"],
                    row["type"],
                    row["time_created"],
                    json.dumps(row["data"]),
                ),
            )
        self.connection.commit()
        return rows

    def test_the_cache_is_written_and_read_back(self):
        result = self.run_reader()
        self.assertEqual(result["status"], "ok")
        self.assertTrue(self.cache_path.exists())
        cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.assertEqual(cache["cursor"], int((self.now - 3600) * 1000))
        self.assertEqual(len(cache["events"]), 10)

    def test_the_cache_is_written_beside_itself_and_renamed(self):
        self.run_reader()
        leftovers = [name for name in os.listdir(self.state) if name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_the_cache_holds_no_error_text(self):
        content = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path, connection = build_database(directory, content["rows"])
            try:
                result = reader().collect_events(path, self.cache_path, self.now)
            finally:
                connection.close()
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("example-user", self.cache_path.read_text(encoding="utf-8"))

    def test_the_next_run_reads_only_the_overlap(self):
        self.run_reader()
        result = self.run_reader()
        self.assertEqual(result["status"], "ok")
        # The window the cursor covers: the overlap and nothing older.
        self.assertEqual(result["counts"]["rows_read"], 3)

    def test_the_next_run_queries_only_the_window_of_the_cursor(self):
        module = reader()
        self.run_reader()
        statements = capture_statements(module, self)
        self.run_reader()
        bounds = [text for text in statements if "session_message" in text]
        self.assertTrue(bounds)
        expected = int((self.now - 3600 - 7200) * 1000)
        for statement in bounds:
            self.assertIn(str(expected), statement)

    def test_the_new_rows_are_added_to_the_history(self):
        self.run_reader()
        self.add_rows(5, int((self.now - 1800) * 1000))
        result = self.run_reader()
        self.assertEqual(result["counts"]["rows_read"], 8)
        self.assertEqual(len(result["events"]), 15)

    def test_a_row_completed_later_shows_up_once(self):
        moment = int((self.now - 900) * 1000)
        unfinished = {
            "id": "msg_unfinished",
            "session_id": "ses_synthetic",
            "type": "assistant",
            "time_created": moment,
            "data": {
                "model": {"providerID": "opencode-go", "id": "example/minimax-m3.1-flash"},
                "time": {"created": moment},
                "tokens": {"input": 10, "output": 0, "reasoning": 0},
            },
        }
        self.connection.execute(
            "INSERT INTO session_message (id, session_id, type, time_created, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                unfinished["id"],
                unfinished["session_id"],
                unfinished["type"],
                unfinished["time_created"],
                json.dumps(unfinished["data"]),
            ),
        )
        self.connection.commit()
        first = self.run_reader()
        pending = [event for event in first["events"] if event["at"] == moment / 1000]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["outcome"], "other")
        # OpenCode completes the row: the same id, the same time, new data.
        finished = dict(unfinished["data"])
        finished["finish"] = "stop"
        self.connection.execute(
            "UPDATE session_message SET data = ? WHERE id = ?",
            (json.dumps(finished), unfinished["id"]),
        )
        self.connection.commit()
        second = self.run_reader()
        completed = [event for event in second["events"] if event["at"] == moment / 1000]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["outcome"], "success")

    def test_the_events_older_than_the_window_are_pruned(self):
        self.run_reader()
        later = self.now + 36 * 86400
        result = self.run_reader(later)
        self.assertEqual(result["events"], [])
        cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.assertEqual(cache["events"], [])


class ConnectionTests(unittest.TestCase):
    """The connection is closed on every path."""

    def capture(self):
        """The connections the reader opens during a test."""
        module = reader()
        connections = []
        original = module.open_database

        def wrapper(target):
            connection = original(target)
            connections.append(connection)
            return connection

        module.open_database = wrapper
        self.addCleanup(setattr, module, "open_database", original)
        return connections

    def test_the_connection_is_closed_after_a_successful_read(self):
        content = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path, connection = build_database(directory, content["rows"])
            try:
                connections = self.capture()
                result = reader().read_events(path, content["now_epoch_ms"] / 1000.0)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(len(connections), 1)
                with self.assertRaises(sqlite3.ProgrammingError):
                    connections[0].execute("SELECT 1")
            finally:
                connection.close()

    def test_the_connection_is_closed_after_a_failed_read(self):
        content = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path, connection = build_database(directory, content["rows"])
            try:
                connections = self.capture()
                result = reader().read_events(
                    path, content["now_epoch_ms"] / 1000.0, timeout_s=0.0
                )
                self.assertEqual(result["status"], "unreadable")
                self.assertEqual(len(connections), 1)
                with self.assertRaises(sqlite3.ProgrammingError):
                    connections[0].execute("SELECT 1")
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
