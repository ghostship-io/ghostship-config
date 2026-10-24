"""One explicit model-evidence store for the picker and the probe recorder (#403).

The recorder writes under the T3 home; the picker used to resolve its own HOME,
so a recorded probe never reached the consumer. These tests hold the wiring that
makes the store explicit in every environment that runs either side.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T3CODE = ROOT / "modules/self-hosted/t3code.nix"
INTEGRATIONS = ROOT / "modules/self-hosted/private-integrations.nix"
T3_STORE = "/home/t3code/.local/state/ghostship/model-evidence.jsonl"
HOST_STORE = "/srv/apps/t3code/home/.local/state/ghostship/model-evidence.jsonl"


class EvidenceStoreTests(unittest.TestCase):
    def test_the_t3_container_names_the_store_explicitly(self):
        text = T3CODE.read_text()
        self.assertIn("GHOSTSHIP_MODEL_EVIDENCE_PATH", text)
        self.assertIn(T3_STORE, text)

    def test_the_mcp_host_and_container_name_the_same_store(self):
        text = INTEGRATIONS.read_text()
        self.assertIn(HOST_STORE, text)
        self.assertIn("/run/ghostship-model-evidence/model-evidence.jsonl", text)
        self.assertIn('"/srv/apps/t3code/home/.local/state/ghostship:/run/ghostship-model-evidence:ro"', text)

    def test_the_mcp_runtime_is_granted_read_by_the_existing_acl_pattern(self):
        text = INTEGRATIONS.read_text()
        self.assertIn("setfacl -m u:62020:rx", text)
        self.assertIn("setfacl -m d:u:62020:rX", text)
        self.assertIn("setfacl -m u:62020:r", text)


if __name__ == "__main__":
    unittest.main()
