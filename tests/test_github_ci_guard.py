"""The host hook refuses a foreign source even if its workflow removes its if."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "modules/self-hosted/github-ci-guard.py"


class RunnerSourceGuardTests(unittest.TestCase):
    def test_host_hook_admits_only_verified_repository_sources(self):
        repository = "example/project"
        def payload(head=repository, base=repository):
            return {"repository": {"full_name": repository}, "pull_request": {
                "base": {"repo": {"full_name": base}},
                "head": {"repo": {"full_name": head}}}}

        cases = [
            ("same", "pull_request", payload(), repository, True),
            ("foreign", "pull_request", payload("external/fork"), repository, False),
            ("wrong-base", "pull_request", payload(base="external/fork"), repository, False),
            ("wrong-binding", "pull_request", payload(), "other/project", False),
            ("missing", "pull_request", {}, repository, False),
            ("null-head", "pull_request", {**payload(), "pull_request": {"head": None}}, repository, False),
            ("unknown-event", "push", payload(), repository, False),
            ("dispatch", "workflow_dispatch", {"repository": {"full_name": repository}}, repository, True),
            ("wrong-dispatch", "workflow_dispatch", {"repository": {"full_name": "external/fork"}}, repository, False),
        ]
        with tempfile.TemporaryDirectory() as directory:
            event_path = Path(directory) / "event.json"
            marker = Path(directory) / "untrusted-step"
            for name, event, value, bound, permitted in cases:
                with self.subTest(name=name):
                    event_path.write_text(json.dumps(value))
                    environment = dict(os.environ, GITHUB_EVENT_PATH=str(event_path),
                                       GITHUB_REPOSITORY=bound, GITHUB_EVENT_NAME=event)
                    result = subprocess.run([sys.executable, "-I", "-S", str(GUARD), repository],
                                            env=environment, capture_output=True, text=True)
                    # The runner stops on a failed hook before any workflow step.
                    if result.returncode == 0:
                        marker.write_text("workflow step")
                    self.assertEqual(marker.exists(), permitted, result.stderr)
                    marker.unlink(missing_ok=True)
                    if not permitted:
                        self.assertNotIn("external/fork", result.stderr)

    def test_missing_or_malformed_payload_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"
            environment = dict(os.environ, GITHUB_EVENT_PATH=str(path),
                               GITHUB_REPOSITORY="example/project", GITHUB_EVENT_NAME="pull_request")
            for content in (None, "invalid", "null", "[]"):
                with self.subTest(content=content):
                    if content is not None:
                        path.write_text(content)
                    result = subprocess.run([sys.executable, "-I", "-S", str(GUARD), "example/project"],
                                            env=environment, capture_output=True)
                    self.assertNotEqual(result.returncode, 0)
