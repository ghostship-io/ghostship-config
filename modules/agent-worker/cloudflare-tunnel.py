"""Provision one dedicated remotely managed Cloudflare tunnel for a T3 worker."""

import argparse
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ZONE = "ghostship.io"
MARKER = "Managed by nixos-config T3 WSL worker"
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
            response = self.request(
                "GET", f"{path}{separator}per_page=100&page={page}"
            )
            output.extend(response["result"])
            if page >= response.get("result_info", {}).get("total_pages", 1):
                return output
            page += 1


def matching_access_app(apps, hostname):
    exact = []
    wildcard = []
    for application in apps:
        if application.get("type") != "self_hosted":
            continue
        destinations = application.get("destinations")
        if destinations is not None:
            domains = [
                item.get("uri", "")
                for item in destinations
                if item.get("type") == "public"
            ]
        else:
            domains = application.get("self_hosted_domains") or [
                application.get("domain", "")
            ]
        for domain in domains:
            # A destination with a path protects only that path. This tunnel
            # publishes the complete T3 backend, so require host-wide Access.
            if not isinstance(domain, str) or "/" in domain:
                continue
            if domain == hostname:
                exact.append(application)
            elif domain.startswith("*."):
                suffix = domain[2:]
                single_label = hostname.count(".") == suffix.count(".") + 1
                if hostname.endswith("." + suffix) and single_label:
                    wildcard.append(application)
    candidates = exact or wildcard
    if len(candidates) > 1:
        raise RuntimeError(f"multiple Access applications cover {hostname}")
    return candidates[0] if candidates else None


def overlapping_access_apps(apps, hostname):
    matches = []
    for application in apps:
        if application.get("type") != "self_hosted":
            continue
        destinations = application.get("destinations")
        if destinations is not None:
            domains = [
                item.get("uri", "")
                for item in destinations
                if item.get("type") == "public"
            ]
        else:
            domains = application.get("self_hosted_domains") or [
                application.get("domain", "")
            ]
        for domain in domains:
            if not isinstance(domain, str):
                continue
            host = domain.split("/", 1)[0]
            exact = host == hostname
            wildcard = False
            if host.startswith("*."):
                suffix = host[2:]
                wildcard = (
                    hostname.endswith("." + suffix)
                    and hostname.count(".") == suffix.count(".") + 1
                )
            if (exact or wildcard) and application not in matches:
                matches.append(application)
    return matches


def desired_config(hostname, port):
    return {
        "ingress": [
            {"hostname": hostname, "service": f"http://127.0.0.1:{port}"},
            {"service": "http_status:404"},
        ],
        "warp-routing": {"enabled": False},
    }


def validate_access(application, policies, hostname):
    allowed = [policy for policy in policies if policy.get("decision") == "allow"]
    public_allow = any(
        any("everyone" in selector for selector in policy.get("include", []))
        for policy in allowed
    )
    if (
        set(application.get("allowed_idps", [])) != {GOOGLE_IDP}
        or not allowed
        or public_allow
        # Ghostship's scoped service-token policy is intentionally shared with
        # browser apps for authenticated monitoring. It is not an anonymous
        # bypass; reject only bypass and public "everyone" admission here.
        or any(policy.get("decision") == "bypass" for policy in policies)
    ):
        raise RuntimeError(
            f"Cloudflare Access for {hostname} must require the approved "
            "identity provider and must not allow everyone or bypass"
        )


def write_secret(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="." + path.name + ".", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(value + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args()
    if not args.hostname.endswith("." + ZONE) or "*" in args.hostname:
        raise ValueError(f"hostname must be an exact name inside {ZONE}")
    if not 1 <= args.port <= 65535:
        raise ValueError("port must be between 1 and 65535")

    api = Cloudflare(os.environ["CLOUDFLARED_API_TOKEN"])
    account_id = os.environ["CLOUDFLARED_ACCOUNT_ID"]
    prefix = "/accounts/" + account_id
    access_apps = api.listing(prefix + "/access/apps")
    access = matching_access_app(access_apps, args.hostname)
    if access is None:
        raise RuntimeError(
            f"no host-wide Cloudflare Access application covers {args.hostname}"
        )
    for application in overlapping_access_apps(access_apps, args.hostname):
        policies = application.get("policies")
        if policies is None:
            policies = api.listing(
                prefix + f"/access/apps/{application['id']}/policies"
            )
        validate_access(application, policies, args.hostname)

    tunnels = [
        tunnel
        for tunnel in api.listing(
            prefix + "/cfd_tunnel?is_deleted=false&name="
            + urllib.parse.quote(args.name)
        )
        if tunnel.get("name") == args.name and tunnel.get("deleted_at") is None
    ]
    if len(tunnels) > 1:
        raise RuntimeError(f"multiple active tunnels are named {args.name}")
    if tunnels:
        tunnel = tunnels[0]
    else:
        tunnel = api.request(
            "POST",
            prefix + "/cfd_tunnel",
            {"name": args.name, "config_src": "cloudflare"},
        )["result"]
        print(f"created tunnel {args.name}")
    tunnel_id = tunnel["id"]

    config_path = prefix + f"/cfd_tunnel/{tunnel_id}/configurations"
    desired = desired_config(args.hostname, args.port)
    current = api.get(config_path).get("config")
    if current != desired:
        api.request("PUT", config_path, {"config": desired})
        print(f"configured tunnel ingress for {args.hostname}")

    zones = api.listing("/zones?name=" + ZONE)
    if len(zones) != 1:
        raise RuntimeError(f"expected exactly one {ZONE} zone")
    zone_id = zones[0]["id"]
    records_path = f"/zones/{zone_id}/dns_records"
    records = [
        record
        for record in api.listing(
            records_path + "?name=" + urllib.parse.quote(args.hostname)
        )
        if record.get("name") == args.hostname
    ]
    if len(records) > 1 or (records and records[0].get("type") != "CNAME"):
        raise RuntimeError(f"ambiguous DNS record for {args.hostname}")
    dns = {
        "type": "CNAME",
        "name": args.hostname,
        "content": tunnel_id + ".cfargotunnel.com",
        "proxied": True,
        "ttl": 1,
        "comment": MARKER,
    }
    if not records:
        api.request("POST", records_path, dns)
        print(f"created DNS record for {args.hostname}")
    elif any(records[0].get(key) != value for key, value in dns.items()):
        existing = records[0]
        same_route = (
            existing.get("content") == dns["content"]
            and existing.get("proxied") is True
        )
        if existing.get("comment") != MARKER and not same_route:
            raise RuntimeError(f"DNS record for {args.hostname} is not managed here")
        api.request("PATCH", records_path + "/" + existing["id"], dns)
        print(f"updated DNS record for {args.hostname}")

    token = api.get(prefix + f"/cfd_tunnel/{tunnel_id}/token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Cloudflare returned an invalid connector token")
    write_secret(args.token_file, token)
    print(f"tunnel {args.name} is ready and protected by Cloudflare Access")


if __name__ == "__main__":
    main()
