"""The routing switch of the AI usage snapshot.

The switch belongs to the owner. The NixOS option
`ghostship.aiUsage.routing.enabled` reaches the collector, and the collector
publishes it: a consumer reads the switch and decides, and the switch is off
until the owner turns it on.

The NixOS option is evaluated with Nix where Nix is available. The
sandboxed check has no Nix, so the module is inspected there instead. Both
paths assert the same contract, and both fail when the switch is missing.
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "modules/self-hosted/ai-usage/default.nix"

# The evaluation of the module is done once: it copies the repository into
# the store, and one evaluation answers every question about the option.
_EVALUATION = None

# The evaluation of the module. The unit is a systemd service, and only its
# option tree is needed here, so the systemd options are stubbed instead of
# a whole host: the switch itself is the module's own logic.
EVAL_EXPRESSION = """
let
  flake = builtins.getFlake "path:__REPO__";
  pkgs = flake.inputs.nixpkgs.legacyPackages.${builtins.currentSystem};
  lib = pkgs.lib;
  systemdStub = { lib, ... }: {
    options.systemd = {
      services = lib.mkOption {
        type = lib.types.attrsOf (lib.types.submodule {
          options = {
            description = lib.mkOption { type = lib.types.str; default = ""; };
            after = lib.mkOption { type = lib.types.listOf lib.types.str; default = []; };
            wants = lib.mkOption { type = lib.types.listOf lib.types.str; default = []; };
            serviceConfig = lib.mkOption { type = lib.types.attrsOf lib.types.anything; default = {}; };
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
  module = __MODULE__;
  evaluate = extra: lib.evalModules {
    modules = [ module systemdStub ] ++ extra;
    specialArgs = { inherit pkgs; };
  };
  off = evaluate [ ];
  on = evaluate [ { ghostship.aiUsage.routing.enabled = true; } ];
in
{
  default = off.config.ghostship.aiUsage.routing.enabled;
  off = off.config.systemd.services.ghostship-ai-usage.serviceConfig.ExecStart;
  on = on.config.systemd.services.ghostship-ai-usage.serviceConfig.ExecStart;
}
"""


def evaluate_module():
    """Evaluate the module with Nix, or return None when Nix is not here."""
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
        path = Path(directory) / "routing-switch.nix"
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

    def option_block(self):
        """The declaration of the routing option, as the module writes it."""
        marker = "options.ghostship.aiUsage.routing.enabled"
        start = self.text.index(marker)
        return self.text[start : self.text.index("};", start)]

    def exec_start(self):
        for line in self.text.splitlines():
            if "ExecStart" in line:
                return line
        raise AssertionError("the unit has no ExecStart")


class RoutingSwitchModuleTests(unittest.TestCase):
    """The NixOS option, and the unit it reaches."""

    def test_the_option_defaults_to_false(self):
        evaluated = evaluate_module()
        if evaluated is None:
            # No Nix here: the declaration itself has to say the default.
            block = ModuleText().option_block()
            self.assertIn("type = lib.types.bool;", block)
            self.assertIn("default = false;", block)
            return
        self.assertIs(evaluated["default"], False)

    def test_the_unit_exec_start_reflects_the_switch(self):
        evaluated = evaluate_module()
        if evaluated is None:
            text = ModuleText()
            self.assertIn("--routing-enabled ${routingEnabled}", text.exec_start())
            self.assertIn(
                'routingEnabled = if cfg.routing.enabled then "true" else "false";',
                text.text,
            )
            return
        self.assertIn("--routing-enabled false", evaluated["off"])
        self.assertIn("--routing-enabled true", evaluated["on"])

    def test_nothing_else_sets_the_switch(self):
        # The option is the owner's, and only the owner sets it. It is
        # declared in the module of the collector, and no other module of the
        # repository may turn it on.
        self.assertIn(
            "options.ghostship.aiUsage.routing.enabled",
            MODULE.read_text(encoding="utf-8"),
        )
        others = []
        for path in sorted(REPO.rglob("*.nix")):
            if ".git" in path.parts or path == MODULE:
                continue
            if "aiUsage" in path.read_text(encoding="utf-8"):
                others.append(str(path.relative_to(REPO)))
        self.assertEqual(others, [])


if __name__ == "__main__":
    unittest.main()
