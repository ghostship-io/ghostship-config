"""Advisor isolation and input checks; all credentials and commands are synthetic."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import sys
from unittest.mock import patch
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AdvisorTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "recovery_advisor", ROOT / "packages/t3code/recovery/advisor.py")
        self.advisor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.advisor)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.auth = self.root / "auth.json"
        self.now = time.time()
        self.write_auth()

    def write_auth(self, expiry=3600, refresh=0):
        payload = base64.urlsafe_b64encode(json.dumps(
            {"exp": self.now + expiry}).encode()).decode().rstrip("=")
        self.auth.write_text(json.dumps({"tokens": {"access_token": "e30." + payload + ".sig"},
                                       "last_refresh": self.now - refresh}))
        self.auth.chmod(0o600)

    def validate(self):
        return self.advisor.validate_auth(self.auth, uid=os.getuid(), now=self.now)

    def test_auth_accepts_only_fresh_private_regular_file(self):
        self.assertEqual(self.validate(), [self.auth.stat().st_dev, self.auth.stat().st_ino])

    def test_auth_rejects_symlink_components(self):
        linked = self.root / "linked"
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.advisor.validate_auth(linked / "auth.json", uid=os.getuid(), now=self.now)

    def test_auth_rejects_hardlinks_and_wrong_mode(self):
        os.link(self.auth, self.root / "duplicate")
        with self.assertRaises(ValueError):
            self.validate()
        (self.root / "duplicate").unlink()
        self.auth.chmod(0o640)
        with self.assertRaises(ValueError):
            self.validate()

    def test_auth_rejects_wrong_owner(self):
        with self.assertRaises(ValueError):
            self.advisor.validate_auth(self.auth, uid=os.getuid() + 1, now=self.now)

    def test_auth_rejects_stale_expiring_and_malformed(self):
        for expiry, refresh in [(1200, 0), (-1, 0), (3600, 7 * 86400), (3600, -60)]:
            self.write_auth(expiry, refresh)
            with self.subTest(expiry=expiry, refresh=refresh), self.assertRaises(ValueError):
                self.validate()
        for malformed in [{"tokens": {}}, {"tokens": {"access_token": 1}}, [], None]:
            self.auth.write_text(json.dumps(malformed))
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                self.validate()

    def test_diagnostics_rejects_malformed_and_oversized_input(self):
        for contents in [b"{", b"[]", b" " * 65537]:
            path = self.root / "diagnostics.json"
            path.write_bytes(contents)
            with self.subTest(size=len(contents)), self.assertRaises(ValueError):
                self.advisor.read_diagnostics(path)

    def test_launcher_uses_fixed_argv_and_clean_environment(self):
        argv = self.advisor.command("/pinned/codex", "/schema", "/out")
        self.assertEqual(argv[0], "/pinned/codex")
        for flag in ["--ignore-user-config", "--ignore-rules", "--ephemeral",
                     "--skip-git-repo-check", "--output-schema"]:
            self.assertIn(flag, argv)
        self.assertIn("gpt-6.1-sol", argv)
        for feature in ["shell_tool", "multi_agent", "apps", "plugins", "browser_use"]:
            self.assertIn(feature, argv)
        env = self.advisor.environment("/private/home", "/ca")
        self.assertEqual(env["CODEX_REFRESH_TOKEN_URL_OVERRIDE"], "http://127.0.0.1:9")
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("SSH_AUTH_SOCK", env)

    def test_output_is_bounded_schema_data(self):
        schema = {"type": "object", "properties": {"action": {"enum": ["none"]}},
                  "required": ["action"], "additionalProperties": False}
        for value in [b'{"action":"shell"}', b'{"action":"none","command":"true"}', b" " * 16385]:
            with self.subTest(value=value[:40]), self.assertRaises(ValueError):
                self.advisor.validate_proposal(value, schema)
        self.assertEqual(self.advisor.validate_proposal(b'{"action":"none"}', schema), {"action": "none"})

    def test_bound_auth_inode_must_match_preflight(self):
        with self.assertRaises(ValueError):
            self.advisor.check_identity(self.auth, [0, 0], uid=os.getuid())

    def test_preflight_identity_is_readable_under_restrictive_service_umask(self):
        identity = self.root / "identity.json"
        args = ["advisor", "--preflight-auth", str(self.auth), "--identity", str(identity)]
        previous = os.umask(0o077)
        try:
            with patch.object(sys, "argv", args), patch.object(self.advisor, "validate_auth", return_value=[1, 2]):
                self.assertEqual(self.advisor.main(), 0)
        finally:
            os.umask(previous)
        self.assertEqual(identity.stat().st_mode & 0o777, 0o644)
        self.assertEqual(json.loads(identity.read_text()), [1, 2])

    def test_launcher_preserves_bound_output_inode_and_emits_only_valid_data(self):
        home = self.root / "private"
        home.mkdir()
        self.auth.rename(home / "auth.json")
        identity = self.root / "identity.json"
        identity.write_text(json.dumps(self.advisor.validate_auth(home / "auth.json", uid=os.getuid())))
        schema = self.root / "schema.json"
        schema.write_text(json.dumps({"type": "object", "properties": {"action": {"enum": ["none"]}},
                                      "required": ["action"], "additionalProperties": False}))
        diagnostics = self.root / "diagnostics.json"
        diagnostics.write_text('{"healthy":true}')
        output = self.root / "proposal.json"
        output.touch(mode=0o600)
        inode = output.stat().st_ino
        fake = self.root / "codex"
        fake.write_text("#!" + sys.executable + "\n" +
                        "import json, os, sys\n" +
                        "assert 'OPENAI_API_KEY' not in os.environ\n" +
                        "assert 'SSH_AUTH_SOCK' not in os.environ\n" +
                        "assert 'healthy' in sys.stdin.read()\n" +
                        "open(sys.argv[sys.argv.index('-o')+1], 'w').write('{\"action\":\"none\"}')\n")
        fake.chmod(0o700)
        arguments = ["advisor", "--identity", str(identity), "--codex", str(fake),
                     "--schema", str(schema), "--diagnostics", str(diagnostics),
                     "--output", str(output), "--home", str(home), "--ca", "/unused-ca"]
        with patch.object(sys, "argv", arguments), patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic"}):
            self.assertEqual(self.advisor.main(auth_uid=os.getuid()), 0)
        self.assertEqual(output.stat().st_ino, inode)
        self.assertEqual(json.loads(output.read_text()), {"action": "none"})


if __name__ == "__main__":
    unittest.main()
