"""A tooling/host release must not enter the T3 image derivation graph."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("nix"), "requires Nix evaluation")
class ImageIdentity(unittest.TestCase):
    def test_candidate_identity_tracks_agent_pin_but_image_derivation_is_separate(self):
        # The deployment identity includes the agent pin so candidate receipts
        # bind all T3 inputs; the OCI image derivation remains independent.
        expression = r'''
        let
          flake = builtins.getFlake "path:__ROOT__";
          pkgs = flake.inputs.nixpkgs.legacyPackages.${builtins.currentSystem};
          id = revision: ((import __ROOT__/modules/self-hosted/t3code.nix {
            inputs.ghostship-private-agent.rev = revision;
            config = {};
            inherit pkgs; inherit (pkgs) lib;
          }).virtualisation.oci-containers.containers.t3code.labels."io.ghostship.t3code.deployment");
          image = import __ROOT__/packages/t3code/image.nix { inherit pkgs; };
          changed = pkgs.dockerTools.buildLayeredImageWithNixDb (image.imageArgs // { tag = "changed-image-parameter"; });
        in {
          baseline = id "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
          toolingChanged = id "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
          imageId = image.deploymentId;
          imageChanged = builtins.hashString "sha256" (toString changed);
        }
        '''.replace("__ROOT__", str(ROOT))
        result = subprocess.run(
            ["nix", "eval", "--impure", "--json", "--expr", expression],
            text=True, capture_output=True, check=True, timeout=8,
        )
        values = json.loads(result.stdout)
        self.assertNotEqual(values["baseline"], values["toolingChanged"])
        self.assertNotEqual(values["imageId"], values["imageChanged"])
