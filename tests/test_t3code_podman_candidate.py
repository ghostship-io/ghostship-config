import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "candidate",
    Path(__file__).resolve().parents[1]
    / "packages/t3code/dev-engine/host-candidate.py",
)
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


class CandidateSafety(unittest.TestCase):
    def test_daemon_owned_symlink_cannot_redirect_root_directory_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "target").mkdir()
            (root / "home").symlink_to(root / "target")
            with (
                self.assertRaises(OSError),
                patch.object(candidate.os, "fchown") as chown,
            ):
                candidate.owned_directory(root / "home", os.getuid(), os.getgid())
            chown.assert_not_called()

    def test_active_or_starting_managers_are_not_adopted(self):
        for state in ("active", "activating", "reloading", "deactivating"):
            with (
                self.subTest(state=state),
                patch.object(candidate, "run", return_value=state),
            ):
                self.assertTrue(candidate.manager_active("user@62040.service"))
        with patch.object(candidate, "run", return_value="inactive"):
            self.assertFalse(candidate.manager_active("user@62040.service"))
