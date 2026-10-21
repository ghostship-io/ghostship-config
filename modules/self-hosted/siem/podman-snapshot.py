"""Root-owned container metadata snapshot and resource counters.

Runs as a short-lived root job, so long-lived SIEM services never hold the
rootful Podman API: anything that can reach that socket can create and exec
containers. Writes two world-readable files atomically:

- containers.json: name -> pid, state, network addresses and netns owner.
  The alert bridge resolves ntfy and T3 from it.
- containers.prom: node_exporter textfile with per-container cgroup counters.

Network bytes come from /proc/<pid>/net/dev, which is per network namespace.
A container joined to another's namespace (`--network=container:X`, e.g.
qBittorrent in Gluetun) would count the same traffic twice, so each namespace
is reported once, under its owner, and members get
ghostship_container_netns_shared{container,netns_owner}. Only the Podman eth*
interfaces count (they equal the host-side veth counters, verified 2026-10-21);
container-to-container traffic is included, and VPN tunnels are not, since
their bytes already cross eth0 encrypted.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

PODMAN = os.environ.get("PODMAN", "podman")


def read(path):
    try:
        return Path(path).read_text()
    except OSError:
        return None


def inspect():
    names = subprocess.run([PODMAN, "ps", "-q"], check=True, capture_output=True,
                           text=True, timeout=60).stdout.split()
    if not names:
        return []
    return json.loads(subprocess.run([PODMAN, "inspect", "--format", "json", *names], check=True,
                                     capture_output=True, text=True, timeout=60).stdout)


def snapshot(containers):
    """Metadata only: no environment, labels, mounts or command lines."""
    by_id = {c["Id"]: c["Name"].lstrip("/") for c in containers}
    result = {}
    for c in containers:
        mode = c.get("HostConfig", {}).get("NetworkMode", "")
        owner = by_id.get(mode.split(":", 1)[1], None) if mode.startswith("container:") else None
        result[c["Name"].lstrip("/")] = {
            "pid": c.get("State", {}).get("Pid") or 0,
            "state": c.get("State", {}).get("Status", ""),
            "networks": {name: net.get("IPAddress", "")
                         for name, net in (c.get("NetworkSettings", {}).get("Networks") or {}).items()},
            "netns_owner": owner,
        }
    return result


def net_bytes(pid):
    rx = tx = 0
    for line in (read(f"/proc/{pid}/net/dev") or "").splitlines()[2:]:
        iface, data = line.split(":", 1)
        # Podman's veth ends (eth0, eth1...) are what crosses the host bridge.
        # Tunnels (Gluetun's tun0/wg0) would count encapsulated bytes twice.
        if iface.strip().startswith("eth"):
            fields = data.split()
            rx, tx = rx + int(fields[0]), tx + int(fields[8])
    return rx, tx


def counters(meta):
    rows, shared = [], []
    for name, info in sorted(meta.items()):
        pid = info["pid"]
        cgroup = read(f"/proc/{pid}/cgroup") if pid else None
        if not cgroup:
            continue
        base = "/sys/fs/cgroup" + cgroup.strip().split("::", 1)[-1]
        stat = dict(line.split() for line in (read(f"{base}/cpu.stat") or "").splitlines() if line)
        values = {
            "cpu_seconds_total": int(stat.get("usage_usec", 0)) / 1e6,
            "memory_bytes": int((read(f"{base}/memory.current") or "0").strip() or 0),
            "pids": int((read(f"{base}/pids.current") or "0").strip() or 0),
        }
        if info["netns_owner"]:
            shared.append((name, info["netns_owner"]))
        else:
            values["network_receive_bytes_total"], values["network_transmit_bytes_total"] = net_bytes(pid)
        rows.append((name, values))
    return rows, shared


def render(rows, shared):
    lines = []
    for metric in ("cpu_seconds_total", "memory_bytes", "pids",
                   "network_receive_bytes_total", "network_transmit_bytes_total"):
        kind = "counter" if metric.endswith("_total") else "gauge"
        lines.append(f"# TYPE ghostship_container_{metric} {kind}")
        lines += [f'ghostship_container_{metric}{{container="{name}"}} {values[metric]}'
                  for name, values in rows if metric in values]
    lines.append("# TYPE ghostship_container_netns_shared gauge")
    lines += [f'ghostship_container_netns_shared{{container="{name}",netns_owner="{owner}"}} 1'
              for name, owner in shared]
    return "\n".join(lines) + "\n"


def write(path, text):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(text)
    os.chmod(temporary, 0o644)
    temporary.replace(path)


def main():
    meta_path, prom_path = Path(sys.argv[1]), Path(sys.argv[2])
    meta = snapshot(inspect())
    write(meta_path, json.dumps(meta, sort_keys=True))
    write(prom_path, render(*counters(meta)))


if __name__ == "__main__":
    main()
