"""The AI usage collector: metric rendering, provider readers, and the pool."""
import importlib.util
import json
import os
import re
import sqlite3
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


metrics = load("ai_usage_metrics", "metrics.py")
util = load("ai_usage_util", "util.py")
catalog_module = load("ai_usage_catalog", "catalog.py")
providers = load("ai_usage_providers", "providers.py")
pool = load("ai_usage_pool", "pool.py")
t3source = load("ai_usage_t3source", "t3source.py")
main = load("ai_usage_main", "main.py")


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


class MetricWriterTests(unittest.TestCase):
    def test_renders_labels_and_types(self):
        writer = metrics.MetricWriter()
        writer.declare("ghostship_ai_quota_used_ratio", "gauge", "Used quota")
        writer.add("ghostship_ai_quota_used_ratio", {"provider": "grok", "window": "weekly"}, 0.25)
        writer.add("ghostship_ai_quota_used_ratio", {"provider": "grok", "window": "session"}, 1)
        text = writer.render()
        self.assertIn("# HELP ghostship_ai_quota_used_ratio Used quota", text)
        self.assertIn("# TYPE ghostship_ai_quota_used_ratio gauge", text)
        self.assertIn('ghostship_ai_quota_used_ratio{provider="grok",window="weekly"} 0.25', text)
        self.assertIn('ghostship_ai_quota_used_ratio{provider="grok",window="session"} 1', text)

    def test_sanitises_label_values(self):
        writer = metrics.MetricWriter()
        writer.add("m", {"provider": 'a"b\\c d'}, 1)
        self.assertIn('provider="a_b_c_d"', writer.render())

    def test_skips_nan_values(self):
        writer = metrics.MetricWriter()
        writer.add("m", {"a": "b"}, float("nan"))
        self.assertNotIn("m{", writer.render())


class CatalogTests(unittest.TestCase):
    def test_free_price_detection(self):
        self.assertTrue(catalog_module.is_free_price({"input": 0, "output": 0}))
        self.assertFalse(catalog_module.is_free_price({"input": 0.5, "output": 0}))
        self.assertFalse(catalog_module.is_free_price(None))

    def test_promo_detection(self):
        self.assertTrue(catalog_module.is_promo("minimax-m3.1-flash-free"))
        self.assertTrue(catalog_module.is_promo("vendor/model:free"))
        self.assertFalse(catalog_module.is_promo("gpt-6.1-sol"))

    def test_price_lookup_uses_provider_aliases(self):
        catalog = catalog_module.Catalog(
            {
                "ollama-cloud": {
                    "models": {
                        "deepseek-v4.1-flash": {
                            "name": "DeepSeek V4.1 Flash",
                            "cost": {"input": 0.15, "output": 0.6},
                        }
                    }
                }
            }
        )
        rates = catalog.price_for("ollama", "deepseek-v4.1-flash")
        self.assertIsNotNone(rates)
        self.assertAlmostEqual(rates["input"], 0.15)
        self.assertIsNone(catalog.price_for("ollama", "missing-model"))

    def test_free_models_list(self):
        catalog = catalog_module.Catalog(
            {
                "opencode-go": {
                    "models": {
                        "minimax-m3.1-flash-free": {
                            "name": "MiniMax M3.1 Flash Free",
                            "cost": {"input": 0, "output": 0},
                        },
                        "gpt-6.1-sol": {
                            "name": "GPT-6.1-Sol",
                            "cost": {"input": 2, "output": 10},
                        },
                    }
                }
            }
        )
        free = catalog.free_models("opencode-go")
        self.assertEqual([entry["model"] for entry in free], ["minimax-m3.1-flash-free"])
        self.assertEqual(free[0]["tier"], "promo")


class GrokTests(unittest.TestCase):
    def test_missing_credential_is_reported(self):
        with tempfile.TemporaryDirectory() as home:
            result = providers.read_grok(home, 1000.0, http=lambda *a, **k: FakeResponse())
        self.assertEqual(result.status, "missing_credentials")

    def test_weekly_window_is_reported(self):
        with tempfile.TemporaryDirectory() as home:
            path = Path(home) / ".grok"
            path.mkdir()
            (path / "auth.json").write_text(
                json.dumps(
                    {
                        "https://auth.x.ai::key": {
                            "auth_mode": "oidc",
                            "key": "token",
                            "email": "person@example.com",
                        }
                    }
                )
            )
            body = {
                "config": {
                    "currentPeriod": {
                        "type": "USAGE_PERIOD_TYPE_WEEKLY",
                        "start": "2026-10-20T05:38:29.840367+00:00",
                        "end": "2026-10-27T05:38:29.840367+00:00",
                    },
                    "creditUsagePercent": 12.5,
                }
            }
            result = providers.read_grok(
                home, 1000.0, http=lambda *a, **k: FakeResponse(body=body)
            )
        self.assertEqual(result.status, "ok")
        used = [sample for sample in result.metrics if sample[0] == "ghostship_ai_quota_used_ratio"]
        self.assertEqual(len(used), 1)
        self.assertAlmostEqual(used[0][2], 0.125)
        self.assertNotIn("person@example.com", json.dumps(result.metrics))


class OpenCodeGoTests(unittest.TestCase):
    def test_usage_windows_are_reported(self):
        with tempfile.TemporaryDirectory() as home:
            share = Path(home) / ".local" / "share" / "opencode"
            share.mkdir(parents=True)
            (share / "auth.json").write_text(
                json.dumps({"opencode-go": {"type": "api", "key": "go-key"}})
            )
            body = {
                "usage": {
                    "rolling": {"status": "ok", "percent": 0, "resetsAt": "2026-10-22T01:30:16.000Z"},
                    "weekly": {"status": "ok", "percent": 10, "resetsAt": "2026-10-26T00:00:00.000Z"},
                    "monthly": {
                        "status": "rate-limited",
                        "percent": 100,
                        "resetsAt": "2026-10-30T22:34:27.000Z",
                    },
                }
            }
            result = providers.read_opencode_go(
                home, 1000.0, http=lambda *a, **k: FakeResponse(body=body)
            )
        self.assertEqual(result.status, "ok")
        windows = {
            sample[1]["window"]: sample[2]
            for sample in result.metrics
            if sample[0] == "ghostship_ai_quota_used_ratio"
        }
        self.assertEqual(set(windows), {"session", "weekly", "monthly"})
        self.assertAlmostEqual(windows["monthly"], 1.0)
        states = [sample for sample in result.metrics if sample[0] == "ghostship_ai_quota_state"]
        self.assertTrue(any(sample[1]["state"] == "rate-limited" for sample in states))


class AntigravityTests(unittest.TestCase):
    def test_model_quotas_are_reported(self):
        with tempfile.TemporaryDirectory() as home:
            base = Path(home) / ".t3" / "userdata" / "providers" / "antigravity" / "acct"
            token_dir = base / "antigravity-acp"
            token_dir.mkdir(parents=True)
            (token_dir / "acp_token.json").write_text(
                json.dumps(
                    {
                        "client_id": "id",
                        "client_secret": "secret",
                        "refresh_token": "refresh",
                        "project_id": "project",
                    }
                )
            )

            def fake_http(url, **kwargs):
                if "oauth2.googleapis.com" in url:
                    return FakeResponse(body={"access_token": "access", "expires_in": 3600})
                if "fetchAvailableModels" in url:
                    return FakeResponse(
                        body={
                            "models": {
                                "gemini-2.5-pro": {
                                    "quotaInfo": {
                                        "remainingFraction": 0.25,
                                        "resetTime": "2026-10-22T01:36:31Z",
                                    },
                                    "weeklyQuotaInfo": {"remainingFraction": 1.0},
                                }
                            }
                        }
                    )
                return FakeResponse(
                    body={
                        "groups": [
                            {
                                "buckets": [
                                    {
                                        "bucketId": "gemini-5h",
                                        "window": "5h",
                                        "remainingFraction": 1.0,
                                        "resetTime": "2026-10-22T01:36:30Z",
                                    }
                                ]
                            }
                        ]
                    }
                )

            result = providers.read_antigravity(home, 1000.0, http=fake_http)
        self.assertIn(result.status, ("ok", "partial"))
        models = {
            sample[1]["model"]
            for sample in result.metrics
            if sample[0] == "ghostship_ai_quota_used_ratio" and sample[1]["model"] != "*"
        }
        self.assertIn("gemini-2.5-pro", models)


class OpenRouterAndOllamaTests(unittest.TestCase):
    def test_openrouter_credits_and_free_allowance(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "secrets.env"
            env.write_text("OPENROUTER_API_KEY=key\n")

            def fake_http(url, **kwargs):
                if "credits" in url:
                    return FakeResponse(body={"data": {"total_credits": 20, "total_usage": 0.5}})
                return FakeResponse(
                    body={
                        "data": {
                            "usage_daily": 0.1,
                            "usage_weekly": 0.2,
                            "usage_monthly": 0.3,
                            "is_free_tier": False,
                            "free_model_daily_requests": {"used": 21, "limit": 1000, "remaining": 979},
                        }
                    }
                )

            result = providers.read_openrouter(str(env), 1000.0, http=fake_http)
        self.assertEqual(result.status, "ok")
        kinds = {
            sample[1]["kind"]
            for sample in result.metrics
            if sample[0] == "ghostship_ai_account_amount"
        }
        self.assertIn("balance", kinds)
        self.assertIn("free_models_remaining", kinds)

    def test_ollama_request_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "secrets.env"
            env.write_text("OLLAMA_API_KEY=key\n")

            def fake_http(url, **kwargs):
                return FakeResponse(
                    body={"range": "7d", "totals": {"request_count": 513}, "buckets": []}
                )

            result = providers.read_ollama(str(env), 1000.0, http=fake_http)
        self.assertEqual(result.status, "ok")
        values = [
            sample[2]
            for sample in result.metrics
            if sample[0] == "ghostship_ai_account_amount"
        ]
        self.assertEqual(values, [513.0, 513.0, 513.0])


class PoolLedgerTests(unittest.TestCase):
    def test_ledger_sums_reservations_per_window(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.sqlite"
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE inference_reservations(id TEXT, job TEXT, provider TEXT, model TEXT,"
                " at REAL, input INTEGER, output INTEGER, usd REAL, neurons REAL)"
            )
            connection.execute(
                "INSERT INTO inference_reservations VALUES('a','j','groq','qwen/qwen3.8-27b',?,10,5,0.01,0)",
                (1000.0,),
            )
            connection.execute(
                "INSERT INTO inference_reservations VALUES('b','j','groq','qwen/qwen3.8-27b',?,10,5,0.01,0)",
                (1000.0 - 90000.0,),
            )
            connection.commit()
            connection.close()
            ledger = pool._read_ledger(path, 1000.0)
        tokens = {
            (sample[1]["kind"], sample[1]["window"]): sample[2]
            for sample in ledger.samples
            if sample[0] == "ghostship_ai_usage_tokens"
        }
        self.assertEqual(tokens[("input", "24h")], 10)
        self.assertEqual(tokens[("input", "7d")], 20)
        self.assertEqual(ledger.status, "ok")

    def test_missing_ledger_is_reported(self):
        ledger = pool._read_ledger("/nonexistent/jobs.sqlite", 1000.0)
        self.assertEqual(ledger.status, "missing_credentials")


class T3UsageTests(unittest.TestCase):
    def test_opencode_models_are_split_by_provider(self):
        self.assertEqual(
            t3source.split_model("opencode", "opencode-go/minimax-m3.1-flash-free"),
            ("opencode-go", "minimax-m3.1-flash-free"),
        )
        self.assertEqual(
            t3source.split_model("opencode", "ollama-cloud/deepseek-v4.1-flash"),
            ("ollama", "deepseek-v4.1-flash"),
        )
        self.assertEqual(
            t3source.split_model("opencode", "claude-opus-5-5"),
            ("opencode", "claude-opus-5-5"),
        )

    def test_buckets_map_to_token_kinds(self):
        buckets = [
            {
                "provider": "claude",
                "model": "claude-opus-5-5",
                "totals": {
                    "uncachedInputTokens": 10,
                    "cachedInputTokens": 20,
                    "cacheCreationTokens": 5,
                    "outputTokens": 7,
                    "reasoningTokens": 3,
                },
                "costUsd": 1.5,
                "costSource": "modelPriced",
                "unpricedRecords": 0,
            }
        ]
        samples = t3source._bucket_samples(buckets, "24h")
        tokens = {sample[1]["kind"]: sample[2] for sample in samples if sample[0] == "ghostship_ai_usage_tokens"}
        self.assertEqual(tokens["input"], 10)
        self.assertEqual(tokens["cache_read"], 20)
        self.assertEqual(tokens["cache_write"], 5)
        self.assertEqual(tokens["output"], 7)
        self.assertEqual(tokens["reasoning"], 3)
        costs = [sample for sample in samples if sample[0] == "ghostship_ai_usage_cost_usd"]
        self.assertEqual(costs[0][1]["basis"], "api_equivalent")
        self.assertEqual(costs[0][2], 1.5)


class EnvFileTests(unittest.TestCase):
    def test_reads_key_values_without_leaking(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secrets.env"
            path.write_text("# comment\nexport KEY=\"value\"\nOTHER=2\n")
            values = util.read_env_file(path)
        self.assertEqual(values["KEY"], "value")
        self.assertEqual(values["OTHER"], "2")

    def test_missing_file_is_empty(self):
        self.assertEqual(util.read_env_file("/nonexistent/secrets.env"), {})


class DashboardTests(unittest.TestCase):
    """The dashboard may only query metrics the collector publishes."""

    def setUp(self):
        self.path = (
            Path(__file__).resolve().parents[1]
            / "modules/self-hosted/siem/dashboards/ai-usage.json"
        )
        self.dashboard = json.loads(self.path.read_text(encoding="utf-8"))

    def test_dashboard_identity(self):
        self.assertEqual(self.dashboard["uid"], "ghostship-ai-usage")
        self.assertIn("ghostship", self.dashboard["tags"])

    def test_panels_have_unique_ids_and_positions(self):
        panels = self.dashboard.get("panels") or []
        identifiers = [panel.get("id") for panel in panels]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        for panel in panels:
            if panel.get("type") == "row":
                continue
            position = panel.get("gridPos") or {}
            self.assertIn("x", position)
            self.assertIn("y", position)
            self.assertIn("w", position)
            self.assertIn("h", position)

    def test_every_query_uses_a_published_metric(self):
        known = set(main.METRIC_HELP)
        # Two metrics of the page are published by the collector in changes
        # that are not in this branch yet: the display name of a model and
        # the basis of its capacity. The page reads them when the collector
        # publishes them, and falls back to the raw model id and to the
        # behaviour of today when it does not.
        pending = {
            "ghostship_ai_model_info",
            "ghostship_ai_model_capacity_basis",
        }
        for panel in self.dashboard.get("panels") or []:
            for target in panel.get("targets") or []:
                expression = target.get("expr") or ""
                for name in re.findall(r"ghostship_ai_[a-z0-9_]+", expression):
                    self.assertTrue(
                        name in known or name in pending,
                        f"{panel.get('title')} queries {name}",
                    )


if __name__ == "__main__":
    unittest.main()
