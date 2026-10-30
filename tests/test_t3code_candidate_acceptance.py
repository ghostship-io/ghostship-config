"""Candidate acceptance creates only exact, production-preserving receipts."""
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
import tarfile
import tempfile
import time
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "t3code_candidate_acceptance", ROOT / "packages/t3code/candidate-acceptance.py"
)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)
probe_spec = importlib.util.spec_from_file_location(
    "t3code_provider_turn_probe", ROOT / "packages/t3code/provider-turn-probe.py"
)
provider_probe = importlib.util.module_from_spec(probe_spec)
probe_spec.loader.exec_module(provider_probe)


class CandidateDeploymentPackagingTest(unittest.TestCase):
    def test_host_packages_acceptance_scripts_with_their_sibling_inputs(self):
        module = (ROOT / "modules/self-hosted/t3code.nix").read_text()
        self.assertIn('t3codeDeploymentScripts = pkgs.runCommand', module)
        for name in (
            "candidate-acceptance.py", "acceptance-launcher-key.py", "hardening-probe.py",
            "provider-turn-probe.py", "runtime-caps.json",
        ):
            with self.subTest(name=name):
                self.assertIn(f"$out/{name}", module)
                self.assertIn(f"packages/t3code/{name}", module)
        self.assertIn('name = "ghostship-t3code-deploy-image"', module)
        self.assertIn('name = "ghostship-t3code-invalidate-failure"', module)
        self.assertIn('environment.systemPackages = [ t3codeInvalidateFailure ];', module)
        self.assertIn('exec ${lib.getExe t3codeImmediateDeploy} --invalidate-failure', module)
        self.assertIn('builtins.readFile ../../packages/t3code/deploy-image.sh', module)
        self.assertIn('CANDIDATE_ACCEPTANCE = "${t3codeDeploymentScripts}/candidate-acceptance.py"', module)
        activation = (ROOT / "packages/t3code/activate-deployment.sh").read_text()
        self.assertIn('start --no-block ghostship-t3code-deploy.service', activation)
        self.assertNotIn('t3code-deploy-when-idle', module)
        self.assertNotIn('t3code-safe-restart', module)

    def test_t3code_image_exposes_systemd_as_oci_entrypoint(self):
        image = (ROOT / "packages/t3code/image.nix").read_text()
        self.assertIn('Entrypoint = [ "${pkgs.systemd}/lib/systemd/systemd" ];', image)
        self.assertIn("Cmd = [ ];", image)


class CandidateAcceptanceTest(unittest.TestCase):
    def test_policy_rejects_minimax_only_snapshot(self):
        policy = {"schema": "ghostship.route-policy/v2", "providers": {"opencode-free": {"admit": False}}, "routes": []}
        rows = [{"provider": "opencode-free", "model": "nvidia/minimaxai/minimax-m3.1-flash", "available": True, "execution": "t3", "target": {"providerInstanceId": "opencode-free", "model": "nvidia/minimaxai/minimax-m3.1-flash"}}]
        self.assertEqual(acceptance.admitted_route_candidates(policy, rows), [])
        self.assertFalse(provider_probe.native_is_admitted(policy, "opencode-free", "nvidia/minimaxai/minimax-m3.1-flash"))

    def test_policy_uses_terra_only_after_primaries_exhausted(self):
        policy = {"schema": "ghostship.route-policy/v2", "providers": {"primary": {"admit": True}, "codex": {"admit": True}}, "routes": [
            {"provider": "primary", "provider_instance": "primary", "model": "flash", "admit": True, "roles": ["worker"], "billing": "subscription"},
            {"provider": "codex", "provider_instance": "codex", "model": "gpt-6.1-terra", "admit": True, "roles": ["worker"], "fallback_only": True, "billing": "subscription"},
        ]}
        rows = [{"provider": "primary", "model": "flash", "available": False, "execution": "t3", "target": {"providerInstanceId": "primary", "model": "flash"}},
                {"provider": "codex", "model": "gpt-6.1-terra", "available": True, "execution": "t3", "target": {"providerInstanceId": "codex", "model": "gpt-6.1-terra", "options": {"serviceTier": "priority", "fastMode": True}}}]
        selected = acceptance.admitted_route_candidates(policy, rows)
        self.assertEqual([(row['instance'], row['model']) for row in selected], [('codex', 'gpt-6.1-terra')])
        self.assertEqual(selected[0]['options']['serviceTier'], 'standard')
        self.assertFalse(selected[0]['options']['fastMode'])
        self.assertEqual(acceptance.admitted_route_candidates(policy, rows[1:]), [])
        self.assertEqual(acceptance.admitted_route_candidates(policy, rows[1:], complete=True)[0]['instance'], 'codex')
        rows[0]['available'] = None
        self.assertEqual(acceptance.admitted_route_candidates(policy, rows), [])
        self.assertEqual(acceptance.admitted_route_candidates(policy, rows, complete=True), [])
        rows[0]['available'] = True
        self.assertEqual([row['instance'] for row in acceptance.admitted_route_candidates(policy, rows)], ['primary'])

    def test_all_exhausted_is_route_unavailable(self):
        with patch.object(acceptance, 'candidate_provider_diagnostics', return_value='fixture'), \
             patch.object(acceptance, 'candidate_agent_command', return_value=Mock(returncode=0, stdout='{"data":{"selected":[]}}')):
            with self.assertRaises(acceptance.RouteUnavailableError):
                acceptance.check_provider_turn(['podman'], 'candidate', None, tooling_path='agent', policy={'schema':'ghostship.route-policy/v2','providers':{},'routes':[]})

    def test_exhausted_primary_probes_admitted_terra_at_standard_tier(self):
        policy = {"schema": "ghostship.route-policy/v2", "providers": {"primary": {"admit": True}, "codex": {"admit": True}}, "routes": [
            {"provider":"primary", "provider_instance":"primary", "model":"flash", "admit":True, "roles":["worker"], "billing":"subscription"},
            {"provider":"codex", "provider_instance":"codex", "model":"gpt-6.1-terra", "admit":True, "roles":["worker"], "billing":"subscription", "fallback_only":True},
        ]}
        snapshot = {"model_selection":{"schema":"ghostship.model-selection/v1", "generated_at_epoch":time.time(), "worker":[]},
                    "candidates":[{"available":True, "native":{"mapped":True, "available":True, "provider_instance_id":"codex", "model_id":"gpt-6.1-terra"}}]}
        primary = {"provider":"primary", "model":"flash", "available":True, "execution":"t3", "target":{"providerInstanceId":"primary", "model":"flash"}}
        calls = []
        def run(engine, name, *args, **kwargs):
            calls.append(args)
            if "pick" in args:
                return Mock(returncode=0, stdout=json.dumps({"data":{"pick":primary}}))
            if "models" in args:
                return Mock(returncode=0, stdout=json.dumps({"data":{"selected":[primary]}}))
            if "primary" in args:
                return Mock(returncode=1, stdout='{"settled":true,"error":{"code":"quota"}}', stderr="")
            return self.probe_success(args) if "--instance" in args else Mock(returncode=0, stdout="passed", stderr="")
        with patch.object(acceptance, "candidate_agent_command", side_effect=run), patch.object(acceptance, "candidate_provider_diagnostics", return_value="fixture"):
            result = acceptance.check_provider_turn([], "candidate", None, tooling_path="agent", policy=policy, snapshot=snapshot)
        self.assertEqual(result, "codex/gpt-6.1-terra")
        probes = self.probe_calls(calls)
        self.assertEqual(len(probes), 2)
        opts = json.loads(probes[1][probes[1].index("--options-json") + 1])
        self.assertEqual(opts, {"serviceTier":"standard", "fastMode":False})
        snapshot["model_selection"]["generated_at_epoch"] = time.time() - 3600
        self.assertEqual(acceptance.fresh_snapshot_routes(snapshot), [])

    def test_three_exhausted_primaries_leave_one_fallback_attempt(self):
        providers = {name: {"admit":True} for name in ("a", "b", "c", "codex")}
        routes = [{"provider":name, "provider_instance":name, "model":"flash", "admit":True, "roles":["worker"], "billing":"subscription"} for name in ("a", "b", "c")]
        routes.append({"provider":"codex", "provider_instance":"codex", "model":"gpt-6.1-terra", "admit":True, "roles":["worker"], "billing":"subscription", "fallback_only":True})
        rows = [{"provider":name, "model":"flash", "available":True, "execution":"t3", "target":{"providerInstanceId":name, "model":"flash"}} for name in ("a", "b", "c")]
        rows.append({"provider":"codex", "model":"gpt-6.1-terra", "available":True, "execution":"t3", "target":{"providerInstanceId":"codex", "model":"gpt-6.1-terra"}})
        calls = []
        def run(engine, name, *args, **kwargs):
            calls.append(args)
            if "pick" in args: return Mock(returncode=0, stdout=json.dumps({"data":{"pick":rows[0]}}))
            if "models" in args: return Mock(returncode=0, stdout=json.dumps({"data":{"selected":rows}}))
            if "codex" in args: return self.probe_success(args)
            return Mock(returncode=1, stdout='{"settled":true,"error":{"code":"quota"}}', stderr="")
        with patch.object(acceptance, "candidate_agent_command", side_effect=run), patch.object(acceptance, "candidate_provider_diagnostics", return_value="fixture"):
            self.assertEqual(acceptance.check_provider_turn([], "candidate", None, tooling_path="agent", policy={"schema":"ghostship.route-policy/v2", "providers":providers, "routes":routes}), "codex/gpt-6.1-terra")
        self.assertEqual(len(self.probe_calls(calls)), 4)

    def test_route_unavailable_records_evidence_and_no_receipt(self):
        failure = acceptance.RouteUnavailableError("picker exhausted", "primary:quota", "route_unavailable: quota")
        with patch.object(acceptance, "command", side_effect=self.command), \
             patch.object(acceptance, "check_candidate", side_effect=failure), \
             patch.object(acceptance.subprocess, "run", return_value=Mock(returncode=0)):
            with self.assertRaises(acceptance.RouteUnavailableError):
                acceptance.accept(self.state, self.archive, "podman", "/socket", self.home,
                                  command_fn=self.command, identity_fn=lambda: self.identity)
        record = json.loads((self.state / "attempts/generation-502.json").read_text())
        self.assertEqual(record["outcome"], "route_unavailable")
        self.assertIn("quota", record["provider_turn"]["evidence"])
        self.assertFalse((self.state / "receipts/generation-502.json").exists())

    def test_only_a_proven_route_failure_can_be_attributed_to_candidate(self):
        policy = {"schema":"ghostship.route-policy/v2", "providers":{"primary":{"admit":True}},
                  "routes":[{"provider":"primary", "provider_instance":"primary", "model":"flash", "admit":True, "roles":["worker"], "billing":"subscription"}]}
        row = {"provider":"primary", "model":"flash", "available":True, "execution":"t3",
               "target":{"providerInstanceId":"primary", "model":"flash"}, "tool_loop":{"state":"proven"}}
        def run(engine, name, *args, **kwargs):
            if "pick" in args:
                return Mock(returncode=0, stdout=json.dumps({"data":{"pick":row}}))
            if "models" in args:
                return Mock(returncode=0, stdout=json.dumps({"data":{"selected":[row]}}))
            return Mock(returncode=1, stdout='{"settled":true,"error":{"code":"no-tool-call"}}', stderr="")
        with patch.object(acceptance, "candidate_agent_command", side_effect=run), patch.object(acceptance, "candidate_provider_diagnostics", return_value="fixture"):
            with self.assertRaises(acceptance.ProviderTurnError) as failure:
                acceptance.check_provider_turn([], "candidate", None, tooling_path="agent", policy=policy)
            self.assertNotIsInstance(failure.exception, (acceptance.RouteUnavailableError, acceptance.RouteUnknownError))
            row["tool_loop"]["state"] = "unknown"
            with self.assertRaises(acceptance.RouteUnknownError):
                acceptance.check_provider_turn([], "candidate", None, tooling_path="agent", policy=policy)

    def test_success_without_exact_settled_proof_is_unknown(self):
        policy = {"schema":"ghostship.route-policy/v2", "providers":{"primary":{"admit":True}},
                  "routes":[{"provider":"primary", "provider_instance":"primary", "model":"flash", "admit":True, "roles":["worker"], "billing":"subscription"}]}
        row = {"provider":"primary", "model":"flash", "available":True, "execution":"t3", "target":{"providerInstanceId":"primary", "model":"flash"}}
        def run(engine, name, *args, **kwargs):
            if "pick" in args: return Mock(returncode=0, stdout=json.dumps({"data":{"pick":row}}))
            if "models" in args: return Mock(returncode=0, stdout=json.dumps({"data":{"selected":[row]}}))
            return Mock(returncode=0, stdout='{"outcome":"passed","settled":true,"instance":"other","model":"flash"}')
        with patch.object(acceptance, "candidate_agent_command", side_effect=run), patch.object(acceptance, "candidate_provider_diagnostics", return_value="fixture"):
            with self.assertRaises(acceptance.RouteUnknownError):
                acceptance.check_provider_turn([], "candidate", None, tooling_path="agent", policy=policy)

    def test_native_codex_options_require_supported_standard_and_never_fast(self):
        client = Mock()
        model = {"id":"gpt-6.1-terra", "options":[{"id":"serviceTier", "type":"enum", "values":["standard", "priority"]}]}
        client.capabilities.return_value = {"providers":[{"providerInstanceId":"codex", "available":True, "models":[model]}]}
        self.assertEqual(provider_probe.standard_options(client, "codex", "gpt-6.1-terra"), {"serviceTier":"standard"})
        model["options"].append({"id":"fastMode", "type":"boolean"})
        self.assertEqual(provider_probe.standard_options(client, "codex", "gpt-6.1-terra"), {"serviceTier":"standard", "fastMode":False})
        model["options"][0]["values"] = ["priority"]
        with self.assertRaises(ValueError):
            provider_probe.standard_options(client, "codex", "gpt-6.1-terra")

    def test_direct_native_probe_submits_exact_standard_target(self):
        bridge_module = types.ModuleType("ghostship_t3.bridge")
        bridge_module.T3Error = type("T3Error", (Exception,), {})
        models_module = types.ModuleType("ghostship_t3.models")
        models_module.read_document = lambda: (_ for _ in ()).throw(AssertionError("picker must not choose the direct target"))
        models_module._selection = lambda *_: {}
        client = Mock()
        client.submit.return_value = {"thread_id":"fixture"}
        client.status.side_effect = [{"state":"completed", "reply":"PROBE_PASS"}, {"active_turn":False}, {"settled":True}]
        client._get.return_value = {"projection":{"runs":[{"id":"r"}], "turnItems":[{"runId":"r", "type":"tool_result", "ok":True}]}}
        with patch.dict(sys.modules, {"ghostship_t3":types.ModuleType("ghostship_t3"), "ghostship_t3.bridge":bridge_module, "ghostship_t3.models":models_module}):
            result = provider_probe.prove_route("codex/gpt-6.1-terra", 10, client, ("codex", "gpt-6.1-terra", {"serviceTier":"standard", "fastMode":False}))
        self.assertEqual(result["outcome"], "passed")
        self.assertTrue(result["settled"])
        self.assertEqual(client.submit.call_args.kwargs["options"], {"serviceTier":"standard", "fastMode":False})
        self.assertEqual(client.submit.call_args.kwargs["instance_id"], "codex")

    def setUp(self):
        allowed = {
            "opencode-free": ["safe", "fallback", "nvidia/first", "nvidia/fallback"],
            "commandCode": ["deepseek/deepseek-v4.1-flash"],
            "ollama": ["deepseek-v4.1-flash:1017"],
            "a": ["one"], "b": ["two"], "c": ["three"], "d": ["four"], "e": ["five"],
        }
        policy = {"schema": "ghostship.route-policy/v2", "providers": {p: {"admit": True} for p in allowed},
                  "routes": [{"provider": p, "provider_instance": p, "model": m, "admit": True,
                              "roles": ["worker"], "billing": "subscription"}
                             for p, models in allowed.items() for m in models]}
        policy_patch = patch.object(acceptance, "read_route_policy", return_value=policy)
        policy_patch.start()
        self.addCleanup(policy_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        (self.state / "desired").write_text("generation-502")
        self.home = self.root / "home"
        self.home.mkdir()
        (self.home / "agent-config").write_text("fixture")
        settings = self.home / ".t3/userdata/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"providerInstances": {
            "opencode-free": {
                "driver": "opencode", "enabled": True,
                "config": {"binaryPath": "opencode", "apiKey": "do-not-copy"},
                "environment": [
                    {"name": "OPENCODE_MODELS_PATH", "value": "/home/t3code/.local/state/t3code-opencode/models.json"},
                    {"name": "XDG_CONFIG_HOME", "value": "/home/t3code/.config/opencode-free"},
                    {"name": "OPENCODE_AUTH_CONTENT", "value": "do-not-copy"},
                ],
            },
            "private-provider": {"driver": "private", "config": {"token": "do-not-copy"}},
        }}))
        model_catalog = self.home / ".cache/opencode/models.json"
        model_catalog.parent.mkdir(parents=True)
        model_catalog.write_text(json.dumps({"openrouter": {
            "name": "OpenRouter", "models": {"provider/model": {}}
        }}))
        filtered_catalog = self.home / ".local/state/t3code-opencode/models.json"
        filtered_catalog.parent.mkdir(parents=True)
        filtered_catalog.write_text(json.dumps({"openrouter": {
            "name": "OpenRouter", "models": {"provider/model": {}}
        }}))
        self.archive = self.root / "image.tar"
        config = b'{"config":{"Entrypoint":["/nix/store/test/lib/systemd/systemd"]},"rootfs":{"diff_ids":["candidate"]}}'
        self.image_id = hashlib.sha256(config).hexdigest()
        with tarfile.open(self.archive, "w") as image:
            for name, content in (
                ("manifest.json", b'[{"Config":"config.json","RepoTags":["localhost/t3:test"]}]'),
                ("config.json", config),
            ):
                member = tarfile.TarInfo(name)
                member.size = len(content)
                image.addfile(member, io.BytesIO(content))
        self.commands = []

        def command(engine, *args, **kwargs):
            self.commands.append(tuple(args))
            if args[:1] == ("exec",) and args[2:4] == ("curl", "-fsS"):
                return Mock(returncode=0, stdout="ok")
            if args[:2] == ("inspect", "t3code-candidate-generation-502"):
                return Mock(returncode=0, stdout="true")
            return Mock(returncode=0, stdout="loaded localhost/t3:test")

        self.command = command
        self.identity = ["prod-id", "2026-10-25T00:00:00Z", 42, "13", "16"]

    def test_candidate_hostname_fits_linux_limit_for_sha256_deployments(self):
        first = acceptance.candidate_name("a" * 64)
        second = acceptance.candidate_name("b" * 64)

        self.assertLessEqual(len(first.encode()), 64)
        self.assertEqual(first, acceptance.candidate_name("a" * 64))
        self.assertNotEqual(first, second)

    def run_acceptance(self):
        with patch.object(acceptance, "command", side_effect=self.command), \
             patch.object(acceptance, "check_candidate", return_value={
                 name: True for name in acceptance.CHECKS
             }), \
             patch.object(acceptance.subprocess, "run", return_value=Mock(returncode=0)):
            return acceptance.accept(
                self.state, self.archive, "podman",
                "/run/t3code-podman-candidate/podman.sock", self.home,
                command_fn=self.command,
                identity_fn=lambda: self.identity,
            )

    def add_installed_toolchain(self, home=None):
        home = Path(home or self.home)
        t3 = home / ".local/share/t3code-tools/t3"
        (t3 / "releases/0.1.1/bin").mkdir(parents=True)
        runtime_t3 = home / ".t3/runtime/versions/0.1.1/t3"
        runtime_t3.parent.mkdir(parents=True)
        runtime_t3.write_text("#!/bin/sh\nexit 0\n")
        runtime_t3.chmod(0o755)
        cursor_sdk = home / ".t3/runtime/versions/0.1.1/node_modules/@cursor/sdk"
        cursor_sdk.mkdir(parents=True)
        (cursor_sdk / "package.json").write_text('{"name":"@cursor/sdk"}\n')
        (t3 / "releases/0.1.1/bin/t3").symlink_to(
            "/home/t3code/.t3/runtime/versions/0.1.1/t3"
        )
        (t3 / "current").symlink_to("releases/0.1.1")

        npm = home / ".local/share/t3code-tools/npm"
        codex = npm / "lib/node_modules/@openai/codex"
        (codex / "bin").mkdir(parents=True)
        (codex / "package.json").write_text('{"version":"1.2.3"}\n')
        (codex / "bin/codex.js").write_text("#!/usr/bin/env node\n")
        (codex / "bin/codex.js").chmod(0o755)
        (npm / "bin").mkdir(parents=True)
        (npm / "bin/codex").symlink_to("../lib/node_modules/@openai/codex/bin/codex.js")

        opencode = home / ".local/share/t3code-tools/opencode"
        (opencode / "releases/2.1.4/bin").mkdir(parents=True)
        executable = opencode / "releases/2.1.4/bin/opencode"
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
        (opencode / "current").symlink_to("releases/2.1.4")
        (npm / "bin/opencode").symlink_to(
            "/home/t3code/.local/share/t3code-tools/opencode/current/bin/opencode"
        )

        shared = home / ".local/state/t3code-shared-agents/bin"
        shared.mkdir(parents=True)
        for name in ("agent", "ghostship", "ghostship-bladebro"):
            launcher = shared / name
            launcher.write_text(
                "#!/bin/sh\nexec /nix/store/0123456789abcdefghijklmnopqrstuv-agent-runtime/bin/"
                + name + " \"$@\"\n"
            )
            launcher.chmod(0o755)
        local_bin = home / ".local/bin"
        local_bin.mkdir(parents=True)
        for name in ("agent", "ghostship", "ghostship-bladebro"):
            (local_bin / name).symlink_to(
                f"../state/t3code-shared-agents/bin/{name}"
            )

    def test_candidate_stages_only_the_active_production_cli_runtimes(self):
        self.add_installed_toolchain()
        candidate_home = self.root / "candidate-home"
        candidate_inputs = self.root / "candidate-inputs"

        toolchain = acceptance.stage_candidate_inputs(
            self.home, candidate_home, candidate_inputs, os.getuid(),
            tooling_path="/nix/store/pinned-agent-tools",
            stage_toolchain=True,
        )

        t3_root = candidate_home / ".local/share/t3code-tools/t3"
        self.assertEqual(os.readlink(t3_root / "current"), "releases/0.1.1")
        self.assertTrue((candidate_home / ".t3/runtime/versions/0.1.1/t3").is_file())
        self.assertTrue(os.access(candidate_home / ".t3/runtime/versions/0.1.1/t3", os.X_OK))
        self.assertTrue((candidate_home / ".t3/runtime/versions/0.1.1/node_modules/@cursor/sdk/package.json").is_file())
        npm = candidate_home / ".local/share/t3code-tools/npm"
        self.assertTrue((npm / "bin/codex").is_symlink())
        self.assertTrue((npm / "lib/node_modules/@openai/codex/bin/codex.js").is_file())
        self.assertTrue((npm / "bin/opencode").is_symlink())
        self.assertTrue((candidate_home / ".local/share/t3code-tools/opencode/releases/2.1.4/bin/opencode").is_file())
        for name in ("agent", "ghostship", "ghostship-bladebro"):
            self.assertTrue((candidate_home / ".local/state/t3code-shared-agents/bin" / name).is_file())
            self.assertTrue((candidate_home / ".local/bin" / name).is_symlink())
        self.assertEqual(toolchain, {"t3": "0.1.1", "codex": "1.2.3", "opencode": "2.1.4"})
        for link in (t3_root / "current", npm / "bin/codex", npm / "bin/opencode"):
            owner = link.stat(follow_symlinks=False)
            self.assertEqual((owner.st_uid, owner.st_gid), (os.getuid(), os.getuid()))
        self.assertFalse((candidate_home / ".codex").exists())

    def test_candidate_provider_auth_contains_only_owner_approved_provider_entries(self):
        auth = self.home / ".local/share/opencode/auth.json"
        auth.parent.mkdir(parents=True)
        auth.write_text(json.dumps({
            "openrouter": {"type": "api", "key": "auth-fixture"},
            "openai": {"type": "oauth", "refresh": "private-fixture"},
        }))
        approved = self.root / "approved-free-workers.json"
        approved.write_text(json.dumps({"entries": [{"provider": "openrouter"}]}))
        candidate_home = self.root / "candidate-home"
        candidate_home.mkdir()
        self.assertTrue(acceptance.stage_candidate_provider_auth(
            self.home, candidate_home, approved
        ))
        projected = json.loads((candidate_home / ".local/share/opencode/auth.json").read_text())
        self.assertEqual(projected, {"openrouter": {"type": "api", "key": "auth-fixture"}})
        self.assertEqual((candidate_home / ".local/share/opencode/auth.json").stat().st_mode & 0o777, 0o600)
        self.assertNotIn("private-fixture", json.dumps(projected))

    def test_candidate_model_routing_snapshot_is_validated_and_staged_read_only(self):
        source = self.root / "routing.json"
        source.write_text(json.dumps({
            "schema": "ghostship.ai-usage.routing", "schema_version": 1,
            "partial": False, "candidates": [],
        }))
        candidate_tmp = self.root / "candidate"
        candidate_tmp.mkdir()
        target = acceptance.stage_candidate_model_routing(source, candidate_tmp, os.getuid())
        self.assertEqual(target.read_text(), source.read_text())
        self.assertEqual(target.stat().st_mode & 0o777, 0o444)
        self.assertEqual(target.stat().st_uid, os.getuid())

    def test_candidate_model_routing_accepts_degraded_snapshot_with_a_usable_route(self):
        candidate_tmp = self.root / "candidate"
        candidate_tmp.mkdir()
        source = self.root / "routing.json"
        source.write_text(json.dumps({
            "schema": "ghostship.ai-usage.routing", "schema_version": 1, "partial": True,
            "coverage": {"sources_failed": 2, "tiers": {"bulk": {"state": "ok"}}},
            "candidates": [{"available": True, "key": "p:m"}],
        }))
        target = acceptance.stage_candidate_model_routing(source, candidate_tmp, os.getuid())
        self.assertEqual(target.read_text(), source.read_text())
        for broken in (
            {"partial": True, "coverage": {"sources_failed": 2, "tiers": {"bulk": {"state": "no_eligible_model"}}},
             "candidates": [{"available": True}]},
            {"partial": True, "coverage": {"sources_failed": 2, "tiers": {"bulk": {"state": "ok"}}},
             "candidates": [{"available": False}]},
        ):
            source.write_text(json.dumps({"schema": "ghostship.ai-usage.routing", "schema_version": 1, **broken}))
            with self.assertRaisesRegex(RuntimeError, "no usable candidate"):
                acceptance.stage_candidate_model_routing(source, candidate_tmp, os.getuid())

    def test_candidate_model_routing_accepts_partial_without_failed_sources(self):
        candidate_tmp = self.root / "candidate"
        candidate_tmp.mkdir()
        source = self.root / "routing.json"
        source.write_text(json.dumps({
            "schema": "ghostship.ai-usage.routing", "schema_version": 1, "partial": True,
            "coverage": {"sources_total": 13, "sources_ok": 12, "sources_partial": 1, "sources_failed": 0,
                         "tiers": {"bulk": {"state": "ok"}}},
            "candidates": [{"available": True}],
        }))
        target = acceptance.stage_candidate_model_routing(source, candidate_tmp, os.getuid())
        self.assertEqual(target.read_text(), source.read_text())
        for coverage in ({"sources_failed": 1}, {}, None):
            source.write_text(json.dumps({
                "schema": "ghostship.ai-usage.routing", "schema_version": 1, "partial": True,
                "coverage": coverage, "candidates": [],
            }))
            with self.assertRaisesRegex(RuntimeError, "no usable candidate"):
                acceptance.stage_candidate_model_routing(source, candidate_tmp, os.getuid())

    def test_routing_snapshot_refusals_are_retryable_preconditions(self):
        # The host's live snapshot is checked before the candidate runs, so its
        # refusals leave the image retryable (exit 75), unlike candidate failures.
        candidate_tmp = self.root / "candidate"
        candidate_tmp.mkdir()
        source = self.root / "routing.json"
        failed = {"schema": "ghostship.ai-usage.routing", "schema_version": 1, "partial": True,
                  "coverage": {"sources_failed": 1}, "candidates": []}
        for content in (None, "not json", json.dumps({"schema": "other"})):
            source.unlink(missing_ok=True)
            if content is not None:
                source.write_text(content)
            with self.assertRaises(acceptance.PreconditionError):
                acceptance.stage_candidate_model_routing(source, candidate_tmp, os.getuid())
        source.write_text(json.dumps(failed))
        with self.assertRaises(acceptance.RouteUnavailableError):
            acceptance.stage_candidate_model_routing(source, candidate_tmp, os.getuid())
        argv = ["candidate-acceptance", "--state-dir", "s", "--image-archive", "i", "--home-dir", "h",
                "--candidate-runtime-dir", "r", "--candidate-home-target", "/c", "--candidate-uid", "1"]
        with patch.object(sys, "argv", argv), \
                patch.object(acceptance, "accept", side_effect=acceptance.PreconditionError("live model routing snapshot has failed sources")), \
                self.assertRaises(SystemExit) as exited:
            acceptance.main()
        self.assertEqual(exited.exception.code, acceptance.PRECONDITION_EXIT)
        with patch.object(sys, "argv", argv), \
                patch.object(acceptance, "accept", side_effect=RuntimeError("candidate acceptance failed")), \
                self.assertRaisesRegex(RuntimeError, "candidate acceptance failed"):
            acceptance.main()

    def test_candidate_stages_missing_shared_agent_store_paths_from_production(self):
        self.add_installed_toolchain()
        agent_wrapper = self.home / ".local/state/t3code-shared-agents/bin/agent"
        agent_wrapper.write_text(
            "#!/bin/sh\nexec /home/t3code/.local/state/ghostship/hotfix/test/agent-wrapper \"$@\"\n"
        )
        candidate_home = self.root / "candidate-home"
        candidate_inputs = self.root / "candidate-inputs"
        acceptance.stage_candidate_inputs(
            self.home, candidate_home, candidate_inputs, os.getuid(),
            tooling_path="/nix/store/pinned-agent-tools", stage_toolchain=True,
        )
        store_path = "/nix/store/0123456789abcdefghijklmnopqrstuv-agent-runtime"
        calls = []

        def run(args, **kwargs):
            calls.append(tuple(args))
            if "path-info" in args:
                return Mock(returncode=0, stdout=json.dumps({store_path: {"narSize": 1}}))
            if len(args) > 2 and str(args[2]).startswith("t3code:/home/t3code/"):
                copied_wrapper = candidate_home / ".local/state/ghostship/hotfix/test/agent-wrapper"
                copied_wrapper.parent.mkdir(parents=True, exist_ok=True)
                copied_wrapper.write_text(
                    "#!/bin/sh\nexec /nix/store/0123456789abcdefghijklmnopqrstuv-agent-runtime/bin/agent \"$@\"\n"
                )
                copied_wrapper.chmod(0o755)
                return Mock(returncode=0, stdout="")
            staged = self.root / "candidate-runtime/nix-store-overlay" / Path(store_path).name
            staged.mkdir(parents=True)
            return Mock(returncode=0, stdout="")

        candidate_tmp = self.root / "candidate-runtime"
        candidate_tmp.mkdir()
        with patch.object(acceptance.subprocess, "run", side_effect=run):
            overlays = acceptance.stage_candidate_agent_store(
                "podman", self.home, candidate_tmp, candidate_home, os.getuid()
            )
        self.assertEqual(overlays, [(str(candidate_tmp / "nix-store-overlay" / Path(store_path).name), store_path)])
        self.assertEqual(len([call for call in calls if "path-info" in call]), 1)
        self.assertTrue(any("t3code:" + store_path in call for call in calls))
        self.assertTrue((candidate_home / ".local/state/ghostship/hotfix/test/agent-wrapper").is_file())
        for path in (
            candidate_home / ".local/state/ghostship",
            candidate_home / ".local/state/ghostship/hotfix",
            candidate_home / ".local/state/ghostship/hotfix/test",
        ):
            self.assertEqual(path.stat().st_uid, os.getuid())

    def test_candidate_mount_policy_allows_only_ephemeral_store_overlay(self):
        self.assertEqual(
            acceptance.validate_candidate_mounts(["/nix/store:/nix/store:O"]),
            ["/nix/store:/nix/store:O"],
        )
        with self.assertRaisesRegex(ValueError, "allowlist"):
            acceptance.validate_candidate_mounts(["/nix/store:/nix/store:rw"])

    def test_pass_writes_exact_receipt_and_removes_the_candidate(self):
        receipt = self.run_acceptance()
        path = self.state / "receipts/generation-502.json"
        self.assertEqual(json.loads(path.read_text()), receipt)
        self.assertEqual(receipt["deployment_id"], "generation-502")
        self.assertEqual(receipt["image_id"], self.image_id)
        self.assertEqual(receipt["candidate_name"], "t3code-candidate-generation-502")
        self.assertEqual(receipt["live_before"], receipt["live_after"])
        self.assertEqual(set(receipt["checks"]), set(acceptance.CHECKS))
        self.assertTrue(all(receipt["checks"].values()))
        self.assertIn(("rm", "--force", "--time", "10", receipt["candidate_name"]), self.commands)
        self.assertTrue(any("/run/secrets/t3code.env:ro" in str(command)
                            for command in self.commands))
        self.assertFalse(any("production" in str(command) for command in self.commands))
        self.assertFalse(any(command[:1] == ("stop",) for command in self.commands))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

        run = next(command for command in self.commands if command[:1] == ("run",))
        self.assertIn("--user=0:0", run)
        self.assertLess(run.index("--user=0:0"), run.index("localhost/t3:test"))
        run_volumes = [run[index + 1] for index, token in enumerate(run[:-1])
                       if token == "--volume"]
        targets = [volume.split(":", 2)[1] for volume in run_volumes]
        workspace_volume = next(volume for volume in run_volumes
                                if volume.split(":", 2)[1] == "/workspace")
        self.assertTrue(workspace_volume.endswith(":/workspace:rw"))
        self.assertNotEqual(workspace_volume.split(":", 1)[0], str(self.home))
        self.assertNotIn("/tmp", targets)
        self.assertNotIn("/nix", targets)
        self.assertNotIn(":/nix/store:rw", run_volumes)
        self.assertNotIn(str(self.home), [volume.split(":", 1)[0] for volume in run_volumes])
        self.assertIn(":/candidate-home:rw", run_volumes[0])
        self.assertTrue(any("/run/t3code-candidate-inputs:ro" in v for v in run_volumes))
        image_tag = run.index("localhost/t3:test")
        unit_option = run.index("--unit=t3code-server.service")
        self.assertGreater(unit_option, image_tag)
        self.assertEqual(run[image_tag + 1:], ("--unit=t3code-server.service",))
        self.assertNotIn("--unit=multi-user.target", run)

    def test_image_details_rejects_a_missing_systemd_entrypoint(self):
        archive_path = self.root / "image-without-entrypoint.tar"
        with tarfile.open(archive_path, "w") as image:
            for name, content in (
                ("manifest.json", b'[{"Config":"config.json","RepoTags":["localhost/t3:test"]}]'),
                ("config.json", b'{"config":{"Cmd":["/nix/store/test-systemd"]},"rootfs":{"diff_ids":["candidate"]}}'),
            ):
                member = tarfile.TarInfo(name)
                member.size = len(content)
                image.addfile(member, io.BytesIO(content))
        with self.assertRaisesRegex(RuntimeError, "systemd entrypoint"):
            acceptance.image_details(archive_path)

    def test_early_candidate_exit_reports_its_exit_code(self):
        def command(engine, *args, **kwargs):
            if args[:4] == ("exec", "candidate", "systemctl", "start"):
                return Mock(returncode=0, stdout="")
            if args[:1] == ("exec",):
                return Mock(returncode=1, stdout="")
            if args[:1] == ("inspect",):
                return Mock(returncode=0, stdout='{"Running":false,"ExitCode":255}')
            return Mock(returncode=1, stdout="")

        with patch.object(acceptance, "command", side_effect=command):
            with self.assertRaisesRegex(RuntimeError, r"exited before app readiness \(exit code 255\)"):
                acceptance.check_candidate(["podman"], "candidate", "provider.env")

    def test_candidate_readiness_starts_the_frontend_proxy_unit(self):
        calls = []

        def command(engine, *args, **kwargs):
            calls.append(tuple(args))
            if args[:4] == ("exec", "candidate", "systemctl", "start"):
                return Mock(returncode=0, stdout="")
            if args[:4] == ("exec", "candidate", "curl", "-fsS"):
                return Mock(returncode=0, stdout="ok")
            if args[:3] == ("exec", "candidate", "agent"):
                return Mock(returncode=0, stdout="ok")
            return Mock(returncode=0, stdout=json.dumps({"data": {"pick": {
                "provider": "openrouter", "model": "cohere/north-mini-code:free",
                "billing": "free", "approved_free": True, "execution": "t3",
                "available": True,
            }}}))

        with patch.object(acceptance, "command", side_effect=command), \
             patch.object(acceptance, "check_provider_turn", return_value=True):
            checks = acceptance.check_candidate(
                ["podman"], "candidate", "provider.env", tooling_path="/nix/store/test-agent"
            )
        self.assertTrue(all(checks.values()))
        self.assertIn(("exec", "candidate", "systemctl", "start",
                       "t3code-access-proxy.service"), calls)
        self.assertIn(("exec", "--user=3000:3000", "candidate", "t3", "project",
                       "add", "/workspace", "--title", "Candidate acceptance"), calls)

    def test_staging_never_copies_oauth_credentials_and_keeps_only_agent_skills(self):
        oauth_paths = (
            ".codex/auth.json", ".claude/.credentials.json",
            ".gemini/oauth_creds.json", ".gemini/antigravity-cli/oauth_creds.json",
            ".config/opencode/auth.json", ".local/share/opencode/auth.json",
        )
        for relative in oauth_paths:
            source = self.home / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("refresh token fixture")
        skill = self.home / ".agents/skills/candidate-check/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("skill fixture")
        (self.home / ".t3/userdata").mkdir(parents=True, exist_ok=True)
        (self.home / ".t3/userdata/state.sqlite").write_text("live threads")
        (self.home / ".t3/worktrees/project").mkdir(parents=True)
        (self.home / ".t3/worktrees/project/file").write_text("live checkout")
        candidate_home = self.root / "candidate-home"
        candidate_inputs = self.root / "candidate-inputs"
        acceptance.stage_candidate_inputs(
            self.home, candidate_home, candidate_inputs, os.getuid(),
            tooling_path="/nix/store/pinned-agent-tools",
        )
        for relative in oauth_paths:
            with self.subTest(path=relative):
                self.assertFalse((candidate_inputs / relative).exists())
                self.assertFalse((candidate_home / relative).is_symlink())
        self.assertEqual((candidate_inputs / ".agents/skills/candidate-check/SKILL.md").read_text(),
                         "skill fixture")
        staged_probe = candidate_inputs / "provider-turn-probe.py"
        self.assertEqual(staged_probe.read_bytes(),
                         (ROOT / "packages/t3code/provider-turn-probe.py").read_bytes())
        self.assertEqual(staged_probe.stat().st_mode & 0o777, 0o444)
        self.assertFalse((candidate_inputs / ".t3").exists())
        candidate_settings = json.loads(
            (candidate_home / ".t3/userdata/settings.json").read_text()
        )
        self.assertEqual(list(candidate_settings["providerInstances"]), ["opencode-free"])
        projected = candidate_settings["providerInstances"]["opencode-free"]
        self.assertEqual(projected["config"], {"binaryPath": "opencode"})
        self.assertEqual([item["name"] for item in projected["environment"]], [
            "OPENCODE_MODELS_PATH", "XDG_CONFIG_HOME",
        ])
        self.assertNotIn("do-not-copy", json.dumps(candidate_settings))
        self.assertFalse((candidate_home / ".t3/userdata/state.sqlite").exists())
        self.assertEqual(
            json.loads((candidate_home / ".cache/opencode/models.json").read_text()),
            {"openrouter": {"name": "OpenRouter", "models": {"provider/model": {}}}},
        )
        self.assertEqual(
            json.loads((candidate_home / ".local/state/t3code-opencode/models.json").read_text()),
            {"openrouter": {"name": "OpenRouter", "models": {"provider/model": {}}}},
        )
        for relative in (
            ".agents/skills",
            ".local/state/ghostship-t3-tools/current",
        ):
            link = candidate_home / relative
            self.assertTrue(link.is_symlink())
            owner = link.stat(follow_symlinks=False)
            self.assertEqual((owner.st_uid, owner.st_gid), (os.getuid(), os.getuid()))

    def test_provider_turn_does_not_probe_unadmitted_minimax(self):
        provider_env = self.root / "provider.env"
        provider_env.write_text("")
        calls = []

        def command(engine, *args, **kwargs):
            calls.append(tuple(args))
            if "pick" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"pick": {
                    "provider": "opencode-free", "model": "nvidia/minimaxai/minimax-m3.1-flash",
                    "billing": "free", "approved_free": True, "execution": "t3",
                    "available": True,
                    "target": {"providerInstanceId": "opencode-free", "model": "nvidia/minimaxai/minimax-m3.1-flash"},
                }}}))
            return self.probe_success(args) if "--instance" in args else Mock(returncode=0, stdout="passed")

        with patch.object(acceptance, "command", side_effect=command):
            with self.assertRaises(acceptance.RouteUnavailableError):
                acceptance.check_provider_turn(["podman"], "candidate", provider_env, tooling_path="/nix/store/test-agent")
        self.assertTrue(any("pick" in call and "--role" in call and "worker" in call
                            and "--kind" in call and "code" in call for call in calls))
        self.assertFalse(self.probe_calls(calls))

    def test_candidate_error_classification_does_not_include_command_output(self):
        self.assertEqual(acceptance.candidate_error_category(Mock(
            returncode=1, stderr="PermissionError: runtime ownership denied"
        )), "exception-permissionerror")
        self.assertEqual(acceptance.candidate_error_category(Mock(
            returncode=1, stderr="RuntimeError: provider request failed"
        )), "exception-runtimeerror")
        self.assertEqual(acceptance.candidate_error_category(Mock(
            returncode=1, stderr="", stdout='{"status":"error","message":"private"}'
        )), "api-error")
        detail = acceptance.candidate_error_summary(Mock(
            returncode=1,
            stderr="OPENROUTER_API_KEY=do-not-print\nRuntimeError: failed under /tmp/private-path",
        ))
        self.assertNotIn("do-not-print", detail)
        self.assertNotIn("private-path", detail)
        detail = acceptance.candidate_error_summary(Mock(
            returncode=1,
            stderr='{"data":{"error":"Unauthorized request using private-token"}}',
        ))
        self.assertEqual(detail, "api-error-request-unauthorized")
        self.assertNotIn("private-token", detail)

    def test_missing_native_t3_route_leaves_no_accepting_receipt_and_tears_down(self):
        def no_route(engine, *args, **kwargs):
            self.commands.append(tuple(args))
            if "pick" in args:
                return Mock(returncode=1, stderr='{"data":{"error":"model unavailable"}}')
            return self.command(engine, *args, **kwargs)

        with patch.object(acceptance, "command", side_effect=no_route), \
             patch.object(acceptance.subprocess, "run", return_value=Mock(returncode=0)):
            with self.assertRaises(acceptance.RouteUnavailableError):
                acceptance.accept(
                    self.state, self.archive, "podman",
                    "/run/t3code-podman-candidate/podman.sock", self.home,
                    command_fn=no_route, identity_fn=lambda: self.identity,
                )
        self.assertFalse((self.state / "receipts/generation-502.json").exists())
        self.assertIn(("rm", "--force", "--time", "10", "t3code-candidate-generation-502"),
                      self.commands)

    def test_provider_turn_uses_an_admitted_subscription_route_when_no_free_route_is_available(self):
        provider_env = self.root / "provider.env"
        provider_env.write_text("")
        calls = []

        def command(engine, *args, **kwargs):
            calls.append(tuple(args))
            if "pick" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"pick": {
                    "provider": "commandCode", "model": "deepseek/deepseek-v4.1-flash",
                    "billing": "subscription", "execution": "t3", "available": True,
                    "target": {"providerInstanceId": "commandCode", "model": "deepseek/deepseek-v4.1-flash"},
                }}}))
            return self.probe_success(args) if "--instance" in args else Mock(returncode=0, stdout="passed")

        with patch.object(acceptance, "command", side_effect=command):
            self.assertEqual(acceptance.check_provider_turn(
                ["podman"], "candidate", provider_env,
                tooling_path="/nix/store/test-agent",
            ), "commandCode/deepseek/deepseek-v4.1-flash")
        self.assertTrue(any(any(item.endswith("provider-turn-probe.py") for item in call) and
                            "commandCode/deepseek/deepseek-v4.1-flash" in call for call in calls))

    def test_provider_turn_never_spends_a_protected_premium_route(self):
        provider_env = self.root / "provider.env"
        provider_env.write_text("")
        for provider, model in (("codex", "gpt-6.1-sol"), ("claude", "claude-opus-5-5"),
                                ("claudeAgent", "claude-sonnet-5-5")):
            with self.subTest(provider=provider):
                pick = {"data": {"pick": {"provider": provider, "model": model,
                                          "billing": "subscription", "execution": "t3",
                                          "available": True}}}
                with patch.object(acceptance, "command", return_value=Mock(
                        returncode=0, stdout=json.dumps(pick))) as command:
                    with self.assertRaises(acceptance.RouteUnavailableError):
                        acceptance.check_provider_turn(["podman"], "candidate", provider_env,
                                                       tooling_path="/nix/store/test-agent")
                self.assertFalse(any(any(str(item).endswith("provider-turn-probe.py") for item in call.args)
                                     for call in command.call_args_list))

    def test_protected_pick_uses_admitted_fallback(self):
        pick = {"provider": "claude", "model": "sonnet", "billing": "subscription", "execution": "t3", "available": True}
        fallback = {"provider": "opencode-free", "model": "fallback", "billing": "free", "approved_free": True, "execution": "t3", "available": True, "target": {"providerInstanceId": "opencode-free", "model": "fallback"}}
        def call(engine, *args, **kwargs):
            if "pick" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"pick": pick}}))
            if "models" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"selected": [pick, fallback]}}))
            return self.probe_success(args) if "--instance" in args else Mock(returncode=0, stdout="passed")
        with patch.object(acceptance, "command", side_effect=call):
            self.assertEqual(acceptance.check_provider_turn(["podman"], "candidate", None, tooling_path="agent"), "opencode-free/fallback")

    def test_protected_approved_free_picker_and_catalog_are_never_probed(self):
        fallback = {"provider": "opencode-free", "model": "safe", "billing": "free",
                    "approved_free": True, "execution": "t3", "available": True, "target": {"providerInstanceId": "opencode-free", "model": "safe"}}
        for provider in ("codex", "claude", "claudeAgent"):
            protected = {**fallback, "provider": provider, "target": {"providerInstanceId": provider, "model": "safe"}}
            for protected_pick in (True, False):
                with self.subTest(provider=provider, protected_pick=protected_pick):
                    calls = []
                    def call(engine, *args, **kwargs):
                        calls.append(args)
                        if "pick" in args:
                            return Mock(returncode=0, stdout=json.dumps({"data": {"pick": protected if protected_pick else {}}}))
                        if "models" in args:
                            return Mock(returncode=0, stdout=json.dumps({"data": {"selected": [protected, fallback]}}))
                        return self.probe_success(args) if "--instance" in args else Mock(returncode=0, stdout="passed")
                    with patch.object(acceptance, "command", side_effect=call):
                        self.assertEqual(acceptance.check_provider_turn(["podman"], "candidate", None, tooling_path="agent"), "opencode-free/safe")
                    probes = [call for call in calls if any(str(arg).endswith("provider-turn-probe.py") for arg in call)]
                    self.assertEqual(len(probes), 1)
                    self.assertIn("opencode-free/safe", probes[0])

    def test_provider_failure_persists_summary_in_attempt(self):
        failure = acceptance.ProviderTurnError("claude/sonnet", "opencode-free/fallback", "failed")
        attempts = self.state / "attempts"
        attempts.mkdir()
        (attempts / "generation-502.json").write_text('{"status":"running"}')
        with patch.object(acceptance, "command", side_effect=self.command), \
             patch.object(acceptance, "check_candidate", side_effect=failure), \
             patch.object(acceptance.subprocess, "run", return_value=Mock(returncode=0)):
            with self.assertRaises(acceptance.ProviderTurnError):
                acceptance.accept(self.state, self.archive, "podman", "/socket", self.home,
                                  command_fn=self.command, identity_fn=lambda: self.identity)
        record = json.loads((attempts / "generation-502.json").read_text())
        self.assertEqual(record["provider_turn"], {"pick": "claude/sonnet", "routes": "opencode-free/fallback", "evidence": "failed"})

    def test_provider_turn_refuses_free_pool_routes_for_t3_execution(self):
        provider_env = self.root / "provider.env"
        provider_env.write_text("")
        pick = {"data": {"pick": {
            "provider": "opencode-free", "model": "model", "billing": "free",
            "approved_free": True, "execution": "free_pool", "available": True,
        }}}
        with patch.object(acceptance, "command", return_value=Mock(
                returncode=0, stdout=json.dumps(pick))) as command:
            with self.assertRaises(acceptance.RouteUnavailableError):
                acceptance.check_provider_turn(
                    ["podman"], "candidate", provider_env,
                    tooling_path="/nix/store/test-agent",
                )
        self.assertFalse(any("models" in call.args and "prove" in call.args
                             for call in command.call_args_list))

    def test_provider_turn_falls_back_after_model_unavailable_and_records_route(self):
        provider_env = self.root / "provider.env"
        provider_env.write_text("")
        first = {"provider": "opencode-free", "model": "nvidia/first",
                 "billing": "free", "approved_free": True,
                 "execution": "t3", "available": True, "target": {"providerInstanceId": "opencode-free", "model": "nvidia/first"}}
        fallback = {"provider": "opencode-free", "model": "nvidia/fallback",
                    "billing": "free", "approved_free": True,
                    "execution": "t3", "available": True, "target": {"providerInstanceId": "opencode-free", "model": "nvidia/fallback"}}
        calls = []

        def command(engine, *args, **kwargs):
            calls.append(tuple(args))
            if any(item.endswith("provider-turn-probe.py") for item in args):
                route = next(item for item in args if item.startswith("opencode-free/"))
                if route.endswith("/first"):
                    return Mock(returncode=1, stderr="", stdout=json.dumps({
                        "outcome": "execution",
                        "settled": True,
                        "error": {"code": provider_probe.safe_failure_code({
                            "outcome": "execution", "detail": "model unavailable"
                        })},
                    }))
                return self.probe_success(args) if "--instance" in args else Mock(returncode=0, stdout="passed")
            if "pick" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"pick": first}}))
            if "models" in args and "--json" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"selected": [first, fallback]}}))
            return Mock(returncode=0, stdout="present")

        with patch.object(acceptance, "command", side_effect=command):
            self.assertEqual(acceptance.check_provider_turn(
                ["podman"], "candidate", provider_env,
                tooling_path="/nix/store/test-agent",
            ), "opencode-free/nvidia/fallback")
        proved = [next(item for item in call if item.startswith("opencode-free/"))
                  for call in calls
                  if any(item.endswith("provider-turn-probe.py") for item in call)]
        self.assertEqual(proved, ["opencode-free/nvidia/first", "opencode-free/nvidia/fallback"])

    def subscription_rows(self, *names):
        return [{"provider": provider, "model": model, "billing": "subscription",
                 "execution": "t3", "available": True, "target": {"providerInstanceId": provider, "model": model}}
                for provider, model in (name.split("/", 1) for name in names)]

    def probe_calls(self, calls):
        return [call for call in calls if any(item.endswith("provider-turn-probe.py") for item in call)]

    def probe_success(self, args):
        instance = args[args.index("--instance") + 1]
        model = args[args.index("--native-model") + 1]
        return Mock(returncode=0, stdout=json.dumps({"outcome":"passed", "settled":True, "instance":instance, "model":model}), stderr="")

    def test_provider_turn_tries_the_next_admitted_route_after_an_api_error(self):
        provider_env = self.root / "provider.env"
        provider_env.write_text("")
        rows = self.subscription_rows("ollama/deepseek-v4.1-flash:1017", "commandCode/deepseek/deepseek-v4.1-flash")
        calls = []

        def command(engine, *args, **kwargs):
            calls.append(tuple(args))
            if any(item.endswith("provider-turn-probe.py") for item in args):
                if "ollama/deepseek-v4.1-flash:1017" in args:
                    return Mock(returncode=1, stderr="", stdout='{"settled":true,"error":{"code":"quota"}}')
                return self.probe_success(args) if "--instance" in args else Mock(returncode=0, stdout="passed")
            if "pick" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"pick": rows[0]}}))
            if "models" in args and "--json" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"selected": rows}}))
            return Mock(returncode=0, stdout="present")

        with patch.object(acceptance, "command", side_effect=command):
            self.assertEqual(acceptance.check_provider_turn(
                ["podman"], "candidate", provider_env, tooling_path="/nix/store/test-agent",
            ), "commandCode/deepseek/deepseek-v4.1-flash")
        self.assertEqual(len(self.probe_calls(calls)), 2)

    def test_provider_turn_probes_at_most_three_routes_then_fails(self):
        provider_env = self.root / "provider.env"
        provider_env.write_text("")
        rows = self.subscription_rows("a/one", "b/two", "c/three", "d/four", "e/five")
        calls = []

        def command(engine, *args, **kwargs):
            calls.append(tuple(args))
            if any(item.endswith("provider-turn-probe.py") for item in args):
                return Mock(returncode=1, stderr="", stdout='{"settled":true,"error":{"code":"quota"}}')
            if "pick" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"pick": rows[0]}}))
            if "models" in args and "--json" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"selected": rows}}))
            return Mock(returncode=0, stdout="present")

        with patch.object(acceptance, "command", side_effect=command):
            with self.assertRaises(acceptance.RouteUnknownError):
                acceptance.check_provider_turn(["podman"], "candidate", provider_env,
                                               tooling_path="/nix/store/test-agent")
        self.assertEqual(len(self.probe_calls(calls)), acceptance.MAX_ACCEPTANCE_ROUTES)

    def test_provider_probe_runs_without_retired_prove_module(self):
        tools = self.root / "agent" / "tools" / "python" / "ghostship_t3"
        tools.mkdir(parents=True)
        (tools / "__init__.py").write_text("")
        (tools / "bridge.py").write_text("""class T3Error(Exception): pass
class Bridge:
    def submit(self, prompt, **kwargs):
        assert kwargs['workspace_root'] == '/workspace'
        assert kwargs['instance_id'] == 'native' and kwargs['model'] == 'model'
        return {'thread_id': 'probe'}
    def status(self, thread_id, wait_s=0):
        return {'state': 'completed', 'reply': 'PROBE_PASS', 'settled': wait_s == 10, 'active_turn': False}
    def settle(self, thread_id): pass
    def _get(self, path):
        return {'projection': {'runs': [{'id': 'run'}], 'turnItems': [{'runId': 'run', 'type': 'tool_result', 'ok': True}]}}
""")
        (tools / "models.py").write_text("""def read_document(): return {}
def _selection(document, now):
    return {'worker': [{'provider': 'p', 'model': 'm', 'native': {'instanceId': 'native', 'model': 'model'}}]}
""")
        env = {**os.environ, 'GHOSTSHIP_TOOLS_ROOT': str(self.root / 'agent')}
        proc = subprocess.run([sys.executable, str(ROOT / 'packages/t3code/provider-turn-probe.py'), 'p/m'],
                              env=env, text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['outcome'], 'passed')
        self.assertTrue(json.loads(proc.stdout)['settled'])

    def test_provider_probe_rejects_marker_without_successful_tool_result(self):
        bridge_module = types.ModuleType("ghostship_t3.bridge")
        bridge_module.T3Error = type("T3Error", (Exception,), {})
        models_module = types.ModuleType("ghostship_t3.models")
        models_module.read_document = lambda: {}
        models_module._selection = lambda document, now: {"worker": [{"provider": "p", "model": "m", "native": {"instanceId": "n", "model": "m"}}]}
        client = Mock()
        client.submit.return_value = {"thread_id": "probe"}
        client.status.side_effect = [{"state": "completed", "reply": "PROBE_PASS"}, {}, {"settled": True}]
        client._get.return_value = {"projection": {"runs": [{"id": "r"}], "turnItems": []}}
        with patch.dict(sys.modules, {"ghostship_t3": types.ModuleType("ghostship_t3"),
                                      "ghostship_t3.bridge": bridge_module,
                                      "ghostship_t3.models": models_module}):
            result = provider_probe.prove_route("p/m", 1, client)
        self.assertEqual(result["outcome"], "no_tool_call")
        self.assertTrue(result["settled"])

    def test_tool_result_requires_same_single_run_and_explicit_success(self):
        client = Mock()
        for runs, items in [
            ([{"id": "r"}], [{"runId": "other", "type": "tool_result", "ok": True}]),
            ([{"id": "r"}], [{"runId": "r", "type": "tool_result", "ok": False}]),
            ([{"id": "r"}], [{"runId": "r", "type": "tool_result"}]),
            ([{"id": "r"}, {"id": "s"}], [{"runId": "r", "type": "tool_result", "ok": True}]),
        ]:
            with self.subTest(runs=runs, items=items):
                client._get.return_value = {"projection": {"runs": runs, "turnItems": items}}
                self.assertFalse(provider_probe.has_tool_result(client, "probe"))

    def test_provider_probe_requires_settlement_and_cancels_active_turn(self):
        bridge_module = types.ModuleType("ghostship_t3.bridge")
        bridge_module.T3Error = type("T3Error", (Exception,), {})
        models_module = types.ModuleType("ghostship_t3.models")
        models_module.read_document = lambda: {}
        models_module._selection = lambda document, now: {"worker": [{"provider": "p", "model": "m", "native": {"instanceId": "n", "model": "m"}}]}
        client = Mock()
        client.submit.return_value = {"thread_id": "probe"}
        client.status.side_effect = [
            {"state": "running", "active_turn": True},
            {"active_turn": True},
            {"active_turn": False},
            {"settled": False},
        ]
        with patch.dict(sys.modules, {"ghostship_t3": types.ModuleType("ghostship_t3"),
                                      "ghostship_t3.bridge": bridge_module,
                                      "ghostship_t3.models": models_module}):
            result = provider_probe.prove_route("p/m", 1, client)
        self.assertEqual(result["outcome"], "timeout")
        self.assertFalse(result["settled"])
        client.cancel.assert_called_once_with("probe")
        client.settle.assert_called_once_with("probe")

    def test_provider_probe_carries_safe_model_unavailable_category(self):
        result = {"outcome": "execution", "detail": "model unavailable: private provider response"}
        self.assertEqual(provider_probe.safe_failure_code(result), "model-unavailable")
        self.assertNotIn("private provider response", json.dumps({
            "error": {"code": provider_probe.safe_failure_code(result)},
        }))

    def test_provider_projection_excludes_github_and_bitwarden_secrets(self):
        projection = self.root / "provider.env"
        projection.write_text(
            "OPENROUTER_API_KEY='provider-only'\n"
            "AGENT_DESKTOP_API_TOKEN=desktop-only\n"
            "GOOGLE_GENERATIVE_AI_API_KEY=''\n"
            "GITHUB_TOKEN=must-not-copy\n"
            "BW_CLIENTSECRET=must-not-copy\n"
        )
        filtered = acceptance.write_provider_env(projection, self.root / "candidate.env")
        self.assertEqual(filtered.read_text(),
                         "OPENROUTER_API_KEY=provider-only\n"
                         "AGENT_DESKTOP_API_TOKEN=desktop-only\n")
        self.assertEqual(filtered.stat().st_mode & 0o777, 0o400)

    def test_candidate_systemd_does_not_run_bootstrap_or_home_hooks(self):
        server, bootstrap = acceptance.write_candidate_systemd_overrides(self.root)
        self.assertEqual((server / "10-candidate.conf").read_text(),
                         "[Service]\nExecStartPre=\nExecStartPost=\n")
        self.assertEqual((bootstrap / "10-candidate.conf").read_text(),
                         "[Service]\nExecStart=\nExecStart=/bin/true\n")

    def test_candidate_mount_allowlist_rejects_production_home_workspace_tmp_and_rw_store(self):
        for mount in (
            "/var/lib/production-t3-home:/candidate-home:rw",
            "/workspace:/workspace:rw",
            "/var/lib/production-t3-tmp:/tmp:rw",
            "/var/lib/production-t3-nix/nix:/nix:rw",
        ):
            with self.subTest(mount=mount), self.assertRaisesRegex(ValueError, "allowlist"):
                acceptance.validate_candidate_mounts([mount])

    def test_candidate_receipt_binds_the_agent_pin_and_provider_inode(self):
        secrets = self.root / "t3code.env"
        secrets.write_text("OPENROUTER_API_KEY=provider-fixture\nGITHUB_TOKEN=excluded\n")
        self.add_installed_toolchain()
        pinned_tooling = "/nix/store/pinned-agent-tools"
        staged = str(self.root / "agent-runtime")
        with patch.object(acceptance, "command", side_effect=self.command), \
             patch.object(acceptance, "check_candidate", return_value={
                 name: True for name in acceptance.CHECKS
             }), patch.object(acceptance, "candidate_agent_path", return_value=pinned_tooling), \
             patch.object(acceptance, "stage_candidate_agent_store", return_value=[
                 (staged, "/nix/store/0123456789abcdefghijklmnopqrstuv-agent-runtime")
             ]), \
             patch.object(acceptance.subprocess, "run", return_value=Mock(returncode=0)):
            receipt = acceptance.accept(
                self.state, self.archive, "podman",
                "/run/t3code-podman-candidate/podman.sock", self.home,
                command_fn=self.command, identity_fn=lambda: self.identity,
                candidate_uid=os.getuid(), provider_secrets_file=secrets,
                tooling_path=pinned_tooling, expected_agent_revision="a" * 40,
                candidate_home_target="/home/t3code",
            )
        self.assertEqual(receipt["agent_revision"], "a" * 40)
        self.assertEqual(receipt["agent_path"], pinned_tooling)
        self.assertEqual(receipt["provider_secret_inode"], str(secrets.stat().st_ino))
        self.assertIn(("cp", staged, f"{receipt['candidate_name']}:/nix/store/"), self.commands)

    def test_a_failed_acceptance_never_leaves_an_approving_receipt(self):
        failing = {name: True for name in acceptance.CHECKS}
        failing["provider_turn"] = False
        with patch.object(acceptance, "command", side_effect=self.command), \
             patch.object(acceptance, "check_candidate", return_value=failing), \
             patch.object(acceptance.subprocess, "run", return_value=Mock(returncode=0)):
            with self.assertRaisesRegex(RuntimeError, "acceptance failed"):
                acceptance.accept(
                    self.state, self.archive, "podman",
                    "/run/t3code-podman-candidate/podman.sock", self.home,
                    command_fn=self.command,
                    identity_fn=lambda: self.identity,
                )
        self.assertFalse((self.state / "receipts/generation-502.json").exists())
        self.assertIn(("rm", "--force", "--time", "10", "t3code-candidate-generation-502"),
                      self.commands)

    def test_a_changed_production_identity_prevents_receipt_creation(self):
        observations = iter([self.identity, [*self.identity[:2], 99, *self.identity[3:]],
                             self.identity])
        with patch.object(acceptance, "command", side_effect=self.command), \
             patch.object(acceptance, "check_candidate", return_value={
                 name: True for name in acceptance.CHECKS
             }), \
             patch.object(acceptance.subprocess, "run", return_value=Mock(returncode=0)):
            with self.assertRaisesRegex(RuntimeError, "production T3 identity changed"):
                acceptance.accept(
                    self.state, self.archive, "podman",
                    "/run/t3code-podman-candidate/podman.sock", self.home,
                    command_fn=self.command,
                    identity_fn=lambda: next(observations),
                )
        self.assertFalse((self.state / "receipts/generation-502.json").exists())


if __name__ == "__main__":
    unittest.main()
