"""The fast gate must reject slow modules and the wrong execution context."""
from contextlib import redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fast_unit_runner", ROOT / "scripts/check-unit.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class FastCheckTests(unittest.TestCase):
    def test_a_passing_module_over_budget_still_fails(self):
        loader = Mock()
        loader.discover.return_value = unittest.TestSuite()
        with redirect_stdout(io.StringIO()):
            self.assertFalse(runner.run_module(Path("test_fixture.py"), loader,
                unittest.TextTestRunner(stream=io.StringIO()), clock=iter((0, 11)).__next__))

    def test_nix_and_checkout_guards_run_before_tests(self):
        environment = dict(os.environ)
        environment.pop("IN_NIX_SHELL", None)
        result = subprocess.run(["bash", str(ROOT / "scripts/check")], cwd=ROOT,
                                env=environment, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Nix environment", result.stderr)
        result = subprocess.run(["bash", str(ROOT / "scripts/check")], cwd=ROOT.parent,
                                env={**environment, "IN_NIX_SHELL": "pure"},
                                capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("assigned checkout", result.stderr)

class DiffWhitespaceTests(unittest.TestCase):
    def test_committed_pr_diff_and_local_edits(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "scripts").mkdir()
            (repo / "scripts/check").write_bytes((ROOT / "scripts/check").read_bytes())
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            for key, value in (("user.name", "Fixture"), ("user.email", "fixture@example.invalid")):
                subprocess.run(["git", "config", key, value], cwd=repo, check=True)
            def git(*args):
                return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
            (repo / "sample").write_text("clean\n")
            git("add", ".")
            git("commit", "-qm", "base")
            base = git("rev-parse", "HEAD")
            (repo / "sample").write_text("bad \n")
            git("add", "sample")
            git("commit", "-qm", "change")
            head = git("rev-parse", "HEAD")
            bin_dir = repo / "bin"
            bin_dir.mkdir()
            for name in ("shellcheck", "actionlint", "python3", "timeout", "gitleaks"):
                stub = bin_dir / name
                stub.write_text("#!/bin/sh\nexit 0\n")
                stub.chmod(0o755)
            env = {**os.environ, "IN_NIX_SHELL": "pure", "PATH": f"{bin_dir}:{os.environ['PATH']}"}
            def check(*args):
                return subprocess.run(["bash", "scripts/check", *args], cwd=repo, env=env,
                                      capture_output=True, text=True, timeout=10)
            self.assertEqual(check().returncode, 0)  # clean checkout remains supported
            result = check(base, head)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("trailing whitespace", result.stdout)
            self.assertNotEqual(check("missing-base", head).returncode, 0)
            (repo / "sample").write_text("local \n")
            self.assertNotEqual(check().returncode, 0)
