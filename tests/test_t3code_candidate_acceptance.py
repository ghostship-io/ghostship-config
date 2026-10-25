"""Candidate acceptance creates only exact, production-preserving receipts."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "t3code_candidate_acceptance", ROOT / "packages/t3code/candidate-acceptance.py"
)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


class CandidateDeploymentPackagingTest(unittest.TestCase):
    def test_host_packages_acceptance_scripts_with_their_sibling_inputs(self):
        module = (ROOT / "modules/self-hosted/t3code.nix").read_text()
        self.assertIn('t3codeDeploymentScripts = pkgs.runCommand', module)
        for name in (
            "candidate-acceptance.py", "hardening-probe.py", "runtime-caps.json",
        ):
            with self.subTest(name=name):
                self.assertIn(f"$out/{name}", module)
                self.assertIn(f"packages/t3code/{name}", module)
        self.assertIn('name = "ghostship-t3code-deploy-image"', module)
        self.assertIn('builtins.readFile ../../packages/t3code/deploy-image.sh', module)
        self.assertIn('CANDIDATE_ACCEPTANCE = "${t3codeDeploymentScripts}/candidate-acceptance.py"', module)
        self.assertIn('systemctl start --no-block ghostship-t3code-deploy.service', module)
        self.assertNotIn('t3code-deploy-when-idle', module)
        self.assertNotIn('t3code-safe-restart', module)

    def test_t3code_image_exposes_systemd_as_oci_entrypoint(self):
        image = (ROOT / "packages/t3code/image.nix").read_text()
        self.assertIn('Entrypoint = [ "${pkgs.systemd}/lib/systemd/systemd" ];', image)
        self.assertIn("Cmd = [ ];", image)


class CandidateAcceptanceTest(unittest.TestCase):
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
        self.assertFalse(any("production" in str(command) for command in self.commands))
        self.assertFalse(any(command[:1] == ("stop",) for command in self.commands))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

        run = next(command for command in self.commands if command[:1] == ("run",))
        run_volumes = [run[index + 1] for index, token in enumerate(run[:-1])
                       if token == "--volume"]
        targets = [volume.split(":", 2)[1] for volume in run_volumes]
        self.assertNotIn("/workspace", targets)
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
        (self.home / ".t3/userdata").mkdir(parents=True)
        (self.home / ".t3/userdata/state.sqlite").write_text("live threads")
        (self.home / ".t3/worktrees/project").mkdir(parents=True)
        (self.home / ".t3/worktrees/project/file").write_text("live checkout")
        candidate_home = self.root / "candidate-home"
        candidate_inputs = self.root / "candidate-inputs"
        acceptance.stage_candidate_inputs(self.home, candidate_home, candidate_inputs, os.getuid())
        for relative in oauth_paths:
            with self.subTest(path=relative):
                self.assertFalse((candidate_inputs / relative).exists())
                self.assertFalse((candidate_home / relative).is_symlink())
        self.assertEqual((candidate_inputs / ".agents/skills/candidate-check/SKILL.md").read_text(),
                         "skill fixture")
        self.assertFalse((candidate_inputs / ".t3").exists())
        self.assertFalse((candidate_home / ".t3").exists())

    def test_provider_turn_uses_only_picker_approved_free_api_key_routes(self):
        provider_env = self.root / "provider.env"
        provider_env.write_text("OPENROUTER_API_KEY=static-key-fixture\n")
        calls = []

        def command(engine, *args, **kwargs):
            calls.append(tuple(args))
            if "pick" in args:
                return Mock(returncode=0, stdout=json.dumps({"data": {"pick": {
                    "provider": "openrouter", "model": "cohere/north-mini-code:free",
                    "billing": "free", "approved_free": True, "execution": "t3",
                    "available": True,
                }}}))
            return Mock(returncode=0, stdout="passed")

        with patch.object(acceptance, "command", side_effect=command):
            self.assertTrue(acceptance.check_provider_turn(
                ["podman"], "candidate", provider_env
            ))
        self.assertTrue(any("--provider" in call and "openrouter" in call for call in calls))
        self.assertTrue(any("prove" in call and "openrouter/cohere/north-mini-code:free" in call
                            for call in calls))

    def test_provider_turn_fails_closed_when_no_static_api_key_is_projected(self):
        provider_env = self.root / "provider.env"
        provider_env.write_text("AGENT_DESKTOP_API_TOKEN=desktop-only\n")
        with patch.object(acceptance, "command") as command:
            with self.assertRaisesRegex(RuntimeError, "no static API key"):
                acceptance.check_provider_turn(["podman"], "candidate", provider_env)
        command.assert_not_called()

    def test_missing_static_api_key_leaves_no_accepting_receipt_and_tears_down(self):
        with patch.object(acceptance, "command", side_effect=self.command), \
             patch.object(acceptance.subprocess, "run", return_value=Mock(returncode=0)):
            with self.assertRaisesRegex(RuntimeError, "no static API key"):
                acceptance.accept(
                    self.state, self.archive, "podman",
                    "/run/t3code-podman-candidate/podman.sock", self.home,
                    command_fn=self.command, identity_fn=lambda: self.identity,
                )
        self.assertFalse((self.state / "receipts/generation-502.json").exists())
        self.assertIn(("rm", "--force", "--time", "10", "t3code-candidate-generation-502"),
                      self.commands)

    def test_provider_turn_refuses_paid_or_unapproved_picker_results(self):
        provider_env = self.root / "provider.env"
        provider_env.write_text("NVIDIA_API_KEY=static-key-fixture\n")
        pick = {"data": {"pick": {
            "provider": "nvidia", "model": "model", "billing": "subscription",
            "approved_free": False, "execution": "t3", "available": True,
        }}}
        with patch.object(acceptance, "command", return_value=Mock(
                returncode=0, stdout=json.dumps(pick))) as command:
            with self.assertRaisesRegex(RuntimeError, "no available trusted free T3 route"):
                acceptance.check_provider_turn(["podman"], "candidate", provider_env)
        self.assertFalse(any("prove" in str(call.args) for call in command.call_args_list))

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
        pinned_tooling = "/nix/store/pinned-agent-tools"
        with patch.object(acceptance, "command", side_effect=self.command), \
             patch.object(acceptance, "check_candidate", return_value={
                 name: True for name in acceptance.CHECKS
             }), patch.object(acceptance, "candidate_agent_path", return_value=pinned_tooling), \
             patch.object(acceptance.subprocess, "run", return_value=Mock(returncode=0)):
            receipt = acceptance.accept(
                self.state, self.archive, "podman",
                "/run/t3code-podman-candidate/podman.sock", self.home,
                command_fn=self.command, identity_fn=lambda: self.identity,
                candidate_uid=os.getuid(), provider_secrets_file=secrets,
                tooling_path=pinned_tooling, expected_agent_revision="a" * 40,
            )
        self.assertEqual(receipt["agent_revision"], "a" * 40)
        self.assertEqual(receipt["agent_path"], pinned_tooling)
        self.assertEqual(receipt["provider_secret_inode"], str(secrets.stat().st_ino))

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
