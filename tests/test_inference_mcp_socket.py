"""Native T3-only MCP cannot access the unrelated inference socket."""
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
class InferenceSocketMountTests(unittest.TestCase):
    def test_native_mcp_has_no_inference_mount_or_dependency(self):
        source = (ROOT / 'modules/self-hosted/inference-bridge.nix').read_text()
        self.assertNotIn('containers.ghostship-private-integrations.volumes', source)
        self.assertNotIn('services.podman-ghostship-private-integrations', source)
