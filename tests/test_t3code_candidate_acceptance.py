"""Candidate acceptance creates only exact, production-preserving receipts."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "t3code_candidate_acceptance", ROOT / "packages/t3code/candidate-acceptance.py"
)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


class CandidateAcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        (self.state / "desired").write_text("generation-502")
        self.home = self.root / "home"
        self.home.mkdir()
        (self.home / "agent-config").write_text("fixture")
        self.archive = self.root / "image.tar"
        config = b'{"rootfs":{"diff_ids":["candidate"]}}'
        self.image_id = hashlib.sha256(config).hexdigest()
        with tarfile.open(self.archive, "w") as image:
            for name, content in (
                ("manifest.json", b'[{"Config":"config.json","RepoTags":["localhost/t3:test"]}]'),
                ("config.json", config),
            ):
                member = tarfile.TarInfo(name)
                member.size = len(content)
                image.addfile(member, io.BytesIO(content))
        self.commands = []

        def command(engine, *args, **kwargs):
            self.commands.append(tuple(args))
            if args[:1] == ("exec",) and args[2:4] == ("curl", "-fsS"):
                return Mock(returncode=0, stdout="ok")
            if args[:2] == ("inspect", "t3code-candidate-generation-502"):
                return Mock(returncode=0, stdout="true")
            return Mock(returncode=0, stdout="loaded localhost/t3:test")

        self.command = command
        self.identity = ["prod-id", "2026-10-25T00:00:00Z", 42, "13", "16"]

    def run_acceptance(self):
        with patch.object(acceptance, "command", side_effect=self.command), \
             patch.object(acceptance, "check_candidate", return_value={
                 name: True for name in acceptance.CHECKS
             }), \
             patch.object(acceptance.subprocess, "run", return_value=Mock(returncode=0)):
            return acceptance.accept(
                self.state, self.archive, "podman",
                "/run/t3code-podman-candidate/podman.sock", self.home,
                command_fn=self.command,
                identity_fn=lambda: self.identity,
            )

    def test_pass_writes_exact_receipt_and_removes_the_candidate(self):
        receipt = self.run_acceptance()
        path = self.state / "receipts/generation-502.json"
        self.assertEqual(json.loads(path.read_text()), receipt)
        self.assertEqual(receipt["deployment_id"], "generation-502")
        self.assertEqual(receipt["image_id"], self.image_id)
        self.assertEqual(receipt["candidate_name"], "t3code-candidate-generation-502")
        self.assertEqual(receipt["live_before"], receipt["live_after"])
        self.assertEqual(set(receipt["checks"]), set(acceptance.CHECKS))
        self.assertTrue(all(receipt["checks"].values()))
        self.assertIn(("rm", "--force", "--time", "10", receipt["candidate_name"]), self.commands)
        self.assertFalse(any("production" in str(command) for command in self.commands))
        self.assertFalse(any(command[:1] == ("stop",) for command in self.commands))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_a_failed_acceptance_never_leaves_an_approving_receipt(self):
        failing = {name: True for name in acceptance.CHECKS}
        failing["provider_turn"] = False
        with patch.object(acceptance, "command", side_effect=self.command), \
             patch.object(acceptance, "check_candidate", return_value=failing), \
             patch.object(acceptance.subprocess, "run", return_value=Mock(returncode=0)):
            with self.assertRaisesRegex(RuntimeError, "acceptance failed"):
                acceptance.accept(
                    self.state, self.archive, "podman",
                    "/run/t3code-podman-candidate/podman.sock", self.home,
                    command_fn=self.command,
                    identity_fn=lambda: self.identity,
                )
        self.assertFalse((self.state / "receipts/generation-502.json").exists())
        self.assertIn(("rm", "--force", "--time", "10", "t3code-candidate-generation-502"),
                      self.commands)

    def test_a_changed_production_identity_prevents_receipt_creation(self):
        observations = iter([self.identity, [*self.identity[:2], 99, *self.identity[3:]],
                             self.identity])
        with patch.object(acceptance, "command", side_effect=self.command), \
             patch.object(acceptance, "check_candidate", return_value={
                 name: True for name in acceptance.CHECKS
             }), \
             patch.object(acceptance.subprocess, "run", return_value=Mock(returncode=0)):
            with self.assertRaisesRegex(RuntimeError, "production T3 identity changed"):
                acceptance.accept(
                    self.state, self.archive, "podman",
                    "/run/t3code-podman-candidate/podman.sock", self.home,
                    command_fn=self.command,
                    identity_fn=lambda: next(observations),
                )
        self.assertFalse((self.state / "receipts/generation-502.json").exists())


if __name__ == "__main__":
    unittest.main()
