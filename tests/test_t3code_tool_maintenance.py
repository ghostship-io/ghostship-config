import unittest
from pathlib import Path


SOURCE = (
    Path(__file__).resolve().parents[1] / "modules/self-hosted/t3code.nix"
).read_text()


class ToolMaintenanceSource(unittest.TestCase):
    def test_npm_agents_resolve_latest_online_before_installing(self):
        self.assertIn(
            'lookup_cache="$(mktemp -d)"', SOURCE
        )
        self.assertIn(
            'npm view --cache "$lookup_cache" --prefer-online '
            '"$package@latest" version',
            SOURCE,
        )
        self.assertIn(
            'npm install -g --prefer-online --no-fund --no-audit '
            '"$package@$expected_version"',
            SOURCE,
        )

    def test_npm_agents_verify_the_installed_manifest_version(self):
        self.assertIn(
            'manifest="$NPM_CONFIG_PREFIX/lib/node_modules/$package/package.json"',
            SOURCE,
        )
        self.assertIn(
            'if [ "$installed_version" != "$expected_version" ]; then', SOURCE
        )

    def test_image_includes_nodes_openssl_certificate_directory(self):
        self.assertIn("    openssl\n", SOURCE)


if __name__ == "__main__":
    unittest.main()
