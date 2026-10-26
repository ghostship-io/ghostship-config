"""The T3 container's Go client reaches the live coordinator without exporting its token."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T3CODE = (ROOT / "modules/self-hosted/t3code.nix").read_text()
IMAGE = (ROOT / "packages/t3code/image.nix").read_text()
CHECKS = (ROOT / "checks.nix").read_text()
CATALOG = (ROOT / "secrets/catalog.nix").read_text()

PASS_ENVIRONMENT = (
    "PassEnvironment=GHOSTSHIP_ROUTE_POLICY_PATH GHOSTSHIP_COORDINATOR_URL "
    "GHOSTSHIP_COORDINATOR_TOKEN_FILE"
)


class T3CoordinatorClientTests(unittest.TestCase):
    def test_the_container_reaches_the_go_service_by_shared_network_name(self):
        self.assertIn(
            'goCoordinatorUrl = "http://ghostship-go-coordinator:18765";', T3CODE
        )
        self.assertIn("GHOSTSHIP_COORDINATOR_URL = goCoordinatorUrl;", T3CODE)

    def test_provider_sessions_get_only_the_token_path(self):
        self.assertIn(PASS_ENVIRONMENT, IMAGE)
        # No credential value may cross into provider sessions, which share the
        # server's cgroup and can read its environment.
        for name in ("GHOSTSHIP_COORDINATOR_TOKEN ", "GHOSTSHIP_COORDINATOR_TOKEN="):
            self.assertNotIn(f"PassEnvironment={name}", IMAGE)
        self.assertIn(
            "GHOSTSHIP_COORDINATOR_TOKEN_FILE = coordinatorTokenFile;", T3CODE
        )
        self.assertIn(
            'coordinatorTokenFile = "/run/secrets/coordinator-token.env";', T3CODE
        )

    def test_the_token_leaves_the_container_environment(self):
        # The t3code projection becomes the container environment, so the token
        # is no longer one of its fields; it has its own mounted file instead.
        t3code_projection = CATALOG.split("    t3code = {", 1)[1].split("\n    };", 1)[0]
        self.assertNotIn("GHOSTSHIP_COORDINATOR_TOKEN", t3code_projection)
        self.assertIn(
            "ghostship.secretProjections.t3code-coordinator-token = {", T3CODE
        )
        self.assertIn("owner = \"apps\";", T3CODE)
        self.assertIn("mode = \"0400\";", T3CODE)
        self.assertIn(
            'fileName = "t3code-coordinator/token.env";', T3CODE
        )
        self.assertIn(
            '"${config.ghostship.selfHostedSecrets.projections.t3code-coordinator-token.containerPath}:'
            '${coordinatorTokenFile}:ro"',
            T3CODE,
        )
        self.assertNotIn('GHOSTSHIP_COORDINATOR_TOKEN = "', IMAGE)
        self.assertNotIn('GHOSTSHIP_COORDINATOR_TOKEN = "', T3CODE)

    def test_the_token_still_comes_from_its_secret_unit(self):
        self.assertEqual(T3CODE.count("unit = \"go-coordinator-auth\";"), 1)
        self.assertIn('key = "TOKEN";', T3CODE)

    def test_the_flake_check_bans_credentials_from_provider_sessions(self):
        self.assertIn("credentialsPassedToSessions == [ ];", CHECKS)
        self.assertIn("projectedSecretNames = pkgs.lib.unique (", CHECKS)
        self.assertIn("t3codePassedEnvironment = pkgs.lib.splitString", CHECKS)
        self.assertIn(
            "t3codeConfig.ghostship.selfHostedSecrets.projections.t3code-coordinator-token",
            CHECKS,
        )
        self.assertIn(PASS_ENVIRONMENT, CHECKS)
        self.assertIn(
            "goCoordinatorSecrets.GHOSTSHIP_COORDINATOR_TOKEN.unit == t3codeServiceToken.unit",
            CHECKS,
        )
        self.assertIn(
            "assert !(t3codeContainer.environment ? GHOSTSHIP_COORDINATOR_TOKEN);", CHECKS
        )


if __name__ == "__main__":
    unittest.main()
