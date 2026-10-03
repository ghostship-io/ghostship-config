"""Offline credential projection validation and rotation, with synthetic keys."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('render', Path(__file__).resolve().parents[2] / 'modules/self-hosted/private-relay-render.py')
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)


class Render(unittest.TestCase):
    def test_missing_duplicate_and_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keep, amazon = root/'keep.env', root/'amazon.env'
            keep.write_text(''); amazon.write_text('')
            with patch.object(render, 'ROOT', root), patch.object(render.os, 'chown'), patch.object(render.grp, 'getgrnam') as group, patch.object(render.sys, 'argv', ['render', str(keep), str(amazon), '/nix/store/fixed/bin/ghostship-mcp']):
                group.return_value.gr_gid = 62020
                with self.assertRaises(SystemExit): render.main()
                self.assertFalse((root/'keep.key').exists())
                keep.write_text('TUNNEL_ID=tunnel_'+'a'*32+'\nAPI_KEY=synthetic-one\n')
                amazon.write_text(keep.read_text())
                with self.assertRaises(SystemExit): render.main()
                self.assertFalse((root/'keep.key').exists())
                amazon.write_text('TUNNEL_ID=tunnel_'+'b'*32+'\nAPI_KEY=synthetic-two\n')
                render.main()
                config = json.loads((root/'keep.yaml').read_text())
                self.assertEqual(config['control_plane']['api_key'], 'file:'+str(root/'keep.key'))
                self.assertNotIn('synthetic', (root/'keep.yaml').read_text())
                self.assertEqual((root/'keep.key').stat().st_mode & 0o777, 0o400)
                keep.write_text(keep.read_text().replace('synthetic-one', 'synthetic-rotated'))
                render.main()
                self.assertEqual((root/'keep.key').read_text(), 'synthetic-rotated')
                self.assertEqual((root/'amazon.key').read_text(), 'synthetic-two')
                amazon.write_text('invalid')
                with self.assertRaises(SystemExit): render.main()
                self.assertEqual((root/'keep.key').read_text(), 'synthetic-rotated')


if __name__ == '__main__': unittest.main()
