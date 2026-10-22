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
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULES = ROOT / "modules" / "self-hosted"


def load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


renderer = load("owner_config_renderer", MODULES / "render-owner-config.py")
provision = load("monitoring_provision", MODULES / "monitoring-provision.py")

IDENTITY_FILE = "/etc/ghostship/owner-identity.env"


class OwnerConfigRendererTests(unittest.TestCase):
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
