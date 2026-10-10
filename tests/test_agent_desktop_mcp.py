import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "modules/self-hosted/agent-desktop-mcp.py"
spec = importlib.util.spec_from_file_location("agent_desktop_mcp", SOURCE)
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


class FileWrites(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_backup_never_follows_a_dangling_destination_symlink(self):
        source = self.root / "config.toml"
        source.write_text("attacker-controlled input")
        outside = self.root / "outside"
        backup = source.with_name(source.name + ".pre-bladebro")
        backup.symlink_to(outside)
        mcp.backup(source)
        self.assertFalse(outside.exists())
        self.assertTrue(backup.is_symlink())

    def test_backup_is_private_and_preserves_the_first_version(self):
        source = self.root / "config.toml"
        source.write_text("original")
        source.chmod(0o755)
        mcp.backup(source)
        source.write_text("changed")
        mcp.backup(source)
        backup = source.with_name(source.name + ".pre-bladebro")
        self.assertEqual(backup.read_text(), "original")
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)

    def test_atomic_write_does_not_follow_target_or_predictable_temp_symlinks(self):
        victim = self.root / "victim"
        victim.write_text("unchanged")
        target = self.root / "config.toml"
        target.symlink_to(victim)
        predictable = Path(f"{target}.tmp.{os.getpid()}")
        predictable.symlink_to(victim)
        mcp.write_file(target, "replacement", os.getuid(), os.getgid(), mode=0o600)
        self.assertEqual(victim.read_text(), "unchanged")
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.read_text(), "replacement")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
