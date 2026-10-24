"""Catch missing providers, stale evidence, lost ZDR config, and model-list filtering."""

import importlib.machinery
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DOCTOR = ROOT / "scripts/provider-zdr-doctor"
DOC = ROOT / "docs/provider-zdr.md"
POOL = ROOT / "modules/self-hosted/inference-pool.json"


def load_doctor():
    spec = importlib.util.spec_from_loader(
        "provider_zdr_doctor", importlib.machinery.SourceFileLoader("provider_zdr_doctor", str(DOCTOR))
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


doctor = load_doctor()


def settings(env=None):
    return {"providerInstances": {"commandCode": {"environment": env or []}}}


def route_config(*, zdr="1", api_key="{env:COMMAND_CODE_API_KEY}", enabled=("command-code",)):
    return json.dumps({"enabled_providers": list(enabled), "providers": {"command-code": {
        "name": "Command Code GOAT",
        "package": "@ai-sdk/openai-compatible",
        "settings": {"baseURL": "https://api.commandcode.ai/provider/v1",
                      "apiKey": api_key},
        "headers": {"x-cmd-zdr": zdr},
    }}})


class DocsTest(unittest.TestCase):
    def test_current_table_covers_every_required_provider(self):
        rows, checks = doctor.validate_docs(ROOT, max_age_days=45)
        self.assertEqual(len(rows), len(doctor.REQUIRED))
        self.assertFalse([check for check in checks if check.status == "fail"], checks)

    def test_missing_provider_is_a_failure(self):
        text = DOC.read_text().replace("| OpenRouter |", "| Removed Provider |")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "docs/provider-zdr.md").write_text(text)
            _, checks = doctor.validate_docs(root, max_age_days=45)
        names = {check.name for check in checks if check.status == "fail"}
        self.assertIn("docs.providers", names)

    def test_stale_and_future_dates_are_failures(self):
        text = DOC.read_text()
        old = (date.today() - timedelta(days=90)).isoformat()
        future = (date.today() + timedelta(days=1)).isoformat()
        text = text.replace("| 2026-10-24 |", f"| {old} |", 1)
        text = text.replace("| 2026-10-24 |", f"| {future} |", 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "docs/provider-zdr.md").write_text(text)
            _, checks = doctor.validate_docs(root, max_age_days=45)
        failures = [check for check in checks if check.status == "fail"]
        self.assertTrue(any("old" in check.detail for check in failures), failures)
        self.assertTrue(any("future" in check.detail for check in failures), failures)

    def test_private_identifier_is_rejected(self):
        text = DOC.read_text().replace(
            "Live read-back: five ZDR scopes",
            "someone@example.com live read-back: five ZDR scopes",
            1,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "docs/provider-zdr.md").write_text(text)
            _, checks = doctor.validate_docs(root, max_age_days=45)
        self.assertTrue(any(check.name.endswith(".private") for check in checks if check.status == "fail"))

    def test_missing_no_filter_statement_is_a_failure(self):
        text = DOC.read_text().replace(doctor.NO_FILTER_SENTENCE, "Model lists may be filtered.")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "docs/provider-zdr.md").write_text(text)
            _, checks = doctor.validate_docs(root, max_age_days=45)
        self.assertTrue(any(check.name == "docs.no-model-filter" and check.status == "fail" for check in checks))


class ConfigTest(unittest.TestCase):
    def test_command_code_requires_zdr_route_and_projected_key(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            (home / ".config/opencode").mkdir(parents=True)
            config = home / ".config/opencode/opencode.jsonc"
            projection = Path(directory) / "t3code.env"
            projection.write_text("COMMAND_CODE_API_KEY=" + "k" * 24 + "\n")
            config.write_text(route_config())
            self.assertEqual(doctor.check_command_code(home, projection, True).status, "pass")
            for label, text in [
                ("zdr off", route_config(zdr="0")),
                ("literal key", route_config(api_key="literal")),
                ("not enabled", route_config(enabled=("ollama-cloud",))),
            ]:
                with self.subTest(case=label):
                    config.write_text(text)
                    self.assertEqual(doctor.check_command_code(home, projection, True).status, "fail")
            config.write_text(route_config())
            projection.write_text("COMMAND_CODE_API_KEY=\n")
            self.assertEqual(doctor.check_command_code(home, projection, True).status, "fail")
            projection.unlink()
            self.assertEqual(doctor.check_command_code(home, projection, True).status, "fail")
            config.unlink()
            self.assertEqual(doctor.check_command_code(home, projection, False).status, "skip")

    def test_commented_jsonc_route_is_read(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            (home / ".config/opencode").mkdir(parents=True)
            config = home / ".config/opencode/opencode.jsonc"
            projection = Path(directory) / "t3code.env"
            projection.write_text("COMMAND_CODE_API_KEY=" + "k" * 24 + "\n")
            config.write_text("""{
  // OpenCode accepts comments and trailing commas.
  "enabled_providers": ["command-code",],
  "providers": {"command-code": {
    "settings": {"baseURL": "https://api.commandcode.ai/provider/v1",
                  "apiKey": "{env:COMMAND_CODE_API_KEY}",},
    "headers": {"x-cmd-zdr": "1"}, /* every request */
  }},
}
""")
            self.assertEqual(doctor.check_command_code(home, projection, True).status, "pass")

    def test_claude_privacy_env_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"env": {"DISABLE_TELEMETRY": "1"}}))
            self.assertEqual(doctor.check_claude(path, True).status, "fail")
            path.write_text(json.dumps({"env": {key: "1" for key in doctor.PRIVACY_ENV}}))
            self.assertEqual(doctor.check_claude(path, True).status, "pass")

    def test_grok_upload_and_sharing_are_checked(self):
        payload = {"settings": {"disable_codebase_upload": True, "sharing_enabled": False}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings_cache.json"
            path.write_text(json.dumps({"payload": json.dumps(payload)}))
            self.assertEqual(doctor.check_grok(path, True).status, "pass")
            payload["settings"]["sharing_enabled"] = True
            path.write_text(json.dumps({"payload": json.dumps(payload)}))
            self.assertEqual(doctor.check_grok(path, True).status, "fail")

    def test_pool_rejects_a_zdr_model_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pool.json"
            path.write_text(json.dumps({"providers": {"groq": {"enabled": True, "zdr_allowlist": ["x"]}}}))
            self.assertEqual(doctor.check_pool(path, True).status, "fail")
            path.write_text(json.dumps({"providers": {"groq": {"enabled": True, "free_only": True}}}))
            self.assertEqual(doctor.check_pool(path, True).status, "pass")


class BrowserTest(unittest.TestCase):
    class Result:
        returncode = 0

        def __init__(self, value):
            self.stdout = json.dumps({"ok": True, "result": value})

    def runner(self, values):
        def run(args, **kwargs):
            url = args[args.index("--url") + 1]
            return self.Result(values[url])

        return run

    def test_browser_checks_compare_the_account_read_back(self):
        values = {
            doctor.BROWSER_CHECKS["openrouter"][0]: {"switches": ["true"] * 5 + ["false"] * 5},
            doctor.BROWSER_CHECKS["groq"][0]: ["true", "true"],
            doctor.BROWSER_CHECKS["chatgpt"][0]: "false",
            doctor.BROWSER_CHECKS["mistral"][0]: ["false", "false"],
            doctor.BROWSER_CHECKS["claude"][0]: {"switches": [
                {"label": "Location metadata", "checked": "false"},
                {"label": "Help improve our AI models", "checked": "false"},
            ]},
            doctor.BROWSER_CHECKS["grok"][0]: ["false", "false"],
        }
        checks = doctor.run_browser_checks(doctor.BROWSER_CHECKS, self.runner(values))
        self.assertTrue(all(check.status == "pass" for check in checks), checks)

    def test_browser_drift_is_a_failure(self):
        values = {
            doctor.BROWSER_CHECKS["openrouter"][0]: {"switches": ["false"] * 10},
            doctor.BROWSER_CHECKS["groq"][0]: ["true", "false"],
            doctor.BROWSER_CHECKS["chatgpt"][0]: "true",
            doctor.BROWSER_CHECKS["mistral"][0]: ["true", "false"],
            doctor.BROWSER_CHECKS["claude"][0]: {"switches": [
                {"label": "Location metadata", "checked": "true"},
                {"label": "Help improve our AI models", "checked": "true"},
            ]},
            doctor.BROWSER_CHECKS["grok"][0]: ["true", "false"],
        }
        checks = doctor.run_browser_checks(doctor.BROWSER_CHECKS, self.runner(values))
        self.assertTrue(all(check.status == "fail" for check in checks), checks)


class AntigravityTest(unittest.TestCase):
    def test_panel_parser(self):
        self.assertEqual(doctor.antigravity_telemetry_state("Enable Telemetry             off"), "off")
        self.assertEqual(doctor.antigravity_telemetry_state("Enable Telemetry on"), "on")
        self.assertEqual(doctor.antigravity_telemetry_state("ENABLE TELEMETRY  OFF"), "off")
        self.assertIsNone(doctor.antigravity_telemetry_state("Search: telemetry"))

    def test_check_reads_the_panel_state(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            workspace = home / "workspace"
            workspace.mkdir()
            settings = home / ".gemini/antigravity-cli/settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps({"trustedWorkspaces": [str(workspace)]}))
            with patch("shutil.which", return_value="/usr/bin/agy"), \
                 patch.object(doctor, "_trusted_antigravity_workspace", return_value=workspace), \
                 patch.object(doctor, "_agy_config_panel", return_value="Enable Telemetry off"):
                self.assertEqual(doctor.check_antigravity(home, True).status, "pass")
            with patch("shutil.which", return_value="/usr/bin/agy"), \
                 patch.object(doctor, "_trusted_antigravity_workspace", return_value=workspace), \
                 patch.object(doctor, "_agy_config_panel", return_value="Enable Telemetry on"):
                self.assertEqual(doctor.check_antigravity(home, True).status, "fail")


class EndToEndTest(unittest.TestCase):
    def test_report_passes_with_live_files_and_fails_without_them(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            home = base / "home"
            (root / "docs").mkdir(parents=True)
            (root / "modules/self-hosted").mkdir(parents=True)
            shutil.copyfile(DOC, root / "docs/provider-zdr.md")
            shutil.copyfile(POOL, root / "modules/self-hosted/inference-pool.json")
            (home / ".config/opencode").mkdir(parents=True)
            (home / ".claude").mkdir(parents=True)
            (home / ".grok").mkdir(parents=True)
            (home / ".config/opencode/opencode.jsonc").write_text(route_config())
            projection = base / "t3code.env"
            projection.write_text("COMMAND_CODE_API_KEY=" + "k" * 24 + "\n")
            (home / ".claude/settings.json").write_text(
                json.dumps({"env": {key: "1" for key in doctor.PRIVACY_ENV}})
            )
            (home / ".grok/settings_cache.json").write_text(
                json.dumps({"payload": json.dumps({"settings": {
                    "disable_codebase_upload": True, "sharing_enabled": False}})})
            )
            report = doctor.build_report(root, home, 45, True, False,
                                         command_code_secrets=projection)
            self.assertTrue(report.ok(), report.as_dict())
            (home / ".claude/settings.json").unlink()
            report = doctor.build_report(root, home, 45, True, False)
            self.assertFalse(report.ok())
            self.assertTrue(any(check.name == "claude-privacy" and check.status == "fail" for check in report.checks))


if __name__ == "__main__":
    unittest.main()
