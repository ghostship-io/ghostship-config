"""Guard root-only mount assembly against traversal and partial failure leaks."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = (
    Path(__file__).resolve().parents[1] / "packages/t3code/docker-sandbox/rootfs.py"
)
SPEC = importlib.util.spec_from_file_location("docker_rootfs", SOURCE)
rootfs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rootfs)


class RootfsSafety(unittest.TestCase):
    def test_destinations_cannot_escape_sandbox(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            root.mkdir()
            sibling = Path(temporary) / "sibling"
            sibling.mkdir()
            (root / "link").symlink_to(sibling)
            for path in ("relative", "/../etc/shadow", "/link/file"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    rootfs.destination(root, path)
            self.assertEqual(rootfs.destination(root, "/workspace"), root / "workspace")

    def test_untrusted_sources_cannot_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "link"
            sibling = Path(temporary) / "sibling"
            sibling.mkdir()
            source.symlink_to(sibling)
            with self.assertRaises(ValueError):
                rootfs.checked_source(str(source))

    def test_failed_mount_assembly_unmounts_partial_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            closure = Path(temporary) / "closure"
            closure.write_text("")
            spec = {
                "closure": str(closure),
                "mounts": [
                    {"source": "/absent-docker-test-source", "target": "/workspace"}
                ],
                "files": {},
                "directories": [],
            }
            with patch.object(rootfs, "run") as run, self.assertRaises(ValueError):
                rootfs.assemble(root, spec)
            self.assertEqual(run.call_args.args, ("umount", "--recursive", str(root)))

    def test_missing_nix_socket_directory_fails_closed(self):
        # Defect: an absent socket directory later appears in the live source
        # and gives the engine access to T3's inner Nix daemon.
        with tempfile.TemporaryDirectory() as temporary:
            closure = Path(temporary) / "closure"
            closure.write_text("")
            spec = {
                "closure": str(closure),
                "mounts": [],
                "files": {},
                "directories": [],
            }
            with (
                patch.object(rootfs, "run"),
                self.assertRaisesRegex(ValueError, "unmasked future socket"),
            ):
                rootfs.assemble(Path(temporary) / "root", spec)


if __name__ == "__main__":
    unittest.main()
