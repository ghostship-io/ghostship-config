"""The agent pin guard: a descendant passes, a sibling fails, and an explicit
approval line passes."""
import importlib.util
import os
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check-agent-pin.py"
spec = importlib.util.spec_from_file_location("check_agent_pin", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def git(repository, *arguments):
    result = subprocess.run(["git", "-C", str(repository), *arguments], check=True,
                            capture_output=True, text=True)
    return result.stdout


class PinGuardTests(unittest.TestCase):
    """Fixture repositories stand in for the agent repository."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.agent = self.root / "agent"
        self.agent.mkdir()
        git(self.agent, "init", "-q", "-b", "main")
        git(self.agent, "config", "user.email", "agent@ghostship.io")
        git(self.agent, "config", "user.name", "Agent")
        (self.agent / "line.txt").write_text("root\n")
        git(self.agent, "add", "line.txt")
        git(self.agent, "commit", "-q", "-m", "root")
        self.root_revision = git(self.agent, "rev-parse", "HEAD").strip()
        # The pinned revision, on the line the fleet follows.
        (self.agent / "line.txt").write_text("pinned\n")
        git(self.agent, "commit", "-q", "-am", "pinned")
        self.base = git(self.agent, "rev-parse", "HEAD").strip()
        # A descendant of the pinned revision.
        (self.agent / "line.txt").write_text("descendant\n")
        git(self.agent, "commit", "-q", "-am", "descendant")
        self.descendant = git(self.agent, "rev-parse", "HEAD").strip()
        # Another line, forked before the pinned revision: it does not descend
        # from the pinned one.
        git(self.agent, "checkout", "-q", "-b", "sibling", self.root_revision)
        (self.agent / "other.txt").write_text("sibling\n")
        git(self.agent, "add", "other.txt")
        git(self.agent, "commit", "-q", "-m", "sibling")
        self.sibling = git(self.agent, "rev-parse", "HEAD").strip()
        git(self.agent, "checkout", "-q", "main")

    def lock(self, revision):
        return {"nodes": {guard.INPUT: {"locked": {
            "type": "github", "owner": "example-org", "repo": "example-agent", "rev": revision}}}}

    def write_lock(self, name, revision):
        path = self.root / name
        path.write_text(json.dumps(self.lock(revision)))
        return path

    def run_check(self, head_revision, approvals=None):
        base_lock = self.write_lock("base.lock", self.base)
        head_lock = self.write_lock("head.lock", head_revision)
        arguments = [sys.executable, str(SCRIPT), "--base-lock", str(base_lock),
                     "--head-lock", str(head_lock), "--agent-repo", str(self.agent)]
        if approvals is not None:
            approval = self.root / "approvals"
            approval.write_text(approvals)
            arguments.extend(["--approvals", str(approval)])
        return subprocess.run(arguments, capture_output=True, text=True, timeout=60)

    def test_a_descendant_of_the_pinned_revision_passes(self):
        result = self.run_check(self.descendant)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("descends from", result.stdout)

    def test_a_sibling_of_the_pinned_revision_fails(self):
        result = self.run_check(self.sibling)
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not descend", result.stdout)
        self.assertIn("pin-regression-approved", result.stdout)

    def test_a_sibling_with_an_approved_reason_passes(self):
        result = self.run_check(self.sibling, "pin-regression-approved: the pinned line was merged upstream\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("approved", result.stdout)

    def test_an_approval_without_a_reason_does_not_pass(self):
        result = self.run_check(self.sibling, "pin-regression-approved:\n")
        self.assertEqual(result.returncode, 1)

    def test_an_unchanged_pin_passes(self):
        result = self.run_check(self.base)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("unchanged", result.stdout)

    def test_a_pin_without_a_comparable_source_fails(self):
        base_lock = self.write_lock("base.lock", self.base)
        head_lock = self.write_lock("head.lock", self.sibling)
        result = subprocess.run([sys.executable, str(SCRIPT), "--base-lock", str(base_lock),
                                 "--head-lock", str(head_lock)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 1)
        self.assertIn("unavailable", result.stdout)


class PullRequestEventTests(unittest.TestCase):
    """The CI path: the event payload, the two locks, and the commit messages."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.agent = self.root / "agent"
        self.agent.mkdir()
        git(self.agent, "init", "-q", "-b", "main")
        git(self.agent, "config", "user.email", "agent@ghostship.io")
        git(self.agent, "config", "user.name", "Agent")
        (self.agent / "line.txt").write_text("root\n")
        git(self.agent, "add", "line.txt")
        git(self.agent, "commit", "-q", "-m", "root")
        root_revision = git(self.agent, "rev-parse", "HEAD").strip()
        (self.agent / "line.txt").write_text("pinned\n")
        git(self.agent, "commit", "-q", "-am", "pinned")
        self.pinned = git(self.agent, "rev-parse", "HEAD").strip()
        git(self.agent, "checkout", "-q", "-b", "sibling", root_revision)
        (self.agent / "other.txt").write_text("sibling\n")
        git(self.agent, "add", "other.txt")
        git(self.agent, "commit", "-q", "-m", "sibling")
        self.sibling = git(self.agent, "rev-parse", "HEAD").strip()

        # The pull request's own repository, with a base branch and a head.
        self.repository = self.root / "nixos-config"
        self.repository.mkdir()
        git(self.repository, "init", "-q", "-b", "main")
        git(self.repository, "config", "user.email", "agent@ghostship.io")
        git(self.repository, "config", "user.name", "Agent")
        self.write_lock(self.repository / "flake.lock", self.pinned)
        git(self.repository, "add", "flake.lock")
        git(self.repository, "commit", "-q", "-m", "base")
        self.base_sha = git(self.repository, "rev-parse", "HEAD").strip()
        git(self.repository, "checkout", "-q", "-b", "feature")
        self.write_lock(self.repository / "flake.lock", self.sibling)
        git(self.repository, "commit", "-q", "-am", "move the pin")
        self.head_sha = git(self.repository, "rev-parse", "HEAD").strip()

    def write_lock(self, path, revision):
        path.write_text(json.dumps({"nodes": {guard.INPUT: {"locked": {
            "type": "git", "url": self.agent.as_uri(), "rev": revision}}}}))

    def event(self, body=""):
        payload = self.root / "event.json"
        payload.write_text(json.dumps({"pull_request": {
            "base": {"sha": self.base_sha}, "head": {"sha": self.head_sha}, "body": body}}))
        return payload

    def run_check(self, body="", commit_message=None):
        if commit_message is not None:
            git(self.repository, "commit", "-q", "--amend", "-m", commit_message)
            self.head_sha = git(self.repository, "rev-parse", "HEAD").strip()
        environment = {**os.environ, "GITHUB_EVENT_PATH": str(self.event(body))}
        return subprocess.run([sys.executable, str(SCRIPT)], cwd=self.repository, env=environment,
                              capture_output=True, text=True, timeout=60)

    def test_a_pull_request_that_moves_the_pin_to_a_sibling_fails(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not descend", result.stdout)

    def test_an_approved_pull_request_body_passes(self):
        result = self.run_check(body="pin-regression-approved: the pinned line was merged upstream\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("approved", result.stdout)

    def test_an_approved_commit_message_passes(self):
        result = self.run_check(commit_message="move the pin\n\npin-regression-approved: upstream merged it\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("approved", result.stdout)


class ApprovalTests(unittest.TestCase):
    def test_the_approval_line_needs_a_reason(self):
        self.assertEqual(guard.approval_reason("pin-regression-approved: the line moved"), "the line moved")
        self.assertIsNone(guard.approval_reason("pin-regression-approved:"))
        self.assertIsNone(guard.approval_reason("pin-regression-approved"))
        self.assertIsNone(guard.approval_reason("the pin was approved"))
        self.assertEqual(guard.approval_reason("notes\npin-regression-approved: upstream merged it\n"),
                         "upstream merged it")

    def test_the_pinned_revision_is_read_from_the_lock(self):
        lock = {"nodes": {guard.INPUT: {"locked": {"rev": "abc123"}}}}
        self.assertEqual(guard.pinned_revision(lock), "abc123")
        self.assertIsNone(guard.pinned_revision({"nodes": {}}))


if __name__ == "__main__":
    unittest.main()
