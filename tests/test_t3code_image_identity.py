"""A tooling/host release must not enter the T3 image derivation graph."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("nix"), "requires Nix evaluation")
class ImageIdentity(unittest.TestCase):
    def test_host_and_agent_inputs_are_not_image_inputs(self):
        # This evaluates real image derivations, without evaluating/building a
        # host. Throwing inputs catch even an accidental transitive dependency.
        expression = r'''
        let
          flake = builtins.getFlake "path:__ROOT__";
          pkgs = flake.inputs.nixpkgs.legacyPackages.${builtins.currentSystem};
          id = inputs: config: ((import __ROOT__/modules/self-hosted/t3code.nix {
            inherit inputs config pkgs; inherit (pkgs) lib;
          }).virtualisation.oci-containers.containers.t3code.labels."io.ghostship.t3code.deployment");
          image = import __ROOT__/packages/t3code/image.nix { inherit pkgs; };
          changed = pkgs.dockerTools.buildLayeredImageWithNixDb (image.imageArgs // { tag = "changed-image-parameter"; });
        in {
          baseline = id {} {};
          toolingChanged = id (throw "image depends on the agent release") (throw "image depends on host config");
          imageChanged = builtins.hashString "sha256" (toString changed);
        }
        '''.replace("__ROOT__", str(ROOT))
        result = subprocess.run(
            ["nix", "eval", "--impure", "--json", "--expr", expression],
            text=True, capture_output=True, check=True, timeout=8,
        )
        values = json.loads(result.stdout)
        self.assertEqual(values["baseline"], values["toolingChanged"])
        self.assertNotEqual(values["baseline"], values["imageChanged"])
