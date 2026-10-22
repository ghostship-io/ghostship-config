"""Containment policy model: admission, nftables rendering and the manifest.

A containment policy describes exactly one container and is deliberately small:

    {
      "container": "candidate-app",
      "network": "ghostship_net",
      "subnet": "10.89.0.0/24",
      "address": "10.89.0.16",
      "mac": "02:89:00:00:00:16",
      "dnsServer": "10.89.0.1",
      "dns": true,
      "ipv6": "deny",
      "publicEgress": {"enabled": true, "protocols": ["tcp"], "ports": [443]},
      "edges": [{"peer": "peer-service", "address": "10.89.0.17",
                 "protocol": "tcp", "port": 8443, "purpose": "service api"}],
      "observed": [{"peer": "other-service", "protocol": "tcp", "port": 9000,
                    "category": "unclassified"}],
      "ingress": {"enabled": false, "ports": []},
      "capabilities": [],
      "privileged": false
    }

Three properties of the model matter:

* The source identity is explicit and reviewed. The policy states the network,
  the subnet, the address and the MAC that belong to the container. The rules
  are keyed by the address and the MAC, not by a device name: a bridge that was
  renamed or created late cannot turn the policy into a no-op, and a peer that
  claims the container's address is dropped before it reaches any chain that
  carries a verdict.
* Edges are directed and specific. Every edge names one peer, one protocol and
  one port. Nothing else the container sends is allowed.
* Observations are evidence, never approvals. Observed edges never become
  rules; they are reported as unresolved dependencies in the manifest so a
  reviewer can approve them one by one.

The renderer emits the same shape as the FlareSolverr egress rules
(modules/self-hosted/flaresolverr-egress.nft): one inet table and one bridge
table per container, replaced in a single nft transaction.
"""

from __future__ import annotations

import ipaddress
import json
import re

PROTOCOLS = ("tcp", "udp")
IPV6_MODES = ("deny", "allow")
TABLE_PREFIX = "ghostship_ci_"
MAX_TABLE_NAME = 32
MAC_PATTERN = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# Free-text fields must not carry coordinates: the repository is public.
URL_PATTERN = re.compile(r"[a-z][a-z0-9+.-]*://", re.IGNORECASE)
ADDRESS_IN_TEXT_PATTERN = re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b")
# Destinations that are never reachable through a public egress edge.
PRIVATE_IPV4 = (
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.0.2.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    "224.0.0.0/4",
    "240.0.0.0/4",
)


class PolicyError(Exception):
    """A policy that must not be turned into rules."""


def table_name(policy_name: str) -> str:
    """nft table name for one policy. Names are bounded by the kernel limit."""
    return TABLE_PREFIX + re.sub(r"[^a-z0-9_]", "_", policy_name.lower())


def _is_ipv4(value) -> bool:
    try:
        address = ipaddress.ip_address(str(value))
    except ValueError:
        return False
    return address.version == 4


def _is_port(value) -> bool:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return False
    return 1 <= port <= 65535


def normalize_capability(value: str) -> str:
    """Podman's capability spelling: case-insensitive, optional CAP_ prefix."""
    upper = str(value).strip().upper()
    return upper[len("CAP_"):] if upper.startswith("CAP_") else upper


def _text_is_clean(value: str) -> bool:
    """Free text stays free of coordinates: no URL, no IPv4 address."""
    return not URL_PATTERN.search(value) and not ADDRESS_IN_TEXT_PATTERN.search(value)


def _check_text(problems: list, value, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{field} must be a non-empty string")
        return
    if not _text_is_clean(value):
        problems.append(f"{field} must not contain URLs or IP addresses (public repository)")


def validate_container(policy_name: str, policy: dict) -> list:
    """Return every admission problem of one container policy."""
    problems: list = []
    if not NAME_PATTERN.match(policy_name):
        problems.append("policy name must be lower case letters, digits and dashes")
    if not isinstance(policy, dict):
        return problems + ["policy must be an object"]

    container = policy.get("container")
    if not isinstance(container, str) or not container.strip():
        problems.append("container must name the OCI container")

    network = policy.get("network")
    if not isinstance(network, str) or not network.strip():
        problems.append("network must name the podman network")
    elif network in ("host", "none") or network.startswith("container:"):
        # host and container networking share the host's stack: no bridge, no
        # identity, no containment.
        problems.append(f"network {network} is not a supported topology")

    address = policy.get("address")
    if not _is_ipv4(address):
        problems.append("address must be an IPv4 address")
    elif str(address).endswith(".0") or str(address).endswith(".255"):
        problems.append("address must be a host address, not a network or broadcast address")

    mac = policy.get("mac")
    if not isinstance(mac, str) or not MAC_PATTERN.match(mac.lower()):
        problems.append("mac must be a MAC address")
    else:
        if int(mac.split(":")[0], 16) & 1:
            problems.append("mac must be unicast")
        if not int(mac.split(":")[0], 16) & 2:
            problems.append("mac must be locally administered")

    dns = policy.get("dns", True)
    dns_server = policy.get("dnsServer")
    subnet = policy.get("subnet")
    network = None
    if isinstance(subnet, str) and subnet:
        try:
            network = ipaddress.ip_network(subnet, strict=False)
        except ValueError:
            problems.append("subnet must be an IPv4 network in CIDR form")
    else:
        problems.append("subnet must be an IPv4 network in CIDR form")
    if network is not None:
        if _is_ipv4(address) and ipaddress.ip_address(str(address)) not in network:
            problems.append(f"address {address} is outside {subnet}")
        if dns and _is_ipv4(dns_server) and ipaddress.ip_address(str(dns_server)) not in network:
            problems.append(f"dnsServer {dns_server} is outside {subnet}")
    if dns:
        if not _is_ipv4(dns_server):
            problems.append("dnsServer must be an IPv4 address when DNS is enabled")
    elif dns_server is not None and not _is_ipv4(dns_server):
        problems.append("dnsServer must be an IPv4 address when it is set")

    ipv6 = policy.get("ipv6", "deny")
    if ipv6 not in IPV6_MODES:
        problems.append(f"ipv6 must be one of {', '.join(IPV6_MODES)}")

    egress = policy.get("publicEgress") or {}
    if not isinstance(egress, dict):
        problems.append("publicEgress must be an object")
    else:
        protocols = egress.get("protocols") or []
        ports = egress.get("ports") or []
        if egress.get("enabled") and not protocols:
            problems.append("publicEgress needs at least one protocol")
        if egress.get("enabled") and not ports:
            problems.append("publicEgress needs at least one port")
        for protocol in protocols:
            if protocol not in PROTOCOLS:
                problems.append(f"publicEgress protocol {protocol} is not supported")
        for port in ports:
            if not _is_port(port):
                problems.append(f"publicEgress port {port} is not a port")

    seen_edges = set()
    edges = policy.get("edges") or []
    if not isinstance(edges, list):
        problems.append("edges must be a list")
        edges = []
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            problems.append(f"edges[{index}] must be an object")
            continue
        peer = edge.get("peer")
        if not isinstance(peer, str) or not peer.strip():
            problems.append(f"edges[{index}].peer must name the peer")
        if not _is_ipv4(edge.get("address")):
            problems.append(f"edges[{index}].address must be an IPv4 address")
        if edge.get("protocol") not in PROTOCOLS:
            problems.append(f"edges[{index}].protocol must be one of {', '.join(PROTOCOLS)}")
        if not _is_port(edge.get("port")):
            problems.append(f"edges[{index}].port must be a port")
        if "purpose" in edge:
            _check_text(problems, edge.get("purpose"), f"edges[{index}].purpose")
        key = (edge.get("address"), edge.get("protocol"), edge.get("port"))
        if key in seen_edges:
            problems.append(f"edges[{index}] repeats an earlier edge")
        seen_edges.add(key)
        if edge.get("address") == address:
            problems.append(f"edges[{index}] points at the container itself")

    observed = policy.get("observed") or []
    if not isinstance(observed, list):
        problems.append("observed must be a list")
        observed = []
    for index, item in enumerate(observed):
        if not isinstance(item, dict):
            problems.append(f"observed[{index}] must be an object")
            continue
        if not isinstance(item.get("peer"), str) or not item.get("peer").strip():
            problems.append(f"observed[{index}].peer must name the peer")
        if item.get("protocol") not in PROTOCOLS:
            problems.append(f"observed[{index}].protocol must be one of {', '.join(PROTOCOLS)}")
        if not _is_port(item.get("port")):
            problems.append(f"observed[{index}].port must be a port")
        if "category" in item:
            _check_text(problems, item.get("category"), f"observed[{index}].category")

    ingress = policy.get("ingress") or {}
    if not isinstance(ingress, dict):
        problems.append("ingress must be an object")
    else:
        for index, entry in enumerate(ingress.get("ports") or []):
            if not isinstance(entry, dict):
                problems.append(f"ingress.ports[{index}] must be an object")
                continue
            if entry.get("protocol") not in PROTOCOLS:
                problems.append(f"ingress.ports[{index}].protocol must be one of {', '.join(PROTOCOLS)}")
            if not _is_port(entry.get("port")):
                problems.append(f"ingress.ports[{index}].port must be a port")

    podman = policy.get("podman") or { }
    if not isinstance(podman, dict):
        problems.append("podman must be an object")
    else:
        if podman.get("user", "root") != "root":
            problems.append(
                f"podman user {podman.get('user')} is a rootless unit, and the rules live "
                "in the rootful host network namespace"
            )
        if podman.get("preRun"):
            problems.append(
                "pre-run podman flags can select a remote or differently rooted podman"
            )

    if policy.get("capabilityDropsAll") is not True:
        problems.append(
            "the policy needs an explicit capability drop of ALL: the runtime default set "
            "comes from a mutable configuration file and could grant NET_RAW or NET_ADMIN"
        )

    capabilities = policy.get("capabilities") or []
    if not isinstance(capabilities, list):
        problems.append("capabilities must be a list")
    else:
        for capability in capabilities:
            for name in str(capability).split(","):
                normalized = normalize_capability(name)
                if normalized in ("NET_ADMIN", "ALL", "NET_RAW", "SYS_ADMIN"):
                    problems.append(
                        f"capability {normalized} defeats the policy: a container with it can "
                        "change its own identity, craft its own frames, or setns into another "
                        "network namespace the rules do not govern"
                    )
    if policy.get("privileged"):
        problems.append("a privileged container cannot be contained")
    return problems


def admit(policies: dict) -> None:
    """Raise PolicyError when any policy must not be turned into rules."""
    problems: list = []
    if not isinstance(policies, dict):
        raise PolicyError("the policy set must be an object")
    version = policies.get("version")
    if version != 1:
        problems.append("policy set version must be 1")
    containers = policies.get("containers")
    if not isinstance(containers, dict):
        problems.append("policy set needs a containers object")
        containers = {}
    for name, policy in containers.items():
        for problem in validate_container(name, policy):
            problems.append(f"{name}: {problem}")
        table = table_name(name)
        if len(table) > MAX_TABLE_NAME:
            problems.append(f"{name}: table name {table} is longer than {MAX_TABLE_NAME} characters")
    if problems:
        raise PolicyError("; ".join(problems))


def _port_match(protocol: str, direction: str, port) -> str:
    return f"{protocol} {direction} {int(port)}"


def _edge_lines(prefix: str, edge: dict, scoped: bool) -> list:
    """Allow one directed edge.

    With `scoped`, the opening is a new connection and the continuation only
    matches when the connection was opened by the container towards the peer.
    A flow the peer opened towards the container never becomes an egress
    exemption, and a flow opened before the policy was loaded stays denied
    unless the edge is approved.

    Without `scoped` the rule matches the edge itself: one peer, one protocol,
    one port. The bridge family is filtered that way because connection
    tracking for bridged frames needs nf_conntrack_bridge, which the harness
    has to prove on the target kernel.
    """
    protocol = edge["protocol"]
    port = int(edge["port"])
    address = edge["address"]
    opening = (
        f"{prefix} ip daddr {address} meta l4proto {protocol} "
        f"{_port_match(protocol, 'dport', port)}"
    )
    if not scoped:
        return [f"{opening} accept"]
    return [
        f"{opening} ct state new accept",
        f"{opening} ct state established,related "
        f"ct original ip saddr {edge['source']} ct original ip daddr {address} accept",
    ]


def render_container(policy_name: str, policy: dict) -> str:
    """Render the nftables ruleset of one container policy."""
    table = table_name(policy_name)
    address = policy["address"]
    mac = policy["mac"].lower()
    edges = []
    for edge in policy.get("edges") or []:
        edge = dict(edge)
        edge["source"] = address
        edges.append(edge)
    observed = policy.get("observed") or []
    egress = policy.get("publicEgress") or {}
    ingress = policy.get("ingress") or {}

    lines: list = []
    lines.append(f"# Generated by modules/self-hosted/container-isolation/generate-policy.py.")
    lines.append(f"# Policy: {policy_name}")
    lines.append(f"# Container: {policy.get('container')}")
    lines.append(f"# Identity: network {policy.get('network')}, address {address}, mac {mac}")
    lines.append(f"# Approved edges: {len(edges)}. Observed, never approved: {len(observed)}.")
    lines.append("#")
    lines.append("# The destroy and create below are one nft transaction: a reload")
    lines.append("# replaces the policy atomically and never leaves the container")
    lines.append("# unprotected.")
    lines.append("")
    lines.append(f"destroy table inet {table}")
    lines.append(f"destroy table bridge {table}")
    lines.append("")
    lines.append(f"table inet {table} {{")
    lines.append("    set private_ipv4 {")
    lines.append("        type ipv4_addr; flags interval;")
    lines.append("        elements = { " + ", ".join(PRIVATE_IPV4[:7]) + ",")
    lines.append("            " + ", ".join(PRIVATE_IPV4[7:]) + " };")
    lines.append("    }")

    # ---- inet forward: routed traffic in both directions ----
    lines.append("    chain forward {")
    lines.append("        type filter hook forward priority -10; policy accept;")
    for edge in edges:
        lines.append(f"        # Approved edge to {edge['peer']} ({edge['protocol']}/{edge['port']}).")
        lines.extend(
            "        " + line
            for line in _edge_lines(f"ip saddr {address}", edge, scoped=True)
        )
    if egress.get("enabled"):
        for protocol in egress.get("protocols") or []:
            for port in egress.get("ports") or []:
                lines.append(
                    f"        # Public egress is explicit: {protocol}/{port} to public addresses."
                )
                lines.append(
                    f"        ip saddr {address} meta l4proto {protocol} "
                    f"{_port_match(protocol, 'dport', port)} ip daddr != @private_ipv4 "
                    f"ct state new accept"
                )
                lines.append(
                    f"        ip saddr {address} meta l4proto {protocol} "
                    f"{_port_match(protocol, 'dport', port)} ip daddr != @private_ipv4 "
                    f"ct state established,related ct original ip saddr {address} "
                    f"ct original ip daddr != @private_ipv4 accept"
                )
    if ingress.get("enabled"):
        for entry in ingress.get("ports") or []:
            lines.append(
                f"        # Egress: the reply of a connection that reached service port {entry['port']}."
            )
            lines.append(
                f"        ip saddr {address} meta l4proto {entry['protocol']} "
                f"{_port_match(entry['protocol'], 'sport', entry['port'])} "
                f"ct state established,related ct direction reply accept"
            )
    lines.append("        # Private and LAN destinations are denied, approved edges aside.")
    lines.append(f"        ip saddr {address} ip daddr @private_ipv4 drop")
    lines.append("        # Everything else this container sends is denied.")
    lines.append(f"        ip saddr {address} drop")
    if ingress.get("enabled"):
        for edge in edges:
            lines.append(
                f"        # Ingress: the reply to the approved edge to {edge['peer']}."
            )
            lines.append(
                f"        ip saddr {edge['address']} ip daddr {address} meta l4proto {edge['protocol']} "
                f"{_port_match(edge['protocol'], 'sport', edge['port'])} ct state established,related "
                f"ct original ip saddr {address} ct original ip daddr {edge['address']} accept"
            )
        for entry in ingress.get("ports") or []:
            protocol = entry["protocol"]
            lines.append(
                f"        # Ingress: declared service port {protocol}/{entry['port']}."
            )
            lines.append(
                f"        ip daddr {address} meta l4proto {protocol} "
                f"{_port_match(protocol, 'dport', entry['port'])} accept"
            )
        lines.append("        # Everything else addressed to the container is denied.")
        lines.append(f"        ip daddr {address} drop")
    lines.append("    }")

    # ---- inet input: traffic the container sends to the host itself ----
    lines.append("    chain input {")
    lines.append("        type filter hook input priority -10; policy accept;")
    if policy.get("dns", True):
        lines.append("        # DNS: the resolver answers over UDP and TCP.")
        for protocol in PROTOCOLS:
            lines.append(
                f"        ip saddr {address} ip daddr {policy['dnsServer']} "
                f"{_port_match(protocol, 'dport', 53)} accept"
            )
    for edge in edges:
        lines.append(
            f"        # Approved edge to {edge['peer']} ({edge['protocol']}/{edge['port']})."
        )
        lines.extend(
            "        " + line
            for line in _edge_lines(f"ip saddr {address}", edge, scoped=True)
        )
    if ingress.get("enabled"):
        for entry in ingress.get("ports") or []:
            lines.append(
                f"        # Egress: the reply of a connection that reached service port {entry['port']}."
            )
            lines.append(
                f"        ip saddr {address} meta l4proto {entry['protocol']} "
                f"{_port_match(entry['protocol'], 'sport', entry['port'])} "
                f"ct state established,related ct direction reply accept"
            )
    lines.append("        # Everything else this container sends to the host is denied.")
    lines.append(f"        ip saddr {address} drop")
    lines.append("    }")
    lines.append("}")

    # ---- bridge: same-segment traffic and the identity binding ----
    # The bridge family names the bridge port, not the bridge, so the rules
    # are bound to the container's MAC and address instead of to a device
    # name. The MAC is the container's own identity and the address belongs
    # to the network the policy names.
    lines.append("")
    lines.append(f"table bridge {table} {{")
    lines.append("    chain prerouting {")
    lines.append("        type filter hook prerouting priority -10; policy accept;")
    lines.append("        # Identity: a frame that claims the container's address from another MAC is dropped.")
    lines.append(f"        ip saddr {address} ether saddr != {mac} drop")
    lines.append("        # Identity: the container's MAC may only claim the container's address.")
    lines.append(f"        ether saddr {mac} ip saddr != {address} drop")
    if policy.get("ipv6", "deny") == "deny":
        lines.append("        # IPv6 is denied for this container.")
        lines.append(f"        ether saddr {mac} ether type ip6 drop")
    lines.append("    }")
    lines.append("    chain forward {")
    lines.append("        type filter hook forward priority -10; policy accept;")
    for edge in edges:
        lines.append(f"        # Approved edge to {edge['peer']} ({edge['protocol']}/{edge['port']}).")
        lines.extend(
            "        " + line
            for line in _edge_lines(
                f"ether saddr {mac} ip saddr {address}", edge, scoped=False
            )
        )
    if ingress.get("enabled"):
        for entry in ingress.get("ports") or []:
            lines.append(
                f"        # Egress: the reply of a connection that reached service port {entry['port']}."
            )
            lines.append(
                f"        ether saddr {mac} ip saddr {address} meta l4proto {entry['protocol']} "
                f"{_port_match(entry['protocol'], 'sport', entry['port'])} "
                f"ct state established,related ct direction reply accept"
            )
    lines.append("        # Everything else this container sends on the bridge is denied.")
    lines.append(f"        ether saddr {mac} ip saddr {address} drop")
    if ingress.get("enabled"):
        for edge in edges:
            lines.append(f"        # Ingress: the reply to the approved edge to {edge['peer']}.")
            lines.append(
                f"        ether daddr {mac} ip saddr {edge['address']} "
                f"ip daddr {address} meta l4proto {edge['protocol']} "
                f"{_port_match(edge['protocol'], 'sport', edge['port'])} ct state established,related "
                f"ct original ip saddr {address} ct original ip daddr {edge['address']} accept"
            )
        for entry in ingress.get("ports") or []:
            protocol = entry["protocol"]
            lines.append(
                f"        # Ingress: declared service port {protocol}/{entry['port']}."
            )
            lines.append(
                f"        ether daddr {mac} ip daddr {address} meta l4proto {protocol} "
                f"{_port_match(protocol, 'dport', entry['port'])} accept"
            )
        lines.append("        # Everything else addressed to the container is denied.")
        lines.append(f"        ether daddr {mac} ip daddr {address} drop")
    lines.append("    }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def unresolved_dependencies(policy: dict) -> list:
    """Observed edges that no approved edge covers.

    Observations are evidence. They are reported here so a reviewer can
    approve them explicitly; nothing in this list becomes a rule.
    """
    approved = {
        (edge.get("address"), edge.get("protocol"), int(edge.get("port", 0)))
        for edge in policy.get("edges") or []
    }
    missing = []
    for item in policy.get("observed") or []:
        key = (item.get("address"), item.get("protocol"), int(item.get("port", 0)))
        if key not in approved:
            missing.append(item)
    return missing


def render_unload(policy_name: str) -> str:
    """Render the ruleset that removes one container's policy."""
    table = table_name(policy_name)
    return (
        f"# Generated by modules/self-hosted/container-isolation/generate-policy.py.\n"
        f"# Removes the containment policy for {policy_name}.\n"
        f"destroy table inet {table}\n"
        f"destroy table bridge {table}\n"
    )


def manifest(policies: dict) -> dict:
    """Describe what was generated, including the unresolved dependencies."""
    containers = {}
    for name, policy in (policies.get("containers") or {}).items():
        table = table_name(name)
        containers[name] = {
            "container": policy.get("container"),
            "network": policy.get("network"),
                "address": policy.get("address"),
            "mac": policy.get("mac"),
            "dnsServer": policy.get("dnsServer"),
            "dns": bool(policy.get("dns", True)),
            "ipv6": policy.get("ipv6", "deny"),
            "publicEgress": policy.get("publicEgress") or {},
            "ingress": policy.get("ingress") or {},
            "tables": {"inet": table, "bridge": table},
            "rulesFile": f"{name}.nft",
            "approved": policy.get("edges") or [],
            "observed": policy.get("observed") or [],
            "unresolved": unresolved_dependencies(policy),
        }
    return {"version": 1, "containers": containers}


def load(path) -> dict:
    with open(path) as handle:
        return json.load(handle)
