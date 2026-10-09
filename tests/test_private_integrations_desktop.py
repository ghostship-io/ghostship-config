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

    def test_private_mcp_joins_both_required_networks(self):
        source = self.source
        self.assertIn('"--network=ghostship_net"', source)
        self.assertIn('"--network=agent_desktop_net"', source)
        self.assertIn('init-agent-desktop-net.service', source)

    def test_both_identities_resolve_to_desktop_chrome(self):
        source = self.source
        self.assertIn('User = { identity = "personal";', source)
        self.assertIn('Agent = { identity = "agent";', source)


if __name__ == "__main__":
    unittest.main()
