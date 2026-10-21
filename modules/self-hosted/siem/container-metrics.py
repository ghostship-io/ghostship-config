"""Per-container CPU, memory, process and network counters for node_exporter.

Writes Prometheus text to the textfile collector every 30 seconds. A container
that suddenly burns CPU or sends far more than usual (cryptominer, proxy,
exfiltration) shows up here before it writes any log line.
"""

import http.client
import json
import os
import socket
import sys
import time
from pathlib import Path

OUT = Path(sys.argv[1])
INTERVAL = 30
# The REST API needs no writable state; `podman ps` takes locks the sandbox forbids.
PODMAN_SOCKET = "/run/podman/podman.sock"


class UnixConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(30)
        self.sock.connect(PODMAN_SOCKET)


def containers():
    connection = UnixConnection("podman")
    connection.request("GET", "/v5.0.0/libpod/containers/json")
    response = connection.getresponse()
    if response.status != 200:
        raise ValueError(f"podman API answered {response.status}")
    return json.loads(response.read())


def read(path):
    try:
        return Path(path).read_text()
    except OSError:
        return None


def sample():
    rows = []
    for c in containers():
        name, pid = c["Names"][0], c.get("Pid")
        cgroup = read(f"/proc/{pid}/cgroup")
        if not pid or not cgroup:
            continue
        base = "/sys/fs/cgroup" + cgroup.strip().split("::", 1)[-1]
        stat = dict(line.split() for line in (read(f"{base}/cpu.stat") or "").splitlines() if line)
        rx = tx = 0
        for line in (read(f"/proc/{pid}/net/dev") or "").splitlines()[2:]:
            iface, data = line.split(":", 1)
            if iface.strip() != "lo":
                fields = data.split()
                rx, tx = rx + int(fields[0]), tx + int(fields[8])
        rows.append((name, {
            "cpu_seconds_total": int(stat.get("usage_usec", 0)) / 1e6,
            "memory_bytes": int((read(f"{base}/memory.current") or "0").strip() or 0),
            "pids": int((read(f"{base}/pids.current") or "0").strip() or 0),
            "network_receive_bytes_total": rx,
            "network_transmit_bytes_total": tx,
        }))
    return rows


def render(rows):
    lines = []
    for metric in ("cpu_seconds_total", "memory_bytes", "pids",
                   "network_receive_bytes_total", "network_transmit_bytes_total"):
        kind = "counter" if metric.endswith("_total") else "gauge"
        lines.append(f"# TYPE ghostship_container_{metric} {kind}")
        lines += [f'ghostship_container_{metric}{{container="{name}"}} {values[metric]}' for name, values in rows]
    return "\n".join(lines) + "\n"


def main():
    while True:
        try:
            temporary = OUT.with_suffix(".tmp")
            temporary.write_text(render(sample()))
            os.chmod(temporary, 0o644)
            temporary.replace(OUT)
        except (OSError, ValueError, KeyError, http.client.HTTPException) as exc:
            print(f"container metrics: {exc}", file=sys.stderr)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
