"""Native T3-only MCP does not receive model-selection evidence."""
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
class EvidenceStoreTests(unittest.TestCase):
    def test_t3_recorder_keeps_its_explicit_store(self):
        text = (ROOT / 'modules/self-hosted/t3code.nix').read_text()
        self.assertIn('GHOSTSHIP_MODEL_EVIDENCE_PATH', text)
        self.assertIn('/home/t3code/.local/state/ghostship/model-evidence/model-evidence.jsonl', text)
    def test_native_connector_does_not_mount_or_grant_evidence(self):
        text = (ROOT / 'modules/self-hosted/private-integrations.nix').read_text()
        self.assertNotIn('/run/ghostship-model-evidence', text)
        self.assertNotIn('setfacl -m u:62020', text)
