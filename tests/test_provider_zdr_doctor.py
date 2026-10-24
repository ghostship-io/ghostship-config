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
    def test_command_code_requires_cmd_zdr(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps(settings([{"name": "CMD_ZDR", "value": "0"}])))
            self.assertEqual(doctor.check_command_code(path, True).status, "fail")
            path.write_text(json.dumps(settings([{"name": "CMD_ZDR", "value": "1"}])))
            self.assertEqual(doctor.check_command_code(path, True).status, "pass")

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
        }
        checks = doctor.run_browser_checks(doctor.BROWSER_CHECKS, self.runner(values))
        self.assertTrue(all(check.status == "pass" for check in checks), checks)

    def test_browser_drift_is_a_failure(self):
        values = {
            doctor.BROWSER_CHECKS["openrouter"][0]: {"switches": ["false"] * 10},
            doctor.BROWSER_CHECKS["groq"][0]: ["true", "false"],
            doctor.BROWSER_CHECKS["chatgpt"][0]: "true",
            doctor.BROWSER_CHECKS["mistral"][0]: ["true", "false"],
        }
        checks = doctor.run_browser_checks(doctor.BROWSER_CHECKS, self.runner(values))
        self.assertTrue(all(check.status == "fail" for check in checks), checks)


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
            (home / ".t3/userdata").mkdir(parents=True)
            (home / ".claude").mkdir(parents=True)
            (home / ".grok").mkdir(parents=True)
            (home / ".t3/userdata/settings.json").write_text(
                json.dumps(settings([{"name": "CMD_ZDR", "value": "1"}]))
            )
            (home / ".claude/settings.json").write_text(
                json.dumps({"env": {key: "1" for key in doctor.PRIVACY_ENV}})
            )
            (home / ".grok/settings_cache.json").write_text(
                json.dumps({"payload": json.dumps({"settings": {
                    "disable_codebase_upload": True, "sharing_enabled": False}})})
            )
            report = doctor.build_report(root, home, 45, True, False)
            self.assertTrue(report.ok(), report.as_dict())
            (home / ".claude/settings.json").unlink()
            report = doctor.build_report(root, home, 45, True, False)
            self.assertFalse(report.ok())
            self.assertTrue(any(check.name == "claude-privacy" and check.status == "fail" for check in report.checks))


if __name__ == "__main__":
    unittest.main()
