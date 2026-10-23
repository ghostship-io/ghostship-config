"""A changed bound engine helper must never stop a busy T3 on host switch."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("nix-instantiate"), "requires Nix evaluation")
class SwitchProtection(unittest.TestCase):
    def test_every_engine_service_preserves_its_running_instance(self):
        # Evaluate the actual module declarations, lazily, without a host build.
        # Default-enabled restart/stop is a failure, including for newly added
        # helpers. No packages need to be built to read these properties.
        expression = r'''
        let
          module = import __MODULE__ {
            pkgs = {};
            lib = {
              mkIf = condition: value: value;
              mkMerge = values: builtins.head values;
            };
            config.ghostship.t3codePodman = { enable = true; uid = 62040; };
          };
        in builtins.mapAttrs (_: unit: {
          restart = unit.restartIfChanged or true;
          stop = unit.stopIfChanged or true;
          dependencies = (unit.requires or []) ++ (unit.bindsTo or []);
        }) module.config.systemd.services
        '''.replace("__MODULE__", str(ROOT / "modules/self-hosted/t3code-podman.nix"))
        result = subprocess.run(
            ["nix-instantiate", "--eval", "--strict", "--json", "--expr", expression],
            text=True, capture_output=True, check=True, timeout=5,
        )
        units = json.loads(result.stdout)
        self.assertIn("user-runtime-dir@62040", units)
        self.assertIn("t3code-podman-rootfs", units)
        for name, unit in units.items():
            with self.subTest(unit=name):
                self.assertFalse(unit["restart"], "switch can restart a T3 dependency")
                self.assertFalse(unit["stop"], "switch can stop a T3 dependency")
                for dependency in unit["dependencies"]:
                    self.assertIn(dependency.removesuffix(".service"), units)
