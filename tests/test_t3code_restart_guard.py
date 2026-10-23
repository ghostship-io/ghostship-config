"""The T3 restart guard: a forced restart needs the owner's own instruction,
and a queued restart still waits for the idle probe."""
import contextlib
import importlib.util
import io
import json
import subprocess
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


class ForcedRestartTests(unittest.TestCase):
    def setUp(self):
        candidate_gate = patch.object(deployer, "require_candidate")
        candidate_gate.start()
        self.addCleanup(candidate_gate.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.state_dir = self.root / "state"
        self.home_dir = self.root / "home"
        self.audit_log = self.root / "audit.log"
        self.ledger = self.root / "ledger.jsonl"
        self.state_dir.mkdir(parents=True)
        self.home_dir.mkdir(parents=True)

    def run_tool(self, *arguments):
        output = io.StringIO()
        with patch.object(sys, "argv", ["t3code-deploy-when-idle", *arguments]), \
             patch("subprocess.run") as mock_run:
            with contextlib.redirect_stdout(output):
                result = deployer.main()
        return result, output.getvalue(), mock_run

    def test_a_forced_restart_without_the_owner_instruction_is_refused(self):
        result, output, mock_run = self.run_tool("--safe-restart", "--force")
        self.assertEqual(result, 2)
        self.assertIn("Refusing to force a T3 Code restart", output)
        self.assertIn("--owner-request", output)
        mock_run.assert_not_called()
        self.assertFalse(self.ledger.exists())

    def test_a_forced_restart_with_the_owner_instruction_is_logged(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append(list(command))
            if "inspect" in command:
                return Mock(returncode=0, stdout="container-id image-id 2026-10-22T00:00:00Z healthy\n")
            return Mock(returncode=0, stdout="")

        with patch.object(sys, "argv", ["t3code-deploy-when-idle", "--safe-restart", "--force",
                                        "--owner-request", "owner: deploy the reviewed change",
                                        "--restart-ledger", str(self.ledger),
                                        "--journal-bin", "/bin/true",
                                        "--audit-log", str(self.audit_log)]), \
             patch("subprocess.run", side_effect=fake_run):
            with contextlib.redirect_stdout(io.StringIO()):
                result = deployer.main()
        self.assertEqual(result, 0)
        self.assertTrue(any("restart" in " ".join(command) for command in calls))
        entries = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["reference"], "owner: deploy the reviewed change")
        self.assertEqual(entry["mode"], "forced")
        self.assertTrue(entry["time"])
        self.assertIn("user", entry["actor"])
        self.assertIn("host", entry["actor"])
        self.assertEqual(entry["pre"]["id"], "container-id")
        self.assertEqual(entry["post"]["id"], "container-id")
        self.assertIn("action=forced-restart", self.audit_log.read_text())

    def test_a_forced_restart_records_its_reference_in_the_journal(self):
        journal = self.root / "journal"
        journal.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> " + str(self.root / "journal.log") + "\n")
        journal.chmod(0o700)
        real_run = subprocess.run

        def fake_run(command, **kwargs):
            if str(journal) in command:
                return real_run(command, **kwargs)
            return Mock(returncode=0, stdout="id\n")

        with patch.object(sys, "argv", ["t3code-deploy-when-idle", "--safe-restart", "--force",
                                        "--owner-request", "activate the reviewed deployment",
                                        "--restart-ledger", str(self.ledger),
                                        "--journal-bin", str(journal),
                                        "--audit-log", str(self.audit_log)]), \
             patch("subprocess.run", side_effect=fake_run):
            with contextlib.redirect_stdout(io.StringIO()):
                result = deployer.main()
        self.assertEqual(result, 0)
        logged = (self.root / "journal.log").read_text()
        self.assertIn("activate the reviewed deployment", logged)
        self.assertIn("t3code-restart", logged)

    def test_a_queued_restart_does_not_restart_immediately(self):
        result, output, mock_run = self.run_tool("--safe-restart", "--state-dir", str(self.state_dir),
                                                 "--audit-log", str(self.audit_log))
        self.assertEqual(result, 0)
        self.assertTrue((self.state_dir / "restart.pending").exists())
        commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertFalse(any("restart" in " ".join(command) for command in commands))
        self.assertTrue(any("start" in " ".join(command) for command in commands))

    def test_a_queued_restart_defers_while_t3_code_is_busy(self):
        (self.state_dir / "restart.pending").write_text("2026-10-22T00:00:00Z\n")
        with patch("subprocess.run", side_effect=[Mock(returncode=0, stdout="active\n")]):
            result = deployer.run_deployment(
                state_dir=self.state_dir,
                home_dir=self.home_dir,
                audit_log=self.audit_log,
                idle_checker=Mock(return_value=False),
                healthy_waiter=Mock(),
                sleep_fn=Mock(),
                deployment_reader=Mock(return_value=""),
            )
        self.assertEqual(result, 0)
        self.assertIn("action=defer", self.audit_log.read_text())
        self.assertTrue((self.state_dir / "restart.pending").exists())


if __name__ == "__main__":
    unittest.main()
