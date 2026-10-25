"""Candidate-accepted T3 image changes restart without an activity gate."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "t3code_candidate_deployer", ROOT / "packages/t3code/deploy-when-idle.py")
deployer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployer)


class CandidateDeployment(unittest.TestCase):
    def test_active_container_restarts_immediately_after_candidate_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            home = root / "home"
            state.mkdir()
            home.mkdir()
            (state / "desired").write_text("target-image\n")
            (state / "applied").write_text("old-image\n")
            events = []

            def run(command, **kwargs):
                events.append(list(command))
                return Mock(returncode=0, stdout="active\n")

            with patch.object(deployer, "candidate_acceptor", create=True), \
                 patch.object(deployer, "require_candidate"), \
                 patch.object(deployer, "container_identity", return_value={"id": "container"}), \
                 patch.object(deployer, "live_inputs_match", return_value=True), \
                 patch.object(deployer.subprocess, "run", side_effect=run):
                result = deployer.run_deployment(
                    state, home, image_archive="target-image.tar",
                    candidate_acceptor=lambda *args, **kwargs: events.append(["candidate-accepted"]),
                    deployment_reader=lambda: "old-image",
                    health_reader=lambda: "healthy",
                    healthy_waiter=lambda: True,
                    tool_lock_acquirer=lambda: None,
                )

            self.assertEqual(result, 0)
            self.assertEqual(events[0], ["candidate-accepted"])
            self.assertEqual(events[1][:2], ["systemctl", "is-active"])
            self.assertEqual(events[2][:2], ["systemctl", "restart"])
            self.assertEqual((state / "applied").read_text().strip(), "target-image")

if __name__ == "__main__":
    unittest.main()
