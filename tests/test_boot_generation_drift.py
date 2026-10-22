"""The boot generation drift check: a profile that no longer describes the
running system, so a reboot would revert the activation."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "modules/self-hosted/boot-generation-drift.py"
spec = importlib.util.spec_from_file_location("boot_generation_drift", SCRIPT)
drift = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drift)


class DriftTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.current = self.root / "current-system"
        self.profile = self.root / "system-profile"
        self.state = self.root / "state.json"
        self.notifications = self.root / "notifications"
        notify = self.root / "notify"
        notify.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> " + str(self.notifications) + "\n")
        notify.chmod(0o700)
        self.config = self.root / "config.json"
        self.config.write_text(json.dumps({
            "state": str(self.state),
            "notify": str(notify),
            "current": str(self.current),
            "profile": str(self.profile),
            "threshold": 600,
        }))

    def link(self, current, profile):
        for path in (self.current, self.profile):
            if path.is_symlink() or path.exists():
                path.unlink()
        for target in (current, profile):
            target.mkdir(exist_ok=True)
        self.current.symlink_to(current)
        self.profile.symlink_to(profile)

    def run_check(self, now=None):
        environment = {**os.environ}
        if now is not None:
            environment["GHOSTSHIP_DRIFT_NOW"] = str(now)
        result = subprocess.run([sys.executable, str(SCRIPT), "--config", str(self.config)],
                                env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def sent(self):
        if not self.notifications.exists():
            return []
        return [line for line in self.notifications.read_text().splitlines() if line]

    def test_matching_generations_never_alert(self):
        self.link(self.root / "store-a", self.root / "store-a")
        self.run_check()
        self.assertEqual(self.sent(), [])

    def test_a_drift_alerts_only_after_the_threshold(self):
        self.link(self.root / "store-a", self.root / "store-b")
        start = 1_700_000_000
        self.run_check(now=start)
        self.assertEqual(self.sent(), [])
        self.run_check(now=start + 599)
        self.assertEqual(self.sent(), [])
        self.run_check(now=start + 601)
        self.assertEqual(len(self.sent()), 1)
        self.assertIn("--dedupe boot-generation-drift", self.sent()[0])
        self.assertIn("--state firing", self.sent()[0])

    def test_the_alert_is_repeated_with_the_same_dedupe_key(self):
        self.link(self.root / "store-a", self.root / "store-b")
        start = 1_700_000_000
        self.run_check(now=start)
        self.run_check(now=start + 601)
        self.run_check(now=start + 1200)
        self.assertEqual(len(self.sent()), 2)
        for line in self.sent():
            self.assertIn("--dedupe boot-generation-drift", line)

    def test_a_recovered_generation_resolves_the_alert(self):
        self.link(self.root / "store-a", self.root / "store-b")
        start = 1_700_000_000
        self.run_check(now=start)
        self.run_check(now=start + 601)
        self.assertEqual(len(self.sent()), 1)
        self.current.unlink()
        self.link(self.root / "store-a", self.root / "store-a")
        self.run_check(now=start + 700)
        self.assertEqual(len(self.sent()), 2)
        self.assertIn("--state resolved", self.sent()[1])
        # The episode ends, so a later drift starts a new one.
        self.current.unlink()
        self.link(self.root / "store-a", self.root / "store-b")
        self.run_check(now=start + 800)
        self.assertEqual(len(self.sent()), 2)
        self.run_check(now=start + 1401)
        self.assertEqual(len(self.sent()), 3)
        self.assertIn("--state firing", self.sent()[2])

    def test_a_missing_generation_is_not_a_drift(self):
        self.profile.symlink_to(self.root / "store-b")
        self.run_check()
        self.assertEqual(self.sent(), [])


class ComparisonTests(unittest.TestCase):
    def test_the_comparison_reads_the_two_generation_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / "store-a"
            store.mkdir()
            current = root / "current-system"
            profile = root / "system-profile"
            current.symlink_to(store)
            profile.symlink_to(store)
            self.assertEqual(drift.read_generation(current), str(store))
            self.assertEqual(drift.read_generation(profile), str(store))
            self.assertFalse(drift.drifted(drift.read_generation(current),
                                           drift.read_generation(profile)))
            other = root / "store-b"
            other.mkdir()
            profile.unlink()
            profile.symlink_to(other)
            self.assertTrue(drift.drifted(drift.read_generation(current),
                                          drift.read_generation(profile)))
            self.assertIsNone(drift.read_generation(root / "missing"))
            self.assertFalse(drift.drifted(None, str(store)))
            self.assertFalse(drift.drifted(str(store), None))


if __name__ == "__main__":
    unittest.main()
