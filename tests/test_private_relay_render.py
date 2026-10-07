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
                source.write_text('TUNNEL_ID=tunnel_'+'a'*32+'\nAPI_KEY=synthetic-one\n')
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
