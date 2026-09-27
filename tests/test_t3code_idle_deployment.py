import fcntl
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_config import load

deployer = load("t3code_deploy_when_idle", "packages/t3code/deploy-when-idle.py")


class TestT3CodeIdleDeployment(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.state_dir = self.root / "state"
        self.home_dir = self.root / "home"
        self.audit_log = self.root / "audit.log"
        self.state_dir.mkdir(parents=True)
        self.home_dir.mkdir(parents=True)

    def test_no_work_needed_when_desired_matches_applied_and_no_restart(self):
        (self.state_dir / "desired").write_text("hash1\n")
        (self.state_dir / "applied").write_text("hash1\n")

        with patch("subprocess.run") as mock_run:
            res = deployer.run_deployment(
                state_dir=self.state_dir,
                home_dir=self.home_dir,
                audit_log=self.audit_log,
            )
            self.assertEqual(res, 0)
            mock_run.assert_not_called()

    def test_defers_restart_when_container_is_busy_with_tasks(self):
        (self.state_dir / "desired").write_text("hash2\n")
        (self.state_dir / "applied").write_text("hash1\n")

        mock_is_active = Mock(return_value=Mock(returncode=0))
        mock_idle_checker = Mock(return_value=False)
        mock_wait_healthy = Mock()
        mock_sleep = Mock()

        with patch("subprocess.run", side_effect=[mock_is_active.return_value]):
            res = deployer.run_deployment(
                state_dir=self.state_dir,
                home_dir=self.home_dir,
                audit_log=self.audit_log,
                idle_checker=mock_idle_checker,
                healthy_waiter=mock_wait_healthy,
                sleep_fn=mock_sleep,
                deployment_reader=Mock(return_value=""),
            )
            self.assertEqual(res, 0)
            mock_idle_checker.assert_called_once()
            mock_sleep.assert_not_called()
            mock_wait_healthy.assert_not_called()
            self.assertEqual((self.state_dir / "applied").read_text().strip(), "hash1")
            self.assertFalse((self.state_dir / "applying").exists())
            log_content = self.audit_log.read_text()
            self.assertIn("action=defer", log_content)
            self.assertIn("reason=active-or-unknown", log_content)

    def test_defers_if_tasks_resume_during_idle_confirmation_window(self):
        (self.state_dir / "desired").write_text("hash2\n")
        (self.state_dir / "applied").write_text("hash1\n")

        mock_is_active = Mock(return_value=Mock(returncode=0))
        # Idle at first, but active on second check after sleep
        mock_idle_checker = Mock(side_effect=[True, False])
        mock_wait_healthy = Mock()
        mock_sleep = Mock()

        with patch("subprocess.run", side_effect=[mock_is_active.return_value]):
            res = deployer.run_deployment(
                state_dir=self.state_dir,
                home_dir=self.home_dir,
                audit_log=self.audit_log,
                confirm_idle_seconds=30,
                idle_checker=mock_idle_checker,
                healthy_waiter=mock_wait_healthy,
                sleep_fn=mock_sleep,
                deployment_reader=Mock(return_value=""),
            )
            self.assertEqual(res, 0)
            self.assertEqual(mock_idle_checker.call_count, 2)
            mock_sleep.assert_called_once_with(30)
            mock_wait_healthy.assert_not_called()
            self.assertEqual((self.state_dir / "applied").read_text().strip(), "hash1")
            log_content = self.audit_log.read_text()
            self.assertIn("action=idle-confirmation", log_content)
            self.assertIn("reason=activity-resumed", log_content)

    def test_applies_update_after_sustained_idle_and_healthy_verification(self):
        (self.state_dir / "desired").write_text("hash2\n")
        (self.state_dir / "applied").write_text("hash1\n")
        (self.state_dir / "restart.pending").write_text("user-request\n")

        mock_is_active = Mock(return_value=Mock(returncode=0))
        mock_restart = Mock(return_value=Mock(returncode=0))
        mock_idle_checker = Mock(return_value=True)
        mock_wait_healthy = Mock(return_value=True)
        mock_sleep = Mock()

        with patch("subprocess.run", side_effect=[mock_is_active.return_value, mock_restart.return_value]):
            res = deployer.run_deployment(
                state_dir=self.state_dir,
                home_dir=self.home_dir,
                audit_log=self.audit_log,
                confirm_idle_seconds=30,
                idle_checker=mock_idle_checker,
                healthy_waiter=mock_wait_healthy,
                sleep_fn=mock_sleep,
                deployment_reader=Mock(return_value=""),
            )
            self.assertEqual(res, 0)
            self.assertEqual(mock_idle_checker.call_count, 2)
            mock_sleep.assert_called_once_with(30)
            mock_wait_healthy.assert_called_once()
            self.assertEqual((self.state_dir / "applied").read_text().strip(), "hash2")
            self.assertFalse((self.state_dir / "applying").exists())
            self.assertFalse((self.state_dir / "restart.pending").exists())
            log_content = self.audit_log.read_text()
            self.assertIn("action=deployment-complete", log_content)

    def test_deployment_failure_preserves_previous_applied_and_pending(self):
        (self.state_dir / "desired").write_text("hash2\n")
        (self.state_dir / "applied").write_text("hash1\n")
        (self.state_dir / "restart.pending").write_text("user-request\n")

        mock_is_active = Mock(return_value=Mock(returncode=0))
        mock_restart = Mock(return_value=Mock(returncode=0))
        mock_idle_checker = Mock(return_value=True)
        # Container fails to become healthy
        mock_wait_healthy = Mock(return_value=False)
        mock_sleep = Mock()

        with patch("subprocess.run", side_effect=[mock_is_active.return_value, mock_restart.return_value]):
            res = deployer.run_deployment(
                state_dir=self.state_dir,
                home_dir=self.home_dir,
                audit_log=self.audit_log,
                confirm_idle_seconds=30,
                idle_checker=mock_idle_checker,
                healthy_waiter=mock_wait_healthy,
                sleep_fn=mock_sleep,
                deployment_reader=Mock(return_value=""),
            )
            self.assertEqual(res, 1)
            self.assertEqual((self.state_dir / "applied").read_text().strip(), "hash1")
            self.assertTrue((self.state_dir / "restart.pending").exists())
            log_content = self.audit_log.read_text()
            self.assertIn("action=deployment-failed", log_content)


    def test_adopts_running_deployment_without_restart(self):
        # After a reboot or a deploy whose health check timed out, the
        # container already runs the desired image.
        (self.state_dir / "desired").write_text("hash2\n")
        (self.state_dir / "applied").write_text("hash1\n")
        (self.state_dir / "applying").write_text("hash2\n")

        with patch("subprocess.run") as mock_run:
            res = deployer.run_deployment(
                state_dir=self.state_dir,
                home_dir=self.home_dir,
                audit_log=self.audit_log,
                idle_checker=Mock(side_effect=AssertionError("idle not needed")),
                deployment_reader=Mock(return_value="hash2"),
                health_reader=Mock(return_value="healthy"),
            )
            self.assertEqual(res, 0)
            mock_run.assert_not_called()
        self.assertEqual((self.state_dir / "applied").read_text().strip(), "hash2")
        self.assertFalse((self.state_dir / "applying").exists())
        self.assertIn("action=adopt-running", self.audit_log.read_text())

    def test_requested_restart_is_not_skipped_by_running_deployment(self):
        (self.state_dir / "desired").write_text("hash2\n")
        (self.state_dir / "applied").write_text("hash1\n")
        (self.state_dir / "restart.pending").write_text("user-request\n")
        reader = Mock(return_value="hash2")

        with patch("subprocess.run", return_value=Mock(returncode=0)):
            res = deployer.run_deployment(
                state_dir=self.state_dir,
                home_dir=self.home_dir,
                audit_log=self.audit_log,
                confirm_idle_seconds=0,
                idle_checker=Mock(return_value=True),
                healthy_waiter=Mock(return_value=True),
                sleep_fn=Mock(),
                deployment_reader=reader,
            )
        self.assertEqual(res, 0)
        reader.assert_not_called()
        self.assertIn("action=restart-container", self.audit_log.read_text())

    def test_defers_while_container_tool_maintenance_holds_lock(self):
        (self.state_dir / "desired").write_text("hash2\n")
        (self.state_dir / "applied").write_text("hash1\n")
        lock = self.home_dir / deployer.TOOL_LOCK
        lock.parent.mkdir(parents=True)
        holder = os.open(lock, os.O_CREAT | os.O_RDWR)
        fcntl.flock(holder, fcntl.LOCK_EX)
        self.addCleanup(os.close, holder)
        calls = []

        def fake_run(cmd, *args, **kwargs):
            calls.append(list(cmd))
            return Mock(returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            res = deployer.run_deployment(
                state_dir=self.state_dir,
                home_dir=self.home_dir,
                audit_log=self.audit_log,
                confirm_idle_seconds=0,
                idle_checker=Mock(return_value=True),
                healthy_waiter=Mock(return_value=True),
                sleep_fn=Mock(),
                deployment_reader=Mock(return_value=""),
            )
        self.assertEqual(res, 0)
        self.assertFalse(any(c[:2] == ["systemctl", "restart"] for c in calls))
        self.assertIn("reason=tool-maintenance", self.audit_log.read_text())

    def test_holds_tool_lock_across_container_restart(self):
        (self.state_dir / "desired").write_text("hash2\n")
        (self.state_dir / "applied").write_text("hash1\n")
        lock = self.home_dir / deployer.TOOL_LOCK
        lock.parent.mkdir(parents=True)
        held_during_restart = []

        def fake_run(cmd, *args, **kwargs):
            if list(cmd[:2]) == ["systemctl", "restart"]:
                probe = os.open(lock, os.O_RDWR)
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held_during_restart.append(False)
                except BlockingIOError:
                    held_during_restart.append(True)
                finally:
                    os.close(probe)
            return Mock(returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            res = deployer.run_deployment(
                state_dir=self.state_dir,
                home_dir=self.home_dir,
                audit_log=self.audit_log,
                confirm_idle_seconds=0,
                idle_checker=Mock(return_value=True),
                healthy_waiter=Mock(return_value=True),
                sleep_fn=Mock(),
                deployment_reader=Mock(return_value=""),
            )
        self.assertEqual(res, 0)
        self.assertEqual(held_during_restart, [True])
        self.assertEqual((self.state_dir / "applied").read_text().strip(), "hash2")

    def _tick(self, idle=True, healthy=False, running="hash2", health="unhealthy", restart_ok=True):
        calls = []

        def fake_run(cmd, *args, **kwargs):
            calls.append(list(cmd))
            if list(cmd[:2]) == ["systemctl", "restart"] and not restart_ok:
                raise deployer.subprocess.CalledProcessError(1, cmd)
            return Mock(returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            res = deployer.run_deployment(
                state_dir=self.state_dir,
                home_dir=self.home_dir,
                audit_log=self.audit_log,
                confirm_idle_seconds=0,
                idle_checker=Mock(return_value=idle),
                healthy_waiter=Mock(return_value=healthy),
                sleep_fn=Mock(),
                deployment_reader=Mock(return_value=running),
                health_reader=Mock(return_value=health),
            )
        restarted = any(c[:2] == ["systemctl", "restart"] for c in calls)
        return res, restarted

    def test_waits_for_starting_container_without_restart(self):
        (self.state_dir / "desired").write_text("hash2\n")
        (self.state_dir / "applied").write_text("hash1\n")
        res, restarted = self._tick(health="starting")
        self.assertEqual(res, 0)
        self.assertFalse(restarted)
        self.assertEqual((self.state_dir / "applied").read_text().strip(), "hash1")

    def test_unhealthy_running_image_retries_then_abandons(self):
        (self.state_dir / "desired").write_text("hash2\n")
        (self.state_dir / "applied").write_text("hash1\n")
        results = [self._tick() for _ in range(deployer.MAX_DEPLOY_ATTEMPTS)]
        self.assertEqual(results, [(1, True)] * deployer.MAX_DEPLOY_ATTEMPTS)
        self.assertIn("action=deployment-abandoned", self.audit_log.read_text())

        # No further restarts or failures until a new image is desired.
        self.assertEqual(self._tick(), (0, False))
        (self.state_dir / "desired").write_text("hash3\n")
        self.assertEqual(self._tick(running="hash2", healthy=True), (0, True))

    def test_cap_holds_when_broken_image_is_not_running(self):
        # A container that exits at start, or never replaced the old image.
        for running in ("", "hash1"):
            (self.state_dir / "desired").write_text("hash2\n")
            (self.state_dir / "applied").write_text("hash1\n")
            (self.state_dir / "failures").write_text(f"hash2 {deployer.MAX_DEPLOY_ATTEMPTS}\n")
            self.assertEqual(self._tick(running=running), (0, False))
            self.assertEqual(
                (self.state_dir / "failures").read_text().split(),
                ["hash2", str(deployer.MAX_DEPLOY_ATTEMPTS)],
            )

    def test_abandonment_is_logged_once(self):
        (self.state_dir / "desired").write_text("hash2\n")
        (self.state_dir / "applied").write_text("hash1\n")
        for _ in range(deployer.MAX_DEPLOY_ATTEMPTS + 2):
            self._tick(running="")
        self.assertEqual(self.audit_log.read_text().count("action=deployment-abandoned"), 1)

    def test_unhealthy_retry_still_respects_idle_gate(self):
        (self.state_dir / "desired").write_text("hash2\n")
        (self.state_dir / "applied").write_text("hash1\n")
        self.assertEqual(self._tick(idle=False), (0, False))
        self.assertIn("reason=active-or-unknown", self.audit_log.read_text())

    def test_failed_restart_command_counts_as_attempt(self):
        (self.state_dir / "desired").write_text("hash2\n")
        (self.state_dir / "applied").write_text("hash1\n")
        res, restarted = self._tick(running="", restart_ok=False)
        self.assertEqual((res, restarted), (1, True))
        self.assertEqual((self.state_dir / "failures").read_text().split(), ["hash2", "1"])

    def test_success_clears_failure_count(self):
        (self.state_dir / "desired").write_text("hash2\n")
        (self.state_dir / "applied").write_text("hash1\n")
        self._tick()
        self.assertTrue((self.state_dir / "failures").exists())
        self.assertEqual(self._tick(healthy=True), (0, True))
        self.assertFalse((self.state_dir / "failures").exists())
        self.assertEqual((self.state_dir / "applied").read_text().strip(), "hash2")

    def test_repeatedly_failing_requested_restart_is_dropped(self):
        (self.state_dir / "desired").write_text("hash1\n")
        (self.state_dir / "applied").write_text("hash1\n")
        (self.state_dir / "restart.pending").write_text("user-request\n")
        for _ in range(deployer.MAX_DEPLOY_ATTEMPTS):
            self.assertEqual(self._tick(running="hash1"), (1, True))
        self.assertFalse((self.state_dir / "restart.pending").exists())
        self.assertEqual(self._tick(running="hash1"), (0, False))


class TestIdleGateOnRetryAfterFailure(unittest.TestCase):
    """Regression: the idle gate must hold on every restart, including the
    retry tick after a deployment that failed health verification.

    A failed deployment leaves `applying == desired`. The gate condition must
    still consult the activity probe so a retry cannot restart the container
    while tasks are active.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.state_dir = self.root / "state"
        self.home_dir = self.root / "home"
        self.audit_log = self.root / "audit.log"
        self.state_dir.mkdir(parents=True)
        self.home_dir.mkdir(parents=True)

    def _run(self, idle, healthy):
        calls = []

        def fake_run(cmd, *args, **kwargs):
            calls.append(list(cmd))
            return Mock(returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            res = deployer.run_deployment(
                state_dir=self.state_dir,
                home_dir=self.home_dir,
                audit_log=self.audit_log,
                confirm_idle_seconds=0,
                idle_checker=Mock(return_value=idle),
                healthy_waiter=Mock(return_value=healthy),
                sleep_fn=Mock(),
                deployment_reader=Mock(return_value=""),
            )
        restarted = any(c[:2] == ["systemctl", "restart"] for c in calls)
        return res, restarted

    def test_retry_after_failed_deploy_defers_when_tasks_active(self):
        (self.state_dir / "desired").write_text("hash2\n")
        (self.state_dir / "applied").write_text("hash1\n")

        # First tick: confirmed idle, restart issued, health never verified.
        res1, restarted1 = self._run(idle=True, healthy=False)
        self.assertEqual(res1, 1)
        self.assertTrue(restarted1)
        self.assertTrue((self.state_dir / "applying").exists())

        # Second tick: tasks are now active. The retry must NOT restart.
        res2, restarted2 = self._run(idle=False, healthy=True)
        self.assertFalse(
            restarted2,
            "container restarted while tasks were active (idle gate bypassed)",
        )
        self.assertEqual(
            (self.state_dir / "applied").read_text().strip(), "hash1"
        )
        self.assertIn("action=defer", self.audit_log.read_text())


if __name__ == "__main__":
    unittest.main()
