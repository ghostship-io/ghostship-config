"""The codex canary preserves settings and refuses unexpected owners."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('provider_flake_setup', ROOT / 'packages/t3code/provider-flake-setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class ProviderFlakeSetup(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(os.environ, {'GHOSTSHIP_PROVIDER_EXECUTABLES': json.dumps({'codex': '/home/t3code/.local/bin/codex'})})
        patch.start()
        self.addCleanup(patch.stop)

    def test_codex_only_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            data = {'providerInstances': {'codex': {'driver': 'codex', 'config': {'binaryPath': 'codex', 'other': 1}},
                                          'opencode': {'driver': 'opencode', 'config': {'binaryPath': 'opencode'}}}}
            path.write_text(json.dumps(data)); path.chmod(0o600)
            setup.configure(path)
            data['providerInstances']['codex']['config']['binaryPath'] = '/usr/lib/ghostship-provider-launchers/codex'
            self.assertEqual(json.loads(path.read_text()), data)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            first = path.read_bytes(); setup.configure(path); self.assertEqual(path.read_bytes(), first)

    def test_candidate_without_codex_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'; path.write_text('{"providerInstances":{"opencode-free":{}}}')
            before = path.read_bytes(); setup.configure(path); self.assertEqual(path.read_bytes(), before)

    def test_settings_symlink_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'; target = Path(directory) / 'owner.json'
            target.write_text('{"providerInstances":{}}'); path.symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                setup.configure(path)
            self.assertTrue(path.is_symlink())
            self.assertEqual(target.read_text(), '{"providerInstances":{}}')

    def test_custom_binary_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            path.write_text('{"providerInstances":{"codex":{"driver":"codex","config":{"binaryPath":"/custom/codex"}}}}')
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'expected original'):
                setup.configure(path)
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
