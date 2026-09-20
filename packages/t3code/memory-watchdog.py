"""Report sustained memory pressure; the caller owns idle checks and restart."""
import json
import os
from pathlib import Path
import sys
import time

GIB = 1024**3


def evaluate(sample, previous):
    same_process = previous.get("pid") == sample["pid"]
    # Require consecutive timer samples, not observations accumulated across gaps.
    consecutive = same_process and 30 <= sample["time"] - previous.get("time", 0) <= 110
    high = sample["anon"] >= 8 * GIB or (
        sample["current"] >= 20 * GIB and sample["pressure"] >= 10
    )
    count = (previous.get("count", 0) if consecutive else 0) + 1 if high else 0
    state = {"pid": sample["pid"], "time": sample["time"], "count": count}
    # Service age supplies a cooldown, including after manual restarts.
    recover = count >= 3 and sample["age"] >= 1800
    return state, recover


def main():
    cgroup = Path("/sys/fs/cgroup/system.slice/t3code-server.service")
    pid = int(sys.argv[1])
    stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    age = float(Path("/proc/uptime").read_text().split()[0]) - int(stat[19]) / os.sysconf("SC_CLK_TCK")
    memory = dict(line.split() for line in (cgroup / "memory.stat").read_text().splitlines())
    pressure = next(line for line in (cgroup / "memory.pressure").read_text().splitlines() if line.startswith("full "))
    sample = {
        "pid": pid, "time": time.monotonic(), "age": age,
        "current": int((cgroup / "memory.current").read_text()),
        "anon": int(memory["anon"]),
        "rss": int(Path(f"/proc/{pid}/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE"),
        "pressure": float(dict(field.split("=") for field in pressure.split()[1:])["avg60"]),
    }
    state_file = Path("/run/t3code-tool-update/memory-watchdog.json")
    try:
        previous = json.loads(state_file.read_text())
        if not isinstance(previous, dict):
            previous = {}
    except (FileNotFoundError, ValueError):
        previous = {}
    state, recover = evaluate(sample, previous)
    state_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = state_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(state))
    temporary.replace(state_file)
    print("memory sample " + json.dumps({**sample, "high_samples": state["count"]}), file=sys.stderr)
    if recover:
        print("sustained high process memory or memory pressure")


if __name__ == "__main__":
    main()
