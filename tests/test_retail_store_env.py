"""The retail clients' private store settings stay outside the repository."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SETTINGS = (
    "COSTCO_WAREHOUSE_ID",
    "COSTCO_WEB_WAREHOUSE_ID",
    "COSTCO_POSTAL_CODE",
    "COSTCO_STATE",
    "SAFEWAY_STORE_ID",
    "SAFEWAY_POSTAL_CODE",
    "TARGET_DEFAULT_STORE",
    "TARGET_POSTAL_CODE",
    "TARGET_STATE",
    "TARGET_TIMEZONE",
    "WALMART_STORE_ID",
    "WALMART_POSTAL_CODE",
    "HOMEDEPOT_STORE_ID",
    "HOMEDEPOT_POSTAL_CODE",
    "HOMEDEPOT_STATE",
    "BESTBUY_POSTAL_CODE",
)


class RetailStoreEnvTests(unittest.TestCase):
    def test_private_env_file_reaches_the_service_executor_and_t3code(self):
        integrations = (ROOT / "modules/self-hosted/private-integrations.nix").read_text()
        t3code = (ROOT / "modules/self-hosted/t3code.nix").read_text()
        self.assertIn("/etc/ghostship/retail-store.env", integrations)
        self.assertIn("environmentFiles", integrations)
        self.assertIn(
            '"f /etc/ghostship/retail-store.env 0600 root root -"', integrations)
        self.assertIn("retailStoreEnv", t3code)
        self.assertIn("/etc/ghostship/retail-store.env", t3code)
        self.assertIn("environmentFiles = [ t3codeSecrets retailStoreEnv ]", t3code)

    def test_docs_name_every_setting_and_the_private_source(self):
        docs = (ROOT / "docs/retail-store-runtime.md").read_text()
        self.assertIn("/etc/ghostship/retail-store.env", docs)
        self.assertIn("systemd.tmpfiles", docs)
        self.assertIn("sole deployer", docs)
        for setting in SETTINGS:
            self.assertIn(setting, docs)


if __name__ == "__main__":
    unittest.main()
