#!/usr/bin/env python3
"""Verify the podman network's metadata before a policy is loaded.

Usage: check-network.py --network <name> --subnet <cidr> [--podman <path>]

The policy binds a container's address on a network. The network therefore has
to exist and to carry the subnet the policy names; otherwise the address
belongs to something else and the rules would match a stranger.

The check reads the network's metadata, not a bridge device. Netavark creates
the bridge when the first container attaches, so requiring the bridge before
the container starts would deadlock the first boot; the network definition
exists as soon as the network is created.

Exit status 0 means the metadata matches. Anything else fails the policy unit,
and the container does not start.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
import sys


def parse_metadata(document) -> dict:
    """Read the subnets and interface names out of `podman network inspect`."""
    entries = document if isinstance(document, list) else [document]
    subnets = []
    interfaces = []
    drivers = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        drivers.append(entry.get("driver"))
        for subnet in entry.get("subnets") or []:
            value = subnet.get("subnet") if isinstance(subnet, dict) else subnet
            if value:
                subnets.append(str(value))
        interface = entry.get("network_interface")
        if interface:
            interfaces.append(str(interface))
    return {
        "subnets": subnets,
        "interfaces": interfaces,
        "drivers": drivers,
        "entries": len(entries),
    }


def carries(metadata: dict, subnet: str) -> bool:
    """True when the network's metadata names exactly this subnet."""
    if metadata.get("entries") != 1 or metadata.get("drivers") != ["bridge"]:
        return False
    expected = ipaddress.ip_network(subnet, strict=False)
    for value in metadata.get("subnets") or []:
        try:
            if ipaddress.ip_network(value, strict=False) == expected:
                return True
        except ValueError:
            continue
    return False


def inspect(podman: str, network: str):
    result = subprocess.run(
        [podman, "network", "inspect", network, "--format", "json"],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None, result.stderr.strip()
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        return None, f"network metadata is not JSON: {error}"
    return parse_metadata(document), None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", required=True)
    parser.add_argument("--subnet", required=True)
    parser.add_argument("--podman", default="podman")
    args = parser.parse_args(argv)

    metadata, error = inspect(args.podman, args.network)
    if metadata is None:
        print(f"network {args.network} cannot be inspected: {error}", file=sys.stderr)
        return 1

    if not carries(metadata, args.subnet):
        print(
            f"network {args.network} carries {', '.join(metadata['subnets']) or 'no subnet'}, "
            f"not a single supported bridge network with subnet {args.subnet}",
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "network": args.network,
                "subnet": args.subnet,
                "interfaces": metadata["interfaces"],
                "ok": True,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
