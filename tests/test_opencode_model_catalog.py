import contextlib
import datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "packages/t3code/opencode-model-catalog.py"
spec = importlib.util.spec_from_file_location("opencode_model_catalog", SOURCE)
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)

TODAY = datetime.date(2026, 10, 19)

LIVE_CONFIG = {
    "$schema": "https://opencode.ai/config.json",
    "enabled_providers": ["ollama-cloud", "opencode-go", "openrouter", "opencode"],
    "provider": {"openrouter": {"models": {}}},
    "model": "ollama-cloud/deepseek-v4.1-flash",
    "small_model": "openrouter/cohere/north-mini-code:free",
    "mcp": {"ghostship": {"type": "remote", "url": "http://127.0.0.1:1/mcp"}},
    "permission": {"edit": "allow"},
}


def model(model_id, released, *, tools=True, cost=1, status=None):
    entry = {"id": model_id, "release_date": released, "tool_call": tools,
             "cost": {"input": cost, "output": cost}}
    if status:
        entry["status"] = status
    return entry


class Trim(unittest.TestCase):
    def source(self):
        return {
            "ollama-cloud": {"id": "ollama-cloud", "models": {
                "new": model("new", "2026-10-01"),
                "old": model("old", "2025-08-05"),
                "pinned-old": model("pinned-old", "2025-01-01"),
                "no-tools": model("no-tools", "2026-09-01", tools=False),
                "deprecated": model("deprecated", "2026-09-01", status="deprecated"),
            }},
            "opencode-go": {"id": "opencode-go", "models": {
                "recent": model("recent", "2026-09-01"),
                "old": model("old", "2025-01-01"),
            }},
            "openrouter": {"id": "openrouter", "models": {
                "a/new:free": model("a/new:free", "2026-09-01", cost=0),
                "a/new-paid": model("a/new-paid", "2026-09-01"),
                "a/old:free": model("a/old:free", "2025-01-01", cost=0),
            }},
            "opencode": {"id": "opencode", "models": {
                "fixture-free": model("fixture-free", "2026-09-01", cost=0),
                "fixture-paid": model("fixture-paid", "2026-09-01"),
            }},
            "anthropic": {"id": "anthropic", "models": {"legacy": model("legacy", "2023-01-01")}},
        }

    def test_keeps_recent_tool_models_and_pins(self):
        result = catalog.trim(self.source(), TODAY, {"ollama-cloud/pinned-old"})
        self.assertEqual(sorted(result["ollama-cloud"]["models"]), ["new", "pinned-old"])
        self.assertEqual(sorted(result["opencode-go"]["models"]), ["recent"])
        # Providers outside the trimmed set pass through unchanged.
        self.assertEqual(result["anthropic"], self.source()["anthropic"])

    def test_openrouter_leaves_the_catalog(self):
        result = catalog.trim(self.source(), TODAY, set())
        self.assertNotIn("openrouter", result)
        self.assertEqual(sorted(result), ["anthropic", "ollama-cloud", "opencode-go"])

    def test_a_pinned_openrouter_model_stays_out(self):
        result = catalog.trim(self.source(), TODAY, {"openrouter/a/new:free"})
        self.assertNotIn("openrouter", result)

    def test_zen_is_absent_even_when_a_free_model_was_pinned(self):
        self.assertNotIn('opencode', catalog.trim(self.source(), TODAY, {'opencode/fixture-free'}))

    def test_new_releases_are_accepted_without_a_list(self):
        source = self.source()
        source["ollama-cloud"]["models"]["future"] = model("future", "2026-10-18")
        self.assertIn("future", catalog.trim(source, TODAY, set())["ollama-cloud"]["models"])


class Config(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.source, self.output = self.root / "models.json", self.root / "out/models.json"
        self.config = self.root / "opencode.jsonc"

    def tearDown(self):
        self.directory.cleanup()

    def write_source(self):
        self.source.write_text(json.dumps(Trim().source()))

    def read_config(self):
        return json.loads(self.config.read_text(encoding="utf-8"))

    def test_retires_the_provider_from_the_live_config(self):
        self.config.write_text(json.dumps(LIVE_CONFIG, indent=2))
        args = ["--source", str(self.source), "--config", str(self.config), "--output", str(self.output)]
        self.write_source()
        self.assertEqual(catalog.main(args), 0)
        config = self.read_config()
        self.assertEqual(config["enabled_providers"], ["ollama-cloud", "opencode-go"])
        self.assertNotIn("openrouter", config["provider"])
        self.assertEqual(config['providers']['opencode']['models'], {
            'fixture-free': {'disabled': True}, 'fixture-paid': {'disabled': True}})
        self.assertEqual(config["small_model"], "ollama-cloud/minimax-m3.1-flash")
        self.assertEqual(config["model"], "ollama-cloud/deepseek-v4.1-flash")
        for key in ("$schema", "mcp", "permission"):
            self.assertEqual(config[key], LIVE_CONFIG[key])

    def test_an_openrouter_default_model_is_replaced(self):
        self.config.write_text(json.dumps({**LIVE_CONFIG, "model": "openrouter/x"}, indent=2))
        self.write_source()
        self.assertEqual(catalog.main(
            ["--source", str(self.source), "--config", str(self.config), "--output", str(self.output)]), 0)
        self.assertEqual(self.read_config()["model"], "ollama-cloud/deepseek-v4.1-flash")

    def test_a_second_run_does_not_rewrite_the_config(self):
        self.config.write_text(json.dumps(LIVE_CONFIG, indent=2))
        self.write_source()
        args = ["--source", str(self.source), "--config", str(self.config), "--output", str(self.output)]
        self.assertEqual(catalog.main(args), 0)
        self.assertNotIn("openrouter", self.config.read_text())
        before_bytes = self.config.read_bytes()
        before = os.stat(self.config).st_mtime_ns
        self.assertEqual(catalog.main(args), 0)
        self.assertEqual(self.config.read_bytes(), before_bytes)
        self.assertEqual(os.stat(self.config).st_mtime_ns, before)

    def test_the_config_is_written_0600_and_atomically(self):
        self.config.write_text(json.dumps(LIVE_CONFIG, indent=2))
        self.write_source()
        self.assertEqual(catalog.main(
            ["--source", str(self.source), "--config", str(self.config), "--output", str(self.output)]), 0)
        self.assertEqual(stat.S_IMODE(os.stat(self.config).st_mode), 0o600)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),
                         ["models.json", "opencode.jsonc", "out"])

    def test_a_missing_config_is_left_alone(self):
        self.write_source()
        args = ["--source", str(self.source), "--config", str(self.config), "--output", str(self.output)]
        self.assertEqual(catalog.main(args), 0)
        self.assertFalse(self.config.exists())
        self.assertTrue(self.output.exists())

    def test_an_invalid_config_is_left_alone_with_one_log_line(self):
        self.config.write_text('{"model": "openrouter/x",}\n')
        before = self.config.read_bytes()
        self.write_source()
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(catalog.main(
                ["--source", str(self.source), "--config", str(self.config), "--output", str(self.output)]), 0)
        self.assertEqual(self.config.read_bytes(), before)
        lines = [line for line in errors.getvalue().splitlines() if str(self.config) in line]
        self.assertEqual(len(lines), 1)

    def test_a_config_already_isolating_free_providers_is_not_rewritten(self):
        plain = {"enabled_providers": ["ollama-cloud"], "model": "ollama-cloud/deepseek-v4.1-flash",
                 "providers": {"opencode": {"models": {
                     'fixture-free': {'disabled': True}, 'fixture-paid': {'disabled': True}}}}}
        self.config.write_text(json.dumps(plain, indent=2))
        before_bytes = self.config.read_bytes()
        before = os.stat(self.config).st_mtime_ns
        self.write_source()
        self.assertEqual(catalog.main(
            ["--source", str(self.source), "--config", str(self.config), "--output", str(self.output)]), 0)
        self.assertEqual(self.config.read_bytes(), before_bytes)
        self.assertEqual(os.stat(self.config).st_mtime_ns, before)


class KeepsPreviousOutput(unittest.TestCase):
    def test_main_keeps_the_previous_output_when_the_cache_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, config, output = root / "models.json", root / "opencode.jsonc", root / "out/models.json"
            source.write_text(json.dumps(Trim().source()))
            config.write_text(json.dumps({"model": "ollama-cloud/pinned-old"}))
            args = ["--source", str(source), "--config", str(config), "--output", str(output)]
            self.assertEqual(catalog.main(args), 0)
            self.assertIn("pinned-old", json.loads(output.read_text())["ollama-cloud"]["models"])
            source.unlink()
            before = output.read_text()
            self.assertEqual(catalog.main(args), 0)
            self.assertEqual(output.read_text(), before)


if __name__ == "__main__":
    unittest.main()
