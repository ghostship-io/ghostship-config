"""Unrelated secret metadata must not change a container's pre-start closure."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("nix"), "requires Nix evaluation")
class ProjectionIdentity(unittest.TestCase):
    def test_projection_renderer_depends_only_on_its_own_specification(self):
        expression = r'''
        let
          flake = builtins.getFlake "path:__ROOT__";
          pkgs = flake.inputs.nixpkgs.legacyPackages.${builtins.currentSystem};
          inherit (pkgs) lib;
          catalog = import __ROOT__/secrets/catalog.nix { recipients = import __ROOT__/secrets/recipients.nix; };
          projection = value: { fileName = "fixture.env"; mode = "0600"; owner = "root"; group = "root"; fields.KEY.value = value; };
          renderers = peer: own: (import __ROOT__/modules/self-hosted/secrets.nix {
            inherit pkgs lib;
            config = {
              ghostship.secretProjections = { fixture = projection own; unrelated = projection peer; };
              age.secrets = lib.mapAttrs (name: _: { path = "/run/agenix/${name}"; }) catalog.units;
            };
          }).config.ghostship.selfHostedSecrets;
          before = renderers "before" "unchanged";
          after = renderers "after" "unchanged";
          changed = renderers "after" "changed";
        in {
          tunnelBefore = toString (before.renderFor "cloudflared-runtime");
          tunnelAfter = toString (after.renderFor "cloudflared-runtime");
          ownBefore = toString (before.renderFor "fixture");
          ownAfter = toString (changed.renderFor "fixture");
          globalBefore = toString before.render;
          globalAfter = toString after.render;
        }
        '''.replace("__ROOT__", str(ROOT))
        result = subprocess.run(["nix", "eval", "--impure", "--json", "--expr", expression],
                                text=True, capture_output=True, check=True, timeout=8)
        values = json.loads(result.stdout)
        self.assertEqual(values["tunnelBefore"], values["tunnelAfter"])
        self.assertNotEqual(values["ownBefore"], values["ownAfter"])
        self.assertNotEqual(values["globalBefore"], values["globalAfter"])

    def test_container_consumers_cannot_use_the_whole_catalog_renderer(self):
        offenders = []
        for path in (ROOT / "modules/self-hosted").glob("*.nix"):
            if path.name != "secrets.nix" and "selfHostedSecrets.render}" in path.read_text():
                offenders.append(path.name)
        self.assertEqual(offenders, [], "shared secret restart triggers: " + ", ".join(offenders))
