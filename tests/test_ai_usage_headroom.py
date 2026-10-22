"""The real headroom of the accounts that used to be unknown.

The collector used to publish an account amount for OpenRouter and Ollama and
no window at all, so every route of those accounts was published as "Unknown
headroom". A window needs three things: the share of the window that is used,
the instant it resets, and how long it runs. These tests cover the windows
that carry them, and the policy that an unknown headroom always says why it
is unknown.
"""
import importlib.util
import json
import sys
import tempfile
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


providers = load("ai_usage_headroom_providers", "providers.py")
ranking = load("ai_usage_headroom_ranking", "ranking.py")

NOW = 1_800_000_000.0
DAY = 86400.0
HOUR = 3600.0


class FakeResponse:
    def __init__(self, status=200, body=None, error=""):
        self.status = status
        self.body = json.dumps(body).encode() if body is not None else b""
        self.error = error

    def json(self):
        return json.loads(self.body) if self.body else None

    @property
    def ok(self):
        return 200 <= self.status < 300 and not self.error


def env_file(directory, name, value="key"):
    path = Path(directory) / "secrets.env"
    path.write_text(f"{name}={value}\n")
    return str(path)


def window_of(windows, kind):
    for window in windows:
        if window.get("kind") == kind:
            return window
    return None


class OllamaBalanceTests(unittest.TestCase):
    """The balance endpoint is what reports the Ollama windows."""

    BALANCE = {
        "included": {
            "session": {
                "remaining_percent": 25,
                "resets_at": "2027-01-15T20:00:00Z",
            },
            "weekly": {
                "remaining_percent": 64.15,
                "resets_at": "2027-01-18T00:00:00Z",
            },
        },
        "purchased": {"balance_usd": 0},
    }

    def _read(self, directory, balance=None, status=200):
        body = self.BALANCE if balance is None else balance

        def fake_http(url, **kwargs):
            if "balance" in url:
                if status != 200:
                    return FakeResponse(status=status)
                return FakeResponse(body=body)
            return FakeResponse(
                body={"range": "7d", "totals": {"request_count": 513}, "buckets": []}
            )

        return providers.read_ollama(
            env_file(directory, "OLLAMA_API_KEY"),
            NOW,
            http=fake_http,
            state_path=str(Path(directory) / "windows.json"),
        )

    def test_the_session_and_the_weekly_window_are_measured(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._read(directory)
        self.assertEqual(result.status, "ok")
        session = window_of(result.windows, "session")
        weekly = window_of(result.windows, "weekly")
        self.assertIsNotNone(session)
        self.assertIsNotNone(weekly)
        # The used share is the rest of the remaining percentage.
        self.assertAlmostEqual(session["usedRatio"], 0.75)
        self.assertAlmostEqual(weekly["usedRatio"], 1.0 - 64.15 / 100.0)
        # The reset is the instant the provider published.
        self.assertEqual(session["resetEpoch"], 1800043200.0)
        self.assertEqual(weekly["resetEpoch"], 1800230400.0)
        # The weekly window is a week long.
        self.assertEqual(weekly["durationSeconds"], 7 * DAY)
        # The account scope: the window belongs to the account, so it gates
        # every route the account serves.
        self.assertEqual(session["model"], "*")
        self.assertEqual(session["provider"], "ollama")
        self.assertNotIn("gating", session)

    def test_the_session_length_is_learned_from_two_successive_resets(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self._read(directory)
            self.assertEqual(window_of(first.windows, "session")["durationSeconds"], DAY)
            # The next collection sees the next session window: the step
            # between the two resets is its length.
            later = dict(self.BALANCE)
            later["included"] = dict(self.BALANCE["included"])
            later["included"]["session"] = {
                "remaining_percent": 100,
                "resets_at": "2027-01-16T01:00:00Z",
            }
            second = self._read(directory, balance=later)
        session = window_of(second.windows, "session")
        self.assertEqual(session["durationSeconds"], 5 * HOUR)
        self.assertEqual(session["basis"], providers.BASIS_PROVIDER_DERIVED)

    def test_a_balance_that_cannot_be_read_leaves_the_windows_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._read(directory, status=503)
        self.assertEqual(result.status, "partial")
        session = window_of(result.windows, "session")
        self.assertIsNotNone(session)
        self.assertIsNone(session["usedRatio"])
        # An unknown reading does not gate the route: it is not evidence that
        # the account is exhausted.
        self.assertFalse(session["gating"])


class OpenRouterWindowTests(unittest.TestCase):
    """The key endpoint reports the free-model allowance of the day."""

    def _read(self, directory, free=None, requests_last_minute=None):
        body = {
            "data": {
                "usage_daily": 0.1,
                "is_free_tier": False,
                "free_model_daily_requests": (
                    free
                    if free is not None
                    else {"used": 21, "limit": 1000, "remaining": 979}
                ),
            }
        }

        def fake_http(url, **kwargs):
            if "credits" in url:
                return FakeResponse(body={"data": {"total_credits": 20, "total_usage": 0.5}})
            return FakeResponse(body=body)

        return providers.read_openrouter(
            env_file(directory, "OPENROUTER_API_KEY"),
            NOW,
            http=fake_http,
            requests_last_minute=requests_last_minute,
        )

    def test_the_daily_allowance_is_a_window(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._read(directory)
        daily = window_of(result.windows, "daily")
        self.assertIsNotNone(daily)
        self.assertAlmostEqual(daily["usedRatio"], 1.0 - 979 / 1000)
        self.assertEqual(daily["durationSeconds"], DAY)
        # The counter covers the current UTC day.
        self.assertEqual(daily["resetEpoch"], 1800057600.0)
        self.assertEqual(daily["model"], "*")
        self.assertEqual(daily["basis"], providers.BASIS_PROVIDER)

    def test_a_counter_above_the_limit_is_a_spent_day(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._read(
                directory, free={"used": 2997, "limit": 1000, "remaining": 0}
            )
        daily = window_of(result.windows, "daily")
        self.assertEqual(daily["usedRatio"], 1.0)

    def test_the_minute_allowance_counts_our_own_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._read(directory, requests_last_minute=5)
        minute = window_of(result.windows, "minute")
        self.assertIsNotNone(minute)
        self.assertAlmostEqual(minute["usedRatio"], 5 / 20)
        self.assertEqual(minute["durationSeconds"], 60.0)
        # A published limit counted against our own requests is never a
        # reading of the provider.
        self.assertEqual(minute["basis"], providers.BASIS_PUBLISHED_COUNTED)

    def test_without_a_count_there_is_no_minute_window(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._read(directory)
        self.assertIsNone(window_of(result.windows, "minute"))


if __name__ == "__main__":
    unittest.main()
