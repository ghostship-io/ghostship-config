"""Content-scoped MCP sources retain the transitive Python package closure."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('nix'), 'requires local pure Nix evaluation')
class SourceClosureTests(unittest.TestCase):
    def test_mcp_helpers_and_grant_profiles_survive_source_filtering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packages = ('mcp', 'registry', 'inference', 'runtime', 'browser', 'desktop',
                        'keep', 'hostops', 'services', 'health', 't3', 'sessions',
                        'delegation', 'deploy', 'github', 'worker', 'workflows')
            for name in packages:
                path = root / 'tools/python' / ('ghostship_' + name)
                path.mkdir(parents=True)
                (path / '__init__.py').touch()
            profiles = root / 'config/sandbox-profiles'
            profiles.mkdir(parents=True)
            (profiles / 'research.json').write_text('{}')
            (root / 'unrelated.txt').write_text('excluded')
            expression = r'''
              let
                prefix = a: b: builtins.substring 0 (builtins.stringLength a) b == a;
                lib = {
                  hasPrefix = prefix;
                  any = builtins.any;
                  removePrefix = a: b: if prefix a b then builtins.substring
                    (builtins.stringLength a) (builtins.stringLength b) b else b;
                };
                result = import __SOURCE__ { inherit lib; agent.outPath = __ROOT__; };
              in { packages = builtins.attrNames (builtins.readDir
                     (result.integrations + "/tools/python"));
                   profiles = builtins.pathExists (result.integrations + "/config/sandbox-profiles/research.json");
                   unrelated = builtins.pathExists (result.integrations + "/unrelated.txt"); }
            '''.replace('__SOURCE__', str(ROOT / 'modules/self-hosted/agent-service-sources.nix')).replace('__ROOT__', str(root))
            result = subprocess.run(['nix', 'eval', '--impure', '--json', '--expr', expression],
                                    capture_output=True, text=True, check=True, timeout=10)
            data = json.loads(result.stdout)
            self.assertEqual(set(data['packages']), {'ghostship_' + n for n in packages})
            self.assertTrue(data['profiles'])
            self.assertFalse(data['unrelated'])
