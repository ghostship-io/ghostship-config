"""The routing snapshot inside the T3 Code container.

The collector publishes the routing snapshot every five minutes, by rename,
to `/run/ghostship-integrations/model-routing.json` for the MCP. The T3 Code
container does not mount that directory, so `agent worker route` run inside
the container reported that the ranking snapshot is missing.

A path unit watches the host projection and copies those bytes into the
container's own tmpfs `/run/ghostship-model-routing/model-routing.json`
whenever the collector publishes. The container is never started, stopped or
recreated for it: a stopped container fails `requisite` instead.

The module is evaluated with Nix where Nix is available; the sandboxed check
has no Nix, so the module's own text is inspected there. Both paths assert the
same contract, and both fail when the path unit or the writer is missing.
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "modules/self-hosted/ai-usage/default.nix"
README = REPO / "modules/self-hosted/ai-usage/README.md"

HOST_PROJECTION = "/run/ghostship-integrations/model-routing.json"
CONTAINER_PROJECTION = "/run/ghostship-model-routing/model-routing.json"
CONTAINER_PROJECTION_DIR = "/run/ghostship-model-routing"
PATH_UNIT = "ghostship-ai-usage-t3-projection"
SERVICE_UNIT = f"{PATH_UNIT}.service"

# The T3 Code container as the base defines it. The projection must not touch
# it: no volume, no environment entry, and no restart of the container.
BASE_VOLUMES = [
    "/srv/apps/t3code/tmp:/tmp:rw",
    "/srv/apps/t3code/docker:/var/lib/docker:rw",
    "/srv/ghostship/workspace:/workspace:rw",
    "/srv/apps/t3code/home:/home/t3code:rw",
    "/srv/apps/t3code/nix-root/nix:/nix:rw",
    "/run/ghostship-secrets/t3code.env:/run/secrets/t3code.env:ro",
    "/mnt/share:/mnt/share:rw",
]
BASE_ENVIRONMENT = {}
BASE_ENVIRONMENT_FILES = ["/run/ghostship-secrets/t3code.env"]

# One evaluation answers every question: the module with the systemd options
# it uses stubbed, and the host's own t3code container, which the change must
# leave exactly as the base defines it.
EVAL_EXPRESSION = """
let
  flake = builtins.getFlake "path:__REPO__";
  pkgs = flake.inputs.nixpkgs.legacyPackages.${builtins.currentSystem};
  lib = pkgs.lib;
  stub = { lib, ... }: {
    options.systemd = {
      services = lib.mkOption {
        type = lib.types.attrsOf (lib.types.submodule {
          options = {
            description = lib.mkOption { type = lib.types.str; default = ""; };
            after = lib.mkOption { type = lib.types.listOf lib.types.str; default = []; };
            wants = lib.mkOption { type = lib.types.listOf lib.types.str; default = []; };
            requisite = lib.mkOption { type = lib.types.listOf lib.types.str; default = []; };
            serviceConfig = lib.mkOption { type = lib.types.attrsOf lib.types.anything; default = {}; };
          };
        });
        default = {};
      };
      paths = lib.mkOption {
        type = lib.types.attrsOf (lib.types.submodule {
          options = {
            description = lib.mkOption { type = lib.types.str; default = ""; };
            wantedBy = lib.mkOption { type = lib.types.listOf lib.types.str; default = []; };
            unit = lib.mkOption { type = lib.types.nullOr lib.types.str; default = null; };
            pathConfig = lib.mkOption { type = lib.types.attrsOf lib.types.anything; default = {}; };
          };
        });
        default = {};
      };
      timers = lib.mkOption {
        type = lib.types.attrsOf (lib.types.submodule {
          options = {
            description = lib.mkOption { type = lib.types.str; default = ""; };
            wantedBy = lib.mkOption { type = lib.types.listOf lib.types.str; default = []; };
            timerConfig = lib.mkOption { type = lib.types.attrsOf lib.types.anything; default = {}; };
          };
        });
        default = {};
      };
      tmpfiles = lib.mkOption {
        type = lib.types.submodule {
          options.rules = lib.mkOption { type = lib.types.listOf lib.types.str; default = []; };
        };
        default = {};
      };
    };
  };
  evaluated = lib.evalModules {
    modules = [ __MODULE__ stub ];
    specialArgs = { inherit pkgs; };
  };
  container =
    flake.nixosConfigurations.chill-penguin.config.virtualisation.oci-containers.containers.t3code;
  service = evaluated.config.systemd.services.ghostship-ai-usage-t3-projection or null;
in
{
  paths = evaluated.config.systemd.paths;
  services = evaluated.config.systemd.services;
  # The script is a store path; reading it builds the one tiny derivation, so
  # the test sees the commands the unit actually runs, not just its name.
  syncScript =
    if service == null then null else builtins.readFile service.serviceConfig.ExecStart;
  hostContainer = {
    inherit (container) volumes environment environmentFiles;
  };
}
"""

_EVALUATION = None


def evaluate_module():
    """Evaluate the module and the host container with Nix, or None."""
    global _EVALUATION
    if _EVALUATION is not None:
        return _EVALUATION
    nix = shutil.which("nix")
    if not nix:
        return None
    expression = EVAL_EXPRESSION.replace("__REPO__", str(REPO)).replace(
        "__MODULE__", str(MODULE)
    )
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "snapshot-projection.nix"
        path.write_text(expression, encoding="utf-8")
        result = subprocess.run(
            [nix, "eval", "--impure", "--json", "--file", str(path)],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=900,
        )
    if result.returncode != 0:
        raise AssertionError(f"the module did not evaluate: {result.stderr.strip()}")
    _EVALUATION = json.loads(result.stdout)
    return _EVALUATION


class ModuleText:
    """The module's own text, for the checks that do not need Nix."""

    def __init__(self):
        self.text = MODULE.read_text(encoding="utf-8")

    def block(self, marker):
        start = self.text.index(marker)
        return self.text[start : self.text.index("};", start)]

    def path_unit(self):
        return self.block(f"systemd.paths.{PATH_UNIT}")

    def service(self):
        return self.block(f"systemd.services.{PATH_UNIT}")


class SnapshotProjectionTests(unittest.TestCase):
    """The path unit, the oneshot, and the copy it writes."""

    def test_the_path_unit_watches_the_host_projection(self):
        evaluated = evaluate_module()
        if evaluated is None:
            text = ModuleText()
            self.assertIn(f'mcpProjection = "{HOST_PROJECTION}";', text.text)
            self.assertIn("pathConfig.PathChanged = mcpProjection;", text.path_unit())
            return
        path = evaluated["paths"].get(PATH_UNIT)
        self.assertIsNotNone(path, f"{PATH_UNIT}.path is not defined")
        self.assertEqual(path["pathConfig"]["PathChanged"], HOST_PROJECTION)

    def test_the_path_unit_starts_the_oneshot_without_a_restart(self):
        evaluated = evaluate_module()
        if evaluated is None:
            text = ModuleText()
            self.assertIn(
                f"systemd.paths.{PATH_UNIT} = {{", text.text
            )
            self.assertIn(
                f"systemd.services.{PATH_UNIT} = {{", text.text
            )
            self.assertIn('Type = "oneshot";', text.service())
            self.assertIn("NoNewPrivileges = true;", text.service())
            self.assertIn('UMask = "0022";', text.service())
            self.assertNotIn("Restart", text.service())
            return
        # A path unit activates the service of the same name.
        self.assertIn(PATH_UNIT, evaluated["paths"])
        service = evaluated["services"].get(PATH_UNIT)
        self.assertIsNotNone(service, f"{SERVICE_UNIT} is not defined")
        config = service["serviceConfig"]
        self.assertEqual(config.get("Type"), "oneshot")
        self.assertIs(config.get("NoNewPrivileges"), True)
        self.assertEqual(config.get("UMask"), "0022")
        self.assertNotIn("Restart", config)

    def test_the_service_writes_the_snapshot_into_the_container(self):
        evaluated = evaluate_module()
        if evaluated is None:
            text = ModuleText()
            self.assertIn("podman exec --user 0:0 t3code", text.text)
            self.assertIn(f"-d -m0755 -o3000 -g3000 ${{t3ProjectionDir}}", text.text)
            self.assertIn(f't3Projection = "{CONTAINER_PROJECTION}";', text.text)
            self.assertIn('t3ProjectionDir = builtins.dirOf t3Projection;', text.text)
            self.assertIn("--user 3000:3000 t3code", text.text)
            self.assertIn("mv -fT ${t3Projection}.new ${t3Projection}", text.text)
            self.assertIn("chmod 0644 ${t3Projection}.new", text.text)
            return
        service = evaluated["services"].get(PATH_UNIT)
        self.assertIsNotNone(service, f"{SERVICE_UNIT} is not defined")
        script = evaluated["syncScript"]
        self.assertIsNotNone(script, f"{SERVICE_UNIT} does not run a script")
        self.assertIn("podman exec --user 0:0 t3code", script)
        self.assertIn("install", script)
        self.assertIn(f"-d -m0755 -o3000 -g3000 {CONTAINER_PROJECTION_DIR}", script)
        self.assertIn("podman exec -i --user 3000:3000 t3code", script)
        self.assertIn(HOST_PROJECTION, script)
        # The sync script runs the writer from the container's store; its own
        # body is the literal the module writes. The replacement is by rename,
        # so a consumer never reads half a snapshot, and the mode is explicit
        # so the host umask does not decide it.
        writers = [
            token
            for token in script.split()
            if token.endswith("-ghostship-model-routing-write")
        ]
        self.assertEqual(len(set(writers)), 1, "the writer script is not named")
        text = ModuleText().text
        self.assertIn(f"cat > ${{t3Projection}}.new", text)
        self.assertIn(f"chmod 0644 ${{t3Projection}}.new", text)
        self.assertIn("mv -fT ${t3Projection}.new ${t3Projection}", text)

    def test_the_service_requires_the_running_container(self):
        evaluated = evaluate_module()
        if evaluated is None:
            service = ModuleText().service()
            self.assertIn('after = [ "podman-t3code.service" ];', service)
            self.assertIn('requisite = [ "podman-t3code.service" ];', service)
            return
        service = evaluated["services"].get(PATH_UNIT)
        self.assertIsNotNone(service, f"{SERVICE_UNIT} is not defined")
        self.assertIn("podman-t3code.service", service["after"])
        self.assertIn("podman-t3code.service", service["requisite"])

    def test_the_service_never_starts_stops_or_recreates_the_container(self):
        evaluated = evaluate_module()
        if evaluated is None:
            service = ModuleText().service()
            for verb in ("stop", "restart", "rm", "create", "run"):
                self.assertNotIn(f"podman {verb}", service)
            return
        service = evaluated["services"].get(PATH_UNIT)
        self.assertIsNotNone(service, f"{SERVICE_UNIT} is not defined")
        script = evaluated["syncScript"]
        self.assertIsNotNone(script, f"{SERVICE_UNIT} does not run a script")
        for verb in ("stop", "restart", "rm", "create", "run"):
            self.assertNotIn(f"podman {verb}", script)

    def test_the_t3code_container_is_unchanged(self):
        evaluated = evaluate_module()
        if evaluated is None:
            self.assertNotIn(
                "virtualisation.oci-containers", ModuleText().text
            )
            return
        container = evaluated["hostContainer"]
        self.assertEqual(container["volumes"], BASE_VOLUMES)
        self.assertEqual(container["environment"], BASE_ENVIRONMENT)
        self.assertEqual(container["environmentFiles"], BASE_ENVIRONMENT_FILES)

    def test_the_readme_names_the_container_copy_and_its_readers(self):
        text = README.read_text(encoding="utf-8")
        self.assertIn(CONTAINER_PROJECTION, text)
        paragraph = text[text.index(CONTAINER_PROJECTION) :]
        paragraph = paragraph[: paragraph.index("\n\n")]
        self.assertIn("read only", paragraph.lower())


if __name__ == "__main__":
    unittest.main()
