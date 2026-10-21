"""Independent watchdog for the SIEM alert path.

The bridge is the only thing that turns firing rules into notifications, so a
hung or broken bridge would look like a quiet, green system. This root job runs
on its own timer and checks, without the bridge:

- the bridge's last poll and per-source success (its textfile metrics),
- ntfy and T3 delivery failures and dead letters,
- the vmalert, VictoriaLogs and VictoriaMetrics APIs directly,
- the container snapshot's age.

Each problem opens one episode: an ntfy security alert plus, once per episode,
a T3 incident through ghostship-notify --incident (queued even if ntfy is
down). Publishing retries until ntfy accepts; clearing sends one resolution.
A dead host cannot report itself: that is the off-host dead-man's job.
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def parse_metrics(text):
    values = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        name, _, value = line.rpartition(" ")
        try:
            values[name] = float(value)
        except ValueError:
            continue
    return values


def reachable(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 300
    except OSError:
        return False


def problems(config, now, metrics_text, mtime, snapshot_mtime, probe=reachable):
    """Current problems as {key: message}."""
    found = {}
    m = parse_metrics(metrics_text) if metrics_text is not None else None
    if m is None or now - mtime > config["bridge_stale"]:
        found["bridge-stalled"] = "SIEM alert bridge has not reported progress"
    else:
        last_poll = m.get("ghostship_siem_bridge_last_poll_timestamp_seconds", 0)
        if now - last_poll > config["bridge_stale"]:
            found["bridge-stalled"] = f"SIEM alert bridge last polled {int(now - last_poll)}s ago"
        for source in config["sources"]:
            at = m.get(f'ghostship_siem_bridge_source_last_success_timestamp_seconds{{source="{source}"}}', 0)
            if now - at > config["source_stale"]:
                found[f"source-{source}"] = f"bridge cannot read vmalert-{source} ({int(now - at)}s)"
        for channel in ("ntfy", "t3"):
            failures = m.get(f'ghostship_siem_bridge_delivery_consecutive_failures{{channel="{channel}"}}', 0)
            if failures >= config["delivery_failures"]:
                found[f"delivery-{channel}"] = f"{int(failures)} consecutive {channel} delivery failures"
        if m.get("ghostship_siem_bridge_dead_letters", 0) > 0:
            found["dead-letters"] = f"{int(m['ghostship_siem_bridge_dead_letters'])} alert(s) undelivered for a day"
    for name, url in config["probes"].items():
        if not probe(url):
            found[f"probe-{name}"] = f"{name} is not answering"
    if snapshot_mtime is None or now - snapshot_mtime > config["snapshot_stale"]:
        found["snapshot-stale"] = "container snapshot is stale"
    return found


def notify(config, state_name, key, message, incident):
    command = [config["notify"], "--topic", "security", "--source", "siem-watchdog",
               "--state", state_name, "--priority", "5" if state_name == "firing" else "2",
               "--title", f"SIEM pipeline: {key}", message]
    if incident:
        command.insert(1, "--incident")
    try:
        return subprocess.run(command, check=False, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def step(state, found, now, send):
    """Advance episode state; send(state_name, key, message, incident) -> delivered."""
    episodes = state.setdefault("episodes", {})
    for key, message in found.items():
        episode = episodes.setdefault(key, {"since": now, "delivered": False, "incident": False})
        episode["message"] = message
        if not episode["delivered"]:
            episode["delivered"] = send("firing", key, message, not episode["incident"])
            episode["incident"] = True
    for key in [k for k in episodes if k not in found]:
        episode = episodes[key]
        if not episode["delivered"] or send("resolved", key, f"cleared: {episode['message']}", False):
            del episodes[key]


def read(path):
    try:
        return Path(path).read_text(), Path(path).stat().st_mtime
    except OSError:
        return None, 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text())
    state_path = Path(config["state"])
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    now = time.time()
    text, mtime = read(config["bridge_metrics"])
    _, snap = read(config["snapshot"])
    found = problems(config, now, text, mtime, snap or None)
    step(state, found, now, lambda *a: notify(config, *a))
    temporary = state_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state))
    temporary.replace(state_path)
    for key, message in sorted(found.items()):
        print(f"siem watchdog: {key}: {message}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
