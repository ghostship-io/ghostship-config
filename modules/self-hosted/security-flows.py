#!/usr/bin/env python3
"""Aggregate the observe-only nftables flow sets into a container edge map.

The kernel sets hold (source, destination, protocol, port) tuples with a
counter of new connections. Each collection resolves addresses to container
names at that moment and merges counter deltas into a root-only JSON state
file. Only connection metadata is kept: no payloads, no query strings.
"""

import argparse
import ipaddress
import json
import os
import subprocess
import sys
import tempfile
import time

# (label, family, table, set). The accepted sets sit after every filter, so
# a connection counted in flows but not in accepted was dropped.
SETS = [
    ("inet", "inet", "ghostship_flows", "flows4"),
    ("inet", "inet", "ghostship_flows", "flows6"),
    ("bridge", "bridge", "ghostship_flows", "flows4"),
    ("inet-accepted", "inet", "ghostship_flows", "accepted4"),
    ("inet-accepted", "inet", "ghostship_flows", "accepted6"),
    ("bridge-accepted", "bridge", "ghostship_flows", "accepted4"),
]
ACCEPTED_SUFFIX = "-accepted"
MAX_WAN_SAMPLES = 16
# Podman reassigns addresses when a container is recreated; elements created
# before that still name the old address until their 6h set timeout.
ADDRESS_MEMORY_SECONDS = 24 * 3600
PRIVATE = [
    ipaddress.ip_network(n)
    for n in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "100.64.0.0/10",
        "169.254.0.0/16",
        "fc00::/7",
        "fe80::/10",
    )
]


def run_json(argv):
    return json.loads(subprocess.check_output(argv, text=True))


def set_elements(nft, family, table, name):
    try:
        doc = run_json([nft, "-j", "list", "set", family, table, name])
    except subprocess.CalledProcessError:
        return None
    for item in doc.get("nftables", []):
        if "set" in item:
            return item["set"].get("elem", [])
    return []


def parse_element(elem):
    body = elem.get("elem", elem)
    value = body.get("val") if isinstance(body, dict) else None
    values = value.get("concat") if isinstance(value, dict) else None
    if not values or len(values) != 4:
        return None
    counter = body.get("counter") or {}
    src, dst, proto, port = values
    return (str(src), str(dst), str(proto), int(port)), int(counter.get("packets", 1))


def address_names(podman):
    names = {}
    containers = run_json([podman, "ps", "--format", "json"])
    ids = [c["Id"] for c in containers]
    if not ids:
        return names
    for row in run_json([podman, "inspect", *ids]):
        name = row["Name"].lstrip("/")
        mode = row.get("HostConfig", {}).get("NetworkMode", "")
        for net in (row.get("NetworkSettings", {}).get("Networks") or {}).values():
            for key in ("IPAddress", "GlobalIPv6Address"):
                address = net.get(key)
                # Shared namespaces (qBittorrent in Gluetun) keep the owner's name.
                if address and not mode.startswith("container:"):
                    names.setdefault(address, name)
    return names


def host_addresses(ip):
    found = set()
    for link in run_json([ip, "-j", "addr"]):
        for info in link.get("addr_info", []):
            found.add(info["local"])
    return found


def classify(address, names, host, extra):
    if address in names:
        return names[address]
    if address in host:
        return "host"
    if address in extra:
        return extra[address]
    parsed = ipaddress.ip_address(address)
    # Discovery traffic (Plex GDM, SSDP, mDNS, device beacons) is not a peer edge.
    if parsed.is_multicast or address == "255.255.255.255" or (parsed.version == 4 and address.endswith(".255")):
        return "broadcast"
    if any(parsed in net for net in PRIVATE):
        return f"lan:{address}"
    return "wan"


def remember_addresses(state, names, now):
    """Return current names plus recently released addresses' last owners."""
    history = state.setdefault("addresses", {})
    for address, name in names.items():
        history[address] = {"name": name, "last_seen": now}
    for address in [a for a, h in history.items() if now - h["last_seen"] > ADDRESS_MEMORY_SECONDS]:
        del history[address]
    return {**{a: h["name"] for a, h in history.items()}, **names}


def load_state(path):
    try:
        with open(path) as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {"edges": {}, "elements": {}, "collections": 0}


def save_state(path, state):
    directory = os.path.dirname(path)
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=".flows-")
    with os.fdopen(fd, "w") as handle:
        json.dump(state, handle, indent=1, sort_keys=True)
    os.replace(temporary, path)


def merge(state, observed, names, host, extra, now):
    """Fold one collection into the state; returns newly seen edge keys."""
    previous = state.get("elements", {})
    current = {}
    new_edges = []
    for (family, (src, dst, proto, port)), packets in observed.items():
        raw = f"{family}|{src}|{dst}|{proto}|{port}"
        current[raw] = packets
        before = previous.get(raw)
        # A smaller counter means the element expired and was recreated.
        delta = packets if before is None or packets < before else packets - before
        if delta == 0:
            continue
        source = classify(src, names, host, extra)
        target = classify(dst, names, host, extra)
        key = f"{source}|{target}|{proto}|{port}"
        edge = state["edges"].get(key)
        if edge is None:
            edge = {"first_seen": now, "last_seen": now, "connections": 0, "accepted": 0, "hooks": []}
            state["edges"][key] = edge
            new_edges.append(key)
        if family.endswith(ACCEPTED_SUFFIX):
            edge["accepted"] = edge.get("accepted", 0) + delta
            continue
        edge["last_seen"] = now
        edge["connections"] += delta
        if family not in edge["hooks"]:
            edge["hooks"].append(family)
        if target == "wan":
            samples = edge.setdefault("wan_samples", [])
            if dst not in samples and len(samples) < MAX_WAN_SAMPLES:
                samples.append(dst)
    state["elements"] = current
    state["collections"] = state.get("collections", 0) + 1
    state["last_collection"] = now
    return new_edges


def collect(args):
    observed = {}
    missing = []
    for label, family, table, name in SETS:
        elements = set_elements(args.nft, family, table, name)
        if elements is None:
            missing.append(f"{family} {table} {name}")
            continue
        for elem in elements:
            parsed = parse_element(elem)
            if parsed:
                observed[(label, parsed[0])] = parsed[1]
    names = address_names(args.podman)
    host = host_addresses(args.ip)
    extra = dict(item.split("=", 1) for item in args.name or [])
    state = load_state(args.state)
    now = int(time.time())
    names = remember_addresses(state, names, now)
    new_edges = merge(state, observed, names, host, extra, now)
    state["missing_sets"] = missing
    save_state(args.state, state)
    print(json.dumps({"observed": len(observed), "new_edges": new_edges, "missing_sets": missing}))
    # Missing kernel sets mean the observer was unloaded; surface it as a failure.
    return 1 if missing else 0


def verdict(edge):
    """accepted, dropped, partial, or unknown for edges recorded before verdicts."""
    if "accepted" not in edge:
        return "unknown"
    if edge["accepted"] <= 0:
        return "dropped"
    return "accepted" if edge["accepted"] >= edge["connections"] else "partial"


def report(args):
    state = load_state(args.state)
    since = time.time() - args.since_hours * 3600 if args.since_hours else 0
    rows = []
    for key, edge in state["edges"].items():
        if edge.get("last_seen", 0) < since:
            continue
        source, target, proto, port = key.split("|")
        if args.source and source != args.source:
            continue
        rows.append((source, target, proto, int(port), edge))
    rows.sort(key=lambda r: (r[0], r[1], r[3]))
    if args.json:
        print(json.dumps([{"source": s, "target": t, "proto": p, "port": n, "verdict": verdict(e), **e} for s, t, p, n, e in rows], indent=1))
        return 0
    for source, target, proto, port, edge in rows:
        first = time.strftime("%Y-%m-%d", time.gmtime(edge["first_seen"]))
        last = time.strftime("%Y-%m-%d %H:%M", time.gmtime(edge["last_seen"]))
        print(f"{source:32} -> {target:32} {proto}/{port:<6} n={edge['connections']:<8} {verdict(edge):<10} first={first} last={last}")
    return 0


REPORT_OPTIONS = {"--json", "--source", "--since-hours"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", default="/var/lib/ghostship-security/flows.json")
    parser.add_argument("--nft", default="nft")
    parser.add_argument("--podman", default="podman")
    parser.add_argument("--ip", default="ip")
    parser.add_argument("--name", action="append", help="ADDRESS=LABEL for known non-container hosts")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("collect")
    rep = sub.add_parser("report")
    rep.add_argument("--json", action="store_true")
    rep.add_argument("--source")
    rep.add_argument("--since-hours", type=float, default=0)
    argv = list(sys.argv[1:] if argv is None else argv)
    if not {"collect", "report"} & set(argv):
        # Default to report; its options must follow the subcommand.
        first = next((i for i, a in enumerate(argv) if a.split("=")[0] in REPORT_OPTIONS), len(argv))
        argv.insert(first, "report")
    args = parser.parse_args(argv)
    return collect(args) if args.command == "collect" else report(args)


if __name__ == "__main__":
    sys.exit(main())
