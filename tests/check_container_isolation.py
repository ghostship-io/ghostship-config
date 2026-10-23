#!/usr/bin/env python3
"""Containment policy checks: the model self-test and the namespace harness.

Two modes:

* `selftest` runs without privileges. It checks the policy model, the
  admission rules and the rendered ruleset: an unsupported topology, an
  ambiguous identity or an unsafe capability set must be refused, and an
  observed edge must never become a rule.
* `harness` runs as root on the target. It builds a disposable topology in
  its own network namespaces and loads the generated ruleset inside the
  router namespace only. Every namespace, bridge and nft table belongs to the
  run and is removed with it; the host's own rules, networks and containers
  are never touched.

The harness proves containment with real packets. Every denied destination is
proven reachable before the policy is loaded, so a later failure is the
policy's doing and not a broken topology.

Usage:
  check_container_isolation.py selftest
  check_container_isolation.py [--nft /path/to/nft] [--ip /path/to/ip] harness
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODEL = REPO / "modules" / "self-hosted" / "container-isolation"
sys.path.insert(0, str(MODEL))

import policy as model  # noqa: E402  (path is set above)

# Synthetic topology. The addresses are test values inside the ranges the
# repository already uses for its own networks; nothing here is a coordinate
# of a real host.
BRIDGE = "citest0"
SUBNET = "10.89.9.0/24"
GATEWAY = "10.89.9.1"
APP_IP = "10.89.9.16"
APP_MAC = "02:00:00:00:09:16"
PEER_IP = "10.89.9.17"
STRANGER_IP = "10.89.9.18"
SPOOFER_IP = "10.89.9.19"
ROUTED_IP = "10.89.10.17"
ROUTED_GATEWAY = "10.89.10.1"
LAN_IP = "192.168.77.10"
LAN_GATEWAY = "192.168.77.1"
PUBLIC_IP = "1.1.1.2"
PUBLIC_GATEWAY = "1.1.1.1"
V6_PREFIX = "fd00:c1::"
APP_V6 = V6_PREFIX + "16"
PEER_V6 = V6_PREFIX + "17"

APPROVED_PORT = 8443
ROUTED_PORT = 8444
UNAPPROVED_PORT = 9999
SERVICE_PORT = 8080
PUBLIC_PORT = 443
PUBLIC_DENIED_PORT = 8080
SPOOF_PORT = 9998
INGRESS_PORT = 9100
INGRESS_CLIENT_PORT = 9102
UNDECLARED_PORT = 9101
HOST_EDGE_PORT = 8081
REVOKE_PORT = 9200
DNS_PORT = 53
DNS_ANSWER = "203.0.113.10"


def synthetic_policy(ingress: bool = False) -> dict:
    """The policy the harness loads. Same shape the module generates."""
    return {
        "version": 2,
        "containers": {
            "candidate": {
                "container": "candidate-app",
                "network": "ghostship_net",
                "subnet": SUBNET,
                "address": APP_IP,
                "mac": APP_MAC,
                "dnsServer": GATEWAY,
                "dns": True,
                "ipv6": "deny",
                "publicEgress": {
                    "enabled": True,
                    "protocols": ["tcp"],
                    "ports": [PUBLIC_PORT],
                },
                "edges": [
                    {
                        "peer": "peer-service",
                        "address": PEER_IP,
                        "protocol": "tcp",
                        "port": APPROVED_PORT,
                        "purpose": "service api",
                    },
                    {
                        "peer": "routed-service",
                        "address": ROUTED_IP,
                        "protocol": "tcp",
                        "port": ROUTED_PORT,
                        "purpose": "service api",
                    },
                    {
                        "peer": "host-service",
                        "address": GATEWAY,
                        "protocol": "tcp",
                        "port": HOST_EDGE_PORT,
                        "purpose": "host api",
                    },
                ],
                "observed": [
                    {
                        "peer": "stranger",
                        "address": STRANGER_IP,
                        "protocol": "tcp",
                        "port": SERVICE_PORT,
                        "category": "unclassified",
                    }
                ],
                "ingress": {
                    "enabled": ingress,
                    "ports": (
                        [
                            {"protocol": "tcp", "port": INGRESS_PORT},
                            {"protocol": "tcp", "port": INGRESS_CLIENT_PORT},
                        ]
                        if ingress
                        else []
                    ),
                },
                "capabilities": [],
                "capabilityDropsAll": True,
                "privileged": False,
                "namespaces": {
                    "pid": [],
                    "userns": [],
                    "ipc": [],
                    "uts": [],
                    "cgroupns": [],
                    "pod": [],
                },
            }
        },
    }


# ---------------------------------------------------------------- helpers


def dns_query(name: str = "host.test") -> bytes:
    header = struct.pack("!HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0)
    question = (
        b"".join(bytes([len(label)]) + label.encode() for label in name.split("."))
        + b"\x00"
    )
    return header + question + struct.pack("!HH", 1, 1)


def dns_reply(query: bytes) -> bytes:
    header = struct.pack("!HHHHHH", 0x1234, 0x8180, 1, 1, 0, 0)
    question = query[12:]
    answer = struct.pack("!HHHIH", 0xC00C, 1, 1, 60, 4)
    answer += socket.inet_aton(DNS_ANSWER)
    return header + question + answer


def helper_lines(bind: str, port: str, countfile: str) -> int:
    """A line server: one reply per request line, on a kept open connection."""
    port = int(port)
    if ":" in bind:
        server = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        server.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    else:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((bind, port))
    server.listen(16)

    def serve(connection) -> None:
        try:
            connection.settimeout(30)
            buffer = b""
            while True:
                data = connection.recv(4096)
                if not data:
                    break
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    connection.sendall(b"OK\n")
                    with open(countfile, "a") as handle:
                        handle.write("answer\n")
        except OSError:
            pass
        finally:
            connection.close()

    while True:
        connection, _ = server.accept()
        with open(countfile, "a") as handle:
            handle.write("connect\n")
        threading.Thread(target=serve, args=(connection,), daemon=True).start()


def helper_udp(bind: str, port: str, countfile: str) -> int:
    """A UDP server that counts what it receives."""
    port = int(port)
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((bind, port))
    while True:
        data, peer = server.recvfrom(2048)
        with open(countfile, "a") as handle:
            handle.write(f"packet:{peer[0]}\n")
        server.sendto(b"OK", peer)


def helper_dns(bind: str, port: str, countfile: str) -> int:
    """A DNS responder that answers over UDP and over TCP."""
    port = int(port)
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp.bind((bind, port))
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp.bind((bind, port))
    tcp.listen(8)

    def count(protocol: str) -> None:
        with open(countfile, "a") as handle:
            handle.write(f"{protocol}\n")

    def over_tcp() -> None:
        while True:
            try:
                connection, _ = tcp.accept()
            except OSError:
                return
            with connection:
                try:
                    length = connection.recv(2)
                    if len(length) == 2:
                        size = struct.unpack("!H", length)[0]
                        query = connection.recv(size)
                        count("tcp")
                        answer = dns_reply(query)
                        connection.sendall(struct.pack("!H", len(answer)) + answer)
                except OSError:
                    pass

    threading.Thread(target=over_tcp, daemon=True).start()
    while True:
        try:
            data, peer = udp.recvfrom(2048)
            count("udp")
            udp.sendto(dns_reply(data), peer)
        except OSError:
            pass


def helper_probe(host: str, port: str, timeout: str) -> int:
    """Connect, send one request and read the reply. Prints the verdict."""
    port = int(port)
    timeout = float(timeout)
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    client = socket.socket(family, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect((host, port))
        client.sendall(b"ping\n")
        data = client.recv(64)
        print("ok" if data.startswith(b"OK") else "unexpected:" + repr(data[:16]))
    except OSError as error:
        print("blocked:" + type(error).__name__)
    finally:
        client.close()
    return 0


def helper_dns_query(server: str, port: str, protocol: str, timeout: str) -> int:
    """Ask the resolver over UDP or TCP and wait for the answer."""
    port = int(port)
    timeout = float(timeout)
    query = dns_query()
    try:
        if protocol == "udp":
            client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            client.settimeout(timeout)
            client.sendto(query, (server, port))
            data, _ = client.recvfrom(2048)
        else:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(timeout)
            client.connect((server, port))
            client.sendall(struct.pack("!H", len(query)) + query)
            size = struct.unpack("!H", client.recv(2))[0]
            data = client.recv(size)
        print("ok" if len(data) > 12 else "short:" + repr(data[:8]))
    except OSError as error:
        print("blocked:" + type(error).__name__)
    finally:
        client.close()
    return 0


def helper_spoof(source: str, destination: str, port: str) -> int:
    """Send one UDP packet with a source address the sender does not own."""
    port = int(port)
    payload = b"spoof"
    udp_length = 8 + len(payload)
    ip_header = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        20 + udp_length,
        0,
        0,
        64,
        socket.IPPROTO_UDP,
        0,
        socket.inet_aton(source),
        socket.inet_aton(destination),
    )
    udp_header = struct.pack("!HHHH", 40000, port, udp_length, 0)
    raw = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
    raw.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
    raw.sendto(ip_header + udp_header + payload, (destination, 0))
    raw.close()
    print("sent")
    return 0


def helper_probe_from(source: str, host: str, port: str, timeout: str) -> int:
    """Connect from a chosen source address, which the namespace must own."""
    port = int(port)
    timeout = float(timeout)
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(timeout)
    client.bind((source, 0))
    try:
        client.connect((host, port))
        client.sendall(b"ping\n")
        data = client.recv(64)
        print("ok" if data.startswith(b"OK") else "unexpected:" + repr(data[:16]))
    except OSError as error:
        print("blocked:" + type(error).__name__)
    finally:
        client.close()
    return 0


def helper_freebind(source: str, destination: str, port: str) -> int:
    """Bind a socket to an address this namespace does not own, then send."""
    port = int(port)
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.setsockopt(socket.IPPROTO_IP, getattr(socket, "IP_FREEBIND", 15), 1)
    client.bind((source, 0))
    client.sendto(b"freebind", (destination, port))
    client.close()
    print("sent")
    return 0


def helper_hold_bound(
    source: str,
    source_port: str,
    host: str,
    port: str,
    resultfile: str,
    signalfile: str,
) -> int:
    """Hold a connection whose source port equals the declared service port."""
    source_port = int(source_port)
    port = int(port)
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    client.bind((source, source_port))
    client.settimeout(5)
    client.connect((host, port))
    client.sendall(b"one\n")
    first = client.recv(64)
    with open(resultfile, "w") as handle:
        handle.write("first:" + first.decode(errors="replace").strip() + "\n")
    deadline = time.time() + 60
    while time.time() < deadline and not os.path.exists(signalfile):
        time.sleep(0.1)
    try:
        client.settimeout(4)
        client.sendall(b"two\n")
        second = client.recv(64)
        with open(resultfile, "a") as handle:
            handle.write("second:" + second.decode(errors="replace").strip() + "\n")
    except OSError as error:
        with open(resultfile, "a") as handle:
            handle.write("second:blocked:" + type(error).__name__ + "\n")
    finally:
        client.close()
    return 0


def helper_hold(host: str, port: str, resultfile: str, signalfile: str) -> int:
    """Hold a connection open across the policy load and use it afterwards."""
    port = int(port)
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(5)
    client.connect((host, port))
    client.sendall(b"one\n")
    first = client.recv(64)
    with open(resultfile, "w") as handle:
        handle.write("first:" + first.decode(errors="replace").strip() + "\n")
    deadline = time.time() + 60
    while time.time() < deadline and not os.path.exists(signalfile):
        time.sleep(0.1)
    try:
        client.settimeout(4)
        client.sendall(b"two\n")
        second = client.recv(64)
        with open(resultfile, "a") as handle:
            handle.write("second:" + second.decode(errors="replace").strip() + "\n")
    except OSError as error:
        with open(resultfile, "a") as handle:
            handle.write("second:blocked:" + type(error).__name__ + "\n")
    finally:
        client.close()
    return 0


HELPERS = {
    "lines": helper_lines,
    "udp": helper_udp,
    "dns": helper_dns,
    "probe": helper_probe,
    "dnsq": helper_dns_query,
    "spoof": helper_spoof,
    "freebind": helper_freebind,
    "probe-from": helper_probe_from,
    "hold": helper_hold,
    "hold-bound": helper_hold_bound,
}


# ---------------------------------------------------------------- self-test


def selftest() -> int:
    """Check the model and the rendered ruleset. No privileges needed."""
    failures: list = []

    def expect(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    spec = synthetic_policy()
    model.admit(spec)
    rules = model.render_container("candidate", spec["containers"]["candidate"])

    # The container's own traffic ends in a deny.
    expect(
        "ip saddr 10.89.9.16 drop" in rules, "the egress chain does not end in a deny"
    )
    expect(
        "ether saddr 02:00:00:00:09:16 ip saddr 10.89.9.16 drop" in rules,
        "the bridge chain does not end in a deny",
    )
    # The approved edge is present, the observed edge is not.
    expect("ip daddr 10.89.9.17" in rules, "the approved edge is missing")
    expect("8080" not in rules, "an observed edge reached the ruleset")
    expect("stranger" not in rules, "an observed peer reached the ruleset")
    # Continuation is scoped to the original direction.
    expect(
        "ct original ip saddr 10.89.9.16 ct original ip daddr 10.89.9.17 accept"
        in rules,
        "the continuation is not scoped to the approved direction",
    )
    # The identity is bound.
    expect(
        "ip saddr 10.89.9.16 ether saddr != 02:00:00:00:09:16 drop" in rules,
        "a peer claiming the container's address is not dropped",
    )
    expect(
        "ether saddr 02:00:00:00:09:16 ip saddr != 10.89.9.16 drop" in rules,
        "the container's address is not bound to its MAC",
    )
    # The bridge family names the bridge port, not the bridge, so no rule
    # may depend on a device name there.
    expect(
        "iifname" not in rules.split("\ntable bridge ", 1)[1],
        "a bridge rule depends on a device name",
    )
    expect("ether type ip6 drop" in rules, "IPv6 is not denied")
    # DNS over UDP and TCP.
    expect("udp dport 53 accept" in rules, "DNS over UDP is missing")
    expect("tcp dport 53 accept" in rules, "DNS over TCP is missing")
    # Public egress is explicit, and it belongs to forwarded traffic only: a
    # host-bound public address needs an approved host edge or DNS.
    expect(
        "tcp dport 443 ip daddr != @private_ipv4" in rules,
        "the public egress rule is missing",
    )
    input_chain = rules.split("chain input", 1)[1].split("\n    }", 1)[0]
    expect(
        "@private_ipv4" not in input_chain,
        "the input chain allows public egress to a host address",
    )
    expect(
        "ip daddr 10.89.9.1 meta l4proto tcp tcp dport 8081" in input_chain,
        "the approved host edge is missing from the input chain",
    )

    # The ingress contract allows the reply of a declared service port and
    # nothing else.
    ingress_rules = model.render_container(
        "candidate", synthetic_policy(ingress=True)["containers"]["candidate"]
    )
    expect(
        "ct state established,related ct direction reply accept" in ingress_rules,
        "the service reply is not scoped to the reply direction",
    )
    bridge_table = ingress_rules.split("\ntable bridge ", 1)[1]
    for chain, section, prefix in (
        ("forward", ingress_rules.split("chain forward", 1)[1], "ip saddr 10.89.9.16"),
        ("input", ingress_rules.split("chain input", 1)[1], "ip saddr 10.89.9.16"),
        (
            "bridge",
            bridge_table.split("chain forward", 1)[1],
            "ether saddr 02:00:00:00:09:16 ip saddr 10.89.9.16",
        ),
    ):
        expect(
            f"{prefix} meta l4proto tcp tcp sport 9100 ct state established,related "
            "ct direction reply accept" in section,
            f"the ingress reply rule is missing from the {chain} chain",
        )
    expect(
        "ip daddr 10.89.9.16 meta l4proto tcp tcp dport 9100 accept" in ingress_rules,
        "the declared ingress port is not open",
    )
    # Private destinations are denied.
    expect(
        "ip daddr @private_ipv4 drop" in rules, "private destinations are not denied"
    )

    # Admission refuses what cannot be contained.
    def refuses(mutate, message: str) -> None:
        broken = synthetic_policy()
        mutate(broken["containers"]["candidate"])
        try:
            model.admit(broken)
        except model.PolicyError:
            return
        failures.append("admission accepted " + message)

    def admits(mutate, message: str) -> None:
        good = synthetic_policy()
        mutate(good["containers"]["candidate"])
        try:
            model.admit(good)
        except model.PolicyError as error:
            failures.append(f"admission refused {message}: {error}")

    for options in (
        ["--label", "--cap-drop=ALL"],
        ["--label", "--ip=10.89.9.16", "--label", "--mac-address=02:00:00:00:00:16"],
        ["--runtime=/tmp/example-runtime"],
        ["--remote=true"],
        ["--unknown-future-context=example"],
        ["--"],
        ["-l", "example"],
    ):
        refuses(
            lambda p, options=options: p.update({"podman": {"extraOptions": options}}),
            "noncanonical or context-changing argv",
        )
    admits(
        lambda p: p.update(
            {
                "podman": {
                    "extraOptions": [
                        "--label=--cap-drop=ALL",
                        "--env=EXAMPLE=--ip=decoy",
                    ]
                }
            }
        ),
        "inline flag-shaped label and environment values",
    )
    # The allowed capability set is one list, and the Nix admission reads the
    # same one: the two cannot drift apart.
    expected_capabilities = (
        "CHOWN",
        "DAC_OVERRIDE",
        "FOWNER",
        "FSETID",
        "KILL",
        "NET_BIND_SERVICE",
        "SETFCAP",
        "SETGID",
        "SETPCAP",
        "SETUID",
        "SYS_CHROOT",
    )
    expect(
        getattr(model, "ALLOWED_CAPABILITIES", None) == expected_capabilities,
        "the allowed capability set is not the one the Nix admission reads",
    )

    refuses(lambda p: p.update({"network": "host"}), "host networking")
    refuses(lambda p: p.update({"network": "container:other"}), "container networking")
    refuses(lambda p: p.update({"network": "none"}), "no networking")
    refuses(lambda p: p.pop("mac"), "a missing MAC")
    refuses(lambda p: p.pop("address"), "a missing address")
    refuses(lambda p: p.update({"mac": "03:00:00:00:09:17"}), "a multicast MAC")
    refuses(
        lambda p: p.update({"mac": "00:00:00:00:09:16"}), "a globally administered MAC"
    )
    refuses(lambda p: p.update({"capabilities": ["NET_ADMIN"]}), "NET_ADMIN")
    refuses(lambda p: p.update({"capabilities": ["NET_RAW"]}), "NET_RAW")
    refuses(lambda p: p.update({"capabilities": ["ALL"]}), "ALL")
    refuses(lambda p: p.update({"capabilities": ["SYS_ADMIN"]}), "SYS_ADMIN")
    refuses(
        lambda p: p.update({"capabilities": ["cap_sys_admin"]}),
        "a lower-case SYS_ADMIN",
    )
    # The capability set is an allowlist: everything outside it is refused,
    # in every spelling, and the message names the capability.
    refuses(lambda p: p.update({"capabilities": ["SYS_MODULE"]}), "SYS_MODULE")
    refuses(
        lambda p: p.update({"capabilities": ["sys_ptrace"]}), "a lower-case sys_ptrace"
    )
    refuses(
        lambda p: p.update({"capabilities": ["CAP_DAC_READ_SEARCH"]}),
        "CAP_DAC_READ_SEARCH",
    )
    refuses(lambda p: p.update({"capabilities": ["BPF"]}), "BPF")
    refuses(
        lambda p: p.update({"capabilities": ["CHOWN", "BPF"]}),
        "BPF beside an allowed capability",
    )
    refuses(
        lambda p: p.update({"capabilities": ["NET_BIND_SERVICE,PERFMON"]}),
        "PERFMON in a comma list",
    )
    # The capabilities inside the allowed set are admitted.
    admits(
        lambda p: p.update({"capabilities": ["NET_BIND_SERVICE"]}),
        "an allowed capability",
    )
    admits(
        lambda p: p.update({"capabilities": ["cap_chown", "setuid", "SETGID"]}),
        "the allowed capabilities in podman's spellings",
    )
    admits(lambda p: p.update({"capabilities": []}), "no capability at all")
    # A host namespace is outside the rules, in every spelling.
    refuses(
        lambda p: p.update({"namespaces": dict(p["namespaces"], pid=["host"])}),
        "a host pid namespace",
    )
    refuses(
        lambda p: p.update({"namespaces": dict(p["namespaces"], userns=["host"])}),
        "a host user namespace",
    )
    refuses(
        lambda p: p.update(
            {"namespaces": dict(p["namespaces"], ipc=["container:other"])}
        ),
        "another container's ipc namespace",
    )
    refuses(
        lambda p: p.update(
            {"namespaces": dict(p["namespaces"], uts=["ns:/proc/1/ns/uts"])}
        ),
        "a host uts namespace named by path",
    )
    refuses(
        lambda p: p.update({"namespaces": dict(p["namespaces"], cgroupns=["host"])}),
        "a host cgroup namespace",
    )
    refuses(
        lambda p: p.update({"namespaces": dict(p["namespaces"], pod=["mypod"])}),
        "a container in a pod",
    )
    refuses(lambda p: p.pop("namespaces"), "a policy without the namespace fields")
    # The private and the automatic namespace stay admitted.
    admits(
        lambda p: p.update({"namespaces": dict(p["namespaces"], userns=["auto"])}),
        "an automatic user namespace",
    )
    admits(
        lambda p: p.update({"namespaces": dict(p["namespaces"], pid=["private"])}),
        "a private pid namespace",
    )
    refuses(
        lambda p: p.update({"capabilityDropsAll": False}),
        "a missing capability drop of ALL",
    )
    refuses(lambda p: p.update({"privileged": True}), "a privileged container")
    refuses(
        lambda p: p.update({"address": "10.89.8.16"}), "an address outside the subnet"
    )
    refuses(
        lambda p: p.update({"dnsServer": "8.8.8.8"}), "a resolver outside the subnet"
    )
    refuses(lambda p: p.update({"ipv6": "maybe"}), "an unknown IPv6 mode")
    refuses(
        lambda p: p.update({"edges": p["edges"] + [dict(p["edges"][0])]}),
        "a duplicated edge",
    )
    refuses(
        lambda p: p.update(
            {"edges": [dict(p["edges"][0], purpose="https://example.invalid/api")]}
        ),
        "a coordinate in a free text field",
    )
    refuses(
        lambda p: p.update({"edges": [dict(p["edges"][0], protocol="sctp")]}),
        "an unsupported protocol",
    )

    # The network metadata gate: the right subnet passes, everything else
    # fails before a rule is loaded. The podman call is faked, so this runs
    # without privileges.
    network_gate = MODEL / "check-network.py"
    with tempfile.TemporaryDirectory() as directory:
        fake = Path(directory) / "podman"
        fake.write_text('#!/bin/sh\nprintf %s "$FAKE_NETWORK_JSON"\n')
        fake.chmod(0o755)

        def gate(document: str) -> int:
            environment = dict(os.environ, FAKE_NETWORK_JSON=document)
            return subprocess.run(
                [
                    sys.executable,
                    str(network_gate),
                    "--network",
                    "ghostship_net",
                    "--subnet",
                    "10.89.0.0/24",
                    "--podman",
                    str(fake),
                ],
                env=environment,
                capture_output=True,
                text=True,
            ).returncode

        expect(
            gate(
                '[{"name":"ghostship_net","driver":"bridge","subnets":[{"subnet":"10.89.0.0/24","gateway":"10.89.0.1"}]}]'
            )
            == 0,
            "the network gate refused the network that carries the subnet",
        )
        expect(
            gate(
                '[{"name":"ghostship_net","driver":"bridge","subnets":[{"subnet":"10.89.9.0/24"}]}]'
            )
            != 0,
            "the network gate accepted a different subnet",
        )
        expect(gate("[]") != 0, "the network gate accepted a network with no subnet")
        for driver in ("macvlan", "ipvlan", "unknown", None):
            metadata = {
                "name": "ghostship_net",
                "subnets": [{"subnet": "10.89.0.0/24"}],
            }
            if driver is not None:
                metadata["driver"] = driver
            expect(
                gate(json.dumps([metadata])) != 0,
                f"the network gate accepted unsupported or missing driver {driver}",
            )
        expect(
            gate(
                json.dumps(
                    [
                        {"driver": "bridge", "subnets": [{"subnet": "10.89.0.0/24"}]},
                        {"driver": "macvlan", "subnets": [{"subnet": "10.89.0.0/24"}]},
                    ]
                )
            )
            != 0,
            "the network gate accepted ambiguous mixed-driver metadata",
        )
        expect(
            gate(
                '[{"name":"other","driver":"bridge","subnets":[{"subnet":"10.89.0.0/24"}]}]'
            )
            == 0,
            "the network gate did not read the subnet of the named network",
        )

    # The unresolved dependencies are reported and stay out of the rules.
    manifest = model.manifest(spec)
    entry = manifest["containers"]["candidate"]
    expect(
        len(entry["unresolved"]) == 1, "the observed edge is not reported as unresolved"
    )
    expect(len(entry["approved"]) == 3, "the approved edges are not reported")

    print(
        json.dumps(
            {"selftest": "ok" if not failures else "failed", "failures": failures},
            indent=1,
        )
    )
    return 1 if failures else 0


# ---------------------------------------------------------------- harness


class Harness:
    def __init__(self, ip_binary: str, nft_binary: str):
        self.ip = ip_binary
        self.nft = nft_binary
        self.prefix = f"ciso-{os.getpid()}-{secrets.token_hex(3)}"
        self.namespaces: list = []
        self.servers: list = []
        self.tmp = Path(tempfile.mkdtemp(prefix="ciso-"))

    # -- plumbing
    def run(self, *args, check=True, input_text=None):
        return subprocess.run(
            args, text=True, capture_output=True, check=check, input=input_text
        )

    def ip_run(self, *args, check=True):
        return self.run(self.ip, *args, check=check)

    def ns(self, name: str, *args, check=True):
        return self.run(self.ip, "netns", "exec", name, *args, check=check)

    def namespace(self, suffix: str) -> str:
        return f"{self.prefix}-{suffix}"

    def count(self, name: str) -> int:
        path = self.tmp / name
        if not path.exists():
            return 0
        return len([line for line in path.read_text().splitlines() if line])

    def start_server(self, namespace: str, mode: str, *args) -> None:
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "helper",
            mode,
            *[str(a) for a in args],
        ]
        process = subprocess.Popen(
            [self.ip, "netns", "exec", namespace, *command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.servers.append(process)

    # -- topology
    def build(self) -> None:
        router = self.namespace("router")
        names = {
            "router": router,
            "app": self.namespace("app"),
            "peer": self.namespace("peer"),
            "stranger": self.namespace("stranger"),
            "spoofer": self.namespace("spoofer"),
            "routed": self.namespace("routed"),
            "lan": self.namespace("lan"),
            "public": self.namespace("public"),
        }
        self.names = names
        for name in names.values():
            self.ip_run("netns", "add", name)
            self.namespaces.append(name)
            self.ip_run("-n", name, "link", "set", "lo", "up")

        self.ip_run("-n", router, "link", "add", BRIDGE, "type", "bridge")
        self.ip_run("-n", router, "link", "set", BRIDGE, "up")
        self.ip_run("-n", router, "addr", "add", f"{GATEWAY}/24", "dev", BRIDGE)
        self.ip_run(
            "-n", router, "-6", "addr", "add", f"{V6_PREFIX}1/64", "dev", BRIDGE
        )

        # Same-segment peers on the bridge.
        self.wire(names["app"], "v_app", "eth0", BRIDGE, APP_IP, APP_MAC, GATEWAY)
        self.wire(names["peer"], "v_peer", "eth0", BRIDGE, PEER_IP, None, GATEWAY)
        self.wire(
            names["stranger"], "v_str", "eth0", BRIDGE, STRANGER_IP, None, GATEWAY
        )
        # The spoofing namespace is separate: a local route for the
        # container's address would capture that namespace's own return
        # traffic, and nothing else depends on its connectivity.
        self.wire(names["spoofer"], "v_spf", "eth0", BRIDGE, SPOOFER_IP, None, GATEWAY)
        self.ip_run(
            "-n", names["app"], "-6", "addr", "add", f"{APP_V6}/64", "dev", "eth0"
        )
        self.ip_run(
            "-n", names["peer"], "-6", "addr", "add", f"{PEER_V6}/64", "dev", "eth0"
        )

        # Routed targets behind the router.
        self.wire(
            names["routed"], "v_rout", "eth0", None, ROUTED_IP, None, ROUTED_GATEWAY
        )
        self.ip_run(
            "-n", router, "addr", "add", f"{ROUTED_GATEWAY}/24", "dev", "v_rout"
        )
        self.wire(names["lan"], "v_lan", "eth0", None, LAN_IP, None, LAN_GATEWAY)
        self.ip_run("-n", router, "addr", "add", f"{LAN_GATEWAY}/24", "dev", "v_lan")
        self.wire(
            names["public"], "v_pub", "eth0", None, PUBLIC_IP, None, PUBLIC_GATEWAY
        )
        self.ip_run("-n", router, "addr", "add", f"{PUBLIC_GATEWAY}/24", "dev", "v_pub")

        self.ns(router, "sh", "-c", "echo 1 > /proc/sys/net/ipv4/ip_forward")
        self.ns(router, "sh", "-c", "echo 1 > /proc/sys/net/ipv6/conf/all/forwarding")

    def wire(self, namespace, left, right, bridge, address, mac, gateway) -> None:
        router = self.names["router"]
        self.ip_run(
            "-n", router, "link", "add", left, "type", "veth", "peer", "name", right
        )
        self.ip_run("-n", router, "link", "set", right, "netns", namespace)
        if bridge:
            self.ip_run("-n", router, "link", "set", left, "master", bridge)
        self.ip_run("-n", router, "link", "set", left, "up")
        self.ip_run("-n", namespace, "link", "set", right, "up")
        if mac:
            self.ip_run("-n", namespace, "link", "set", right, "address", mac)
        self.ip_run("-n", namespace, "addr", "add", f"{address}/24", "dev", right)
        self.ip_run("-n", namespace, "route", "add", "default", "via", gateway)

    def serve(self) -> None:
        router = self.names["router"]
        self.start_server(router, "dns", GATEWAY, DNS_PORT, self.tmp / "dns.count")
        self.start_server(
            router, "lines", GATEWAY, SERVICE_PORT, self.tmp / "host.count"
        )
        self.start_server(
            self.names["peer"],
            "lines",
            "0.0.0.0",
            APPROVED_PORT,
            self.tmp / "peer.count",
        )
        self.start_server(
            self.names["peer"],
            "lines",
            "0.0.0.0",
            UNAPPROVED_PORT,
            self.tmp / "peerport.count",
        )
        self.start_server(
            self.names["peer"], "lines", "::", SERVICE_PORT, self.tmp / "peerv6.count"
        )
        self.start_server(
            self.names["peer"], "udp", "0.0.0.0", SPOOF_PORT, self.tmp / "spoof.count"
        )
        self.start_server(
            self.names["stranger"],
            "lines",
            "0.0.0.0",
            SERVICE_PORT,
            self.tmp / "stranger.count",
        )
        self.start_server(
            self.names["stranger"],
            "lines",
            "0.0.0.0",
            REVOKE_PORT,
            self.tmp / "revoke.count",
        )
        self.start_server(
            self.names["routed"],
            "lines",
            "0.0.0.0",
            ROUTED_PORT,
            self.tmp / "routed.count",
        )
        self.start_server(
            self.names["lan"], "lines", "0.0.0.0", SERVICE_PORT, self.tmp / "lan.count"
        )
        self.start_server(
            self.names["public"],
            "lines",
            "0.0.0.0",
            PUBLIC_PORT,
            self.tmp / "public.count",
        )
        self.start_server(
            self.names["app"],
            "lines",
            "0.0.0.0",
            INGRESS_PORT,
            self.tmp / "ingress.count",
        )
        self.start_server(
            self.names["app"],
            "lines",
            "0.0.0.0",
            UNDECLARED_PORT,
            self.tmp / "undeclared.count",
        )
        self.start_server(
            router, "lines", GATEWAY, HOST_EDGE_PORT, self.tmp / "hostedge.count"
        )
        self.start_server(
            router, "lines", PUBLIC_GATEWAY, PUBLIC_PORT, self.tmp / "hostpublic.count"
        )
        self.start_server(
            self.names["public"],
            "lines",
            "0.0.0.0",
            PUBLIC_DENIED_PORT,
            self.tmp / "publicdenied.count",
        )

    # -- probes
    def probe(self, namespace: str, host: str, port: int, timeout: float = 3.0) -> str:
        result = self.ns(
            namespace,
            sys.executable,
            str(Path(__file__).resolve()),
            "helper",
            "probe",
            host,
            str(port),
            str(timeout),
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"the probe itself failed in {namespace}: {result.stderr.strip()}"
            )
        return result.stdout.strip()

    def probe_from(
        self, namespace: str, source: str, host: str, port: int, timeout: float = 3.0
    ) -> str:
        result = self.ns(
            namespace,
            sys.executable,
            str(Path(__file__).resolve()),
            "helper",
            "probe-from",
            source,
            host,
            str(port),
            str(timeout),
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"the probe itself failed in {namespace}: {result.stderr.strip()}"
            )
        return result.stdout.strip()

    def dns_query(self, namespace: str, protocol: str, timeout: float = 3.0) -> str:
        result = self.ns(
            namespace,
            sys.executable,
            str(Path(__file__).resolve()),
            "helper",
            "dnsq",
            GATEWAY,
            str(DNS_PORT),
            protocol,
            str(timeout),
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"the DNS probe failed in {namespace}: {result.stderr.strip()}"
            )
        return result.stdout.strip()

    def spoof(self, mode: str = "raw") -> None:
        """A peer on the bridge claims the container's address.

        `raw` crafts the packet, `freebind` lets the kernel build it from a
        source address the namespace does not own. Both are one-sided: the
        sender keeps its own MAC. `freebind` needs the kernel to be able to
        route the foreign source, which a peer with NET_ADMIN can arrange.
        """
        if mode == "freebind":
            self.ns(
                self.names["spoofer"],
                self.ip,
                "route",
                "add",
                "local",
                f"{APP_IP}/32",
                "dev",
                "lo",
                check=False,
            )
        result = self.ns(
            self.names["spoofer"],
            sys.executable,
            str(Path(__file__).resolve()),
            "helper",
            mode,
            APP_IP,
            PEER_IP,
            str(SPOOF_PORT),
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"the {mode} spoof could not be sent: {result.stderr.strip()}"
            )
        time.sleep(1)

    def forge(self) -> None:
        """A peer adopts both the container's address and its MAC.

        This is the documented boundary of an address and MAC binding: the
        frame is indistinguishable from the container's own. Enforcement
        therefore needs an isolated bridge or per-port MAC security.
        """
        self.ns(
            self.names["spoofer"], self.ip, "link", "set", "eth0", "address", APP_MAC
        )
        self.ns(
            self.names["spoofer"], self.ip, "addr", "add", f"{APP_IP}/24", "dev", "eth0"
        )
        time.sleep(1)

    def load_policy(self, rules_path: Path) -> None:
        self.ns(self.names["router"], self.nft, "-f", str(rules_path))

    def table_count(self) -> int:
        result = self.ns(self.names["router"], self.nft, "list", "tables", check=False)
        return len(
            [
                line
                for line in result.stdout.splitlines()
                if "ghostship_ci_candidate" in line
            ]
        )

    def cleanup(self) -> None:
        for process in self.servers:
            process.terminate()
        for process in self.servers:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        for name in reversed(self.namespaces):
            self.run(self.ip, "netns", "delete", name, check=False)
        shutil.rmtree(self.tmp, ignore_errors=True)


def harness(ip_binary: str, nft_binary: str) -> int:
    if os.geteuid() != 0:
        print("the harness needs root: it creates its own namespaces", file=sys.stderr)
        return 2
    if shutil.which(nft_binary) is None and not Path(nft_binary).exists():
        print(f"nft binary {nft_binary} not found", file=sys.stderr)
        return 2

    harness = Harness(ip_binary, nft_binary)
    report: dict = {}
    try:
        harness.build()
        harness.serve()

        # The ruleset is the generated one, not a hand written copy.
        spec = synthetic_policy()
        ingress_spec = synthetic_policy(ingress=True)
        revoked_spec = synthetic_policy(ingress=True)
        revoked_spec["containers"]["candidate"]["edges"].append(
            {
                "peer": "stranger-service",
                "address": STRANGER_IP,
                "protocol": "tcp",
                "port": REVOKE_PORT,
                "purpose": "service api",
            }
        )
        model.admit(spec)
        model.admit(ingress_spec)
        model.admit(revoked_spec)
        rules_dir = harness.tmp / "rules"
        rules_dir.mkdir()
        rules_path = rules_dir / "candidate.nft"
        rules_path.write_text(
            model.render_container("candidate", spec["containers"]["candidate"])
        )
        ingress_path = rules_dir / "candidate-ingress.nft"
        ingress_path.write_text(
            model.render_container("candidate", ingress_spec["containers"]["candidate"])
        )
        revoked_path = rules_dir / "candidate-revoked.nft"
        revoked_path.write_text(
            model.render_container("candidate", revoked_spec["containers"]["candidate"])
        )

        # Wait for every service the baseline uses, so a slow start cannot
        # look like a policy decision.
        waiting = [
            (harness.names["app"], PEER_IP, APPROVED_PORT),
            (harness.names["app"], PEER_IP, UNAPPROVED_PORT),
            (harness.names["app"], STRANGER_IP, SERVICE_PORT),
            (harness.names["app"], GATEWAY, SERVICE_PORT),
            (harness.names["app"], LAN_IP, SERVICE_PORT),
            (harness.names["app"], ROUTED_IP, ROUTED_PORT),
            (harness.names["app"], PUBLIC_IP, PUBLIC_PORT),
            (harness.names["app"], PUBLIC_IP, PUBLIC_DENIED_PORT),
            (harness.names["app"], GATEWAY, HOST_EDGE_PORT),
            (harness.names["app"], PUBLIC_GATEWAY, PUBLIC_PORT),
            (harness.names["app"], STRANGER_IP, REVOKE_PORT),
        ]
        deadline = time.time() + 40
        for namespace, host, port in waiting:
            while time.time() < deadline:
                if harness.probe(namespace, host, port, timeout=1) == "ok":
                    break
                time.sleep(0.5)
            else:
                raise AssertionError(f"the service {host}:{port} never answered")
        while time.time() < deadline:
            if harness.dns_query(harness.names["app"], "udp", timeout=1) == "ok":
                break
            time.sleep(0.5)
        else:
            raise AssertionError("the resolver never answered")

        denied = [
            ("same-bridge peer", PEER_IP, UNAPPROVED_PORT),
            ("same-bridge stranger", STRANGER_IP, SERVICE_PORT),
            ("host service", GATEWAY, SERVICE_PORT),
            ("private lan", LAN_IP, SERVICE_PORT),
            ("public port outside the egress list", PUBLIC_IP, PUBLIC_DENIED_PORT),
            ("host public service", PUBLIC_GATEWAY, PUBLIC_PORT),
        ]
        allowed = [
            ("approved same-bridge edge", PEER_IP, APPROVED_PORT),
            ("approved routed edge", ROUTED_IP, ROUTED_PORT),
            ("public egress", PUBLIC_IP, PUBLIC_PORT),
            ("approved host edge", GATEWAY, HOST_EDGE_PORT),
        ]

        # Baseline: every denied destination is reachable now, so a later
        # failure is the policy's doing.
        for name, host, port in denied:
            verdict = harness.probe(harness.names["app"], host, port)
            if verdict != "ok":
                raise AssertionError(
                    f"baseline: {name} ({host}:{port}) was not reachable: {verdict}"
                )
        for name, host, port in allowed:
            verdict = harness.probe(harness.names["app"], host, port)
            if verdict != "ok":
                raise AssertionError(
                    f"baseline: {name} ({host}:{port}) was not reachable: {verdict}"
                )
        if harness.dns_query(harness.names["app"], "udp") != "ok":
            raise AssertionError("baseline: DNS over UDP did not answer")
        if harness.dns_query(harness.names["app"], "tcp") != "ok":
            raise AssertionError("baseline: DNS over TCP did not answer")
        baseline_v6 = harness.probe(harness.names["app"], PEER_V6, SERVICE_PORT)
        if baseline_v6 != "ok":
            raise AssertionError(f"baseline: IPv6 was not reachable: {baseline_v6}")

        # Baseline: a peer that claims the container's address reaches the
        # service while no policy is loaded. Both one-sided attacks are
        # proven first: a crafted packet and a socket bound to a foreign
        # source address.
        for mode in ("spoof", "freebind"):
            before = harness.count("spoof.count")
            harness.spoof(mode)
            if harness.count("spoof.count") == before:
                raise AssertionError(
                    f"baseline: the {mode} spoof never reached the service"
                )

        # A connection that is opened before the policy is loaded.
        hold_result = harness.tmp / "hold.result"
        hold = subprocess.Popen(
            [
                harness.ip,
                "netns",
                "exec",
                harness.names["app"],
                sys.executable,
                str(Path(__file__).resolve()),
                "helper",
                "hold",
                STRANGER_IP,
                str(SERVICE_PORT),
                str(hold_result),
                str(harness.tmp / "hold.signal"),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        harness.servers.append(hold)
        deadline = time.time() + 10
        while time.time() < deadline and not hold_result.exists():
            time.sleep(0.1)
        if not hold_result.exists():
            raise AssertionError("the pre-policy connection was never established")

        # Load the policy inside the router namespace only.
        harness.load_policy(rules_path)
        report["tables"] = harness.table_count()

        for name, host, port in denied:
            verdict = harness.probe(harness.names["app"], host, port, timeout=2)
            if not verdict.startswith("blocked:"):
                raise AssertionError(
                    f"policy: {name} ({host}:{port}) was not denied: {verdict}"
                )
        report["denied"] = [name for name, _, _ in denied]

        for name, host, port in allowed:
            verdict = harness.probe(harness.names["app"], host, port)
            if verdict != "ok":
                raise AssertionError(
                    f"policy: {name} ({host}:{port}) was denied: {verdict}"
                )
        report["allowed"] = [name for name, _, _ in allowed]

        if harness.dns_query(harness.names["app"], "udp") != "ok":
            raise AssertionError("policy: DNS over UDP was denied")
        if harness.dns_query(harness.names["app"], "tcp") != "ok":
            raise AssertionError("policy: DNS over TCP was denied")
        report["dns"] = "udp and tcp"

        verdict = harness.probe(harness.names["app"], PEER_V6, SERVICE_PORT, timeout=2)
        if not verdict.startswith("blocked:"):
            raise AssertionError(f"policy: IPv6 was not denied: {verdict}")
        report["ipv6"] = "denied"

        # A peer that claims the container's address is dropped, whichever
        # way it builds the packet.
        for mode in ("spoof", "freebind"):
            before = harness.count("spoof.count")
            harness.spoof(mode)
            if harness.count("spoof.count") != before:
                raise AssertionError(f"policy: the {mode} spoof reached the service")
        report["spoof"] = "crafted and freebind rejected"

        # The connection that was opened before the policy is loaded is cut.
        (harness.tmp / "hold.signal").write_text("go\n")
        deadline = time.time() + 15
        while time.time() < deadline:
            text = hold_result.read_text()
            if "second:" in text:
                break
            time.sleep(0.2)
        text = hold_result.read_text()
        if "second:OK" in text:
            raise AssertionError(
                "policy: the pre-policy connection still carried traffic"
            )
        if "second:" not in text:
            raise AssertionError(
                f"policy: the pre-policy connection never reported: {text}"
            )
        report["prepolicy"] = "cut"

        # A reload replaces the policy without a gap and without duplicates.
        harness.load_policy(rules_path)
        if harness.table_count() != 2:
            raise AssertionError(
                f"policy: the reload left {harness.table_count()} tables"
            )
        verdict = harness.probe(
            harness.names["app"], STRANGER_IP, SERVICE_PORT, timeout=2
        )
        if not verdict.startswith("blocked:"):
            raise AssertionError(
                f"policy: the reload opened the same-bridge peer: {verdict}"
            )
        verdict = harness.probe(harness.names["app"], PEER_IP, APPROVED_PORT)
        if verdict != "ok":
            raise AssertionError(
                f"policy: the reload broke the approved edge: {verdict}"
            )
        report["reload"] = "atomic"

        # A broken policy never replaces a working one.
        broken = harness.tmp / "broken.nft"
        broken.write_text("table inet ghostship_ci_broken {\n this is not nft\n}\n")
        result = harness.ns(
            harness.names["router"], harness.nft, "-f", str(broken), check=False
        )
        if result.returncode == 0:
            raise AssertionError("policy: a broken ruleset was accepted")
        verdict = harness.probe(
            harness.names["app"], STRANGER_IP, SERVICE_PORT, timeout=2
        )
        if not verdict.startswith("blocked:"):
            raise AssertionError(
                "policy: the broken ruleset disturbed the loaded policy"
            )
        report["broken"] = "refused"

        # The explicit ingress contract: the container serves one declared
        # port, and its replies are allowed on the bridge and on the routed
        # path while every other egress stays denied.
        harness.load_policy(ingress_path)
        verdict = harness.probe(harness.names["app"], PUBLIC_IP, PUBLIC_PORT)
        if verdict != "ok":
            raise AssertionError(
                f"policy: ingress filtering broke approved public egress: {verdict}"
            )
        report["ingress_public_egress"] = "request and reply"
        for name, client in (
            ("bridge", harness.names["peer"]),
            ("routed", harness.names["routed"]),
        ):
            verdict = harness.probe(client, APP_IP, INGRESS_PORT)
            if verdict != "ok":
                raise AssertionError(
                    f"policy: the {name} inbound service did not answer: {verdict}"
                )
        verdict = harness.probe(
            harness.names["peer"], APP_IP, UNDECLARED_PORT, timeout=2
        )
        if not verdict.startswith("blocked:"):
            raise AssertionError(
                f"policy: an undeclared inbound port answered: {verdict}"
            )
        verdict = harness.probe(
            harness.names["app"], STRANGER_IP, SERVICE_PORT, timeout=2
        )
        if not verdict.startswith("blocked:"):
            raise AssertionError(
                f"policy: the ingress contract widened egress: {verdict}"
            )
        verdict = harness.probe(
            harness.names["app"], PUBLIC_GATEWAY, PUBLIC_PORT, timeout=2
        )
        if not verdict.startswith("blocked:"):
            raise AssertionError(
                f"policy: the ingress contract allowed a host public destination: {verdict}"
            )
        report["ingress"] = "bridge and routed request/reply"

        # A flow that was approved, is already tracked, and whose edge is then
        # revoked must stop. The client binds its source port to the declared
        # service port, so a reply rule that only matched port and state would
        # keep the revoked edge alive.
        harness.load_policy(revoked_path)
        revoke_result = harness.tmp / "revoke.result"
        revoke_signal = harness.tmp / "revoke.signal"
        holder = subprocess.Popen(
            [
                harness.ip,
                "netns",
                "exec",
                harness.names["app"],
                sys.executable,
                str(Path(__file__).resolve()),
                "helper",
                "hold-bound",
                APP_IP,
                str(INGRESS_CLIENT_PORT),
                STRANGER_IP,
                str(REVOKE_PORT),
                str(revoke_result),
                str(revoke_signal),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        harness.servers.append(holder)
        deadline = time.time() + 10
        while time.time() < deadline and not revoke_result.exists():
            time.sleep(0.1)
        if not revoke_result.exists():
            raise AssertionError("the approved edge never carried its first request")
        first = revoke_result.read_text()
        if "first:OK" not in first:
            raise AssertionError(f"the approved edge failed its first request: {first}")

        # Same generated policy, with the stranger edge removed.
        harness.load_policy(ingress_path)
        revoke_signal.write_text("go\n")
        deadline = time.time() + 15
        while time.time() < deadline:
            text = revoke_result.read_text()
            if "second:" in text:
                break
            time.sleep(0.2)
        text = revoke_result.read_text()
        if "second:OK" in text:
            raise AssertionError(
                "policy: the revoked edge kept answering because the reply rule "
                "matched an application-initiated flow"
            )
        if "second:" not in text:
            raise AssertionError(f"policy: the revoked flow never reported: {text}")
        report["revoke"] = "tracked approved flow cut after revocation"

        # The documented boundary, probed last because the forged identity
        # disturbs the bridge's address and MAC mapping: a peer that forges
        # both the address and the MAC is indistinguishable from the
        # container at this layer.
        harness.forge()
        before = harness.count("peer.count")
        harness.probe_from(
            harness.names["spoofer"], APP_IP, PEER_IP, APPROVED_PORT, timeout=2
        )
        after = harness.count("peer.count")
        report["forging"] = (
            "address+MAC forging inherits the container's approved edges and is "
            "not detected; containment needs an isolated bridge or per-port MAC "
            "security"
            if after > before
            else "address+MAC forging was blocked (unexpected)"
        )

        print(json.dumps({"harness": "ok", **report}, indent=1))
        return 0
    except AssertionError as error:
        print(
            json.dumps({"harness": "failed", "error": str(error), **report}, indent=1)
        )
        return 1
    finally:
        harness.cleanup()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["selftest", "harness", "helper"])
    parser.add_argument("--nft", default=os.environ.get("NFT_BINARY", "nft"))
    parser.add_argument("--ip", default=os.environ.get("IP_BINARY", "ip"))
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    if args.mode == "helper":
        if not args.rest:
            print("the helper needs a mode", file=sys.stderr)
            return 2
        mode = args.rest[0]
        if mode not in HELPERS:
            print(f"unknown helper {mode}", file=sys.stderr)
            return 2
        return HELPERS[mode](*args.rest[1:]) or 0
    if args.mode == "selftest":
        return selftest()
    return harness(args.ip, args.nft)


if __name__ == "__main__":
    sys.exit(main())
