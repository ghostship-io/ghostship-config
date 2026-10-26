"""The T3 container's Go client reaches the live coordinator with its token."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T3CODE = (ROOT / "modules/self-hosted/t3code.nix").read_text()
IMAGE = (ROOT / "packages/t3code/image.nix").read_text()
CHECKS = (ROOT / "checks.nix").read_text()
CATALOG = (ROOT / "secrets/catalog.nix").read_text()


class T3CoordinatorClientTests(unittest.TestCase):
    def test_the_container_reaches_the_go_service_by_shared_network_name(self):
        self.assertIn(
            'goCoordinatorUrl = "http://ghostship-go-coordinator:18765";', T3CODE
        )
        self.assertIn("GHOSTSHIP_COORDINATOR_URL = goCoordinatorUrl;", T3CODE)

    def test_provider_sessions_inherit_the_url_and_the_shared_secret(self):
        self.assertIn(
            "PassEnvironment=GHOSTSHIP_ROUTE_POLICY_PATH GHOSTSHIP_COORDINATOR_URL GHOSTSHIP_COORDINATOR_TOKEN",
            IMAGE,
        )

    def test_the_token_comes_from_the_projection_not_the_repo(self):
        self.assertNotIn('GHOSTSHIP_COORDINATOR_TOKEN = "', T3CODE)
        self.assertNotIn('GHOSTSHIP_COORDINATOR_TOKEN = "', IMAGE)
        self.assertIn(
            'GHOSTSHIP_COORDINATOR_TOKEN = {\n'
            '          unit = "go-coordinator-auth";\n'
            '          key = "TOKEN";\n'
            "        };",
            CATALOG,
        )

    def test_the_flake_check_pins_the_url_and_the_shared_secret(self):
        self.assertIn("t3codeContainer.environment.GHOSTSHIP_COORDINATOR_URL", CHECKS)
        self.assertIn(
            "goCoordinatorSecrets.GHOSTSHIP_COORDINATOR_TOKEN.unit == t3codeServiceToken.unit",
            CHECKS,
        )
        self.assertIn(
            "PassEnvironment=GHOSTSHIP_ROUTE_POLICY_PATH GHOSTSHIP_COORDINATOR_URL GHOSTSHIP_COORDINATOR_TOKEN",
            CHECKS,
        )


if __name__ == "__main__":
    unittest.main()
