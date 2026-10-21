"""Per-container CPU, memory, process and network counters for node_exporter.

Writes Prometheus text to the textfile collector every 30 seconds. A container
that suddenly burns CPU or sends far more than usual (cryptominer, proxy,
exfiltration) shows up here before it writes any log line.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

OUT = Path(sys.argv[1])
INTERVAL = 30


def read(path):
    try:
        return Path(path).read_text()
    except OSError:
        return None


def sample():
    ps = subprocess.run(["podman", "ps", "--format", "json"], capture_output=True, check=True, timeout=60)
    names = [c["Names"][0] for c in json.loads(ps.stdout or b"[]")]
    if not names:
        return []
    inspect = subprocess.run(["podman", "inspect", "--format", "json", *names],
                             capture_output=True, check=True, timeout=60)
    rows = []
    for c in json.loads(inspect.stdout):
        name, pid = c["Name"].lstrip("/"), c["State"]["Pid"]
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
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            print(f"container metrics: {exc}", file=sys.stderr)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
