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
