"""Post-merge real SDK and runtime closure invariance."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("nix"), "requires Nix evaluation")
class ImageIdentity(unittest.TestCase):
    def test_unrelated_source_and_agent_revision_do_not_change_runtime_or_images(self):
        expression = r'''
        let
          f = builtins.getFlake "path:__ROOT__";
          agent = f.inputs.ghostship-private-agent;
          pkgs = f.inputs.nixpkgs.legacyPackages.${builtins.currentSystem};
          other = agent // {
            rev = "unrelated-release";
            outPath = builtins.path {
              path = agent.outPath; name = "unrelated-agent-release";
              filter = path: _: !(builtins.elem (toString path) [ (toString agent.outPath + "/VERSION") (toString agent.outPath + "/README.md") ]);
            };
          };
          runtime = a: import __ROOT__/modules/self-hosted/agent-service-runtimes.nix {
            agent = a; system = builtins.currentSystem;
          };
          r = runtime agent;
          s = runtime other;
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
          hooks = [ (toString r.hooks) (toString s.hooks) ];
          coordinator = [ (toString r.coordinator) (toString s.coordinator) ];
          integrations = [ (toString r.integrations) (toString s.integrations) ];
          worker = [ (workerImage agent) (workerImage poison) ];
          ownConfig = [ (base "60000") (base "60001") ];
          workerOrdering = builtins.map (name: (workerModule agent).systemd.services.${name}.after)
            [ "ghostship-inference-bridge" "ghostship-inference-scheduler" ];
        }
        '''.replace('__ROOT__', str(ROOT))
        result = subprocess.run(['nix', 'eval', '--impure', '--json', '--expr', expression],
                                text=True, capture_output=True, check=True, timeout=60)
        data = json.loads(result.stdout)
        for name in ['hooks', 'coordinator', 'integrations', 'worker']:
            self.assertEqual(*data[name], name + ' depends on unrelated agent input')
        self.assertNotEqual(*data['ownConfig'])
        for after in data['workerOrdering']:
            self.assertIn('ghostship-runtime-ghostship-worker.service', after)
