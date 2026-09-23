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

    def test_claude_uses_the_version_matched_native_package_binary(self):
        self.assertIn(
            'native_binary="$native_dir/claude"', SOURCE
        )
        self.assertIn(
            'native_manifest="$native_dir/package.json"', SOURCE
        )
        self.assertIn(
            'ln "$native_binary" "$temporary"', SOURCE
        )
        self.assertIn(
            'npm install -g --force --prefer-online --no-fund --no-audit', SOURCE
        )
        self.assertIn(
            'verify_claude_native_binary "$expected_version" "$native_manifest" "$native_binary"',
            SOURCE,
        )
        self.assertIn(
            'Claude Code $expected_version is using the verified $platform native executable',
            SOURCE,
        )

    def test_user_cli_shims_replace_existing_links_instead_of_following_them(self):
        self.assertIn('temporary="$HOME/.local/bin/.$name.tmp.$$"', SOURCE)
        self.assertIn('mv -f "$temporary" "$HOME/.local/bin/$name"', SOURCE)
        self.assertIn('temporary="$HOME/.local/bin/.opencode.tmp.$$"', SOURCE)
        self.assertIn('mv -f "$temporary" "$HOME/.local/bin/opencode"', SOURCE)
        self.assertIn('temporary="$HOME/.local/bin/.t3.tmp.$$"', SOURCE)
        self.assertIn('mv -f "$temporary" "$HOME/.local/bin/t3"', SOURCE)

    def test_cli_version_probes_have_a_hard_timeout(self):
        self.assertIn(
            'timeout --kill-after=3s 15s "$tool_path" --version', SOURCE
        )
        self.assertIn('printf "unavailable:%s', SOURCE)

    def test_npm_agents_parse_json_output_from_user_npm_configuration(self):
        self.assertIn('const parsed = JSON.parse(input);', SOURCE)
        self.assertIn('if (typeof parsed === "string") version = parsed;', SOURCE)

    def test_image_includes_nodes_openssl_certificate_directory(self):
        self.assertIn("    openssl\n", SOURCE)


if __name__ == "__main__":
    unittest.main()
