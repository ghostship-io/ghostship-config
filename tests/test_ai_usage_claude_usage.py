"""The Claude subscription windows, read from the Claude Code OAuth session."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage/collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import catalog
import claude_usage
import limit_models
import main
from util import HttpResult

NOW = 1792810000.0
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ai-usage" / "claude-usage.json"


class FakeResponse(HttpResult):
    def __init__(self, status=200, body=None, error=""):
        super().__init__(status, json.dumps(body).encode() if body is not None else b"", error)


def captured(*_args, **_kwargs):
    return FakeResponse(200, json.loads(FIXTURE.read_text(encoding="utf-8")))


class CredentialsTests(unittest.TestCase):
    def write(self, document):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / ".credentials.json"
        path.write_text(json.dumps(document))
        return path

    def test_only_the_access_token_and_expiry_leave_the_file(self):
        path = self.write(
            {
                "claudeAiOauth": {
                    "accessToken": "sk-ant-oat-SECRET",
                    "refreshToken": "sk-ant-ort-SECRET",
                    "expiresAt": int((NOW + 3600) * 1000),
                    "subscriptionType": "max",
                }
            }
        )
        token, expires = claude_usage.read_credentials(str(path))
        self.assertEqual(token, "sk-ant-oat-SECRET")
        self.assertAlmostEqual(expires, NOW + 3600)
        self.assertNotIn("refreshToken", token)

    def test_a_missing_or_malformed_file_is_unusable(self):
        self.assertIsNone(claude_usage.read_credentials("/nonexistent/.credentials.json"))
        path = self.write({"claudeAiOauth": {"refreshToken": "only-a-refresh"}})
        self.assertIsNone(claude_usage.read_credentials(str(path)))


class WindowTests(unittest.TestCase):
    def read(self, response=captured, expires=None):
        path = Path(tempfile.mkdtemp()) / ".credentials.json"
        path.write_text(
            json.dumps(
                {
                    "claudeAiOauth": {
                        "accessToken": "sk-ant-oat-SENTINEL",
                        "expiresAt": int(expires if expires is not None else (NOW + 3600) * 1000),
                    }
                }
            )
        )
        return claude_usage.read(NOW, str(path), http=response)

    def test_the_captured_fixture_yields_the_two_windows(self):
        result = self.read()
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.reason, "ok")
        self.assertEqual({window["kind"] for window in result.windows}, {"session", "weekly"})
        session = next(window for window in result.windows if window["kind"] == "session")
        weekly = next(window for window in result.windows if window["kind"] == "weekly")
        self.assertAlmostEqual(session["usedRatio"], 0.02)
        self.assertAlmostEqual(weekly["usedRatio"], 0.57)
        self.assertEqual(weekly["durationSeconds"], 7 * 86400)
        self.assertEqual(weekly["observedAtEpoch"], NOW)
        self.assertIsNotNone(weekly["resetEpoch"])
        self.assertEqual(weekly["source"], "claude_usage")
        labels = {
            (name, metrics["window"])
            for name, metrics, _value in result.metrics
            if name == "ghostship_ai_quota_used_ratio"
        }
        self.assertEqual(labels, {("ghostship_ai_quota_used_ratio", "session"),
                                  ("ghostship_ai_quota_used_ratio", "weekly")})
        self.assertNotIn("sk-ant-oat-SENTINEL", json.dumps(result.metrics))
        self.assertNotIn(".credentials.json", json.dumps(result.metrics))

    def test_the_weekly_window_gates_the_claude_candidates(self):
        windows = [
            {
                "provider": window["provider"],
                "kind": window["kind"],
                "remaining_ratio": 1.0 - window["usedRatio"],
                "reset_at": "2026-10-29T03:00:00Z",
                "source": window["source"],
                "pace_state": "on_pace",
            }
            for window in self.read().windows
        ]
        model = limit_models.resolve(
            "claude",
            "claude-opus-5-5",
            now=NOW,
            windows=windows,
        )
        self.assertEqual(model["basis"], "measured")
        self.assertEqual(model["affordable"]["binding_window"], "weekly")
        weekly = next(row for row in model["windows"] if row["kind"] == "weekly")
        session = next(row for row in model["windows"] if row["kind"] == "session")
        self.assertAlmostEqual(weekly["remaining_ratio"], 0.43)
        self.assertAlmostEqual(session["remaining_ratio"], 0.98)
        self.assertEqual(weekly["basis"], "discovered")

    def test_an_expired_credential_is_a_reason_not_a_reading(self):
        result = self.read(expires=NOW - 1)
        self.assertEqual(result.status, "expired_credentials")
        self.assertEqual(result.reason, "expired_credentials")
        self.assertEqual(result.windows, [])

    def test_a_missing_credential_is_not_a_zero(self):
        result = claude_usage.read(NOW, "/nonexistent/.credentials.json")
        self.assertEqual(result.status, "missing_credentials")
        self.assertEqual(result.windows, [])

    def test_a_failed_probe_keeps_a_fixed_reason(self):
        result = self.read(response=lambda *_args, **_kwargs: FakeResponse(401, {"error": "sk-ant-oat-SENTINEL"}))
        self.assertEqual(result.status, "error")
        self.assertEqual(result.reason, "http_unauthorized")
        self.assertEqual(result.windows, [])
        self.assertNotIn("sk-ant-oat-SENTINEL", json.dumps(result.reason))

    def test_a_response_without_a_window_is_not_a_reading(self):
        result = self.read(response=lambda *_args, **_kwargs: FakeResponse(200, {"limits": []}))
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.reason, "invalid_response")
        self.assertEqual(result.windows, [])

    def test_the_snapshot_reports_the_claude_candidate_usage(self):
        source = self.read()
        with tempfile.TemporaryDirectory() as folder:
            context = {
                "offered_models": [("claude", "claude-opus-5-5")],
                "native_models": {
                    ("claude", "claude-opus-5-5"): {
                        "providerInstance": "claudeAgent",
                        "modelId": "claude-opus-5-5",
                        "available": True,
                    }
                },
            }
            results = [source]
            _, ranked = main.ranking_samples(
                results,
                catalog.Catalog({}),
                context,
                NOW,
                t3_home=folder,
                t3_state=str(Path(folder) / "state.sqlite"),
                state_path=str(Path(folder) / "ranking.json"),
            )
            snapshot = main.build_snapshot(
                results,
                ranked,
                context,
                NOW,
                measured_windows=source.windows,
                catalog=catalog.Catalog({}),
            )
        candidate = next(row for row in snapshot["candidates"]
                         if row["model"] == "claude-opus-5-5")
        self.assertEqual(candidate["quota_state"], "available")
        self.assertAlmostEqual(candidate["capacity"]["remaining_ratio"], 0.43)
        binding = candidate["capacity"]["capacity_binding"]
        self.assertEqual(binding["kind"], "weekly")
        self.assertTrue(binding["reset_at"])
        self.assertEqual(snapshot["quota"]["provider_capacity"]["claude"]["remaining_ratio"], 0.43)


if __name__ == "__main__":
    unittest.main()
