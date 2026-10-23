"""The Grafana plugins are vendored in the repository, pinned by version and hash.

A plugin that Grafana fetches at runtime is a plugin that breaks the build
when the vendor's site is down, and a plugin that changes under the dashboard
without a review. Every plugin the UI loads is unpacked from a hashed
artifact in the repository, and the bundle is mounted read-only.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "modules/self-hosted/siem/ui.nix"

BUSINESS_TEXT_ID = "marcusolsson-dynamictext-panel"
BUSINESS_TEXT_VERSION = "6.3.0"


class GrafanaPluginPinTests(unittest.TestCase):
    def setUp(self):
        self.ui = UI.read_text(encoding="utf-8")

    def test_the_business_text_plugin_is_pinned_with_a_version_and_a_hash(self):
        """A plugin without a pinned version and hash is one the host fetches itself."""
        blocks = re.findall(r"pkgs\.fetchurl \{(.*?)\};", self.ui, re.S)
        pinned = [block for block in blocks if BUSINESS_TEXT_ID in block]
        self.assertEqual(
            len(pinned), 1, "the Business Text plugin is vendored once, by hash"
        )
        block = pinned[0]
        url = re.search(r'url = "([^"]+)"', block)
        digest = re.search(r'sha256 = "([^"]+)"', block)
        self.assertIsNotNone(url, "the pinned plugin carries its url")
        self.assertIsNotNone(digest, "the pinned plugin carries its hash")
        self.assertIn(
            f"{BUSINESS_TEXT_ID}/versions/{BUSINESS_TEXT_VERSION}/download",
            url.group(1),
            "the pinned plugin names its version, never a moving target",
        )
        self.assertRegex(
            digest.group(1),
            r"^sha256-[A-Za-z0-9+/]{43}=$",
            "the pinned plugin carries a sha256 of the artifact",
        )

    def test_the_pinned_plugins_are_unpacked_into_the_bundle_grafana_reads(self):
        """A pinned plugin that is not in the bundle is a pin that pins nothing."""
        bundle = re.search(
            r'plugins = pkgs\.runCommand "grafana-siem-plugins".*?\'\'(.*?)\'\';',
            self.ui,
            re.S,
        )
        self.assertIsNotNone(bundle, "the plugin bundle is a derivation")
        body = bundle.group(1)
        self.assertIn(
            "unzip -q ${businessTextPluginZip} -d $out",
            body,
            "the Business Text plugin is unpacked into the bundle",
        )
        self.assertIn(
            '"${plugins}:/var/lib/grafana-plugins:ro"',
            self.ui,
            "the bundle is the plugin directory Grafana reads",
        )

    def test_no_plugin_is_installed_when_grafana_starts(self):
        """A runtime install would fetch an unpinned artifact on every boot."""
        self.assertNotIn("plugins install", self.ui)
        self.assertNotIn("GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS", self.ui)
        self.assertIn('GF_PLUGINS_PREINSTALL_DISABLED = "true"', self.ui)
        self.assertIn('GF_PLUGINS_PUBLIC_KEY_RETRIEVAL_DISABLED = "true"', self.ui)


if __name__ == "__main__":
    unittest.main()
