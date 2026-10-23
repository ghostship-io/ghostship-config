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


    def test_coordinator_uses_shared_import_closure_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('github','t3','sessions'):
                folder=root/'tools/python'/('ghostship_'+name)
                folder.mkdir(parents=True)
                (folder/'__init__.py').touch()
            (root/'tools/python/ghostship_github/ingress.py').touch()
            (root/'lib').mkdir()
            (root/'lib/coordinator-python-packages.nix').write_text(
                '[ "ghostship_github" "ghostship_t3" "ghostship_sessions" ]')
            (root/'config/agents').mkdir(parents=True)
            (root/'config/agents/runtime-policy.json').write_text('{}')
            expression = r'''
              let
                prefix = a: b: builtins.substring 0 (builtins.stringLength a) b == a;
                lib = {
                  hasPrefix = prefix; any = builtins.any; filter = builtins.filter;
                  hasSuffix = a: b: let n = builtins.stringLength b - builtins.stringLength a;
                    in n >= 0 && builtins.substring n (builtins.stringLength a) b == a;
                  removePrefix = a: b: if prefix a b then builtins.substring
                    (builtins.stringLength a) (builtins.stringLength b) b else b;
                };
                result = import __SOURCE__ { inherit lib; agent.outPath = __ROOT__; };
              in { sessions = builtins.pathExists (result.coordinator + "/tools/python/ghostship_sessions/__init__.py");
                   policy = builtins.pathExists (result.coordinator + "/config/agents/runtime-policy.json");
                   inventory = builtins.pathExists (result.coordinator + "/lib/coordinator-python-packages.nix");
                   ingress = builtins.pathExists (result.coordinator + "/tools/python/ghostship_github/ingress.py"); }
            '''.replace('__SOURCE__',str(ROOT/'modules/self-hosted/agent-service-sources.nix')).replace('__ROOT__',str(root))
            result=subprocess.run(['nix','eval','--impure','--json','--expr',expression],
                                  capture_output=True,text=True,check=True,timeout=10)
            self.assertEqual(json.loads(result.stdout),
                             {'sessions':True,'policy':True,'inventory':True,'ingress':False})
