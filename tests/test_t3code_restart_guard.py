"""A T3 restart proceeds immediately after candidate image acceptance."""
import contextlib
import fcntl
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "t3code_deploy_when_idle_guard", ROOT / "packages/t3code/deploy-when-idle.py")
deployer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployer)


class CandidateRestartTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.state_dir = self.root / "state"
        self.home_dir = self.root / "home"
        self.state_dir.mkdir()
        self.home_dir.mkdir()

    def test_immediate_restart_requires_candidate_acceptance_but_no_owner_words(self):
        calls = []
        def fake_run(command, **kwargs):
            calls.append(list(command))
            return Mock(returncode=0, stdout="")
        with patch.object(sys, "argv", ["t3code-deploy-when-idle", "--safe-restart", "--force",
                                        "--image-archive", str(self.root / "image.tar"),
                                        "--state-dir", str(self.state_dir),
                                        "--restart-ledger", str(self.root / "ledger"),
                                        "--journal-bin", "/bin/true"]), \
             patch.object(deployer, "produce_candidate_receipt"), \
             patch.object(deployer, "require_candidate"), \
             patch.object(deployer, "container_identity", return_value={"id": "candidate"}), \
             patch.object(deployer, "live_inputs_match", return_value=True), \
             patch("subprocess.run", side_effect=fake_run), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(deployer.main(), 0)
        self.assertTrue(any(command[:2] == ["systemctl", "restart"] for command in calls))
        entry = json.loads((self.root / "ledger").read_text())
        self.assertEqual(entry["mode"], "candidate-accepted")
        self.assertNotIn("reference", entry)

    def test_candidate_acceptance_cli_emits_the_verified_receipt(self):
        receipt = {"verified": True, "deployment_id": "target", "image_id": "image",
                   "checks": {name: True for name in (
                       "app_ready", "provider_turn", "agent_cli", "skills", "desktop_transport")}}
        def accept_while_locked(*_args, **_kwargs):
            competing_fd = os.open(self.state_dir / "deploy.lock", os.O_RDWR)
            try:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(competing_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(competing_fd)

        with patch.object(sys, "argv", ["t3code-deploy-when-idle", "--accept-candidate", "--json",
                                        "--state-dir", str(self.state_dir),
                                        "--image-archive", str(self.root / "image.tar"),
                                        "--expected-deployment-id", "target"]), \
             patch.object(deployer, "produce_candidate_receipt", side_effect=accept_while_locked), \
             patch.object(deployer, "verify_candidate_receipt", return_value=receipt), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(deployer.main(), 0)
        self.assertEqual(json.loads(output.getvalue()), receipt)
        competing_fd = os.open(self.state_dir / "deploy.lock", os.O_RDWR)
        try:
            fcntl.flock(competing_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(competing_fd, fcntl.LOCK_UN)
        finally:
            os.close(competing_fd)

if __name__ == "__main__":
    unittest.main()
