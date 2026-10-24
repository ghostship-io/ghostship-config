"""Keep Claude's logging and telemetry opt-outs managed, idempotent, and non-destructive."""

import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packages/t3code/provider-privacy"


def load(name):
    spec = importlib.util.spec_from_loader(
        f"provider_privacy_{name}",
        importlib.machinery.SourceFileLoader(f"provider_privacy_{name}", str(SOURCE / f"{name}.py")),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


setup = load("setup")


class PrivacyTest(unittest.TestCase):
    def test_configure_preserves_other_settings_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / ".claude/settings.json"
            path.parent.mkdir()
            path.write_text(json.dumps({"theme": "dark", "env": {"KEEP": "yes"}}))
            self.assertTrue(setup.configure(home))
            data = json.loads(path.read_text())
            self.assertEqual(data["theme"], "dark")
            self.assertEqual(data["env"]["KEEP"], "yes")
            for key, value in setup.PRIVACY.items():
                self.assertEqual(data["env"][key], value)
            before = path.stat().st_mtime_ns
            self.assertFalse(setup.configure(home))
            self.assertEqual(path.stat().st_mtime_ns, before)
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")

    def test_configure_creates_a_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            self.assertTrue(setup.configure(home))
            data = json.loads((home / ".claude/settings.json").read_text())
            self.assertEqual(data["env"], setup.PRIVACY)

    def test_invalid_env_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / ".claude/settings.json"
            path.parent.mkdir()
            original = json.dumps({"env": ["not", "an", "object"]})
            path.write_text(original)
            with self.assertRaises(ValueError):
                setup.configure(home)
            self.assertEqual(path.read_text(), original)

    def test_image_copies_and_runs_the_setup_before_the_server(self):
        image = (ROOT / "packages/t3code/image.nix").read_text()
        self.assertIn("cp -r ${./provider-privacy}/. usr/share/t3code-provider-privacy/", image)
        directive = "ExecStartPre=-${managedBin}/python3 /usr/share/t3code-provider-privacy/setup.py"
        self.assertIn(directive, image)
        self.assertLess(image.index(directive), image.index("ExecStart=${managedBin}/t3code-server-run"))


if __name__ == "__main__":
    unittest.main()
