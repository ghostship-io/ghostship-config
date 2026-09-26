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
            )
            self.assertEqual(res, 1)
            self.assertEqual((self.state_dir / "applied").read_text().strip(), "hash1")
            self.assertTrue((self.state_dir / "restart.pending").exists())
            log_content = self.audit_log.read_text()
            self.assertIn("action=deployment-failed", log_content)



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
