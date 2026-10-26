"""Offline credential projection validation and rotation, with synthetic keys."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('render', Path(__file__).resolve().parents[1] / 'modules/self-hosted/private-relay-render.py')
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)


class Render(unittest.TestCase):
    def test_missing_and_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'ghostship.env'
            source.write_text('')
            with patch.object(render, 'ROOT', root), patch.object(render.os, 'chown'), patch.object(render.grp, 'getgrnam') as group, patch.object(render.sys, 'argv', ['render', str(source), '/nix/store/fixed/bin/ghostship-mcp']):
                group.return_value.gr_gid = 62020
                with self.assertRaises(SystemExit): render.main()
                self.assertFalse((root/'ghostship.key').exists())
                source.write_text('TUNNEL_ID=tunnel_'+'a'*32+'\nAPI_KEY=synthetic-one\nHOME_POSTAL_CODE=12345\n')
                render.main()
                config = json.loads((root/'ghostship.yaml').read_text())
                self.assertEqual(config['control_plane']['api_key'], 'file:'+str(root/'ghostship.key'))
                self.assertEqual(config['mcp']['commands'][0]['command'], '/nix/store/fixed/bin/ghostship-mcp ghostship')
                # ChatGPT's connector omits notifications/initialized, so the
                # tunnel must supply it for the stateful stdio MCP child.
                self.assertTrue(config['mcp']['stdio_send_initialized_notification'])
                self.assertNotIn('synthetic', (root/'ghostship.yaml').read_text())
                self.assertEqual((root/'ghostship.key').stat().st_mode & 0o777, 0o400)
                self.assertFalse((root/'keep.yaml').exists())
                self.assertFalse((root/'amazon.yaml').exists())
                source.write_text(source.read_text().replace('synthetic-one', 'synthetic-rotated'))
                render.main()
                self.assertEqual((root/'ghostship.key').read_text(), 'synthetic-rotated')
                source.write_text('invalid')
                with self.assertRaises(SystemExit): render.main()
                self.assertEqual((root/'ghostship.key').read_text(), 'synthetic-rotated')


if __name__ == '__main__': unittest.main()

class HomePostalTests(unittest.TestCase):
    """The rendered runtime destination comes from private configuration (#463)."""

    def test_the_postal_code_comes_from_private_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            retail = Path(temporary) / 'retail.env'
            retail.write_text('COSTCO_POSTAL_CODE=12345\n')
            with patch.dict('os.environ', {'GHOSTSHIP_RETAIL_ENV': str(retail)}):
                self.assertEqual(render.home_postal({}), '12345')
                self.assertEqual(render.home_postal({'HOME_POSTAL_CODE': '54321'}), '54321')

    def test_a_missing_or_malformed_postal_code_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            retail = Path(temporary) / 'missing.env'
            with patch.dict('os.environ', {'GHOSTSHIP_RETAIL_ENV': str(retail)}):
                with self.assertRaises(SystemExit):
                    render.home_postal({})
                with self.assertRaises(SystemExit):
                    render.home_postal({'HOME_POSTAL_CODE': 'not-a-code'})

class NativeProjectionTests(unittest.TestCase):
    def test_native_mount_contains_the_rendered_key_and_rotates_it(self):
        """Regression: YAML alone left the official tunnel's file key absent."""
        import os
        import subprocess
        module = (Path(__file__).resolve().parents[1] /
                  'modules/self-hosted/private-integrations.nix').read_text()
        projection = module.split('          target=/run/ghostship-native-mcp\n', 1)[1].split("        '';", 1)[0]
        self.assertIn('-m 0400 -o 62020 -g 62020', projection)
        # Exercise the deployed shell projection unprivileged; only ownership
        # changes to this test account. Contents and restrictive modes are real.
        projection = projection.replace('-o root -g ghostship-mcp', '')
        projection = projection.replace('-o 62020 -g 62020', '')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / 'rendered', root / 'mounted'
            source.mkdir()
            canonical = root / 'native-grant'
            canonical.write_text('{"synthetic":"native-grant"}')
            (source / 'ghostship.yaml').write_text(json.dumps({
                'control_plane': {'api_key': 'file:/run/ghostship-integrations/ghostship.key'}}))
            projection = projection.replace('/run/ghostship-integrations/', str(source) + '/')
            for value in ('synthetic-first', 'synthetic-rotated'):
                (source / 'ghostship.key').write_text(value)
                subprocess.run(['sh', '-eu', '-c', projection], check=True,
                               env={**os.environ, 'target': str(target), 'canonical': str(canonical)},
                               timeout=2)
                config = json.loads((target / 'ghostship.yaml').read_text())
                key = target / Path(config['control_plane']['api_key'].removeprefix('file:')).name
                self.assertEqual(key.read_text(), value)
                for name in ('ghostship.key', 'ghostship.yaml', 't3-token'):
                    self.assertEqual((target / name).stat().st_mode & 0o777, 0o400)
                self.assertEqual(list(target.glob('*.new')), [])
                self.assertNotIn(value, (target / 'ghostship.yaml').read_text())
