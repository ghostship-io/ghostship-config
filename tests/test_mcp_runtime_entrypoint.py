"""Pure builder fixtures catch a missing client export without building images."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "modules/self-hosted"


@unittest.skipUnless(shutil.which("nix"), "requires Nix expression evaluator")
class McpEntrypoint(unittest.TestCase):
    def evaluate(self, expression):
        result = subprocess.run(
            ["nix", "eval", "--impure", "--json", "--expr", expression],
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_deployed_base_exports_client_through_current_runtime(self):
        source = (MODULES / "private-integrations.nix").read_text()
        call = re.search(r'baseImage = (import ./service-base-image.nix \{.*?\n  \});',
                         source, re.S).group(1)
        call = call.replace('./service-base-image.nix', str(MODULES / 'service-base-image.nix'))
        script = self.evaluate('''let pkgs = {
          bash = "fixture-bash"; coreutils = "fixture-coreutils"; cacert = "fixture-certs";
          lib.concatMapStringsSep = sep: f: xs: builtins.concatStringsSep sep (map f xs);
          dockerTools.buildLayeredImage = args: args;
        }; in (''' + call + ''').fakeRootCommands''')
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["sh", "-eu", "-c", script], cwd=directory, check=True, timeout=2)
            link = Path(directory) / "bin/ghostship-mcp"
            self.assertTrue(link.is_symlink(), "base image does not export the MCP client")
            self.assertEqual(str(link.readlink()), "/run/ghostship-runtime/current/bin/ghostship-mcp")

    def test_published_runtime_includes_the_client_and_server(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            (fixture / "lib").mkdir()
            (fixture / "lib/private-integrations.nix").write_text('''{...}: {
              runtime = "/fixture-client";
              relay = "/fixture-relay";
              sharedSocket = "/fixture-socket";
            }''')
            (fixture / "lib/mkPackages.nix").write_text('{...}: {serviceClients = {};}')
            (fixture / "nixpkgs.nix").write_text('''{...}: {
              lib = {
                removePrefix = p: s: builtins.substring (builtins.stringLength p) (-1) s;
                hasPrefix = p: s: builtins.substring 0 (builtins.stringLength p) s == p;
                any = builtins.any;
              };
              bash = "/fixture-shell"; cacert = "/fixture-certs";
              python3.withPackages = _: "/fixture-python";
              writeTextFile = args: "/fixture/" + args.name;
              symlinkJoin = args: args;
            }''')
            result = self.evaluate('''let r = import ''' + str(MODULES / "agent-service-runtimes.nix") + ''' {
              system = "fixture-system";
              agent = {outPath = ''' + json.dumps(str(fixture)) + ''';
                inputs.nixpkgs = ''' + str(fixture / "nixpkgs.nix") + ''';};
            }; in r.integrations.paths''')
            self.assertIn("/fixture-client", result, "runtime publishes no MCP client")
            self.assertIn("/fixture/ghostship-integrations-entrypoint", result)
