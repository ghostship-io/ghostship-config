"""Candidate acceptance creates only exact, production-preserving receipts."""
import hashlib
import importlib.util
import io
import json
import os
import sys
from pathlib import Path
import tarfile
import tempfile
import unittest
from datetime import datetime, timezone
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
            "candidate-acceptance.py", "hardening-probe.py",
            "provider-turn-probe.py", "runtime-caps.json",
        ):
            with self.subTest(name=name):
                self.assertIn(f"$out/{name}", module)
                self.assertIn(f"packages/t3code/{name}", module)
        self.assertIn('name = "ghostship-t3code-deploy-image"', module)
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
    ROUTING_NOW = 1_800_000_000

    def setUp(self):
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

    def routing_row(self, provider, model, instance_id=None, *, role="worker"):
        native = {"instanceId": instance_id or provider, "model": model}
        return {
            "provider": provider,
            "model": model,
            "native": native,
            "available": True,
            "selection_eligible": True,
            "picker_eligible": True,
            "billing": "subscription",
            "approved_free": None,
            "role": role,
        }

    def route_policy(self, roles=None):
        return {"schema": "ghostship.route-policy/v1", "roles": roles or {},
                "authorizations": []}

    def routing_document(self, *, failed_sources=("claude_usage",), worker_rows=None,
                         orchestrator_rows=None, generated_at=None, missing_coverage=False,
                         provider_map_overrides=None):
        now = self.ROUTING_NOW
        timestamp = datetime.fromtimestamp(now, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        worker_rows = list(worker_rows or [self.routing_row("ollama", "deepseek-v4.1-flash")])
        orchestrator_rows = list(
            [self.routing_row("codex", "gpt-6.1-sol", role="orchestrator")]
            if orchestrator_rows is None else orchestrator_rows
        )
        provider_names = {row["provider"] for row in worker_rows + orchestrator_rows}
        providers = {}
        for provider in provider_names:
            lanes = {
                "worker": [dict(row) for row in worker_rows if row["provider"] == provider],
                "orchestrator": [dict(row) for row in orchestrator_rows if row["provider"] == provider],
            }
            providers[provider] = {
                **lanes,
                "selected": {
                    role: (dict(next((row["native"] for row in lanes[role]
                                      if row["available"] and row["selection_eligible"]), None))
                           if any(row["available"] and row["selection_eligible"]
                                  for row in lanes[role]) else None)
                    for role in ("worker", "orchestrator")
                },
            }
        sources = []
        for source_id, source_providers in acceptance.QUOTA_SOURCE_PROVIDERS.items():
            if source_id in acceptance.DYNAMIC_QUOTA_SOURCES:
                source_providers = sorted(provider_names)
            if provider_map_overrides and source_id in provider_map_overrides:
                source_providers = provider_map_overrides[source_id]
            failed = source_id in failed_sources
            sources.append({
                "id": source_id,
                "quota_providers": list(source_providers),
                "status": "error" if failed else "ok",
                "reason": "http_error" if failed else "ok",
                "observed_at": timestamp,
                "observed_at_epoch": now,
                "last_success_at": None if failed else timestamp,
            })
        failed_count = len(failed_sources)
        total = len(sources)
        document = {
            "schema": "ghostship.ai-usage.routing",
            "schema_version": 1,
            "generated_at": generated_at or timestamp,
            "max_age_seconds": 900,
            "partial": bool(failed_count),
            "coverage": {
                "sources_total": total,
                "sources_ok": total - failed_count,
                "sources_partial": 0,
                "sources_failed": failed_count,
                "sources": sources,
            },
            "model_selection": {
                "schema": "ghostship.model-selection/v1",
                "generated_at": generated_at or timestamp,
                "max_age_seconds": 900,
                "partial": bool(failed_count),
                "worker": worker_rows,
                "orchestrator": orchestrator_rows,
                "providers": providers,
            },
            "policy": {"model_selection": {"provider_roles": {}}},
            "candidates": [],
        }
        if missing_coverage:
            document.pop("coverage")
        return document

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
        source.write_text(json.dumps(self.routing_document(failed_sources=())))
        candidate_tmp = self.root / "candidate"
        candidate_tmp.mkdir()
        with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW):
            target = acceptance.stage_candidate_model_routing(source, candidate_tmp, os.getuid(), route_policy=self.route_policy())
        self.assertEqual(target.read_text(), source.read_text())
        self.assertEqual(target.stat().st_mode & 0o777, 0o444)
        self.assertEqual(target.stat().st_uid, os.getuid())

    def test_candidate_model_routing_accepts_failure_for_unselected_provider_as_unavailable(self):
        candidate_tmp = self.root / "candidate"
        candidate_tmp.mkdir()
        source = self.root / "routing.json"
        document = self.routing_document()
        document["policy"]["model_selection"]["provider_roles"] = {
            "claude": ["orchestrator", "worker"], "ollama": ["worker"],
        }
        source.write_text(json.dumps(document))
        with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW):
            target = acceptance.stage_candidate_model_routing(source, candidate_tmp, os.getuid(), route_policy=self.route_policy())
        copied = json.loads(target.read_text())
        unavailable = next(row for row in copied["coverage"]["sources"]
                           if row["id"] == "claude_usage")
        self.assertEqual(unavailable["status"], "error")
        self.assertEqual(unavailable["reason"], "http_error")

    def test_candidate_model_routing_requires_failed_sources_for_orchestrator_routes(self):
        candidate_tmp = self.root / "candidate"
        candidate_tmp.mkdir()
        source = self.root / "routing.json"
        claude = self.routing_row("claude", "claude-sonnet-5-5", role="orchestrator")
        document = self.routing_document(orchestrator_rows=[claude])
        source.write_text(json.dumps(document))
        with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW):
            with self.assertRaisesRegex(RuntimeError, "incomplete source for an enabled route"):
                acceptance.stage_candidate_model_routing(source, candidate_tmp, os.getuid(), route_policy=self.route_policy())

    def test_disabled_claude_requires_policy_denial_for_orchestrator_and_reviewer(self):
        candidate_tmp = self.root / "candidate"
        candidate_tmp.mkdir()
        source = self.root / "routing.json"
        claude = self.routing_row("claude", "claude-opus-5-5", role="orchestrator")
        codex = self.routing_row("codex", "gpt-6.1-sol", role="orchestrator")
        document = self.routing_document(orchestrator_rows=[claude, codex])
        source.write_text(json.dumps(document))
        codex_route = {"provider": "codex", "model": "gpt-6.1-sol"}
        policy = self.route_policy({
            "worker": {"allow": [{"provider": "ollama", "model": "deepseek-v4.1-flash"}]},
            "orchestrator": {"allow": [codex_route]},
            "reviewer": {"allow": [codex_route]},
        })
        with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW):
            target = acceptance.stage_candidate_model_routing(
                source, candidate_tmp, os.getuid(), route_policy=policy
            )
        copied = json.loads(target.read_text())
        failed = next(row for row in copied["coverage"]["sources"]
                      if row["id"] == "claude_usage")
        self.assertEqual((failed["status"], failed["reason"]), ("error", "http_error"))

        policy["roles"]["reviewer"]["allow"].append(
            {"provider": "claude", "model": "claude-opus-5-5"}
        )
        with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW):
            with self.assertRaisesRegex(RuntimeError, "incomplete source for an enabled route"):
                acceptance._validate_routing_source_coverage(
                    document, route_policy=policy
                )

    def test_incomplete_sources_require_a_route_policy_and_unknown_or_partial_never_downgrade(self):
        document = self.routing_document()
        with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW):
            with self.assertRaisesRegex(RuntimeError, "route policy is required"):
                acceptance._validate_routing_source_coverage(document)
            unknown_reason = self.routing_document()
            next(row for row in unknown_reason["coverage"]["sources"]
                 if row["id"] == "claude_usage")["reason"] = "unknown"
            with self.assertRaisesRegex(RuntimeError, "unknown source failure"):
                acceptance._validate_routing_source_coverage(
                    unknown_reason, route_policy=self.route_policy()
                )
            for status, reason in (("mystery", "http_error"), ("partial", "source_partial"),
                                   ("error", "http_unauthorized")):
                claude = self.routing_row("claude", "claude-opus-5-5", role="orchestrator")
                variant = self.routing_document(orchestrator_rows=[claude])
                source = next(row for row in variant["coverage"]["sources"]
                              if row["id"] == "claude_usage")
                source["status"] = status
                source["reason"] = reason
                with self.subTest(status=status):
                    with self.assertRaises(RuntimeError):
                        acceptance._validate_routing_source_coverage(
                            variant, route_policy=self.route_policy()
                        )

    def test_retired_route_missing_credentials_stays_unavailable_without_blocking(self):
        candidate_tmp = self.root / "candidate"
        candidate_tmp.mkdir()
        source = self.root / "routing.json"
        document = self.routing_document()
        claude = next(row for row in document["coverage"]["sources"]
                      if row["id"] == "claude_usage")
        claude.update(status="not_configured", reason="missing_credentials")
        source.write_text(json.dumps(document))
        policy = self.route_policy({
            "worker": {"allow": [{"provider": "ollama", "model": "deepseek-v4.1-flash"}]},
            "orchestrator": {"allow": [{"provider": "codex", "model": "gpt-6.1-sol"}]},
            "reviewer": {"allow": [{"provider": "codex", "model": "gpt-6.1-sol"}]},
        })
        with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW):
            target = acceptance.stage_candidate_model_routing(
                source, candidate_tmp, os.getuid(), route_policy=policy
            )
        copied = json.loads(target.read_text())
        source_row = next(row for row in copied["coverage"]["sources"]
                          if row["id"] == "claude_usage")
        self.assertEqual((source_row["status"], source_row["reason"]),
                         ("not_configured", "missing_credentials"))

    def test_stale_disabled_provider_source_stays_unavailable_without_blocking(self):
        candidate_tmp = self.root / "candidate"
        candidate_tmp.mkdir()
        source = self.root / "routing.json"
        document = self.routing_document(
            failed_sources=("claude_usage", "command_code_usage")
        )
        command_source = next(row for row in document["coverage"]["sources"]
                              if row["id"] == "command_code_usage")
        old_epoch = self.ROUTING_NOW - 3600
        old_timestamp = datetime.fromtimestamp(old_epoch, tz=timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
        command_source.update(status="stale", reason="stale_reading",
                              observed_at=old_timestamp, observed_at_epoch=old_epoch)
        source.write_text(json.dumps(document))
        policy = self.route_policy({
            "worker": {"allow": [{"provider": "ollama", "model": "deepseek-v4.1-flash"}]},
            "orchestrator": {"allow": [{"provider": "codex", "model": "gpt-6.1-sol"}]},
            "reviewer": {"allow": [{"provider": "codex", "model": "gpt-6.1-sol"}]},
        })
        with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW):
            target = acceptance.stage_candidate_model_routing(
                source, candidate_tmp, os.getuid(), route_policy=policy
            )
        copied = json.loads(target.read_text())
        source_row = next(row for row in copied["coverage"]["sources"]
                          if row["id"] == "command_code_usage")
        self.assertEqual((source_row["status"], source_row["reason"]),
                         ("stale", "stale_reading"))

    def test_candidate_worker_lane_uses_the_native_policy_identity(self):
        claude = self.routing_row("claude", "claude-sonnet-5-5")
        ollama = self.routing_row("ollama", "deepseek-v4.1-flash")
        document = self.routing_document(worker_rows=[claude, ollama], failed_sources=())
        policy = self.route_policy({"worker": {
            "allow": [{"provider": "ollama", "model": "deepseek-v4.1-flash"}],
        }})
        expected = acceptance._candidate_acceptance_worker_routes(
            document, route_policy=policy, now=self.ROUTING_NOW
        )
        self.assertEqual(expected, {("ollama", "deepseek-v4.1-flash")})

    def test_routing_acceptance_requires_the_policy_mount_it_will_run(self):
        with self.assertRaisesRegex(RuntimeError, "route policy mount is required"):
            acceptance.accept(
                self.state, self.archive, "podman",
                "/run/t3code-podman-candidate/podman.sock", self.home,
                model_routing_file=self.root / "routing.json",
                command_fn=self.command, identity_fn=lambda: self.identity,
            )

    def test_ranked_rows_and_provider_group_must_agree_with_native_selection(self):
        document = self.routing_document(failed_sources=())
        document["model_selection"]["providers"]["ollama"]["selected"]["worker"] = {
            "instanceId": "ollama", "model": "different-model",
        }
        with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW):
            with self.assertRaisesRegex(RuntimeError, "does not match producer lane"):
                acceptance._validate_routing_source_coverage(
                    document, route_policy=self.route_policy()
                )

    def test_pinned_picker_and_policy_define_required_route_for_acceptance(self):
        agent_source = os.environ.get("GHOSTSHIP_TEST_AGENT_SOURCE")
        if not agent_source:
            self.skipTest("the flake-pinned agent source is available in config-tests")
        source_path = str(Path(agent_source) / "tools/python")
        if source_path not in sys.path:
            sys.path.insert(0, source_path)
        from ghostship_t3.models import _provider_choice
        from ghostship_t3.route_policy import decision

        claude = self.routing_row(
            "claude", "claude-opus-5-5", instance_id="claudeAgent", role="orchestrator"
        )
        codex = self.routing_row("codex", "gpt-6.1-sol", role="orchestrator")
        document = self.routing_document(orchestrator_rows=[claude, codex])
        selection = document["model_selection"]
        selected_claude = _provider_choice(selection, "claude", "orchestrator")
        self.assertEqual(selected_claude, claude["native"])
        codex_first = self.routing_row("codex", "gpt-6.1-sol", role="orchestrator")
        codex_fallback = self.routing_row("codex", "gpt-6.1-terra", role="orchestrator")
        fallback_document = self.routing_document(
            orchestrator_rows=[codex_first, codex_fallback], failed_sources=()
        )["model_selection"]
        codex_group = fallback_document["providers"]["codex"]
        codex_group["orchestrator"][0].update(
            state="spent", limiting_window={"remaining_ratio": 0}
        )
        fallback_document["orchestrator"][0].update(
            state="spent", limiting_window={"remaining_ratio": 0}
        )
        self.assertEqual(
            _provider_choice(fallback_document, "codex", "orchestrator"),
            codex_fallback["native"],
        )

        policy = self.route_policy({
            "worker": {"allow": [{"provider": "ollama", "model": "deepseek-v4.1-flash"}]},
            "orchestrator": {"allow": [{"provider": "codex", "model": "gpt-6.1-sol"}]},
            "reviewer": {"allow": [{"provider": "codex", "model": "gpt-6.1-sol"}]},
        })
        self.assertFalse(decision("claudeAgent", "claude-opus-5-5", "orchestrator",
                                  policy=policy, now=self.ROUTING_NOW)[0])
        self.assertFalse(decision("claudeAgent", "claude-opus-5-5", "reviewer",
                                  policy=policy, now=self.ROUTING_NOW)[0])
        with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW):
            acceptance._validate_routing_source_coverage(document, route_policy=policy)
        provider_env = self.root / "provider.env"
        provider_env.write_text("")
        worker_route = {
            "provider": "ollama", "model": "deepseek-v4.1-flash",
            "billing": "subscription", "execution": "t3", "available": True,
        }

        def candidate_command(_engine, *args, **_kwargs):
            if "pick" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"pick": worker_route}}))
            if "models" in args and "--json" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"selected": [worker_route]}}))
            return Mock(returncode=0, stdout="passed")

        with patch.object(acceptance, "command", side_effect=candidate_command):
            self.assertEqual(acceptance.check_provider_turn(
                ["podman"], "candidate", provider_env,
                tooling_path="/nix/store/test-agent", routing_document=document,
                route_policy=policy,
            ), "ollama/deepseek-v4.1-flash")

        policy["roles"]["orchestrator"]["allow"].append(
            {"provider": "claudeAgent", "model": "claude-opus-5-5"}
        )
        with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW):
            with self.assertRaisesRegex(RuntimeError, "incomplete source for an enabled route"):
                acceptance._validate_routing_source_coverage(document, route_policy=policy)

    def test_candidate_model_routing_requires_failed_sources_for_worker_fallbacks(self):
        candidate_tmp = self.root / "candidate"
        candidate_tmp.mkdir()
        source = self.root / "routing.json"
        rows = [
            self.routing_row("ollama", "deepseek-v4.1-flash"),
            self.routing_row("claude", "claude-sonnet-5-5"),
        ]
        document = self.routing_document(worker_rows=rows)
        source.write_text(json.dumps(document))
        with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW):
            with self.assertRaisesRegex(RuntimeError, "incomplete source for an enabled route"):
                acceptance.stage_candidate_model_routing(source, candidate_tmp, os.getuid(), route_policy=self.route_policy())

    def test_candidate_model_routing_rejects_auth_unknown_and_partial_required_sources(self):
        candidate_tmp = self.root / "candidate"
        candidate_tmp.mkdir()
        source = self.root / "routing.json"
        claude = self.routing_row("claude", "claude-sonnet-5-5", role="orchestrator")
        for status, reason in (("error", "http_unauthorized"), ("unknown", "unknown"),
                               ("partial", "source_partial")):
            document = self.routing_document(orchestrator_rows=[claude])
            row = next(item for item in document["coverage"]["sources"]
                       if item["id"] == "claude_usage")
            row["status"] = status
            row["reason"] = reason
            if status == "partial":
                row["observed_at_epoch"] = self.ROUTING_NOW
            document["coverage"]["sources_failed"] = 0 if status == "partial" else 1
            document["coverage"]["sources_partial"] = 1 if status == "partial" else 0
            document["partial"] = True
            document["model_selection"]["partial"] = True
            with self.subTest(status=status):
                source.write_text(json.dumps(document))
                with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW):
                    with self.assertRaises(RuntimeError):
                        acceptance.stage_candidate_model_routing(source, candidate_tmp, os.getuid(), route_policy=self.route_policy())

    def test_candidate_model_routing_refuses_unproven_routes_and_partial_without_coverage(self):
        candidate_tmp = self.root / "candidate"
        candidate_tmp.mkdir()
        source = self.root / "routing.json"
        cases = (
            self.routing_document(missing_coverage=True),
            self.routing_document(provider_map_overrides={"claude_usage": []}),
            self.routing_document(provider_map_overrides={"pool_events": []}),
            self.routing_document(worker_rows=[{
                **self.routing_row("ollama", "deepseek-v4.1-flash"), "native": {"junk": 1},
            }]),
        )
        cases[0]["partial"] = False
        cases[0]["model_selection"]["partial"] = False
        empty_providers = self.routing_document()
        empty_providers["model_selection"]["providers"] = {}
        unknown_source = self.routing_document()
        unknown_source["coverage"]["sources"][-1]["id"] = "unclassified_source"
        missing_source = self.routing_document()
        missing_source["coverage"]["sources"].pop()
        missing_source["coverage"]["sources_total"] -= 1
        missing_source["coverage"]["sources_ok"] -= 1
        cases += (empty_providers, unknown_source, missing_source)
        for document in cases:
            with self.subTest(document=document):
                source.write_text(json.dumps(document))
                with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW):
                    with self.assertRaises(RuntimeError):
                        acceptance.stage_candidate_model_routing(source, candidate_tmp, os.getuid(), route_policy=self.route_policy())

    def test_candidate_model_routing_requires_exact_source_counts_and_fresh_readings(self):
        candidate_tmp = self.root / "candidate"
        candidate_tmp.mkdir()
        source = self.root / "routing.json"
        good = self.routing_document()
        bad_coverages = (
            {**good["coverage"], "sources_failed": True},
            {**good["coverage"], "sources_failed": "1"},
            {**good["coverage"], "sources_total": good["coverage"]["sources_total"] + 1},
            {**good["coverage"], "sources_ok": 0},
            {**good["coverage"], "sources_partial": 1},
        )
        for coverage in bad_coverages:
            with self.subTest(coverage=coverage):
                source.write_text(json.dumps({**good, "coverage": coverage}))
                with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW):
                    with self.assertRaises(RuntimeError):
                        acceptance.stage_candidate_model_routing(source, candidate_tmp, os.getuid(), route_policy=self.route_policy())
        stale_source = self.routing_document(failed_sources=())
        next(row for row in stale_source["coverage"]["sources"] if row["id"] == "ollama")[
            "observed_at_epoch"] = self.ROUTING_NOW - 901
        source.write_text(json.dumps(stale_source))
        with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW):
            with self.assertRaisesRegex(RuntimeError, "source reading is stale"):
                acceptance.stage_candidate_model_routing(source, candidate_tmp, os.getuid(), route_policy=self.route_policy())

    def test_candidate_model_routing_rejects_stale_snapshot(self):
        candidate_tmp = self.root / "candidate"
        candidate_tmp.mkdir()
        source = self.root / "routing.json"
        document = self.routing_document(generated_at="2000-01-01T00:00:00Z")
        source.write_text(json.dumps(document))
        with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW):
            with self.assertRaisesRegex(RuntimeError, "snapshot is stale"):
                acceptance.stage_candidate_model_routing(source, candidate_tmp, os.getuid(), route_policy=self.route_policy())

    def test_candidate_routing_copy_is_the_exact_validated_snapshot(self):
        candidate_tmp = self.root / "candidate"
        candidate_tmp.mkdir()
        source = self.root / "routing.json"
        document = self.routing_document()
        original = json.dumps(document).encode()
        source.write_bytes(original)
        validator = acceptance._validate_routing_source_coverage

        def validate_then_replace(checked_document, now=None, route_policy=None):
            validator(checked_document, now=now, route_policy=route_policy)
            source.write_text("{}")

        with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW), \
             patch.object(acceptance, "_validate_routing_source_coverage",
                          side_effect=validate_then_replace):
            target = acceptance.stage_candidate_model_routing(source, candidate_tmp, os.getuid(), route_policy=self.route_policy())
        self.assertEqual(target.read_bytes(), original)

    def test_candidate_model_routing_rejects_failed_source_for_selected_provider(self):
        candidate_tmp = self.root / "candidate"
        candidate_tmp.mkdir()
        source = self.root / "routing.json"
        document = self.routing_document(worker_rows=[
            self.routing_row("claude", "claude-sonnet-5-5"),
        ])
        source.write_text(json.dumps(document))
        with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW):
            with self.assertRaisesRegex(RuntimeError, "incomplete source for an enabled route"):
                acceptance.stage_candidate_model_routing(source, candidate_tmp, os.getuid(), route_policy=self.route_policy())

    def test_candidate_model_routing_keeps_count_and_partial_fail_closed(self):
        candidate_tmp = self.root / "candidate"
        candidate_tmp.mkdir()
        source = self.root / "routing.json"
        base = {
            "schema": "ghostship.ai-usage.routing", "schema_version": 1, "partial": True,
            "coverage": {"sources_failed": 1, "sources": [
                {"id": "claude_usage", "status": "unknown", "quota_providers": ["claude"]},
            ]},
            "model_selection": {"providers": {
                "claude": {"selected": {"worker": {"instanceId": "claude", "model": "sonnet"},
                                         "orchestrator": None}},
            }},
        }
        for coverage in (
            {"sources": base["coverage"]["sources"]},
            {"sources_failed": "1", "sources": base["coverage"]["sources"]},
            {"sources_failed": 0, "sources": base["coverage"]["sources"]},
            {"sources_failed": 0, "sources": [{"id": "claude_usage", "status": "partial",
                                                   "quota_providers": ["claude"]}]},
            {"sources_failed": 1, "sources": [{"id": "claude_usage", "status": "missing_credentials",
                                                   "quota_providers": ["claude"]}]},
            {"sources_failed": 1, "sources": [{"id": "claude_usage", "status": "error"}]},
            {"sources_failed": 1, "sources": [{"id": "unknown_source", "status": "error"}]},
        ):
            with self.subTest(coverage=coverage):
                source.write_text(json.dumps({**base, "coverage": coverage}))
                with self.assertRaises(RuntimeError):
                    acceptance.stage_candidate_model_routing(source, candidate_tmp, os.getuid(), route_policy=self.route_policy())
        mismatched_epoch = self.routing_document(failed_sources=())
        mismatched_epoch["model_selection"]["generated_at_epoch"] = self.ROUTING_NOW - 901
        source.write_text(json.dumps(mismatched_epoch))
        with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW):
            with self.assertRaisesRegex(RuntimeError, "selection epoch"):
                acceptance.stage_candidate_model_routing(
                    source, candidate_tmp, os.getuid(), route_policy=self.route_policy()
                )

    def test_routing_snapshot_refusals_are_retryable_preconditions(self):
        # The host's live snapshot is checked before the candidate runs, so its
        # refusals leave the image retryable (exit 75), unlike candidate failures.
        candidate_tmp = self.root / "candidate"
        candidate_tmp.mkdir()
        source = self.root / "routing.json"
        failed = {"schema": "ghostship.ai-usage.routing", "schema_version": 1, "partial": True,
                  "coverage": {"sources_failed": 1}, "candidates": []}
        for content in (None, "not json", json.dumps({"schema": "other"}), json.dumps(failed)):
            source.unlink(missing_ok=True)
            if content is not None:
                source.write_text(content)
            with self.assertRaises(acceptance.PreconditionError):
                acceptance.stage_candidate_model_routing(source, candidate_tmp, os.getuid(), route_policy=self.route_policy())
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

        routing_document = self.routing_document()
        with patch.object(acceptance, "command", side_effect=command), \
             patch.object(acceptance, "check_provider_turn", return_value=True) as provider_turn:
            checks = acceptance.check_candidate(
                ["podman"], "candidate", "provider.env", tooling_path="/nix/store/test-agent",
                routing_document=routing_document,
            )
        self.assertTrue(all(checks.values()))
        self.assertIs(provider_turn.call_args.kwargs["routing_document"], routing_document)
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

    def test_provider_turn_proves_the_native_opencode_free_t3_route(self):
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
                }}}))
            return Mock(returncode=0, stdout="passed")

        with patch.object(acceptance, "command", side_effect=command):
            self.assertEqual(acceptance.check_provider_turn(
                ["podman"], "candidate", provider_env,
                tooling_path="/nix/store/test-agent",
            ), "opencode-free/nvidia/minimaxai/minimax-m3.1-flash")
        self.assertTrue(any("pick" in call and "--role" in call and "worker" in call
                            and "--kind" in call and "code" in call for call in calls))
        self.assertTrue(any(any(item.endswith("provider-turn-probe.py") for item in call) and
                            "opencode-free/nvidia/minimaxai/minimax-m3.1-flash" in call
                            for call in calls))

    def test_provider_turn_requires_cli_routes_to_match_the_validated_native_lane(self):
        provider_env = self.root / "provider.env"
        provider_env.write_text("")
        expected = self.routing_row("ollama", "deepseek-v4.1-flash")
        document = self.routing_document(worker_rows=[expected])
        route = {"provider": "ollama", "model": "deepseek-v4.1-flash",
                 "billing": "subscription", "execution": "t3", "available": True}
        policy = self.route_policy()
        with patch.object(acceptance.time, "time", return_value=self.ROUTING_NOW):
            acceptance._validate_routing_source_coverage(document, route_policy=policy)

        def command(engine, *args, **kwargs):
            if "pick" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"pick": route}}))
            if "models" in args and "--json" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"selected": [route]}}))
            return Mock(returncode=0, stdout="passed")

        with patch.object(acceptance, "command", side_effect=command):
            self.assertEqual(acceptance.check_provider_turn(
                ["podman"], "candidate", provider_env,
                tooling_path="/nix/store/test-agent", routing_document=document,
                route_policy=policy,
            ), "ollama/deepseek-v4.1-flash")

    def test_provider_turn_rejects_cli_route_missing_from_validated_native_lane(self):
        provider_env = self.root / "provider.env"
        provider_env.write_text("")
        document = self.routing_document()
        route = {"provider": "commandCode", "model": "deepseek/deepseek-v4.1-flash",
                 "billing": "subscription", "execution": "t3", "available": True}
        calls = []

        def command(engine, *args, **kwargs):
            calls.append(tuple(args))
            if "pick" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"pick": route}}))
            if "models" in args and "--json" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"selected": [route]}}))
            return Mock(returncode=0, stdout="present")

        with patch.object(acceptance, "command", side_effect=command):
            with self.assertRaisesRegex(RuntimeError, "route is absent from the validated routing snapshot"):
                acceptance.check_provider_turn(
                    ["podman"], "candidate", provider_env,
                    tooling_path="/nix/store/test-agent", routing_document=document,
                )
        self.assertFalse(any(any(str(item).endswith("provider-turn-probe.py") for item in call)
                             for call in calls))

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
            with self.assertRaisesRegex(RuntimeError, "no approved available T3 fallback"):
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
                }}}))
            return Mock(returncode=0, stdout="passed")

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
                    with self.assertRaisesRegex(RuntimeError, "no approved available free or subscription T3 route"):
                        acceptance.check_provider_turn(["podman"], "candidate", provider_env,
                                                       tooling_path="/nix/store/test-agent")
                self.assertFalse(any(any(str(item).endswith("provider-turn-probe.py") for item in call.args)
                                     for call in command.call_args_list))

    def test_provider_turn_refuses_free_pool_routes_for_t3_execution(self):
        provider_env = self.root / "provider.env"
        provider_env.write_text("")
        pick = {"data": {"pick": {
            "provider": "opencode-free", "model": "model", "billing": "free",
            "approved_free": True, "execution": "free_pool", "available": True,
        }}}
        with patch.object(acceptance, "command", return_value=Mock(
                returncode=0, stdout=json.dumps(pick))) as command:
            with self.assertRaisesRegex(RuntimeError, "no approved available free or subscription T3 route"):
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
                 "execution": "t3", "available": True}
        fallback = {"provider": "opencode-free", "model": "nvidia/fallback",
                    "billing": "free", "approved_free": True,
                    "execution": "t3", "available": True}
        first_row = self.routing_row("opencode-free", "nvidia/first")
        first_row.update(billing="free", approved_free={"provider": "nvidia"})
        fallback_row = self.routing_row("opencode-free", "nvidia/fallback")
        fallback_row.update(billing="free", approved_free={"provider": "nvidia"})
        routing_document = self.routing_document(worker_rows=[first_row, fallback_row])
        calls = []

        def command(engine, *args, **kwargs):
            calls.append(tuple(args))
            if any(item.endswith("provider-turn-probe.py") for item in args):
                route = next(item for item in args if item.startswith("opencode-free/"))
                if route.endswith("/first"):
                    return Mock(returncode=1, stderr="", stdout=json.dumps({
                        "outcome": "execution",
                        "error": {"code": provider_probe.safe_failure_code({
                            "outcome": "execution", "detail": "model unavailable"
                        })},
                    }))
                return Mock(returncode=0, stdout="passed")
            if "pick" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"pick": first}}))
            if "models" in args and "--json" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"selected": [first, fallback]}}))
            return Mock(returncode=0, stdout="present")

        with patch.object(acceptance, "command", side_effect=command):
            self.assertEqual(acceptance.check_provider_turn(
                ["podman"], "candidate", provider_env,
                tooling_path="/nix/store/test-agent", routing_document=routing_document,
            ), "opencode-free/nvidia/fallback")
        proved = [next(item for item in call if item.startswith("opencode-free/"))
                  for call in calls
                  if any(item.endswith("provider-turn-probe.py") for item in call)]
        self.assertEqual(proved, ["opencode-free/nvidia/first", "opencode-free/nvidia/fallback"])

    def subscription_rows(self, *names):
        return [{"provider": provider, "model": model, "billing": "subscription",
                 "execution": "t3", "available": True}
                for provider, model in (name.split("/", 1) for name in names)]

    def probe_calls(self, calls):
        return [call for call in calls if any(item.endswith("provider-turn-probe.py") for item in call)]

    def test_provider_turn_tries_the_next_admitted_route_after_an_api_error(self):
        provider_env = self.root / "provider.env"
        provider_env.write_text("")
        rows = self.subscription_rows("ollama/deepseek-v4.1-flash:1017", "commandCode/deepseek/deepseek-v4.1-flash")
        calls = []

        def command(engine, *args, **kwargs):
            calls.append(tuple(args))
            if any(item.endswith("provider-turn-probe.py") for item in args):
                if "ollama/deepseek-v4.1-flash:1017" in args:
                    return Mock(returncode=1, stderr="", stdout='{"status":"error","message":"provider api"}')
                return Mock(returncode=0, stdout="passed")
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
                return Mock(returncode=1, stderr="", stdout='{"status":"error","message":"provider api"}')
            if "pick" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"pick": rows[0]}}))
            if "models" in args and "--json" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"selected": rows}}))
            return Mock(returncode=0, stdout="present")

        with patch.object(acceptance, "command", side_effect=command):
            with self.assertRaisesRegex(RuntimeError, "no live picker route proved a turn"):
                acceptance.check_provider_turn(["podman"], "candidate", provider_env,
                                               tooling_path="/nix/store/test-agent")
        self.assertEqual(len(self.probe_calls(calls)), acceptance.MAX_ACCEPTANCE_ROUTES)

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
