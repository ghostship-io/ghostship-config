"""Grafana's SIEM UI configuration (modules/self-hosted/siem/ui.nix).

The browser reaches Grafana through Cloudflare Access, and the auth proxy
trusts only cloudflared's address. Grafana must not also keep an account that
a password path could use, so it creates no administrator at all.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "modules/self-hosted/siem/ui.nix"


def grafana_environment():
    """The environment of the grafana container, as a mapping.

    A value is either a quoted string or a name from the module, such as the
    cloudflared address the auth proxy trusts.
    """
    text = UI.read_text()
    start = text.index("grafana = {")
    block = text[start:text.index("cloudflared.extraOptions", start)]
    begin = block.index("environment = {")
    end = block.index("};", begin)
    assignments = re.findall(
        r'(?m)^\s*([A-Z0-9_]+) = (?:"([^"]*)"|([A-Za-z0-9_.-]+));$', block[begin:end])
    return {key: quoted or bare for key, quoted, bare in assignments}


class GrafanaAccountTests(unittest.TestCase):
    def setUp(self):
        self.environment = grafana_environment()

    def test_grafana_creates_no_default_administrator(self):
        # Grafana creates admin/admin on the first start unless it is told
        # not to, and the account outlives the login paths below.
        self.assertEqual(
            self.environment.get("GF_SECURITY_DISABLE_INITIAL_ADMIN_CREATION"), "true")
        # The well-known password must not be configured either.
        self.assertNotIn("GF_SECURITY_ADMIN_PASSWORD", self.environment)
        self.assertNotIn("GF_SECURITY_ADMIN_USER", self.environment)

    def test_the_password_paths_stay_closed(self):
        # No form login, no basic auth, no anonymous access, no sign-up:
        # the only way in is the auth proxy, which trusts the header from
        # cloudflared's fixed address alone.
        self.assertEqual(self.environment.get("GF_AUTH_DISABLE_LOGIN_FORM"), "true")
        self.assertEqual(self.environment.get("GF_AUTH_BASIC_ENABLED"), "false")
        self.assertEqual(self.environment.get("GF_AUTH_ANONYMOUS_ENABLED"), "false")
        self.assertEqual(self.environment.get("GF_USERS_ALLOW_SIGN_UP"), "false")

    def test_the_auth_proxy_flow_still_signs_users_in(self):
        self.assertEqual(self.environment.get("GF_AUTH_PROXY_ENABLED"), "true")
        self.assertEqual(
            self.environment.get("GF_AUTH_PROXY_HEADER_NAME"), "Cf-Access-Authenticated-User-Email")
        self.assertEqual(self.environment.get("GF_AUTH_PROXY_AUTO_SIGN_UP"), "true")
        self.assertEqual(self.environment.get("GF_AUTH_PROXY_WHITELIST"), "cloudflaredAddress")
        # Without an administrator to promote them, the users are viewers.
        self.assertEqual(self.environment.get("GF_USERS_AUTO_ASSIGN_ORG_ROLE"), "Viewer")

    def test_the_dashboards_and_datasources_are_still_provisioned(self):
        text = UI.read_text()
        self.assertIn("cp ${./dashboards}/*.json", text)
        self.assertIn("datasources/siem.yaml", text)
        self.assertIn("dashboards/siem.yaml", text)


if __name__ == "__main__":
    unittest.main()
