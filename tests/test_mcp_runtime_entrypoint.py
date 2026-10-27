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

    def test_startup_failures_invalidate_previous_completion(self):
        binary = shutil.which("mcp-rollout")
        self.assertIsNotNone(binary, "run inside the CI shell containing mcp-rollout")
        shell = shutil.which("sh")
        self.assertIsNotNone(shell)
        source = (MODULES / "private-integrations.nix").read_text()
        script = re.search(r'snapshotMcp = pkgs.writeShellScript "ghostship-snapshot-mcp" \'\'(.*?)\n  \'\';', source, re.S).group(1)
        for failure in ("health", "start-time"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "bin").mkdir()
                (root / "bin/mcp-rollout").symlink_to(binary)
                (root / "bin/podman").write_text(f'#!{shell}\nexit 1\n')
                (root / "bin/podman").chmod(0o755)
                (root / "bin/chown").write_text(f'#!{shell}\nexit 0\n')
                (root / "bin/chown").chmod(0o755)
                (root / "wait").write_text(f'#!{shell}\nexit ' + ('1' if failure == 'health' else '0') + '\n')
                (root / "wait").chmod(0o755)
                (root / "rollout.json").write_text('{"complete":true}')
                (root / "server.json").write_text('{}')
                actual = script.replace('${mcpRollout}', str(root)).replace('${waitForMcpHealthy}', str(root / 'wait')).replace('${pkgs.podman}', str(root)).replace('${runtimes.private.sharedSocket}', '/unused').replace('/var/lib/ghostship-skills', str(root))
                result = subprocess.run([shell, '-c', actual], capture_output=True, text=True, timeout=5,
                                        env={"PATH": str(root / "bin")})
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(json.loads((root / 'rollout.json').read_text())['complete'])
                self.assertFalse((root / 'server.json').exists())

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
            (fixture / "lib/native-mcp.nix").write_text('{...}: "/fixture-client"')
            (fixture / "lib/openai-relay.nix").write_text('{...}: "/fixture-relay"')
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
