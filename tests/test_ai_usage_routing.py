"""The routing switch of the AI usage snapshot.

The switch belongs to the owner. The NixOS option
`ghostship.aiUsage.routing.enabled` reaches the collector, and the collector
publishes it: a consumer reads the switch and decides, and the switch is off
until the owner turns it on. The switch is published in the routing snapshot,
in every projection of that snapshot, and in the
`ghostship_ai_routing_enabled` gauge.

The NixOS option is evaluated with Nix where Nix is available. The
sandboxed check has no Nix, so the module is inspected there instead. Both
paths assert the same contract, and both fail when the switch is missing.
"""

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COLLECTOR = REPO / "modules/self-hosted/ai-usage/collector"
MODULE = REPO / "modules/self-hosted/ai-usage/default.nix"
if str(COLLECTOR) not in sys.path:
    sys.path.insert(0, str(COLLECTOR))

import main as main_module  # noqa: E402
import ranking as ranking_module  # noqa: E402
import snapshot as snapshot_module  # noqa: E402

NOW = 1_800_000_000.0

POLICY = {
    "frontierPrimeModels": (),
    "allowedGptModels": ("gpt-6.1-sol",),
    "backgroundProviderInstances": ("opencode",),
}

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


class FakeCatalog:
    """A catalog that prices the models the test names, and nothing else."""

    def __init__(self, models, prices=None):
        self.prices = dict(prices or {})
        self.document = {}
        for provider, model in models:
            entry = {
                "name": model,
                "family": provider,
                "release_date": "2026-01-01",
            }
            if (provider, model) in self.prices:
                entry["cost"] = self.prices[(provider, model)]
            models_of_provider = self.document.setdefault(provider, {"models": {}})
            models_of_provider["models"][model] = entry

    def model_entry(self, provider, model):
        return (self.document.get(provider) or {}).get("models", {}).get(model)

    def price_for(self, provider, model):
        return self.prices.get((provider, model))

    def model_name(self, provider, model):
        return model

    def release_date(self, provider, model):
        return "2026-01-01"


def aa_record(model):
    """A measured record of one model, so the ranking may use it."""
    return {
        "model": model,
        "indices": {
            "intelligence_index": 50.0,
            "coding_index": 50.0,
            "agentic_index": 50.0,
            "engineering_index": 50.0,
        },
        "cost_per_task": 0.2,
        "median_performance": 100.0,
    }


def aa_cache(models):
    return {
        "status": "ok",
        "index_version": "4.3",
        "fetched_at": "2027-01-15T08:00:00Z",
        "fetched_at_epoch": NOW - 60.0,
        "age_seconds": 60.0,
        "records": [aa_record(model) for model in models],
    }


def build_snapshot(
    models, prices=None, free_models=(), promo_models=(), routing_enabled=False
):
    """Build a real snapshot of the named models, with a real ranking."""
    feed = aa_cache([model for _provider, model in models])
    catalog = FakeCatalog(models, prices)
    ranked = ranking_module.rank_models(
        models=[
            ranking_module.ModelRecord(provider, model) for provider, model in models
        ],
        catalog=catalog,
        quota_windows={},
        free_models=set(free_models),
        promo_models=set(promo_models),
        usage_tokens={},
        aa_cache=feed,
        now=NOW,
    )
    return snapshot_module.build_snapshot(
        now=NOW,
        sources=[
            {"id": "t3", "status": "ok", "reason": "ok", "observed_at_epoch": NOW}
        ],
        ranked=ranked,
        native_models={
            (provider, model): {
                "providerInstance": provider,
                "modelId": model,
                "options": [],
            }
            for provider, model in models
        },
        policy=POLICY,
        aa_cache=feed,
        catalog=catalog,
        free_models=set(free_models),
        promo_models=set(promo_models),
        routing_enabled=routing_enabled,
    )


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


class RoutingSnapshotTests(unittest.TestCase):
    """The switch in the snapshot, in the projections, and in the metrics."""

    def test_the_snapshot_carries_the_routing_block_and_it_is_off_by_default(self):
        data = build_snapshot([("claude", "claude-opus-5-5")])
        self.assertIn("routing", data)
        self.assertIs(data["routing"]["enabled"], False)
        self.assertEqual(data["routing"]["source"], "nixos-option")

    def test_the_switch_on_publishes_the_routing_block(self):
        data = build_snapshot([("claude", "claude-opus-5-5")], routing_enabled=True)
        self.assertIs(data["routing"]["enabled"], True)
        self.assertEqual(data["routing"]["source"], "nixos-option")

    def test_the_gauge_reads_zero_while_the_switch_is_off(self):
        data = build_snapshot([("claude", "claude-opus-5-5")])
        text = main_module.render([], [], NOW, 1.0, data)
        self.assertIn("# HELP ghostship_ai_routing_enabled", text)
        self.assertIn("ghostship_ai_routing_enabled 0\n", text + "\n")

    def test_the_gauge_reads_one_while_the_switch_is_on(self):
        data = build_snapshot([("claude", "claude-opus-5-5")], routing_enabled=True)
        text = main_module.render([], [], NOW, 1.0, data)
        self.assertIn("# HELP ghostship_ai_routing_enabled", text)
        self.assertIn("ghostship_ai_routing_enabled 1\n", text + "\n")

    def test_the_gauge_carries_no_label(self):
        data = build_snapshot([("claude", "claude-opus-5-5")], routing_enabled=True)
        text = main_module.render([], [], NOW, 1.0, data)
        samples = [
            line
            for line in text.splitlines()
            if line.startswith("ghostship_ai_routing_enabled")
        ]
        self.assertEqual(samples, ["ghostship_ai_routing_enabled 1"])

    def test_a_projection_carries_the_same_routing_block(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = root / "routing.json"
            projection = root / "model-routing.json"
            data = build_snapshot([("claude", "claude-opus-5-5")], routing_enabled=True)
            snapshot_module.write_snapshot(str(canonical), data)
            snapshot_module.publish(data, [str(projection)])
            written = json.loads(canonical.read_text(encoding="utf-8"))
            projected = json.loads(projection.read_text(encoding="utf-8"))
            self.assertEqual(
                written["routing"], {"enabled": True, "source": "nixos-option"}
            )
            self.assertEqual(projected["routing"], written["routing"])

    def test_the_collector_writes_the_switch_into_the_snapshot_and_the_projection(self):
        # The whole way through: the unit's argument, the snapshot, the
        # projection, and the gauge.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = root / "routing.json"
            projection = root / "model-routing.json"
            output = root / "ai-usage.prom"
            original = main_module.collect
            main_module.collect = lambda *args, **kwargs: ([], [], {})
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    code = main_module.main(
                        [
                            "--output",
                            str(output),
                            "--state",
                            str(root / "state.json"),
                            "--snapshot",
                            str(canonical),
                            "--projection",
                            str(projection),
                            "--facts",
                            "/dev/null",
                            "--aa-cache",
                            "/dev/null",
                            "--aa-3d-cache",
                            "/dev/null",
                            "--now",
                            str(NOW),
                            "--routing-enabled",
                            "true",
                        ]
                    )
            finally:
                main_module.collect = original
            self.assertEqual(code, 0)
            written = json.loads(canonical.read_text(encoding="utf-8"))
            projected = json.loads(projection.read_text(encoding="utf-8"))
            self.assertIs(written["routing"]["enabled"], True)
            self.assertEqual(projected["routing"], written["routing"])
            metrics = output.read_text(encoding="utf-8")
            self.assertIn("ghostship_ai_routing_enabled 1", metrics)

    def test_the_collector_keeps_the_switch_off_without_the_argument(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = root / "routing.json"
            output = root / "ai-usage.prom"
            original = main_module.collect
            main_module.collect = lambda *args, **kwargs: ([], [], {})
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    code = main_module.main(
                        [
                            "--output",
                            str(output),
                            "--state",
                            str(root / "state.json"),
                            "--snapshot",
                            str(canonical),
                            "--facts",
                            "/dev/null",
                            "--aa-cache",
                            "/dev/null",
                            "--aa-3d-cache",
                            "/dev/null",
                            "--now",
                            str(NOW),
                        ]
                    )
            finally:
                main_module.collect = original
            self.assertEqual(code, 0)
            written = json.loads(canonical.read_text(encoding="utf-8"))
            self.assertIs(written["routing"]["enabled"], False)
            metrics = output.read_text(encoding="utf-8")
            self.assertIn("ghostship_ai_routing_enabled 0", metrics)


if __name__ == "__main__":
    unittest.main()
