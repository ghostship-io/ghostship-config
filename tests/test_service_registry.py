import configparser
import copy
import unittest

from test_config import load

cloudflare = load("cloudflare_sync", "modules/self-hosted/cloudflare-sync.py")
dashboards = load("dashboard_sync", "modules/self-hosted/dashboard-sync.py")


def app(name="Sonarr", hostname="sonarr.ghostship.io"):
    return {
        "name": name,
        "container": "sonarr",
        "group": "Automation",
        "icon": "sh-sonarr",
        "description": "TV",
        "hostname": hostname,
        "origin": "http://sonarr:8989",
        "access": "google",
        "order": 1,
        "widget": {"type": "sonarr", "key": "env:API_KEY"},
        "muximux": {
            "enable": True,
            "url": "https://" + hostname,
            "icon": "fa-cube",
            "color": "#fff",
            "dropdown": True,
        },
    }


class RegistryTests(unittest.TestCase):
    def test_tunnel_merge_preserves_unmanaged_routes_and_global_options(self):
        current = {
            "warp-routing": {"enabled": True},
            "ingress": [
                {
                    "hostname": "codex.ghostship.io",
                    "service": "http://codex:8214",
                },
                {
                    "hostname": "codex.ghostship.io",
                    "service": "http://codex-web:8214",
                },
                {"hostname": "old.ghostship.io", "service": "http://old:80"},
                {
                    "hostname": "sonarr.ghostship.io",
                    "service": "http://old:8989",
                    "originRequest": {"connectTimeout": 30},
                },
                {"service": "http_status:404"},
            ],
        }
        untouched = copy.deepcopy(current)
        routes = {"sonarr.ghostship.io": app()}
        result = cloudflare.merge_ingress(
            current, routes, ["old.ghostship.io"]
        )
        self.assertEqual(current, untouched)
        self.assertEqual(result["warp-routing"], current["warp-routing"])
        self.assertEqual(result["ingress"][1:3], current["ingress"][:2])
        self.assertEqual(
            result["ingress"][0]["originRequest"], {"connectTimeout": 30}
        )
        self.assertEqual(result["ingress"][-1], {"service": "http_status:404"})
        self.assertEqual(
            result, cloudflare.merge_ingress(result, routes, list(routes))
        )

    def test_ambiguous_managed_tunnel_rule_is_rejected(self):
        rules = [
            {
                "hostname": "sonarr.ghostship.io",
                "path": "/api",
                "service": "http://x",
            },
            {"service": "http_status:404"},
        ]
        with self.assertRaises(ValueError):
            cloudflare.merge_ingress(
                {"ingress": rules}, {"sonarr.ghostship.io": app()}, []
            )

    def test_dns_removal_requires_marker_and_current_tunnel(self):
        records = [
            {
                "id": "1",
                "name": "old.ghostship.io",
                "type": "CNAME",
                "content": "other.cfargotunnel.com",
                "comment": cloudflare.MARKER,
            },
            {
                "id": "2",
                "name": "manual.ghostship.io",
                "type": "CNAME",
                "content": "ours.cfargotunnel.com",
            },
            {
                "id": "3",
                "name": "retired.ghostship.io",
                "type": "CNAME",
                "content": "ours.cfargotunnel.com",
                "comment": cloudflare.MARKER,
            },
        ]
        operations = cloudflare.dns_operations(
            records,
            {},
            [r["name"] for r in records],
            "ours.cfargotunnel.com",
            "zone",
        )
        self.assertEqual(len(operations), 1)
        self.assertEqual(
            operations[0][:2], ("DELETE", "/zones/zone/dns_records/3")
        )

    def test_synced_dns_has_no_writes(self):
        record = {
            "id": "1",
            "name": "sonarr.ghostship.io",
            "type": "CNAME",
            "content": "ours.cfargotunnel.com",
            "proxied": True,
            "ttl": 1,
            "comment": cloudflare.MARKER,
        }
        self.assertEqual(
            cloudflare.dns_operations(
                [record],
                {record["name"]: app()},
                [],
                record["content"],
                "zone",
            ),
            [],
        )

    def test_browser_route_requires_google_access_without_bypass(self):
        access = {
            "type": "self_hosted",
            "domain": "*.ghostship.io",
            "allowed_idps": [cloudflare.GOOGLE_IDP],
            "policies": [{"decision": "allow"}],
        }
        routes = {"sonarr.ghostship.io": app()}
        cloudflare.validate_access([access], routes)
        access["policies"].append({"decision": "bypass"})
        with self.assertRaises(ValueError):
            cloudflare.validate_access([access], routes)
        with self.assertRaises(ValueError):
            cloudflare.validate_access([], routes)

    def test_path_only_access_does_not_cover_whole_hostname(self):
        access = {
            "type": "self_hosted",
            "domain": "other.ghostship.io",
            "self_hosted_domains": [
                "other.ghostship.io",
                "sonarr.ghostship.io/admin",
            ],
            "allowed_idps": [cloudflare.GOOGLE_IDP],
            "policies": [{"decision": "allow"}],
        }
        with self.assertRaises(ValueError):
            cloudflare.validate_access(
                [access], {"sonarr.ghostship.io": app()}
            )
        access["self_hosted_domains"] = ["*.ghostship.io"]
        access["destinations"] = [
            {"type": "public", "uri": "sonarr.ghostship.io/admin"}
        ]
        with self.assertRaises(ValueError):
            cloudflare.validate_access(
                [access], {"sonarr.ghostship.io": app()}
            )
        access["destinations"] = [
            {"type": "public", "uri": "sonarr.ghostship.io"}
        ]
        cloudflare.validate_access([access], {"sonarr.ghostship.io": app()})

    def test_dashboard_rename_removes_owned_entry_and_preserves_custom_entries(
        self,
    ):
        data = [
            {
                "Automation": [
                    {"Old Sonarr": {"href": "https://old"}},
                    {"Personal link": {"href": "https://example.org"}},
                ]
            }
        ]
        updated = app("New Sonarr", "tv.ghostship.io")
        result = dashboards.homepage_entries(
            data,
            [updated],
            ["Old Sonarr"],
            lambda value: "resolved" if value.startswith("env:") else value,
        )
        entries = result[0]["Automation"]
        self.assertEqual(entries[0], data[0]["Automation"][1])
        self.assertEqual(
            entries[1]["New Sonarr"]["href"], "https://tv.ghostship.io"
        )
        self.assertEqual(
            entries[1]["New Sonarr"]["widget"]["url"], updated["origin"]
        )
        self.assertEqual(entries[1]["New Sonarr"]["widget"]["key"], "resolved")
        parser = configparser.ConfigParser(interpolation=None)
        parser["Old Sonarr"] = {"url": "https://old"}
        parser["Personal link"] = {"url": "https://example.org"}
        dashboards.muximux_entries(parser, [updated], ["Old Sonarr"])
        self.assertNotIn("Old Sonarr", parser)
        self.assertEqual(parser["Personal link"]["url"], "https://example.org")
        self.assertEqual(
            parser["New Sonarr"]["url"], entries[1]["New Sonarr"]["href"]
        )
        before = {key: dict(parser[key]) for key in parser.sections()}
        dashboards.muximux_entries(parser, [updated], ["New Sonarr"])
        self.assertEqual(
            before, {key: dict(parser[key]) for key in parser.sections()}
        )
