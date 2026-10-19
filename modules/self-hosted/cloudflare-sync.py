"""Reconcile registry-owned routes/DNS after verifying tunnel Access protection."""

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
    return domain == hostname or (
        domain.startswith("*.") and hostname.endswith(domain[1:])
        and hostname.count(".") == domain.count(".")
    )


def access_domains(application):
    # Destinations take precedence, including an explicitly empty list.
    if application.get("destinations") is not None:
        return [
            item.get("uri", "")
            for item in application["destinations"]
            if item.get("type") == "public"
        ]
    return application.get("self_hosted_domains") or [
        application.get("domain", "")
    ]


def relevant_domains(application, hostname):
    return [
        domain
        for domain in access_domains(application)
        if matches(domain.split("/", 1)[0], hostname)
        or matches(hostname, domain.split("/", 1)[0])
    ]


def fetch_access_policies(api, prefix, apps, hostnames):
    result = copy.deepcopy(apps)
    for application in result:
        if application.get("type") != "self_hosted" or not any(
            relevant_domains(application, host) for host in hostnames
        ):
            continue
        if not application.get("id"):
            raise ValueError("Relevant Access application has no ID")
        # The apps endpoint can return policy references, not full rules.
        application["policies"] = api.listing(
            prefix + f"/access/apps/{application['id']}/policies"
        )
    return result


def restricted_identity(selector):
    if not isinstance(selector, dict) or len(selector) != 1:
        return False
    kind, value = next(iter(selector.items()))
    field = {"email": "email", "email_domain": "domain"}.get(kind)
    return bool(
        field
        and isinstance(value, dict)
        and isinstance(value.get(field), str)
        and value[field].strip()
        and "*" not in value[field]
    )


def typed_service_token(selector):
    return (
        isinstance(selector, dict)
        and set(selector) == {"service_token"}
        and isinstance(selector["service_token"], dict)
        and isinstance(selector["service_token"].get("token_id"), str)
        and bool(selector["service_token"]["token_id"].strip())
        and selector["service_token"]["token_id"] != "*"
    )


def validate_access(apps, routes):
    for hostname in routes:
        # Tunnel wildcards route deeper names than Access wildcards protect.
        # Require explicit routes so every routed hostname can be verified.
        if "*" in hostname:
            raise ValueError(f"Wildcard tunnel ingress is not supported: {hostname}")
        covering = [
            (application, domain)
            for application in apps
            if application.get("type") == "self_hosted"
            for domain in relevant_domains(application, hostname)
        ]
        if not any(
            "/" not in domain and matches(domain, hostname)
            for _, domain in covering
        ):
            raise ValueError(f"No browser Access protection for {hostname}")
        for app, _ in covering:
            if app.get("options_preflight_bypass"):
                raise ValueError(
                    f"Unauthenticated OPTIONS bypass for {hostname}; inspect it first"
                )
            policies = app.get("policies")
            if not isinstance(policies, list) or not policies:
                raise ValueError(
                    f"Missing Access policy evidence for {hostname}"
                )
            browser_allow = False
            for policy in policies:
                decision = policy.get("decision")
                include = policy.get("include")
                if decision == "deny":
                    continue
                if (
                    decision == "allow"
                    and isinstance(include, list)
                    and include
                    and all(restricted_identity(item) for item in include)
                ):
                    browser_allow = True
                    continue
                if (
                    decision == "non_identity"
                    and isinstance(include, list)
                    and include
                    and all(typed_service_token(item) for item in include)
                ):
                    continue
                raise ValueError(
                    f"Unexpected Access policy for {hostname}; inspect it first"
                )
            if not browser_allow or set(app.get("allowed_idps", [])) != {GOOGLE_IDP}:
                raise ValueError(
                    f"No restricted Google identity Access policy for {hostname}"
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
    desired = merge_ingress(current["config"], routes, previous)
    # Audit existing rules as well as the proposed configuration, including
    # unrelated legacy exact/wildcard hosts and all path-specific overrides.
    hostnames = set(routes) | {
        rule["hostname"]
        for config in (current["config"], desired)
        for rule in config.get("ingress", [])
        if rule.get("hostname")
    }
    apps = fetch_access_policies(api, prefix, apps, hostnames)
    validate_access(apps, hostnames)
    operations = []
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
