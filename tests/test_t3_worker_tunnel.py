import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "t3_worker_tunnel",
    ROOT / "modules/agent-worker/cloudflare-tunnel.py",
)
tunnel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tunnel)


class T3WorkerTunnelTests(unittest.TestCase):
    def test_dedicated_tunnel_targets_worker_loopback(self):
        self.assertEqual(
            tunnel.desired_config("armored-armadillo-t3.ghostship.io", 3774),
            {
                "ingress": [
                    {
                        "hostname": "armored-armadillo-t3.ghostship.io",
                        "service": "http://127.0.0.1:3774",
                    },
                    {"service": "http_status:404"},
                ],
                "warp-routing": {"enabled": False},
            },
        )

    def test_wildcard_access_covers_worker(self):
        apps = [
            {
                "type": "self_hosted",
                "destinations": [{"type": "public", "uri": "*.ghostship.io"}],
            }
        ]
        self.assertIs(
            tunnel.matching_access_app(
                apps, "armored-armadillo-t3.ghostship.io"
            ),
            apps[0],
        )

    def test_path_scoped_access_does_not_cover_worker(self):
        apps = [
            {
                "type": "self_hosted",
                "domain": "armored-armadillo-t3.ghostship.io/admin",
            }
        ]
        self.assertIsNone(
            tunnel.matching_access_app(
                apps, "armored-armadillo-t3.ghostship.io"
            )
        )

    def test_exact_access_takes_precedence_over_wildcard(self):
        wildcard = {
            "type": "self_hosted",
            "domain": "*.ghostship.io",
        }
        exact = {
            "type": "self_hosted",
            "domain": "armored-armadillo-t3.ghostship.io",
        }
        self.assertIs(
            tunnel.matching_access_app(
                [wildcard, exact], "armored-armadillo-t3.ghostship.io"
            ),
            exact,
        )

    def test_wildcard_does_not_cover_multiple_labels(self):
        app = {"type": "self_hosted", "domain": "*.ghostship.io"}
        self.assertIsNone(
            tunnel.matching_access_app(
                [app], "nested.armored-armadillo.ghostship.io"
            )
        )

    def test_path_specific_access_is_included_in_validation_set(self):
        root = {"type": "self_hosted", "domain": "*.ghostship.io"}
        path = {
            "type": "self_hosted",
            "domain": "armored-armadillo-t3.ghostship.io/api/*",
        }
        self.assertEqual(
            tunnel.overlapping_access_apps(
                [root, path], "armored-armadillo-t3.ghostship.io"
            ),
            [root, path],
        )

    def test_secret_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token"
            tunnel.write_secret(path, "secret")
            self.assertEqual(path.read_text(), "secret\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_access_rejects_public_allow(self):
        app = {"allowed_idps": [tunnel.GOOGLE_IDP]}
        with self.assertRaises(RuntimeError):
            tunnel.validate_access(
                app,
                [{"decision": "allow", "include": [{"everyone": {}}]}],
                "armored-armadillo-t3.ghostship.io",
            )

    def test_access_accepts_identity_allow(self):
        app = {"allowed_idps": [tunnel.GOOGLE_IDP]}
        tunnel.validate_access(
            app,
            [
                {
                    "decision": "allow",
                    "include": [{"email": {"email": "user@example.com"}}],
                }
            ],
            "armored-armadillo-t3.ghostship.io",
        )

    def test_access_accepts_scoped_service_auth(self):
        app = {"allowed_idps": [tunnel.GOOGLE_IDP]}
        tunnel.validate_access(
            app,
            [
                {"decision": "allow", "include": [{"email": {}}]},
                {
                    "decision": "non_identity",
                    "include": [{"service_token": {"token_id": "scoped"}}],
                },
            ],
            "armored-armadillo-t3.ghostship.io",
        )


if __name__ == "__main__":
    unittest.main()
