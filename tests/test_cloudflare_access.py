import copy
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "cloudflare_access_sync",
    Path(__file__).resolve().parents[1] / "modules/self-hosted/cloudflare-sync.py")
cloudflare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cloudflare)


def identity_policy():
    return {
        "decision": "allow",
        "include": [{"email": {"email": "owner@example.org"}}],
    }


def application(domain="*.ghostship.io", policies=None):
    return {
        "id": "access-app",
        "name": "Existing Google protection",
        "type": "self_hosted",
        "domain": domain,
        "allowed_idps": [cloudflare.GOOGLE_IDP],
        "policies": [identity_policy()] if policies is None else policies,
    }


class AccessTests(unittest.TestCase):
    def test_native_marker_does_not_skip_access(self):
        for hostname in ("ntfy.ghostship.io", "sonarr.ghostship.io"):
            with (
                self.subTest(hostname=hostname),
                self.assertRaises(ValueError),
            ):
                cloudflare.validate_access(
                    [], {hostname: {"access": "native"}}
                )

    def test_existing_restrictive_wildcard_and_typed_service_policy_work(self):
        app = application(
            policies=[
                identity_policy(),
                {
                    "decision": "non_identity",
                    "include": [
                        {"service_token": {"token_id": "scoped-token"}}
                    ],
                },
            ]
        )
        cloudflare.validate_access(
            [app], {"ntfy.ghostship.io": {"access": "native"}}
        )
        cloudflare.validate_access([app], {"*.ghostship.io": {}})

    def test_unsafe_decisions_and_insufficient_evidence_fail(self):
        policies = [
            {"decision": "bypass", "include": [{"everyone": {}}]},
            {"decision": "allow", "include": [{"everyone": {}}]},
            {"decision": "non_identity", "include": [{"everyone": {}}]},
            {"decision": "non_identity", "include": [{"service_token": {}}]},
            {
                "decision": "allow",
                "include": [{"login_method": {"id": cloudflare.GOOGLE_IDP}}],
            },
            {"decision": "allow"},
            {"id": "policy-reference"},
            {"decision": "unknown"},
        ]
        for policy in policies:
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                cloudflare.validate_access(
                    [application(policies=[identity_policy(), policy])],
                    {"ntfy.ghostship.io": {}},
                )
        for policies in ([], None):
            app = application()
            app["policies"] = policies
            with (
                self.subTest(policies=policies),
                self.assertRaises(ValueError),
            ):
                cloudflare.validate_access([app], {"ntfy.ghostship.io": {}})

    def test_path_overrides_cannot_hide_behind_wildcard(self):
        for domain in (
            "ntfy.ghostship.io/api",
            "ntfy.ghostship.io/api/nested",
            "*.ghostship.io/api",
        ):
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                cloudflare.validate_access(
                    [
                        application(),
                        application(
                            domain,
                            [
                                {
                                    "decision": "bypass",
                                    "include": [{"everyone": {}}],
                                }
                            ],
                        ),
                    ],
                    {"ntfy.ghostship.io": {}},
                )

    def test_exact_override_is_audited_for_wildcard_ingress(self):
        with self.assertRaises(ValueError):
            cloudflare.validate_access(
                [
                    application(),
                    application(
                        "legacy.ghostship.io/nested/path",
                        [{"decision": "bypass"}],
                    ),
                ],
                {"*.ghostship.io": {}},
            )

    def test_path_only_and_narrower_wildcards_do_not_cover_hostname(self):
        for domain, hostname in (
            ("ntfy.ghostship.io/api", "ntfy.ghostship.io"),
            ("*.sub.ghostship.io", "*.ghostship.io"),
            ("ntfy.ghostship.io", "*.ghostship.io"),
            ("*.ghostship.io", "ghostship.io"),
        ):
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                cloudflare.validate_access(
                    [application(domain)], {hostname: {}}
                )

    def test_effective_destinations_override_legacy_domains(self):
        app = application()
        app["destinations"] = [
            {"type": "public", "uri": "ntfy.ghostship.io/api"}
        ]
        with self.assertRaises(ValueError):
            cloudflare.validate_access([app], {"ntfy.ghostship.io": {}})
        app["destinations"] = [{"type": "public", "uri": "ntfy.ghostship.io"}]
        app["domain"] = "unrelated.example.org"
        cloudflare.validate_access([app], {"ntfy.ghostship.io": {}})
        app["destinations"] = []
        with self.assertRaises(ValueError):
            cloudflare.validate_access([app], {"ntfy.ghostship.io": {}})

    def test_policy_references_are_fetched_for_every_overlapping_app(self):
        from unittest.mock import Mock

        apps = [
            application(),
            application("ntfy.ghostship.io/api"),
            application("other.example.org"),
        ]
        for index, app in enumerate(apps):
            app["id"] = str(index)
            app["policies"] = [{"id": "reference"}]
        original = copy.deepcopy(apps)
        api = Mock()
        api.listing.return_value = [identity_policy()]
        result = cloudflare.fetch_access_policies(
            api, "/accounts/a", apps, {"ntfy.ghostship.io"}
        )
        self.assertEqual(
            [call.args[0] for call in api.listing.call_args_list],
            [
                "/accounts/a/access/apps/0/policies",
                "/accounts/a/access/apps/1/policies",
            ],
        )
        self.assertEqual(apps, original)
        cloudflare.validate_access(result, {"ntfy.ghostship.io": {}})

    def run_reconciler(
        self, ingress, apps, policies, apply=False, records=None
    ):
        from unittest.mock import Mock

        api = Mock()
        api.get.return_value = {"config": {"ingress": ingress}}

        def listing(path):
            if path.startswith("/zones?"):
                return [{"id": "zone"}]
            if path.endswith("/dns_records"):
                return records or []
            if path.endswith("/access/apps"):
                return apps
            if path.endswith("/policies"):
                return policies
            raise AssertionError(path)

        api.listing.side_effect = listing
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "registry.json"
            registry.write_text(
                json.dumps(
                    {
                        "ntfy": {
                            "hostname": "ntfy.ghostship.io",
                            "access": "native",
                            "origin": "http://ntfy:80",
                        }
                    }
                )
            )
            args = ["cloudflare-sync", str(registry), "--state-dir", directory]
            if apply:
                args.append("--apply")
            with (
                patch.object(cloudflare, "Cloudflare", return_value=api),
                patch.object(sys, "argv", args),
                patch.dict(
                    os.environ,
                    {
                        "CLOUDFLARED_API_TOKEN": "test",
                        "CLOUDFLARED_ACCOUNT_ID": "a",
                        "CLOUDFLARED_TUNNEL_ID": "t",
                    },
                ),
            ):
                try:
                    cloudflare.main()
                except ValueError:
                    api.request.assert_not_called()
                    self.assertFalse(
                        (Path(directory) / "managed.json").exists()
                    )
                    raise
        return api

    def test_unrelated_legacy_rules_are_checked_before_any_writes(self):
        for host in (
            "legacy.ghostship.io",
            "*.legacy.ghostship.io",
            "legacy.example.org",
        ):
            with self.subTest(host=host), self.assertRaises(ValueError):
                self.run_reconciler(
                    [
                        {"hostname": host, "service": "http://legacy:80"},
                        {"service": "http_status:404"},
                    ],
                    [application("ntfy.ghostship.io")],
                    [identity_policy()],
                    apply=True,
                )

    def test_fetched_bypass_refuses_before_writes(self):
        with self.assertRaises(ValueError):
            self.run_reconciler(
                [{"service": "http_status:404"}],
                [application()],
                [
                    {"decision": "bypass", "include": [{"everyone": {}}]},
                ],
                apply=True,
            )

    def test_ntfy_renamed_app_never_generates_access_mutations(self):
        app = application("ntfy.ghostship.io", [{"id": "reference"}])
        app["name"] = "Ghostship ntfy (Cloudflare Access)"
        api = self.run_reconciler(
            [{"service": "http_status:404"}],
            [app],
            [identity_policy()],
            apply=True,
        )
        self.assertTrue(api.request.called)
        self.assertTrue(
            all(
                "/access/" not in call.args[1]
                for call in api.request.call_args_list
            )
        )

    def test_protected_synced_routes_are_idempotent_and_preserve_legacy_rules(
        self,
    ):
        ingress = [
            {"hostname": "ntfy.ghostship.io", "service": "http://ntfy:80"},
            {
                "hostname": "legacy.ghostship.io",
                "path": "/api",
                "service": "http://legacy:80",
            },
            {"hostname": "*.ghostship.io", "service": "http://legacy:80"},
            {"service": "http_status:404"},
        ]
        original = copy.deepcopy(ingress)
        api = self.run_reconciler(
            ingress,
            [application()],
            [identity_policy()],
            apply=True,
            records=[
                {
                    "id": "dns",
                    "name": "ntfy.ghostship.io",
                    "type": "CNAME",
                    "content": "t.cfargotunnel.com",
                    "proxied": True,
                    "ttl": 1,
                    "comment": cloudflare.MARKER,
                },
                {
                    "id": "legacy-dns",
                    "name": "legacy.ghostship.io",
                    "type": "CNAME",
                    "content": "t.cfargotunnel.com",
                    "proxied": True,
                    "ttl": 1,
                },
            ],
        )
        api.request.assert_not_called()
        self.assertEqual(ingress, original)

    def test_plan_with_protected_wildcard_never_writes(self):
        api = self.run_reconciler(
            [{"service": "http_status:404"}],
            [application()],
            [identity_policy()],
        )
        api.request.assert_not_called()
