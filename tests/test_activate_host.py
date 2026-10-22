"""The activation helper: the system profile is set before the switch, and the
two generation links are verified afterwards."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/activate-host"


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
        self.environment = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "GHOSTSHIP_CURRENT_SYSTEM": str(self.current),
            "GHOSTSHIP_SYSTEM_PROFILE": str(self.profile),
        }

    def run_helper(self, *arguments):
        return subprocess.run([str(SCRIPT), *arguments], env=self.environment,
                              capture_output=True, text=True, timeout=30)

    def steps(self):
        if not self.log.exists():
            return []
        return self.log.read_text().splitlines()

    def test_the_profile_is_set_before_the_switch(self):
        result = self.run_helper("--toplevel", str(self.toplevel))
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
        result = self.run_helper("--toplevel", str(self.toplevel))
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


if __name__ == "__main__":
    unittest.main()
