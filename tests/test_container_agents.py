"""Integration checks for sharing resources without clobbering user state."""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "setup_container_agents",
    Path(__file__).resolve().parents[1] / "scripts/setup-container-agents.py",
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class ContainerAgentsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.home, self.source, self.package = (
            root / "home",
            root / "source",
            root / "package",
        )
        skill = self.source / "skills/example/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: example\ndescription: Example workflow\n---\n")
        command = self.package / "bin/example"
        command.parent.mkdir(parents=True)
        command.write_text("#!/bin/sh\nexit 0\n")
        command.chmod(0o755)
        self.preferences = root / "AGENTS.md"
        self.preferences.write_text("Shared preferences\n")

    def install(self):
        return installer.install(self.home, self.source, self.package, self.preferences)

    def test_install_reapply_and_prune_preserve_user_resources(self):
        self.assertEqual(self.install(), (1, 1))
        self.assertEqual(self.install(), (1, 1))
        for path in [".agents/skills/example", ".gemini/config/skills/example"]:
            self.assertTrue((self.home / path / "SKILL.md").is_file())
        self.assertTrue(os.access(self.home / ".local/bin/example", os.X_OK))
        for path in [
            ".codex/AGENTS.md",
            ".config/opencode/AGENTS.md",
            ".gemini/GEMINI.md",
        ]:
            self.assertIn("Shared preferences", (self.home / path).read_text())
        local = self.home / ".agents/skills/local"
        local.mkdir()
        (local / "SKILL.md").write_text("local")
        (self.package / "bin/example").unlink()
        self.install()
        self.assertFalse((self.home / ".local/bin/example").is_symlink())
        self.assertEqual((local / "SKILL.md").read_text(), "local")

    def test_conflict_leaves_user_file_and_other_destinations_untouched(self):
        existing = self.home / ".codex/AGENTS.md"
        existing.parent.mkdir(parents=True)
        existing.write_text("User guidance")
        with self.assertRaisesRegex(ValueError, "unmanaged"):
            self.install()
        self.assertEqual(existing.read_text(), "User guidance")
        self.assertFalse((self.home / ".agents").exists())

    def test_migrate_existing_container_launcher(self):
        command = self.package / "bin/agent"
        command.write_text("#!/bin/sh\nexit 0\n")
        command.chmod(0o755)
        old = self.home / ".local/bin/agent"
        old.parent.mkdir(parents=True)
        old.symlink_to(self.home / "tools/bin/agent")
        self.install()
        self.assertEqual(old.resolve(), command)

    def test_antigravity_optional_name_is_normalized_for_other_providers(self):
        skill = self.source / "skills/example/SKILL.md"
        skill.write_text("---\ndescription: Example\n---\nRead references/help.md\n")
        resource = skill.parent / "references"
        resource.mkdir()
        (resource / "help.md").write_text("help")
        self.install()
        installed = self.home / ".agents/skills/example"
        self.assertIn("name: example", (installed / "SKILL.md").read_text())
        self.assertNotIn("name:", skill.read_text())
        self.assertEqual((installed / "references/help.md").read_text(), "help")


if __name__ == "__main__":
    unittest.main()
