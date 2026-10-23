"""The owner identity values come from the deployment, not from this repository.

The account names and addresses the services log in as are supplied in a file
outside the repository and reach the services through their environment. The
tests pin that the code reads the setting, that a missing setting fails with a
clear message instead of a fallback, and that the configuration templates keep
only the placeholder names.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULES = ROOT / "modules" / "self-hosted"


def load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_provision():
    """The provisioning module, with a stub when the socket library is absent.

    The check shell does not carry the Kuma client library, so the module is
    loaded against a stub. The stub only lives for the load, so the modules
    that use the real library keep it.
    """
    stubs: dict[str, types.ModuleType] = {}
    try:
        import engineio.payload  # noqa: F401
        import socketio  # noqa: F401
    except ImportError:
        payload = types.ModuleType("engineio.payload")

        class Payload:  # noqa: D401 - the stub only carries the limit
            max_decode_packets = 16

        payload.Payload = Payload
        engineio = types.ModuleType("engineio")
        engineio.payload = payload
        socketio = types.ModuleType("socketio")
        socketio.Client = object
        stubs = {"engineio": engineio, "engineio.payload": payload, "socketio": socketio}
    with mock.patch.dict(sys.modules, stubs):
        return load("monitoring_provision", MODULES / "monitoring-provision.py")


renderer = load("owner_config_renderer", MODULES / "render-owner-config.py")
provision = load_provision()

IDENTITY_FILE = "/etc/ghostship/owner-identity.env"


class OwnerConfigRendererTests(unittest.TestCase):
    def test_remaining_runtime_identifiers_are_rendered_with_their_json_types(self):
        template = json.dumps({
            "allowed_user_ids": ["@GHOSTSHIP_GITHUB_USER_ID@"],
            "t3_environment_id": "@GHOSTSHIP_T3_ENVIRONMENT_ID@",
            "base_url": "https://example.invalid/accounts/@GHOSTSHIP_CLOUDFLARE_ACCOUNT_ID@/ai",
            "project_id": "@GHOSTSHIP_T3_PROJECT_AGENT@",
        })
        values = {
            "GHOSTSHIP_GITHUB_USER_ID": "7",
            "GHOSTSHIP_T3_ENVIRONMENT_ID": "fixture-environment",
            "GHOSTSHIP_CLOUDFLARE_ACCOUNT_ID": "fixture-account",
            "GHOSTSHIP_T3_PROJECT_AGENT": "fixture-project",
        }
        rendered = json.loads(renderer.render(template, values))
        self.assertEqual(rendered, {
            "allowed_user_ids": [7],
            "t3_environment_id": "fixture-environment",
            "base_url": "https://example.invalid/accounts/fixture-account/ai",
            "project_id": "fixture-project",
        })

    def test_each_remaining_runtime_identifier_is_required_when_used(self):
        names = ("GHOSTSHIP_GITHUB_USER_ID", "GHOSTSHIP_T3_ENVIRONMENT_ID",
                 "GHOSTSHIP_CLOUDFLARE_ACCOUNT_ID", "GHOSTSHIP_T3_PROJECT_AGENT",
                 "GHOSTSHIP_T3_PROJECT_CONFIG", "GHOSTSHIP_T3_PROJECT_3DPRINTING",
                 "GHOSTSHIP_T3_PROJECT_ROMS", "GHOSTSHIP_T3_PROJECT_XPLUS4",
                 "GHOSTSHIP_T3_PROJECT_NEWSLETTER", "GHOSTSHIP_T3_PROJECT_ORCA")
        for name in names:
            with self.subTest(setting=name):
                with self.assertRaises(renderer.MissingIdentity):
                    renderer.render(json.dumps({"value": "@" + name + "@"}), {})

    def test_invalid_numeric_owner_identity_is_rejected_without_its_value(self):
        for value in ("0", "-1", "not-an-id", "1.5", '7", "injected": true'):
            with self.subTest(case=value):
                with self.assertRaises(renderer.MissingIdentity) as error:
                    renderer.render('{"allowed_user_ids":["@GHOSTSHIP_GITHUB_USER_ID@"]}',
                                    {"GHOSTSHIP_GITHUB_USER_ID": value})
                self.assertNotIn(value, str(error.exception))

    def test_a_template_is_filled_from_the_environment(self):
        template = '{"username": "@GHOSTSHIP_KUMA_USERNAME@"}'
        rendered = renderer.render(template, {"GHOSTSHIP_KUMA_USERNAME": "operator"})
        self.assertEqual(json.loads(rendered), {"username": "operator"})

    def test_a_missing_setting_fails_instead_of_falling_back(self):
        template = '{"username": "@GHOSTSHIP_KUMA_USERNAME@"}'
        with self.assertRaises(renderer.MissingIdentity) as failure:
            renderer.render(template, {})
        self.assertIn("GHOSTSHIP_KUMA_USERNAME", str(failure.exception))

    def test_a_template_without_a_placeholder_needs_no_setting(self):
        template = '{"username": "fixed"}'
        self.assertEqual(renderer.render(template, {}), template)

    def test_the_rendered_file_is_written_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            template = pathlib.Path(directory) / "template.json"
            template.write_text('{"username": "@GHOSTSHIP_KUMA_USERNAME@"}')
            output = pathlib.Path(directory) / "rendered.json"
            renderer.write(
                str(template),
                str(output),
                {"GHOSTSHIP_KUMA_USERNAME": "operator"},
                mode=0o600,
            )
            self.assertEqual(json.loads(output.read_text()), {"username": "operator"})
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)


class KumaUsernameTests(unittest.TestCase):
    def test_the_account_name_is_read_from_the_environment(self):
        self.assertEqual(
            provision.kuma_username({"GHOSTSHIP_KUMA_USERNAME": "operator"}), "operator"
        )

    def test_a_missing_account_name_fails_instead_of_falling_back(self):
        for environ in ({}, {"GHOSTSHIP_KUMA_USERNAME": "  "}):
            with self.subTest(environ=environ):
                with self.assertRaises(RuntimeError) as failure:
                    provision.kuma_username(environ)
                self.assertIn("GHOSTSHIP_KUMA_USERNAME", str(failure.exception))


class OwnerIdentityWiringTests(unittest.TestCase):
    """The modules read the settings and keep no account name of their own."""

    def test_the_identity_file_is_the_documented_source(self):
        for name in ("cleanup.nix", "monitoring.nix", "private-integrations.nix",
                     "github-engineering.nix"):
            with self.subTest(module=name):
                source = (MODULES / name).read_text(encoding="utf-8")
                self.assertIn(IDENTITY_FILE, source)

    def test_the_templates_keep_only_the_placeholder_names(self):
        source = (MODULES / "private-integrations.nix").read_text(encoding="utf-8")
        self.assertIn('"@GHOSTSHIP_KEEP_PERSONAL_EMAIL@"', source)
        self.assertIn('"@GHOSTSHIP_KEEP_AGENT_EMAIL@"', source)
        self.assertNotIn('@gmail.com', source)
        self.assertIn('"@GHOSTSHIP_KUMA_USERNAME@"', source)
        engineering = (MODULES / "github-engineering.nix").read_text(encoding="utf-8")
        self.assertIn('"@GHOSTSHIP_GITHUB_ACCOUNT@/', engineering)

    def test_the_ntfy_administrator_account_comes_from_the_environment(self):
        source = (MODULES / "monitoring.nix").read_text(encoding="utf-8")
        self.assertIn("$GHOSTSHIP_NTFY_ADMIN_USER:$NTFY_ADMIN_HASH:admin", source)
        self.assertIn("GHOSTSHIP_NTFY_ADMIN_USER", source)

    def test_the_retired_images_use_the_supplied_account(self):
        source = (MODULES / "cleanup.nix").read_text(encoding="utf-8")
        self.assertIn("ghcr.io/@GHOSTSHIP_GITHUB_ACCOUNT@/", source)
        self.assertIn("expand_owner_account", source)


if __name__ == "__main__":
    unittest.main()
