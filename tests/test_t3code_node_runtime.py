"""Guard T3's Node runtime resolution against the removed execPath override.

T3 0.0.44's ``resolveNodeExecutable`` compares the ``node`` it finds on PATH
with ``process.execPath`` by realpath and by device/inode. The earlier
``t3-runtime-preload.cjs`` shim rewrote ``process.execPath`` to the pinned
Node, so T3 matched the container's Node against its own override and refused
every Antigravity session with ``NodeRuntimeUnavailableError``. The shim is
obsolete because the packaged T3 now resolves Node from ``PATH`` directly.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRELOAD = ROOT / "packages/t3code/t3-runtime-preload.cjs"
LAUNCHERS = (
    ROOT / "modules/self-hosted/t3code.nix",
    ROOT / "modules/agent-worker/t3code-worker.nix",
)


class NodeRuntimeOverrideTest(unittest.TestCase):
    def test_exec_path_override_is_gone(self):
        self.assertFalse(PRELOAD.exists(), "the execPath preload shim is obsolete")
        for launcher in LAUNCHERS:
            text = launcher.read_text()
            self.assertNotIn("T3CODE_NODE_EXECUTABLE", text)
            self.assertNotIn("t3-runtime-preload", text)


if __name__ == "__main__":
    unittest.main()
