"""The Python coordinator runs the pinned Go coordinator from its runtime PATH."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "modules/self-hosted"


@unittest.skipUnless(shutil.which("nix"), "requires Nix expression evaluator")
class CoordinatorReviewCliTests(unittest.TestCase):
    def evaluate(self, expression):
        result = subprocess.run(
            ["nix", "eval", "--impure", "--json", "--expr", expression],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_the_runtime_sources_the_pinned_cli_and_exports_its_path(self):
        source = (MODULES / "agent-service-runtimes.nix").read_text()
        self.assertIn(
            "coordinatorCli = agent.packages.${system}.coordinator;", source
        )
        self.assertIn("paths = [\n      coordinatorCli", source)
        self.assertIn(
            "export PATH=/run/ghostship-runtime/current/bin:$PATH", source
        )

    @unittest.skipUnless(shutil.which("nix"), "requires Nix expression evaluator")
    def test_published_runtime_carries_the_pinned_go_coordinator_on_path(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            (fixture / "lib").mkdir()
            (fixture / "lib/github-integration.nix").write_text('''{...}: {
              coordinatorRuntime = "/fixture-coordinator-code";
              coordinatorPython = "/fixture-python";
            }''')
            (fixture / "lib/coordinator-python-packages.nix").write_text('[ "ghostship_t3" ]')
            (fixture / "tools/python/ghostship_t3").mkdir(parents=True)
            (fixture / "tools/python/ghostship_t3/bridge.py").write_text('# bridge\n')
            (fixture / "tools/python/ghostship_github").mkdir(parents=True)
            (fixture / "tools/python/ghostship_github/gate.py").write_text('# gate\n')
            (fixture / "config/agents").mkdir(parents=True)
            for name in ("runtime-policy.json", "model-identities.json", "coordinator-jobs.json"):
                (fixture / "config/agents" / name).write_text('{}\n')
            (fixture / "nixpkgs.nix").write_text('''{...}: {
              lib = {
                removePrefix = p: s: builtins.substring (builtins.stringLength p) (-1) s;
                hasPrefix = p: s: builtins.substring 0 (builtins.stringLength p) s == p;
                hasSuffix = suffix: s: builtins.substring (builtins.stringLength s - builtins.stringLength suffix) (-1) s == suffix;
                any = builtins.any;
                filter = builtins.filter;
                concatMapStringsSep = sep: f: xs: builtins.concatStringsSep sep (map f xs);
                optionalString = condition: value: if condition then value else "";
              };
              bash = "/fixture-shell";
              cacert = "/fixture-certs";
              writeTextFile = args: {inherit (args) name text;};
              symlinkJoin = args: args;
            }''')
            result = self.evaluate('''let r = import ''' + str(MODULES / "agent-service-runtimes.nix") + ''' {
              system = "fixture-system";
              agent = {
                outPath = ''' + json.dumps(str(fixture)) + ''';
                inputs.nixpkgs = ''' + str(fixture / "nixpkgs.nix") + ''';
                packages."fixture-system".coordinator = "/fixture-go-coordinator";
              };
            }; in r.coordinator''')
            paths = result["paths"]
            self.assertIn(
                "/fixture-go-coordinator", paths,
                "coordinator runtime does not publish the pinned Go coordinator",
            )
            entrypoints = [entry["text"] for entry in paths if isinstance(entry, dict)]
            self.assertEqual(len(entrypoints), 1)
            script = entrypoints[0]
            self.assertIn(
                "export PATH=/run/ghostship-runtime/current/bin:$PATH", script,
                "coordinator entrypoint does not put the runtime bin on PATH",
            )
            self.assertIn("exec /fixture-python/bin/python3", script)
    def test_the_review_store_directory_exists_before_the_container_starts(self):
        coordinator = (MODULES / "github-engineering.nix").read_text()
        self.assertIn(
            '"d ${root}/state/ghostship-coordinator-shadow 0700 ghostship-github ghostship-github -"',
            coordinator,
        )
        self.assertIn(
            '"${config.ghostship.selfHostedSecrets.projections.ghostship-github-coordinator.path}:/run/secrets/github.env:ro"',
            coordinator,
        )
        self.assertIn('"--secrets" "/run/secrets/github.env"', coordinator)


if __name__ == "__main__":
    unittest.main()
