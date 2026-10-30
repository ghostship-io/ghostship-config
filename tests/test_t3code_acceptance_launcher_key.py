"""Failed-candidate identity follows the same managed launcher chain."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "acceptance_launcher_key", ROOT / "packages/t3code/acceptance-launcher-key.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AcceptanceLauncherKeyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.bin = self.home / ".local/state/t3code-shared-agents/bin"
        self.bin.mkdir(parents=True)
        for tool in ("agent", "ghostship", "ghostship-bladebro"):
            (self.bin / tool).write_text(
                f'#!/bin/sh\nexec /nix/store/{"a" * 32}-agent/bin/{tool} "$@"\n'
            )

    def test_store_identity_and_nested_managed_wrapper_change_key(self):
        first = module.launcher_key(self.home, "/home/candidate")
        nested = self.home / ".local/state/ghostship/tools/wrapper"
        nested.parent.mkdir(parents=True)
        nested.write_text(f'exec /nix/store/{"b" * 32}-agent/bin/agent "$@"\n')
        (self.bin / "agent").write_text('exec /home/candidate/.local/state/ghostship/tools/wrapper "$@"\n')
        nested_key = module.launcher_key(self.home, "/home/candidate")
        self.assertNotEqual(first, nested_key)
        nested.write_text(f'exec /nix/store/{"c" * 32}-agent/bin/agent "$@"\n')
        self.assertNotEqual(nested_key, module.launcher_key(self.home, "/home/candidate"))

    def test_unproven_or_missing_launcher_fails_closed(self):
        agent = self.bin / "agent"
        for text in (
            'exec /tmp/mutable/agent "$@"\n',
            f'exec /nix/store/{"a" * 32}-$MUTABLE/bin/agent "$@"\n',
            f'. /tmp/mutable/source\nexec /nix/store/{"a" * 32}-agent/bin/agent "$@"\n',
            f'. /tmp/mutable/source\nexec /nix/store/{"a" * 32}-agent/bin/agent "$@"\nexec /bin/other "$@"\n',
            'exec /home/candidate/.local/state/ghostship/../outside "$@"\n',
        ):
            with self.subTest(text=text):
                agent.write_text(text)
                with self.assertRaises(ValueError):
                    module.launcher_key(self.home, "/home/candidate")
        agent.unlink()
        with self.assertRaises(ValueError):
            module.launcher_key(self.home, "/home/candidate")


if __name__ == "__main__":
    unittest.main()
