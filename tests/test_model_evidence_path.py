"""One explicit model-evidence store for the picker and the probe recorder (#403).

The recorder writes under the T3 home; the picker used to resolve its own HOME,
so a recorded probe never reached the consumer. These tests hold the wiring that
makes the store explicit in every environment that runs either side, and that
only the store's own directory — never the parent state tree — reaches the
integrations container.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T3CODE = ROOT / "modules/self-hosted/t3code.nix"
INTEGRATIONS = ROOT / "modules/self-hosted/private-integrations.nix"
T3_STORE = "/home/t3code/.local/state/ghostship/model-evidence/model-evidence.jsonl"
HOST_STORE = "/srv/apps/t3code/home/.local/state/ghostship/model-evidence/model-evidence.jsonl"
MOUNTED_STORE = "/run/ghostship-model-evidence/model-evidence.jsonl"
MOUNT = ('"/srv/apps/t3code/home/.local/state/ghostship/model-evidence:'
         '/run/ghostship-model-evidence:ro"')
PARENT_MOUNT = '"/srv/apps/t3code/home/.local/state/ghostship:/run/ghostship-model-evidence:ro"'


class EvidenceStoreTests(unittest.TestCase):
    def test_the_t3_container_names_the_store_explicitly(self):
        text = T3CODE.read_text()
        self.assertIn("GHOSTSHIP_MODEL_EVIDENCE_PATH", text)
        self.assertIn(T3_STORE, text)

    def test_the_host_and_the_container_name_the_same_store(self):
        text = INTEGRATIONS.read_text()
        self.assertIn(HOST_STORE, text)
        self.assertIn(MOUNTED_STORE, text)

    def test_only_the_store_directory_is_mounted_into_the_container(self):
        text = INTEGRATIONS.read_text()
        self.assertIn(MOUNT, text)
        self.assertNotIn(PARENT_MOUNT, text)
        # The pre-start names the dedicated directory, not the parent state tree.
        self.assertIn('evidence="$state/model-evidence"', text)

    def test_read_is_granted_by_acl_on_the_store_only(self):
        text = INTEGRATIONS.read_text()
        self.assertIn('setfacl -m u:62020:rx "$evidence"', text)
        self.assertIn('setfacl -m d:u:62020:rX "$evidence"', text)
        # An explicit mask keeps the named entry effective after a 0600 rewrite.
        self.assertIn('setfacl -m u:62020:r,m::r "$evidence/model-evidence.jsonl"', text)
        self.assertNotIn('setfacl -m u:62020:rx "$state"', text)

    def test_the_pre_403_store_is_moved_once_into_the_dedicated_directory(self):
        text = INTEGRATIONS.read_text()
        self.assertIn('legacy="$state/model-evidence.jsonl"', text)
        self.assertIn('mv "$legacy" "$evidence/model-evidence.jsonl"', text)


if __name__ == "__main__":
    unittest.main()
