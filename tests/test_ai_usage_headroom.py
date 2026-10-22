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
from typing import Any

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
main = load("ai_usage_headroom_main", "main.py")
catalog_module = load("ai_usage_headroom_catalog", "catalog.py")
published = load("ai_usage_headroom_published", "published.py")

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


class GoFreeRouteTests(unittest.TestCase):
    """The Go free routes are published as unlimited, and the paid routes are not."""

    CATALOG = {
        "opencode-go": {
            "models": {
                "minimax-m3.1-flash-free": {
                    "name": "MiniMax M3.1 Flash Free",
                    "cost": {"input": 0, "output": 0},
                },
                "minimax-m3.1": {
                    "name": "MiniMax M3.1",
                    "cost": {"input": 1.0, "output": 4.0},
                },
            }
        }
    }

    def _spent_allowance(self):
        return [
            ranking.QuotaWindow(
                kind="monthly",
                used_ratio=1.0,
                reset_epoch=NOW + 10 * DAY,
                duration_seconds=30 * DAY,
                observed_at=NOW,
                quota_id="go_monthly",
            )
        ]

    def _unlimited(self):
        return [
            ranking.QuotaWindow(
                kind="unlimited",
                used_ratio=0.0,
                reset_epoch=None,
                quota_id=published.UNLIMITED_QUOTA_ID,
                observed_at=NOW,
                basis="published",
            )
        ]

    def _rank(self, model, model_windows):
        windows = {"opencode-go": self._spent_allowance()}
        if model_windows:
            windows[f"opencode-go/{model}"] = model_windows
        return ranking.rank_models(
            models=[ranking.ModelRecord("opencode-go", model)],
            catalog=catalog_module.Catalog(self.CATALOG),
            quota_windows=windows,
            free_models={("opencode-go", "minimax-m3.1-flash-free")},
            usage_tokens={},
            now=NOW,
        )

    def test_the_free_route_is_not_gated_by_the_spent_allowance(self):
        ranked = self._rank("minimax-m3.1-flash-free", self._unlimited())
        entry = ranked[0]
        self.assertTrue(entry.available)
        self.assertEqual(entry.remaining, 1.0)
        self.assertTrue(entry.unlimited)
        self.assertTrue(
            any("unlimited (published)" in reason for reason in entry.reasons)
        )

    def test_a_paid_route_is_still_blocked_by_the_spent_allowance(self):
        ranked = self._rank("minimax-m3.1", [])
        entry = ranked[0]
        self.assertFalse(entry.available)
        self.assertEqual(entry.remaining, 0.0)
        self.assertFalse(entry.unlimited)

    def test_the_collector_publishes_the_unlimited_window_for_the_free_routes(self):
        catalog = catalog_module.Catalog(self.CATALOG)
        context = {
            "offered_models": [
                ("opencode-go", "minimax-m3.1-flash-free"),
                ("opencode-go", "minimax-m3.1"),
            ]
        }
        inputs = main.ranking_inputs([], catalog, context, [], now=NOW)
        windows = inputs["windows"]
        free_route = windows.get("opencode-go/minimax-m3.1-flash-free") or []
        self.assertEqual(len(free_route), 1)
        self.assertEqual(free_route[0].quota_id, published.UNLIMITED_QUOTA_ID)
        self.assertEqual(free_route[0].kind, "unlimited")
        self.assertEqual(free_route[0].basis, "published")
        # The paid route keeps the allowance of the account and no window
        # of its own.
        self.assertNotIn("opencode-go/minimax-m3.1", windows)

    def test_a_paid_route_the_catalog_prices_is_never_unlimited(self):
        catalog = catalog_module.Catalog(
            {
                "opencode-go": {
                    "models": {
                        "minimax-m3.1-free": {
                            "name": "MiniMax M3.1 (a paid route)",
                            "cost": {"input": 1.0, "output": 4.0},
                        }
                    }
                }
            }
        )
        context = {"offered_models": [("opencode-go", "minimax-m3.1-free")]}
        inputs = main.ranking_inputs([], catalog, context, [], now=NOW)
        # The catalog prices the route and it is not free, so the published
        # unlimited listing does not apply to it.
        self.assertNotIn("opencode-go/minimax-m3.1-free", inputs["windows"])

    def test_the_snapshot_says_the_route_is_unlimited(self):
        snapshot_module = load("ai_usage_headroom_snapshot", "snapshot.py")
        ranked = self._rank("minimax-m3.1-flash-free", self._unlimited())
        data = snapshot_module.build_snapshot(
            now=NOW,
            sources=[],
            ranked=ranked,
            native_models={},
            policy={
                "frontierPrimeModels": (),
                "allowedGptModels": (),
                "backgroundProviderInstances": (),
            },
            catalog=catalog_module.Catalog(self.CATALOG),
            facts={},
        )
        row = data["candidates"][0]
        labels = [window.get("label") for window in row["quota_windows_applied"]]
        self.assertIn("unlimited (published)", labels)
        self.assertEqual(row["quota_state"], "available")
        self.assertEqual(row["capacity"]["remaining_ratio"], 1.0)


class EnabledProviderHeadroomTests(unittest.TestCase):
    """Every enabled provider has a headroom window, or says why it has none.

    The owner rule, enforced with tooling: the snapshot of the enabled
    providers is checked, and a row whose headroom is unknown without a
    reason fails the check.
    """

    FIXTURE = (
        Path(__file__).resolve().parents[1]
        / "tests/fixtures/ai-usage/enabled-providers.json"
    )

    def _fixture(self):
        return json.loads(self.FIXTURE.read_text(encoding="utf-8"))

    def _catalog(self, fixture):
        prices = {
            ("opencode-go", "minimax-m3.1-flash-free"): {"input": 0, "output": 0},
            ("opencode-go", "minimax-m3.1"): {"input": 1.0, "output": 4.0},
            ("openrouter", "cohere/north-mini-code:free"): {"input": 0, "output": 0},
            ("ollama", "deepseek-v4.1-flash"): {"input": 0.15, "output": 0.6},
            ("codex", "gpt-6.1-sol"): {"input": 1.0, "output": 2.0},
            ("claude", "claude-opus-5-5"): {"input": 4.0, "output": 20.0},
            ("grok", "grok-code"): {"input": 1.0, "output": 3.0},
        }
        document: dict[str, Any] = {}
        for entry in fixture["providers"]:
            provider = entry["provider"]
            models = document.setdefault(provider, {"models": {}})
            for model in entry["models"]:
                models["models"][model] = {
                    "name": model,
                    "cost": prices[(provider, model)],
                }
        return catalog_module.Catalog(document)

    def _readings(self, directory):
        """The measured windows of the accounts that report their own."""
        share = Path(directory) / ".local" / "share" / "opencode"
        share.mkdir(parents=True)
        (share / "auth.json").write_text(
            json.dumps({"opencode-go": {"type": "api", "key": "go-key"}}),
            encoding="utf-8",
        )
        ollama = providers.read_ollama(
            env_file(directory, "OLLAMA_API_KEY"),
            NOW,
            http=lambda url, **kwargs: FakeResponse(
                body={
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
                    "totals": {"request_count": 10},
                }
            ),
        )
        openrouter = providers.read_openrouter(
            env_file(directory, "OPENROUTER_API_KEY"),
            NOW,
            http=lambda url, **kwargs: FakeResponse(
                body={
                    "data": {
                        "free_model_daily_requests": {
                            "used": 21,
                            "limit": 1000,
                            "remaining": 979,
                        }
                    }
                }
            ),
            requests_last_minute=2,
        )
        go = providers.read_opencode_go(
            directory,
            NOW,
            http=lambda url, **kwargs: FakeResponse(
                body={
                    "usage": {
                        "rolling": {"status": "ok", "percent": 0, "resetsAt": "2027-01-15T13:00:00Z"},
                        "weekly": {"status": "ok", "percent": 10, "resetsAt": "2027-01-18T00:00:00Z"},
                        "monthly": {
                            "status": "rate-limited",
                            "percent": 100,
                            "resetsAt": "2027-01-30T22:34:27Z",
                        },
                    }
                }
            ),
        )
        measured: list[dict[str, Any]] = []
        for result in (ollama, openrouter, go):
            measured.extend(result.windows)
        return measured

    def _snapshot(self, directory):
        snapshot_module = load("ai_usage_headroom_snapshot", "snapshot.py")
        fixture = self._fixture()
        catalog = self._catalog(fixture)
        offered = [
            (entry["provider"], model)
            for entry in fixture["providers"]
            for model in entry["models"]
        ]
        measured = self._readings(directory)
        context = {"offered_models": offered}
        inputs = main.ranking_inputs([], catalog, context, measured, now=NOW)
        ranked = ranking.rank_models(
            models=[ranking.ModelRecord(provider, model) for provider, model in offered],
            catalog=catalog,
            quota_windows=inputs["windows"],
            free_models=inputs["free"],
            promo_models=inputs["promo"],
            usage_tokens={},
            now=NOW,
        )
        return snapshot_module.build_snapshot(
            now=NOW,
            sources=[],
            ranked=ranked,
            native_models={},
            policy={
                "frontierPrimeModels": (),
                "allowedGptModels": (),
                "backgroundProviderInstances": (),
            },
            catalog=catalog,
            facts={},
            measured_windows=measured,
        )

    def test_every_enabled_provider_has_a_window_or_a_reason(self):
        snapshot_module = load("ai_usage_headroom_snapshot", "snapshot.py")
        with tempfile.TemporaryDirectory() as directory:
            data = self._snapshot(directory)
        rows = {row["provider"]: row for row in data["candidates"]}
        for entry in self._fixture()["providers"]:
            provider = entry["provider"]
            self.assertIn(provider, rows)
            row = rows[provider]
            remaining = (row.get("capacity") or {}).get("remaining_ratio")
            if remaining is None:
                # The headroom is unknown, so it says why.
                self.assertTrue(
                    row.get("unknown_reason"),
                    f"{provider} has an unknown headroom and no reason",
                )
            else:
                self.assertEqual(row.get("unknown_reason"), "")
        # The rule itself: an unknown headroom without a reason is a gap.
        self.assertEqual(snapshot_module.unknown_headroom_violations(data["candidates"]), [])

    def test_an_unknown_headroom_without_a_reason_is_a_violation(self):
        snapshot_module = load("ai_usage_headroom_snapshot", "snapshot.py")
        violations = snapshot_module.unknown_headroom_violations(
            [
                {
                    "provider": "ollama",
                    "model": "deepseek-v4.1-flash",
                    "quota_state": "unknown",
                    "unknown_reason": "",
                }
            ]
        )
        self.assertEqual(
            violations, [{"provider": "ollama", "model": "deepseek-v4.1-flash"}]
        )

    def test_the_accounts_that_report_their_own_windows_have_headroom(self):
        with tempfile.TemporaryDirectory() as directory:
            data = self._snapshot(directory)
        rows = {(row["provider"], row["model"]): row for row in data["candidates"]}
        for key in (
            ("ollama", "deepseek-v4.1-flash"),
            ("openrouter", "cohere/north-mini-code:free"),
            ("opencode-go", "minimax-m3.1-flash-free"),
            ("opencode-go", "minimax-m3.1"),
        ):
            row = rows[key]
            self.assertIsNotNone(
                (row.get("capacity") or {}).get("remaining_ratio"),
                f"{key} has no headroom window",
            )
            self.assertEqual(row.get("unknown_reason"), "")


if __name__ == "__main__":
    unittest.main()
