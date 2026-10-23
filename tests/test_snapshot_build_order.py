"""Snapshot startup must not race the desktop's storage-locking image build."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SnapshotBuildOrderTests(unittest.TestCase):
    def service(self, desktop):
        containers = '{ agent-desktop = {}; }' if desktop else '{}'
        expression = '''let
          module = import %s {
            config.virtualisation.oci-containers.containers = %s;
            lib.optional = condition: value: if condition then [ value ] else [];
            pkgs = {};
          };
          service = module.systemd.services.ghostship-podman-snapshot;
        in { inherit (service) after; requires = service.requires or []; wants = service.wants or []; }
        ''' % (json.dumps(str(ROOT/'modules/self-hosted/siem/collection.nix')), containers)
        result = subprocess.run(['nix-instantiate', '--eval', '--strict', '--json', '--expr', expression],
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def test_waits_for_enabled_desktop_build_without_pulling_it_in(self):
        service = self.service(True)
        self.assertIn('podman-agent-desktop.service', service['after'])
        self.assertNotIn('podman-agent-desktop.service', service['requires'] + service['wants'])

    def test_hosts_without_desktop_keep_only_the_podman_socket_order(self):
        self.assertEqual(self.service(False)['after'], ['podman.socket'])
