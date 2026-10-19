import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from test_config import load

watch = load("t3code_provider_update_watch", "packages/t3code/provider-update-watch.py")


class ProviderUpdateWatch(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "tools"
        self.state = Path(self.temp.name) / "run" / "provider-watch.last"
        self.latest = {}

    def install(self, package, version):
        manifest = dict(watch.PROVIDERS)[package]
        path = self.root / manifest
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"name": package, "version": version}))
        self.latest.setdefault(package, version)

    def fetch(self, package):
        return self.latest[package]

    def run_check(self, start=None):
        start = start or Mock()
        return watch.check(self.root, self.state, start, self.fetch), start

    def test_current_providers_do_not_start_update(self):
        self.install("@openai/codex", "0.163.0")
        started, start = self.run_check()
        self.assertFalse(started)
        start.assert_not_called()

    def test_new_release_starts_update_once(self):
        self.install("@opencode/cli", "2.0.30")
        self.install("@openai/codex", "0.163.0")
        self.latest["@opencode/cli"] = "2.0.32"
        started, start = self.run_check()
        self.assertTrue(started)
        start.assert_called_once()
        self.assertEqual(self.state.read_text().strip(), "@opencode/cli:2.0.32")

        started, start = self.run_check()
        self.assertFalse(started)
        start.assert_not_called()

    def test_another_release_starts_update_again(self):
        self.install("@anthropic-ai/claude-code", "2.1.302")
        self.latest["@anthropic-ai/claude-code"] = "2.1.303"
        self.run_check()
        self.latest["@anthropic-ai/claude-code"] = "2.1.304"
        started, start = self.run_check()
        self.assertTrue(started)
        start.assert_called_once()

    def test_caught_up_clears_state_so_later_release_triggers(self):
        self.install("@xai-official/grok", "1.0.61")
        self.latest["@xai-official/grok"] = "1.0.62"
        self.run_check()
        self.install("@xai-official/grok", "1.0.62")
        self.run_check()
        self.assertFalse(self.state.exists())

    def test_failed_start_is_retried_next_run(self):
        self.install("@openai/codex", "0.162.0")
        self.latest["@openai/codex"] = "0.163.0"
        with self.assertRaises(RuntimeError):
            self.run_check(Mock(side_effect=RuntimeError("systemctl failed")))
        self.assertFalse(self.state.exists())
        started, _ = self.run_check()
        self.assertTrue(started)

    def test_missing_install_and_lookup_failure_are_skipped(self):
        self.install("@openai/codex", "0.162.0")
        self.install("@opencode/cli", "2.0.30")
        self.latest["@openai/codex"] = "0.163.0"

        def fetch(package):
            if package == "@opencode/cli":
                raise OSError("registry unavailable")
            return self.latest[package]

        found = watch.outdated(self.root, fetch)
        self.assertEqual(found, [("@openai/codex", "0.162.0", "0.163.0")])

    def test_newer_or_prerelease_install_is_not_behind(self):
        self.assertFalse(watch.is_behind("2.1.304", "2.1.303"))
        self.assertTrue(watch.is_behind("2.1.304-beta.1", "2.1.304"))
        self.assertFalse(watch.is_behind("2.1.304", "2.1.304-beta.1"))
        self.assertTrue(watch.is_behind("0.9.0", "0.10.0"))


class ProviderUpdateWatchSource(unittest.TestCase):
    def test_timer_is_wired_to_the_guarded_updater(self):
        source = (
            Path(__file__).resolve().parents[1] / "modules/self-hosted/t3code.nix"
        ).read_text()
        self.assertIn("packages/t3code/provider-update-watch.py", source)
        self.assertIn(
            "multi-user.target.wants/t3code-provider-update-watch.timer", source
        )
        self.assertEqual(watch.UPDATE_UNIT, "t3code-tool-auto-update.service")


if __name__ == "__main__":
    unittest.main()
