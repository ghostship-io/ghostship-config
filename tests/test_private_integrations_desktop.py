"""Static regression checks for the shared Agent Desktop integration wiring."""
from __future__ import annotations

import pathlib
import unittest


MODULE = (pathlib.Path(__file__).resolve().parents[1]
          / "modules/self-hosted/private-integrations.nix")


class DesktopWiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = MODULE.read_text(encoding="utf-8")

    def test_keep_broker_uses_persistent_desktop(self):
        source = self.source
        self.assertIn('GHOSTSHIP_BROWSER_DRIVER=desktop', source)
        self.assertIn('AGENT_DESKTOP_SSH_KEY=/run/ghostship-integrations/agent-desktop-key', source)
        self.assertIn('AGENT_DESKTOP_SSH_KNOWN_HOSTS=', source)
        self.assertNotIn('GHOSTSHIP_PERSONAL_MANAGER_URL', source)
        self.assertNotIn('managerAddress', source)
        self.assertNotIn('profile_id =', source)

    def test_native_mcp_uses_only_t3_network(self):
        source = self.source
        self.assertIn('"--network=ghostship_net"', source)
        self.assertNotIn('"--network=agent_desktop_net"', source)
        self.assertNotIn('init-agent-desktop-net.service', source)

    def test_both_identities_resolve_to_desktop_chrome(self):
        source = self.source
        self.assertIn('User = { identity = "personal";', source)
        self.assertIn('Agent = { identity = "agent";', source)


    def test_service_credentials_are_scoped_and_read_only(self):
        source = self.source
        self.assertNotIn('"${serviceSecretsDir}:/run/ghostship-secrets:ro"', source)
        self.assertIn('/run/ghostship-native-mcp:/run/ghostship-integrations:ro', source)
        self.assertIn('group = "ghostship-mcp";', source)
        projections = source.split("serviceCredentials = {", 1)[1].split("\n  };", 1)[0]
        self.assertNotIn("cloudflare", projections)
        self.assertNotIn("DB_PASS", projections)

    def test_skills_reconcile_is_opt_in(self):
        source = self.source
        self.assertIn("skillsReconcile.enable = lib.mkEnableOption", source)
        self.assertIn("lib.mkIf cfg.skillsReconcile.enable", source)


if __name__ == "__main__":
    unittest.main()
