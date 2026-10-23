"""Fast Nix checks for container image and managed runtime boundaries."""
import json
import shutil
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("nix"), "requires Nix evaluation")
class ImageIdentity(unittest.TestCase):
    def test_worker_image_cannot_force_agent_packages_and_own_image_config_changes_identity(self):
        expression = r'''
        let
          f = builtins.getFlake "path:__ROOT__";
          agent = f.inputs.ghostship-private-agent;
          pkgs = f.inputs.nixpkgs.legacyPackages.${builtins.currentSystem};
          workerModule = a: (import __ROOT__/modules/self-hosted/free-worker.nix {
            inherit pkgs; inherit (pkgs) lib;
            inputs.ghostship-private-agent = a;
            config = {
              ghostship.privateIntegrations.enable = true;
              age.secrets.inference-bridge-token.path = "/run/token";
            };
          }).config.content;
          workerImage = a: (workerModule a).virtualisation.oci-containers.containers.ghostship-worker.imageFile.drvPath;
          # A poisoned package set proves the image cannot force any agent/tool
          # package, independently of how the upstream package is implemented.
          poison = { packages.${builtins.currentSystem} = throw "agent code entered worker image"; };
          base = uid: (import __ROOT__/modules/self-hosted/service-base-image.nix {
            inherit pkgs uid; name = "fixture-service";
          }).drvPath;
        in {
          worker = [ (workerImage agent) (workerImage poison) ];
          ownConfig = [ (base "60000") (base "60001") ];
          workerOrdering = builtins.map (name: (workerModule agent).systemd.services.${name}.after)
            [ "ghostship-inference-bridge" "ghostship-inference-scheduler" ];
        }
        '''.replace('__ROOT__', str(ROOT))
        result = subprocess.run(['nix', 'eval', '--impure', '--json', '--expr', expression],
                                text=True, capture_output=True, check=True, timeout=8)
        data = json.loads(result.stdout)
        for name in ['worker']:
            self.assertEqual(*data[name], name + ' depends on unrelated agent input')
        self.assertNotEqual(*data['ownConfig'])
        for after in data['workerOrdering']:
            self.assertIn('ghostship-runtime-ghostship-worker.service', after)
