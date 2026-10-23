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

    def test_current_repository_source_remains_readable_on_runtime_directory_runners(self):
        # CI's checkout is beneath /run; this exact import/read failed there.
        result, log = self.probe("from pathlib import Path; import unit_guard; assert Path(unit_guard.__file__).read_text(); assert Path(unit_guard.__file__).is_file()")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(log, '')

    def test_source_exception_is_read_only_and_does_not_allow_neighbor_state(self):
        result, log = self.probe("import unit_guard as g; g._source='/run/fixture-source'; assert not g.protected('/run/fixture-source/tests/example.py',source_reads=True); assert g.protected('/run/fixture-source/tests/example.py'); assert g.protected('/run/runtime.json',source_reads=True)")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(log, '')

    def test_runner_layout_allows_source_resolution_and_temp_cleanup_only(self):
        result, log = self.probe("""import os,tempfile
from pathlib import Path
import unit_guard as g
root=Path(os.environ['GHOSTSHIP_UNIT_ROOT'])
source=root/'runtime'/'checkout'
source.mkdir(parents=True)
fixture=source/'fixture.py'
fixture.write_text('fixture')
scratch=Path(tempfile.mkdtemp(dir='/tmp'))
(scratch/'file').write_text('temporary')
os.chdir(source)
g._source=str(source)
g._forbidden=(str(source.parent),)
assert fixture.resolve().read_text() == 'fixture'
import argparse
parser=argparse.ArgumentParser()
parser.add_argument('--state',default='firing')
parser.add_argument('--preferences',default=str(fixture))
parsed=parser.parse_args([])
assert parsed.state == 'firing'
assert parsed.preferences == str(fixture)
fd=os.open(scratch,os.O_RDONLY)
os.remove('file',dir_fd=fd)
os.close(fd)
scratch.rmdir()
try:
 fixture.write_text('must fail')
except PermissionError:
 pass
else:
 raise AssertionError('source mutation allowed')
""")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('host state access', log)

    def test_runtime_socket_alias_default_is_remapped_without_inspecting_host(self):
        result, log = self.probe("import argparse,os; p=argparse.ArgumentParser(); p.add_argument('--socket',default='/var/run/podman/podman.sock'); assert p.parse_args([]).socket.startswith(os.environ['GHOSTSHIP_UNIT_ROOT'])")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(log, '')
