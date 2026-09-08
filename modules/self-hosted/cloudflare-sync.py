"""Reconcile registry-owned routes/DNS and ntfy's narrow native-auth exception."""

import argparse
import copy
import datetime
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ZONE = "ghostship.io"
MARKER = "Managed by nixos-config ghostship.apps"
NATIVE_APP = "Ghostship managed native auth: ntfy"
GOOGLE_IDP = "c694da42-b799-4706-983b-35fa9eb91236"


class Cloudflare:
    def __init__(self, token):
        self.token = token

    def request(self, method, path, data=None):
        request = urllib.request.Request(
            "https://api.cloudflare.com/client/v4" + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(
                f"Cloudflare {method} failed: HTTP {error.code}"
            ) from None
        except (OSError, ValueError):
            raise RuntimeError(f"Cloudflare {method} request failed") from None
        if not result.get("success"):
            raise RuntimeError(f"Cloudflare {method} rejected the operation")
        return result

    def get(self, path):
        return self.request("GET", path)["result"]

    def listing(self, path):
        output = []
        page = 1
        while True:
            separator = "&" if "?" in path else "?"
            result = self.request(
                "GET", f"{path}{separator}per_page=100&page={page}"
            )
            output.extend(result["result"])
            if page >= result.get("result_info", {}).get("total_pages", 1):
                return output
            page += 1


def matches(domain, hostname):
    domain = domain.split("/")[0]
    return domain == hostname or (
        domain.startswith("*.") and hostname.endswith(domain[1:])
    )


def validate_access(apps, routes):
    for hostname, route in routes.items():
        if route["access"] == "native":
            if hostname != "ntfy.ghostship.io":
                raise ValueError(
                    "Only ntfy has an approved native-auth exception"
                )
            continue
        covering = []
        for application in apps:
            if application.get("type") != "self_hosted":
                continue
            # The current API gives destinations precedence over legacy domains.
            if application.get("destinations") is not None:
                domains = [
                    item.get("uri", "")
                    for item in application["destinations"]
                    if item.get("type") == "public"
                ]
            else:
                domains = application.get("self_hosted_domains") or [
                    application.get("domain", "")
                ]
            covering.extend(
                (application, domain)
                for domain in domains
                if matches(domain, hostname)
            )
        if not any("/" not in domain for _, domain in covering):
            raise ValueError(f"No browser Access protection for {hostname}")
        for app, _ in covering:
            policies = app.get("policies", [])
            if (
                GOOGLE_IDP not in app.get("allowed_idps", [])
                or not any(p.get("decision") == "allow" for p in policies)
                or any(p.get("decision") == "bypass" for p in policies)
            ):
                raise ValueError(
                    f"Unexpected Access policy for {hostname}; inspect it first"
                )


def merge_ingress(current, routes, previous):
    ingress = current.get("ingress", [])
    if not ingress or "hostname" in ingress[-1] or "path" in ingress[-1]:
        raise ValueError("Expected terminal catch-all tunnel rule")
    owned = set(routes) | set(previous)
    old = {}
    unrelated = []
    for rule in ingress[:-1]:
        hostname = rule.get("hostname")
        if hostname not in owned:
            unrelated.append(copy.deepcopy(rule))
            continue
        if rule.get("path") or hostname in old:
            raise ValueError(f"Ambiguous managed tunnel rules for {hostname}")
        old[hostname] = rule
    managed = []
    for hostname, route in sorted(routes.items()):
        rule = copy.deepcopy(old.get(hostname, {}))
        rule.update(hostname=hostname, service=route["origin"])
        managed.append(rule)
    result = copy.deepcopy(current)
    # Exact managed routes precede wildcard/unmanaged rules. Unrelated rules,
    # including the in-flight Codex duplicates, retain their relative order.
    result["ingress"] = managed + unrelated + [copy.deepcopy(ingress[-1])]
    return result


def dns_operations(records, routes, previous, target, zone_id):
    operations = []
    prefix = f"/zones/{zone_id}/dns_records"
    for hostname in sorted(routes):
        existing = [record for record in records if record["name"] == hostname]
        if len(existing) > 1 or (existing and existing[0]["type"] != "CNAME"):
            raise ValueError(f"Ambiguous DNS record for {hostname}")
        desired = {
            "type": "CNAME",
            "name": hostname,
            "content": target,
            "proxied": True,
            "ttl": 1,
            "comment": MARKER,
        }
        if not existing:
            operations.append(
                ("POST", prefix, desired, f"Create DNS {hostname}")
            )
        elif any(
            existing[0].get(key) != value for key, value in desired.items()
        ):
            operations.append(
                (
                    "PATCH",
                    prefix + "/" + existing[0]["id"],
                    desired,
                    f"Sync DNS {hostname}",
                )
            )
    for hostname in sorted(set(previous) - set(routes)):
        for record in records:
            if (
                record["name"] == hostname
                and record["type"] == "CNAME"
                and record.get("comment") == MARKER
                and record["content"] == target
            ):
                operations.append(
                    (
                        "DELETE",
                        prefix + "/" + record["id"],
                        None,
                        f"Remove retired managed DNS {hostname}",
                    )
                )
    return operations


def save_json(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(".new")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry")
    parser.add_argument(
        "--apply", action="store_true", help="apply the reconciled changes"
    )
    parser.add_argument("--state-dir", default="/var/lib/ghostship-cloudflare")
    args = parser.parse_args()
    registry = json.loads(Path(args.registry).read_text())
    routes = {
        app["hostname"]: app for app in registry.values() if app["hostname"]
    }
    if any(
        not host.endswith("." + ZONE) or "/" in host or "*" in host
        for host in routes
    ):
        raise ValueError(
            "Registry hostnames must be exact names inside ghostship.io"
        )
    state_dir = Path(args.state_dir)
    state_file = state_dir / "managed.json"
    previous = (
        json.loads(state_file.read_text()) if state_file.exists() else []
    )
    api = Cloudflare(os.environ["CLOUDFLARED_API_TOKEN"])
    prefix = "/accounts/" + os.environ["CLOUDFLARED_ACCOUNT_ID"]
    tunnel_id = os.environ["CLOUDFLARED_TUNNEL_ID"]
    tunnel_path = prefix + f"/cfd_tunnel/{tunnel_id}/configurations"
    zones = api.listing("/zones?name=" + ZONE)
    if len(zones) != 1:
        raise ValueError("Expected exactly one ghostship.io zone")
    records = api.listing(f"/zones/{zones[0]['id']}/dns_records")
    apps = api.listing(prefix + "/access/apps")
    current = api.get(tunnel_path)
    validate_access(apps, routes)
    desired = merge_ingress(current["config"], routes, previous)
    operations = []
    native = [app for app in apps if app.get("domain") == "ntfy.ghostship.io"]
    if len(native) > 1 or any(app.get("name") != NATIVE_APP for app in native):
        raise ValueError("An unmanaged ntfy Access application already exists")
    if "ntfy.ghostship.io" in routes:
        if not native:
            operations.append(
                (
                    "POST",
                    prefix + "/access/apps",
                    {
                        "name": NATIVE_APP,
                        "type": "self_hosted",
                        "domain": "ntfy.ghostship.io",
                        "policies": [
                            {
                                "name": "Native ntfy authentication",
                                "decision": "bypass",
                                "include": [{"everyone": {}}],
                            }
                        ],
                    },
                    "Create ntfy-only native-auth exception",
                )
            )
        else:
            policies = api.listing(
                prefix + f"/access/apps/{native[0]['id']}/policies"
            )
            if (
                len(policies) != 1
                or policies[0].get("decision") != "bypass"
                or policies[0].get("include") != [{"everyone": {}}]
                or policies[0].get("exclude")
                or policies[0].get("require")
            ):
                raise ValueError(
                    "Managed ntfy exception drifted; inspect before changing it"
                )
    if desired != current["config"]:
        operations.append(
            (
                "PUT",
                tunnel_path,
                {"config": desired},
                "Synchronize managed tunnel routes",
            )
        )
    operations.extend(
        dns_operations(
            records,
            routes,
            previous,
            tunnel_id + ".cfargotunnel.com",
            zones[0]["id"],
        )
    )
    if (
        "ntfy.ghostship.io" not in routes
        and "ntfy.ghostship.io" in previous
        and native
    ):
        operations.append(
            (
                "DELETE",
                prefix + f"/access/apps/{native[0]['id']}",
                None,
                "Remove retired ntfy Access exception",
            )
        )
    for _, _, _, description in operations:
        print(description)
    if not args.apply:
        print(f"Plan only: {len(operations)} changes; no Cloudflare writes")
        return
    # Capture recoverable remote state before the first mutation, never tokens.
    if operations:
        stamp = datetime.datetime.now(datetime.UTC).strftime(
            "%Y%m%dT%H%M%S%fZ"
        )
        save_json(
            state_dir / "history" / f"{stamp}.json",
            {"tunnel": current, "dns": records, "apps": apps},
        )
    # Persist the ownership union before writes so partial runs/renames can be
    # retried or rolled back without losing track of newly-created records.
    save_json(state_file, sorted(set(previous) | set(routes)))
    for method, path, data, _ in operations:
        if path == tunnel_path and api.get(tunnel_path) != current:
            raise RuntimeError(
                "Tunnel changed during reconciliation; retry from fresh state"
            )
        api.request(method, path, data)
    save_json(state_file, sorted(routes))
    print(f"Cloudflare synchronized: {len(routes)} managed hostnames")


if __name__ == "__main__":
    main()
