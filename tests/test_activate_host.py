"""The activation helper: the system profile is set before the switch, the
two generation links are verified afterwards, and the deploy slot guards the
whole activation."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/activate-host"


def interpreter() -> str:
    """The shell the helper's shebang names.

    The helper starts with `#!/usr/bin/env bash`, and a Nix build sandbox has
    no /usr/bin/env, so the kernel cannot resolve the shebang and the helper
    looks missing. The test runs the helper with the interpreter the shebang
    names, which the sandbox does have.
    """
    shebang = SCRIPT.read_text().splitlines()[0]
    parts = shebang[2:].split() if shebang.startswith("#!") else []
    if parts and os.path.basename(parts[0]) == "env":
        parts = parts[1:]
    name = parts[0] if parts else "sh"
    return shutil.which(name) or name


class ActivateHostTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.log = self.root / "log"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.toplevel = self.root / "generation"
        (self.toplevel / "bin").mkdir(parents=True)
        self.current = self.root / "current-system"
        self.profile = self.root / "system-profile"
        # A stand-in for nix-env that records the profile it was asked to set.
        nix_env = self.bin / "nix-env"
        nix_env.write_text(
            "#!/bin/sh\n"
            f"printf 'nix-env %s\\n' \"$*\" >> {self.log}\n"
            "profile=''\n"
            "target=''\n"
            "while [ $# -gt 0 ]; do\n"
            "  case \"$1\" in\n"
            "    -p) profile=\"$2\"; shift 2 ;;\n"
            "    --set) target=\"$2\"; shift 2 ;;\n"
            "    *) shift ;;\n"
            "  esac\n"
            "done\n"
            f"ln -sfn \"$target\" \"$profile\"\n"
        )
        nix_env.chmod(0o700)
        # A stand-in for switch-to-configuration that starts the generation.
        switch = self.toplevel / "bin/switch-to-configuration"
        switch.write_text(
            "#!/bin/sh\n"
            f"printf 'switch %s\\n' \"$*\" >> {self.log}\n"
            f"ln -sfn {self.toplevel} {self.current}\n"
        )
        switch.chmod(0o700)
        # A stand-in for deploy-slot that records each call as tab-separated
        # arguments, so a test sees the exact argument boundaries.
        self.slot_log = self.root / "slot-log"
        self.slot_bin = self.bin / "deploy-slot"
        self.slot_bin.write_text(
            "#!/bin/sh\n"
            "{\n"
            "  printf 'call'\n"
            "  for arg in \"$@\"; do printf '\\t%s' \"$arg\"; done\n"
            "  printf '\\n'\n"
            "} >> \"$FAKE_SLOT_LOG\"\n"
            "case \"$1\" in\n"
            "  check)\n"
            "    [ -z \"${FAKE_SLOT_CHECK_OUTPUT:-}\" ] || printf '%s\\n' \"$FAKE_SLOT_CHECK_OUTPUT\"\n"
            "    exit \"${FAKE_SLOT_CHECK_STATUS:-0}\"\n"
            "    ;;\n"
            "  release)\n"
            "    [ -z \"${FAKE_SLOT_RELEASE_OUTPUT:-}\" ] || printf '%s\\n' \"$FAKE_SLOT_RELEASE_OUTPUT\"\n"
            "    exit \"${FAKE_SLOT_RELEASE_STATUS:-0}\"\n"
            "    ;;\n"
            "esac\n"
            "exit 1\n"
        )
        self.slot_bin.chmod(0o700)
        self.environment = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "GHOSTSHIP_CURRENT_SYSTEM": str(self.current),
            "GHOSTSHIP_SYSTEM_PROFILE": str(self.profile),
            "GHOSTSHIP_DEPLOY_SLOT_BIN": str(self.slot_bin),
            "FAKE_SLOT_LOG": str(self.slot_log),
        }
        self.environment.pop("GHOSTSHIP_DEPLOY_HOLDER", None)

    def run_helper(self, *arguments, environment=None):
        return subprocess.run([interpreter(), str(SCRIPT), *arguments],
                              env=environment or self.environment,
                              capture_output=True, text=True, timeout=30)

    def steps(self):
        if not self.log.exists():
            return []
        return self.log.read_text().splitlines()

    def slot_calls(self):
        if not self.slot_log.exists():
            return []
        return [line.split("\t")[1:]
                for line in self.slot_log.read_text().splitlines()]

    def matching_generation(self, name="generation"):
        target = self.root / name
        target.mkdir(exist_ok=True)
        self.current.symlink_to(target)
        self.profile.symlink_to(target)

    def test_the_profile_is_set_before_the_switch(self):
        result = self.run_helper("--toplevel", str(self.toplevel), "--holder", "test-holder")
        self.assertEqual(result.returncode, 0, result.stderr)
        steps = self.steps()
        self.assertEqual(len(steps), 2)
        self.assertTrue(steps[0].startswith("nix-env"))
        self.assertIn(f"--set {self.toplevel}", steps[0])
        self.assertIn(str(self.profile), steps[0])
        self.assertTrue(steps[1].startswith("switch"))
        self.assertIn("the running system and the system profile name", result.stdout)

    def test_a_mismatch_after_the_switch_fails(self):
        switch = self.toplevel / "bin/switch-to-configuration"
        switch.write_text(
            "#!/bin/sh\n"
            f"printf 'switch %s\\n' \"$*\" >> {self.log}\n"
            f"ln -sfn {self.root}/other {self.current}\n"
        )
        switch.chmod(0o700)
        result = self.run_helper("--toplevel", str(self.toplevel), "--holder", "test-holder")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match the system profile", result.stderr)

    def test_verify_only_reports_a_mismatch_without_activating(self):
        self.current.symlink_to(self.root / "other")
        self.profile.symlink_to(self.toplevel)
        result = self.run_helper("--verify-only")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match the system profile", result.stderr)
        self.assertEqual(self.steps(), [])

    def test_verify_only_accepts_matching_generations(self):
        self.current.symlink_to(self.toplevel)
        self.profile.symlink_to(self.toplevel)
        result = self.run_helper("--verify-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.steps(), [])

    def test_a_directory_that_is_not_a_generation_is_refused(self):
        result = self.run_helper("--toplevel", str(self.root))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not a built system generation", result.stderr)
        self.assertEqual(self.steps(), [])

    def test_activation_without_a_holder_is_refused(self):
        result = self.run_helper("--toplevel", str(self.toplevel))
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("agent deploy slot acquire", result.stderr)
        self.assertEqual(self.steps(), [])
        self.assertEqual(self.slot_calls(), [])

    def test_a_slot_check_that_refuses_the_holder_is_refused(self):
        self.environment["FAKE_SLOT_CHECK_STATUS"] = "3"
        self.environment["FAKE_SLOT_CHECK_OUTPUT"] = '{"holder": "other-session"}'
        result = self.run_helper("--toplevel", str(self.toplevel), "--holder", "test-holder")
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("other-session", result.stderr)
        self.assertEqual(self.steps(), [])
        self.assertEqual(self.slot_calls(), [["check", "--holder", "test-holder"]])

    def test_a_missing_slot_tool_fails_closed(self):
        self.environment["GHOSTSHIP_DEPLOY_SLOT_BIN"] = str(self.root / "no-such-deploy-slot")
        result = self.run_helper("--toplevel", str(self.toplevel), "--holder", "test-holder")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("missing or not executable", result.stderr)
        self.assertEqual(self.steps(), [])

    def test_a_slot_check_error_fails_closed(self):
        for status in ("1", "2"):
            with self.subTest(status=status):
                if self.slot_log.exists():
                    self.slot_log.unlink()
                self.environment["FAKE_SLOT_CHECK_STATUS"] = status
                result = self.run_helper("--toplevel", str(self.toplevel), "--holder", "test-holder")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(self.steps(), [])
                self.assertEqual(self.slot_calls(), [["check", "--holder", "test-holder"]])

    def test_the_holder_environment_variable_is_used(self):
        self.environment["GHOSTSHIP_DEPLOY_HOLDER"] = "env-holder"
        result = self.run_helper("--toplevel", str(self.toplevel))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.slot_calls(), [["check", "--holder", "env-holder"]])

    def test_verify_only_releases_the_verified_generation(self):
        self.matching_generation("system-413-link")
        result = self.run_helper("--verify-only", "--holder", "test-holder")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.slot_calls(),
                         [["release", "--holder", "test-holder", "--generation", "413"]])

    def test_verify_only_a_mismatch_does_not_release(self):
        self.matching_generation("system-413-link")
        result = self.run_helper("--verify-only", "--holder", "test-holder")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.slot_calls()), 1)
        self.profile.unlink()
        self.profile.symlink_to(self.root / "other")
        result = self.run_helper("--verify-only", "--holder", "test-holder")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("does not match the system profile", result.stderr)
        self.assertEqual(len(self.slot_calls()), 1)

    def test_verify_only_a_refused_release_exits_three(self):
        self.matching_generation("system-413-link")
        self.environment["FAKE_SLOT_RELEASE_STATUS"] = "3"
        self.environment["FAKE_SLOT_RELEASE_OUTPUT"] = '{"holder": "another-deploy"}'
        result = self.run_helper("--verify-only", "--holder", "test-holder")
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("another-deploy", result.stderr)

    def test_verify_only_without_a_holder_never_calls_the_slot_tool(self):
        self.matching_generation()
        result = self.run_helper("--verify-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.slot_calls(), [])
        # A holder is what makes verify-only touch the slot at all.
        result = self.run_helper("--verify-only", "--holder", "test-holder")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.slot_calls(), [["release", "--holder", "test-holder"]])

    def test_the_holder_reaches_the_slot_tool_as_one_argument(self):
        holder = "it's \"me\""
        result = self.run_helper("--toplevel", str(self.toplevel), "--holder", holder)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.slot_calls(), [["check", "--holder", holder]])

    def test_an_activation_keeps_the_slot_held(self):
        # The deploy's checks after the switch (T3 unchanged, the upgrade timer
        # off) run inside the slot; only verify-only releases it.
        self.matching_generation("system-413-link")
        result = self.run_helper("--toplevel", str(self.toplevel), "--holder", "test-holder")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("release", [call[0] for call in self.slot_calls()])
        self.assertIn("still holds the deploy slot", result.stdout)


if __name__ == "__main__":
    unittest.main()
