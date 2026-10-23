"""The gate must reject host/network attempts, including caught failures and children."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

GUARD = Path(__file__).resolve().parents[1] / 'scripts/test-isolation'


class IsolationTests(unittest.TestCase):
    def probe(self, code):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'violations.log'
            result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                env={**os.environ, 'GHOSTSHIP_UNIT_ROOT': directory,
                     'GHOSTSHIP_UNIT_VIOLATIONS': str(log), 'PYTHONPATH': str(GUARD)}, timeout=5)
            return result, log.read_text() if log.exists() else ''

    def test_reads_writes_and_network_are_blocked_before_the_operation(self):
        for code, kind in (("open('/var/lib/ghostship-ai-usage/announced-resets.json')", 'host state'),
                           ("open('/run/ghostship-unit-fixture', 'w')", 'host state'),
                           ("import os; os.stat('/run/ghostship-unit-fixture')", 'host state'),
                           ("import sqlite3; sqlite3.connect('file:/var/lib/fixture.sqlite?mode=ro',uri=True)", 'host'),
                           ("import os; os.system('true')", 'unguarded'),
                           ("import socket; socket.create_connection(('127.0.0.1', 9))", 'network'),
                           ("import subprocess; subprocess.run(['ghostship-notify','--help'])", 'external')):
            with self.subTest(code=code):
                result, log = self.probe(code)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(kind, log)

    def test_catching_the_failure_still_leaves_gate_evidence(self):
        result, log = self.probe("try:\n open('/run/ghostship-unit-fixture')\nexcept OSError:\n pass")
        self.assertEqual(result.returncode, 0)
        self.assertIn('host state access', log)

    def test_python_child_with_an_explicit_environment_retains_the_guard(self):
        result, log = self.probe("import subprocess,sys; subprocess.run([sys.executable,'-c',\"open('/run/ghostship-unit-fixture')\"],env={})")
        self.assertEqual(result.returncode, 0)
        self.assertIn('host state access', log)

    def test_runtime_path_defaults_are_temporary_but_explicit_paths_are_not_rewritten(self):
        result, log = self.probe("import argparse,os; p=argparse.ArgumentParser(); p.add_argument('--state',default='/var/lib/example/state.json'); assert p.parse_args([]).state.startswith(os.environ['GHOSTSHIP_UNIT_ROOT']); assert p.parse_args(['--state','/run/example']).state == '/run/example'")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(log, '')
