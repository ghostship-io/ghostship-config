"""The configuration drift check: the running system must match the system
profile, and its recorded configuration revision must not stay behind main.

These tests drive the real command against temporary Git remotes and a fake
running system, and pin the notification, the state retention, the explicit
failures and the guard that no build or switch command is ever run.
"""
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "modules/self-hosted/configuration-drift.py"
THRESHOLD = 86400
START = 1_700_000_000


class ConfigurationDriftTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.remote = self.root / "remote.git"
        self.work = self.root / "work"
        self.attempts = self.root / "attempts"
        self.fail_flag = self.root / "notify-fails"
        self.config_path = self.root / "config.json"
        self.revision_file = self.root / "running-revision"
        self.home = self.root / "home"
        self.cwd = self.root / "cwd"
        self.home.mkdir()
        self.cwd.mkdir()

        self.git("init", "--bare", "--quiet", str(self.remote))
        self.git("init", "--quiet", "-b", "main", str(self.work))
        self.git("remote", "add", "origin", str(self.remote), cwd=self.work)
        self.git("config", "user.name", "Test", cwd=self.work)
        self.git("config", "user.email", "test@example.invalid", cwd=self.work)

        self.running = self.root / "running-system"
        (self.running / "sw/bin").mkdir(parents=True)
        tool = self.running / "sw/bin/nixos-version"
        tool.write_text(
            "#!/bin/sh\n"
            'test "$1" = "--configuration-revision" || exit 2\n'
            f"cat {shlex.quote(str(self.revision_file))}\n"
        )
        tool.chmod(0o700)
        self.profile = self.root / "system-profile"
        self.profile.symlink_to(self.running)
        self.other_system = self.root / "other-system"
        self.other_system.mkdir()

        notify = self.root / "notify"
        notify.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$*\" >> {shlex.quote(str(self.attempts))}\n"
            f"test ! -e {shlex.quote(str(self.fail_flag))} || exit 1\n"
            "exit 0\n"
        )
        notify.chmod(0o700)
        self.notify = notify

        self.shim = self.root / "shim"
        self.shim.mkdir()
        self.guard = self.root / "commands.log"
        for name in ("nix", "nixos-rebuild", "nix-env", "nix-store", "systemctl",
                     "switch-to-configuration", "sudo", "podman"):
            shim = self.shim / name
            shim.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' \"$0 $*\" >> {shlex.quote(str(self.guard))}\n"
                "exit 42\n"
            )
            shim.chmod(0o700)

        self.config = {
            "state": str(self.root / "state"),
            "notify": str(self.notify),
            "git": "git",
            "remote": str(self.remote),
            "branch": "main",
            "running_system": str(self.running),
            "profile": str(self.profile),
            "threshold": THRESHOLD,
        }
        self.write_config()
        self.first = self.commit("first")
        self.set_running(self.first)

    # -- helpers ---------------------------------------------------------

    def git(self, *arguments, cwd=None, check=True):
        result = subprocess.run(["git", *arguments], cwd=cwd, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise AssertionError(f"git {' '.join(arguments)} failed: {result.stderr}")
        return result

    def commit(self, message):
        (self.work / "content").write_text(message)
        self.git("-c", "core.hooksPath=/dev/null", "add", "content", cwd=self.work)
        self.git("-c", "core.hooksPath=/dev/null", "commit", "--quiet",
                 "-m", message, cwd=self.work)
        revision = self.git("rev-parse", "HEAD", cwd=self.work).stdout.strip()
        self.git("push", "--quiet", "origin", "main", cwd=self.work)
        return revision

    def push_main(self, revision):
        self.git("push", "--quiet", "--force", "origin", f"{revision}:main", cwd=self.work)

    def set_running(self, revision):
        self.revision_file.write_text(revision if revision is not None else "")

    def write_config(self):
        self.config_path.write_text(json.dumps(self.config))

    def run_check(self, now=None):
        environment = {**os.environ}
        environment["PATH"] = str(self.shim) + os.pathsep + environment.get("PATH", "")
        environment["HOME"] = str(self.home)
        if now is not None:
            environment["GHOSTSHIP_CONFIGURATION_DRIFT_NOW"] = str(now)
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--config", str(self.config_path)],
            cwd=self.cwd,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def sent(self):
        if not self.attempts.exists():
            return []
        return [line for line in self.attempts.read_text().splitlines() if line]

    def state(self):
        path = Path(self.config["state"]) / "state.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text())

    def assert_quiet_success(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)

    # -- the revision threshold ------------------------------------------

    def test_up_to_date_revision_is_quiet(self):
        self.assert_quiet_success(self.run_check(now=START))
        self.assertEqual(self.sent(), [])
        self.assertEqual(self.state(), {})

    def test_behind_for_exactly_one_day_does_not_alert(self):
        self.commit("second")
        self.assert_quiet_success(self.run_check(now=START))
        self.assert_quiet_success(self.run_check(now=START + THRESHOLD))
        self.assertEqual(self.sent(), [])
        self.assertEqual(self.state()["first_observed_behind"], START)

    def test_behind_for_more_than_one_day_alerts(self):
        self.commit("second")
        self.assert_quiet_success(self.run_check(now=START))
        self.assert_quiet_success(self.run_check(now=START + THRESHOLD + 1))
        self.assertEqual(len(self.sent()), 1)
        line = self.sent()[0]
        self.assertIn("--topic security", line)
        self.assertIn("--source configuration", line)
        self.assertIn("--state firing", line)
        self.assertIn("--dedupe configuration-drift-revision", line)
        self.assertNotIn("--incident", line)
        self.assertEqual(self.state()["first_observed_behind"], START)

    def test_main_advancing_keeps_the_first_observation(self):
        self.commit("second")
        self.assert_quiet_success(self.run_check(now=START))
        tip = self.commit("third")
        self.assert_quiet_success(self.run_check(now=START + THRESHOLD + 1))
        self.assertEqual(len(self.sent()), 1)
        self.assertEqual(self.state()["first_observed_behind"], START)
        self.assertEqual(self.state()["main_revision"], tip)

    def test_convergence_clears_the_observation(self):
        self.commit("second")
        self.assert_quiet_success(self.run_check(now=START))
        self.assert_quiet_success(self.run_check(now=START + THRESHOLD + 1))
        self.assertEqual(len(self.sent()), 1)

        tip = self.git("rev-parse", "HEAD", cwd=self.work).stdout.strip()
        self.set_running(tip)
        self.assert_quiet_success(self.run_check(now=START + 90_000))
        self.assertEqual(len(self.sent()), 1)
        self.assertEqual(self.state(), {})

        self.commit("fourth")
        self.assert_quiet_success(self.run_check(now=START + 90_000))
        self.assertEqual(len(self.sent()), 1)
        self.assertEqual(self.state()["first_observed_behind"], START + 90_000)
        self.assert_quiet_success(self.run_check(now=START + 90_000 + THRESHOLD + 1))
        self.assertEqual(len(self.sent()), 2)

    def test_a_new_running_revision_starts_a_fresh_observation(self):
        self.commit("second")
        second = self.git("rev-parse", "HEAD", cwd=self.work).stdout.strip()
        self.commit("third")
        self.assert_quiet_success(self.run_check(now=START))
        self.assert_quiet_success(self.run_check(now=START + THRESHOLD + 1))
        self.assertEqual(len(self.sent()), 1)

        self.set_running(second)
        self.assert_quiet_success(self.run_check(now=START + THRESHOLD + 2))
        self.assertEqual(len(self.sent()), 1)
        self.assertEqual(self.state()["first_observed_behind"], START + THRESHOLD + 2)
        self.assert_quiet_success(self.run_check(now=START + 2 * THRESHOLD + 2))
        self.assertEqual(len(self.sent()), 1)
        self.assert_quiet_success(self.run_check(now=START + 2 * THRESHOLD + 3))
        self.assertEqual(len(self.sent()), 2)

    def test_a_running_revision_ahead_of_main_does_not_alert(self):
        second = self.commit("second")
        self.set_running(second)
        self.assert_quiet_success(self.run_check(now=START))
        self.push_main(self.first)
        self.assert_quiet_success(self.run_check(now=START + THRESHOLD + 1))
        self.assertEqual(self.sent(), [])
        self.assertEqual(self.state(), {})

    # -- generation drift -------------------------------------------------

    def test_a_generation_mismatch_alerts_without_waiting(self):
        self.profile.unlink()
        self.profile.symlink_to(self.other_system)
        self.assert_quiet_success(self.run_check(now=START))
        self.assertEqual(len(self.sent()), 1)
        line = self.sent()[0]
        self.assertIn("--topic security", line)
        self.assertIn("--dedupe configuration-drift-generation", line)
        self.assertNotIn("--incident", line)
        self.assertEqual(self.state(), {})

    def test_a_missing_profile_symlink_is_an_error(self):
        self.profile.unlink()
        result = self.run_check(now=START)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("profile", result.stderr)
        self.assertEqual(self.sent(), [])

    # -- explicit errors, never health -----------------------------------

    def test_a_missing_running_revision_is_an_error(self):
        self.revision_file.unlink()
        result = self.run_check(now=START)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown", result.stderr)
        self.assertNotIn("revision:", result.stdout)
        self.assertEqual(self.sent(), [])

    def test_a_dirty_running_revision_is_an_error(self):
        self.set_running("dirty")
        result = self.run_check(now=START)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("dirty", result.stderr)
        self.assertNotIn("revision:", result.stdout)
        self.assertEqual(self.sent(), [])

    def test_a_fetch_failure_is_an_error(self):
        self.config["remote"] = str(self.root / "missing.git")
        self.write_config()
        result = self.run_check(now=START)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fetch", result.stderr)
        self.assertEqual(self.sent(), [])

    def test_unrelated_histories_are_an_error(self):
        self.assert_quiet_success(self.run_check(now=START))

        other_remote = self.root / "other.git"
        other_work = self.root / "other-work"
        self.git("init", "--bare", "--quiet", str(other_remote))
        self.git("init", "--quiet", "-b", "main", str(other_work))
        self.git("remote", "add", "origin", str(other_remote), cwd=other_work)
        self.git("config", "user.name", "Test", cwd=other_work)
        self.git("config", "user.email", "test@example.invalid", cwd=other_work)
        (other_work / "content").write_text("unrelated")
        self.git("-c", "core.hooksPath=/dev/null", "add", "content", cwd=other_work)
        self.git("-c", "core.hooksPath=/dev/null", "commit", "--quiet",
                 "-m", "unrelated", cwd=other_work)
        self.git("push", "--quiet", "origin", "main", cwd=other_work)

        self.config["remote"] = str(other_remote)
        self.write_config()
        result = self.run_check(now=START + THRESHOLD + 1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unrelated", result.stderr)
        self.assertEqual(self.sent(), [])

    def test_a_delivery_failure_is_nonzero_and_retries(self):
        self.commit("second")
        self.assert_quiet_success(self.run_check(now=START))
        self.fail_flag.write_text("")
        result = self.run_check(now=START + THRESHOLD + 1)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.sent()), 1)
        self.assertEqual(self.state()["first_observed_behind"], START)

        self.fail_flag.unlink()
        self.assert_quiet_success(self.run_check(now=START + THRESHOLD + 2))
        self.assertEqual(len(self.sent()), 2)

    # -- the read-only guard ---------------------------------------------

    def test_no_build_switch_or_service_command_is_run(self):
        self.commit("second")
        before = sorted(str(path) for path in self.running.rglob("*"))
        self.assert_quiet_success(self.run_check(now=START))
        self.assert_quiet_success(self.run_check(now=START + THRESHOLD + 1))
        self.assertEqual(len(self.sent()), 1)

        self.assertFalse(self.guard.exists(), self.guard.read_text() if self.guard.exists() else "")
        self.assertEqual(sorted(str(path) for path in self.running.rglob("*")), before)
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertEqual(list(self.cwd.iterdir()), [])
        self.assertEqual(self.git("status", "--porcelain", cwd=self.work).stdout, "")
        allowed = {"state.json", "repository.git"}
        self.assertLessEqual({path.name for path in Path(self.config["state"]).iterdir()}, allowed)


if __name__ == "__main__":
    unittest.main()
