"""Fast Nix checks for container image and managed runtime boundaries."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("nix"), "requires Nix evaluation")
class RuntimeIdentity(unittest.TestCase):
    def test_ingress_and_coordinator_code_changes_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = root / 'before'
            (before / 'lib').mkdir(parents=True)
            (before / 'lib/github-integration.nix').write_text('# builder fixture\n')
            code = before / 'tools/python/ghostship_github'
            code.mkdir(parents=True)
            (code / 'ingress.py').write_text('# ingress one\n')
            (code / 'coordinator.py').write_text('# coordinator one\n')
            bridge = before / 'tools/python/ghostship_t3'
            bridge.mkdir()
            (bridge / 'bridge.py').write_text('# bridge\n')
            for variant, filename in [('ingress', 'ingress.py'), ('coordinator', 'coordinator.py')]:
                shutil.copytree(before, root / variant)
                (root / variant / 'tools/python/ghostship_github' / filename).write_text('# changed\n')
            shutil.copytree(before, root / 'unrelated')
            (root / 'unrelated' / 'VERSION').write_text('new release\n')
            (root / 'unrelated' / 'README.md').write_text('unrelated docs\n')
            shutil.copytree(before, root / 'integrations')
            mcp = root / 'integrations' / 'tools/python/ghostship_mcp'
            mcp.mkdir()
            (mcp / 'server.py').write_text('# private code change\n')
            expression = r'''
            let
              f = builtins.getFlake "path:__ROOT__";
              r = name: import __ROOT__/modules/self-hosted/agent-service-sources.nix {
                agent.outPath = __FIXTURE__ + "/${name}";
                lib = f.inputs.nixpkgs.lib;
              };
            in builtins.map (name: { hooks = toString (r name).hooks; coordinator = toString (r name).coordinator; integrations = toString (r name).integrations; })
              [ "before" "ingress" "coordinator" "unrelated" "integrations" ]
            '''.replace('__ROOT__', str(ROOT)).replace('__FIXTURE__', json.dumps(str(root)))
            data = json.loads(subprocess.check_output(['nix', 'eval', '--impure', '--json', '--expr', expression],
                                                     text=True, timeout=5))
            self.assertNotEqual(data[0]['hooks'], data[1]['hooks'])
            self.assertEqual(data[0]['coordinator'], data[1]['coordinator'])
            self.assertEqual(data[0]['hooks'], data[2]['hooks'])
            self.assertNotEqual(data[0]['coordinator'], data[2]['coordinator'])
            self.assertEqual(data[0], data[3])
            self.assertEqual(data[0]['hooks'], data[4]['hooks'])
            self.assertEqual(data[0]['coordinator'], data[4]['coordinator'])
            self.assertNotEqual(data[0]['integrations'], data[4]['integrations'])

    def test_generated_publisher_cannot_propagate_a_stop_to_its_container(self):
        expression = r'''
        let
          f = builtins.getFlake "path:__ROOT__";
          system = f.inputs.nixpkgs.lib.nixosSystem {
            system = builtins.currentSystem;
            modules = [ __ROOT__/modules/self-hosted/container-runtimes.nix
              ({ pkgs, ... }: {
                system.stateVersion = "26.05";
                boot.isContainer = true;
                virtualisation.oci-containers.backend = "podman";
                virtualisation.oci-containers.containers.fixture.image = "fixture:base";
                ghostship.containerRuntimes.fixture.runtime = pkgs.writeShellScriptBin "start" "exit 0";
              }) ];
          };
          c = system.config;
        in {
          wants = c.systemd.services.podman-fixture.wants;
          after = c.systemd.services.podman-fixture.after;
          requires = c.systemd.services.podman-fixture.requires;
          bindsTo = c.systemd.services.podman-fixture.bindsTo;
          publisher = c.systemd.services.ghostship-runtime-fixture.script;
          container = c.systemd.services.podman-fixture.script;
        }
        '''.replace('__ROOT__', str(ROOT))
        result = subprocess.run(['nix', 'eval', '--impure', '--json', '--expr', expression],
                                text=True, capture_output=True, check=True, timeout=8)
        data = json.loads(result.stdout)
        unit = 'ghostship-runtime-fixture.service'
        self.assertIn(unit, data['wants'])
        self.assertIn(unit, data['after'])
        self.assertNotIn(unit, data['requires'] + data['bindsTo'])
        self.assertIn('nix copy --no-check-sigs', data['publisher'])
        self.assertIn('local?root=/var/lib/ghostship-container-runtimes/fixture/store', data['publisher'])
        self.assertIn('/store/nix:/nix:ro', data['container'])
        self.assertNotIn('-start', data['container'])
