"""MCP transport must survive ownership reconciliation of the coding home."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('nix'), 'Nix evaluator required')
class InferenceSocketMountTests(unittest.TestCase):
    def test_mcp_socket_is_independent_of_the_coding_home(self):
        # Evaluate the actual module's mount contract without a host, network,
        # nixpkgs or another repository. Unused service definitions stay lazy.
        expression = '''
          let m = import __MODULE__ {
            config.ghostship.privateIntegrations.enable = true;
            lib.mkIf = condition: value: if condition then value else {};
            pkgs = {}; inputs = {};
          };
          in m.config.virtualisation.oci-containers.containers.ghostship-private-integrations.volumes
        '''.replace('__MODULE__', str(ROOT / 'modules/self-hosted/inference-bridge.nix'))
        result = subprocess.run(['nix', 'eval', '--impure', '--json', '--expr', expression],
                                capture_output=True, text=True, check=True, timeout=5)
        mounts = json.loads(result.stdout)
        endpoint = '/run/ghostship-integrations/inference-socket'
        selected = [mount.split(':') for mount in mounts if mount.split(':')[1] == endpoint]
        self.assertEqual(len(selected), 1)
        source, _, access = selected[0]
        self.assertEqual(access, 'ro')
        self.assertNotIn('home', Path(source).parts,
                         'a coding-home chown can remove MCP access to the socket')
        self.assertEqual(Path(source).name, 'socket')
