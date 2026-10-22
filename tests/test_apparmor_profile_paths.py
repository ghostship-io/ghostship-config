"""The include tree the AppArmor check reads.

The host pins its own platform, so the package its parser searches is a
store path of that platform and no other machine can build it. The check
therefore reads the copy of the machine it runs on, and these tests hold
that resolution: the tree comes from the running machine, a different
package version is refused, and a missing directory is named.
"""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tests/check-apparmor-profiles.py"
spec = importlib.util.spec_from_file_location("check_apparmor_profiles", SCRIPT)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

HOST_PACKAGE = "/nix/store/host-apparmor-profiles-5.0.2"


class IncludePathTests(unittest.TestCase):
    """The include tree of the machine that runs the check."""

    def setUp(self):
        self.host_packages = check.host_packages
        self.local_package = check.local_package
        self.realise = check.realise
        self.addCleanup(self.restore)
        self.configured = os.environ.pop("APPARMOR_INCLUDE_DIR", None)
        if self.configured is not None:
            self.addCleanup(self.restore_environment)

    def restore(self):
        check.host_packages = self.host_packages
        check.local_package = self.local_package
        check.realise = self.realise

    def restore_environment(self):
        os.environ["APPARMOR_INCLUDE_DIR"] = self.configured

    def fake(self, local, host_name="apparmor-profiles-5.0.2",
             local_name="apparmor-profiles-5.0.2"):
        """The host's package, and this machine's copy of it."""
        check.host_packages = lambda root, host: [
            {"name": host_name, "pname": "apparmor-profiles", "out": HOST_PACKAGE}]
        check.local_package = lambda root, pname: {
            "name": local_name, "out": str(local), "drv": "/nix/store/local.drv"}
        check.realise = lambda root, derivations: None

    def test_the_tree_comes_from_the_machine_that_runs_the_check(self):
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / "apparmor-profiles"
            (local / "etc/apparmor.d").mkdir(parents=True)
            self.fake(local)
            paths = check.include_paths(ROOT, "chill-penguin")
            self.assertEqual(paths, [local / "etc/apparmor.d"])
            self.assertNotIn(HOST_PACKAGE, [str(path) for path in paths])

    def test_a_different_package_version_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / "apparmor-profiles"
            (local / "etc/apparmor.d").mkdir(parents=True)
            self.fake(local, host_name="apparmor-profiles-5.0.1",
                      local_name="apparmor-profiles-5.0.2")
            with self.assertRaises(check.CheckError) as failure:
                check.include_paths(ROOT, "chill-penguin")
            self.assertIn("apparmor-profiles-5.0.1", str(failure.exception))
            self.assertIn("apparmor-profiles-5.0.2", str(failure.exception))

    def test_a_missing_include_directory_is_named(self):
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / "apparmor-profiles"
            self.fake(local)
            with self.assertRaises(check.CheckError) as failure:
                check.include_paths(ROOT, "chill-penguin")
            self.assertIn(str(local), str(failure.exception))

    def test_a_missing_include_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "nowhere"
            with self.assertRaises(check.CheckError) as failure:
                check.check_include_directory(str(missing))
            self.assertIn(str(missing), str(failure.exception))

    def test_an_include_directory_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(check.check_include_directory(directory), Path(directory))

    def test_the_same_version_is_accepted(self):
        check.check_package_version("apparmor-profiles-5.0.2", "apparmor-profiles-5.0.2")


if __name__ == "__main__":
    unittest.main()
