#!/usr/bin/env python3
"""Poll the Synology NAS over SNMPv3 and alert on storage and hardware health.

Reads the Synology system, disk and RAID MIBs plus HOST-RESOURCES storage for
/volume* usage, and publishes each problem to the operations topic through
ghostship-notify: once when it starts firing, again daily while it persists,
and once when it resolves. A failed poll raises its own finding and keeps the
earlier findings active, so an unreachable NAS never reads as healthy.
The SNMP passphrases reach net-snmp through a private snmp.conf, never argv.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

TOPIC = "operations"
PRIORITY = {"critical": 5, "high": 4, "medium": 3}
REALERT_SECONDS = 24 * 3600
SYSTEM_TEMPERATURE_LIMIT = 60
DISK_TEMPERATURE_LIMIT = 55
VOLUME_WARN, VOLUME_CRITICAL = 85, 95

SYNO = "1.3.6.1.4.1.6574"
SYSTEM = f"{SYNO}.1"  # systemStatus.1, temperature.2, powerStatus.3, systemFan.4.1, cpuFan.4.2
DISK = f"{SYNO}.2.1.1"  # diskID.2, diskStatus.5, diskTemperature.6, diskHealthStatus.13
RAID = f"{SYNO}.3.1.1"  # raidName.2, raidStatus.3
STORAGE = "1.3.6.1.2.1.25.2.3.1"  # hrStorageDescr.3, Size.5, Used.6
SUBTREES = (SYSTEM, DISK, RAID, STORAGE)

DISK_STATUS = {4: ("high", "system partition failed"), 5: ("critical", "crashed")}
DISK_HEALTH = {2: ("high", "health warning"), 3: ("critical", "health critical"), 4: ("critical", "failing")}
RAID_STATUS = {11: ("critical", "degraded"), 12: ("critical", "crashed"), 21: ("high", "status unknown")}


class Finding:
    def __init__(self, key, severity, source, message):
        self.key, self.severity, self.source, self.message = key, severity, source, message

    def as_dict(self):
        return {"severity": self.severity, "source": self.source, "message": self.message}


# --- polling ----------------------------------------------------------------


def snmp_conf(credentials, directory):
    """Write the client config holding the SNMPv3 identity; returns its path."""
    path = os.path.join(directory, "snmp.conf")
    lines = [
        "defVersion 3",
        "defSecurityLevel authPriv",
        "defAuthType SHA",
        "defPrivType AES",
        f"defSecurityName {credentials['USER']}",
        f"defAuthPassphrase {credentials['AUTH_PASS']}",
        f"defPrivPassphrase {credentials['PRIV_PASS']}",
        f"persistentDir {directory}",
    ]
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def walk_argv(host, subtree):
    return ["snmpbulkwalk", "-m", "", "-On", "-Oq", "-Oe", "-t", "5", "-r", "1", host, subtree]


def parse_walk(text):
    """`-On -Oq -Oe` output lines (".OID value") to {oid: int or str}."""
    values = {}
    for line in text.splitlines():
        oid, _, raw = line.strip().partition(" ")
        if not oid.startswith("."):
            continue
        raw = raw.strip()
        if len(raw) >= 2 and raw[0] == raw[-1] == '"':
            values[oid[1:]] = raw[1:-1]
            continue
        try:
            values[oid[1:]] = int(raw)
        except ValueError:
            values[oid[1:]] = raw
    return values


def poll(host, credentials, run=subprocess.run):
    """Walk every subtree; raises RuntimeError naming the first failure."""
    values = {}
    with tempfile.TemporaryDirectory(prefix="synology-snmp-") as directory:
        snmp_conf(credentials, directory)
        env = {**os.environ, "SNMPCONFPATH": directory, "MIBS": ""}
        for subtree in SUBTREES:
            result = run(walk_argv(host, subtree), capture_output=True, text=True, env=env, timeout=60)
            if result.returncode != 0 or "Timeout" in result.stderr:
                reason = (result.stderr.strip().splitlines() or ["no response"])[0][:160]
                raise RuntimeError(f"SNMP walk of {subtree} failed: {reason}")
            values.update(parse_walk(result.stdout))
    if not any(oid.startswith(SYSTEM + ".") for oid in values):
        raise RuntimeError("SNMP returned no Synology system MIB values")
    return values


# --- evaluation -------------------------------------------------------------


def rows(values, table, column):
    """{row index: value} for one table column."""
    prefix = f"{table}.{column}."
    return {oid[len(prefix):]: value for oid, value in values.items() if oid.startswith(prefix)}


def unsigned(value):
    return value + 2**32 if isinstance(value, int) and value < 0 else value


def evaluate(values):
    found = []
    scalar = lambda suffix: values.get(f"{SYSTEM}.{suffix}")  # noqa: E731
    if scalar("1.0") == 2:
        found.append(Finding("system.status", "critical", "system", "Synology reports system status Failed"))
    if scalar("3.0") == 2:
        found.append(Finding("system.power", "critical", "power", "Synology reports a power supply failure"))
    for suffix, name in (("4.1.0", "system fan"), ("4.2.0", "CPU fan")):
        if scalar(suffix) == 2:
            found.append(Finding(f"fan.{name.split()[0].lower()}", "high", "fan", f"Synology reports {name} failure"))
    temperature = scalar("2.0")
    if isinstance(temperature, int) and temperature >= SYSTEM_TEMPERATURE_LIMIT:
        found.append(Finding("system.temperature", "high", "temperature", f"system temperature {temperature}C (limit {SYSTEM_TEMPERATURE_LIMIT}C)"))

    names = rows(values, DISK, 2)
    for column, table in ((5, DISK_STATUS), (13, DISK_HEALTH)):
        for index, status in rows(values, DISK, column).items():
            if status in table:
                severity, text = table[status]
                found.append(Finding(f"disk.{index}.{column}", severity, "disk", f"{names.get(index, 'disk ' + index)} {text}"))
    for index, temp in rows(values, DISK, 6).items():
        if isinstance(temp, int) and temp >= DISK_TEMPERATURE_LIMIT:
            found.append(Finding(f"disk.{index}.temperature", "high", "temperature", f"{names.get(index, 'disk ' + index)} at {temp}C (limit {DISK_TEMPERATURE_LIMIT}C)"))

    raid_names = rows(values, RAID, 2)
    for index, status in rows(values, RAID, 3).items():
        if status in RAID_STATUS:
            severity, text = RAID_STATUS[status]
            found.append(Finding(f"raid.{index}", severity, "raid", f"{raid_names.get(index, 'RAID ' + index)} {text}"))

    sizes, used = rows(values, STORAGE, 5), rows(values, STORAGE, 6)
    for index, descr in rows(values, STORAGE, 3).items():
        size, use = unsigned(sizes.get(index)), unsigned(used.get(index))
        if not str(descr).startswith("/volume") or not isinstance(size, int) or not isinstance(use, int) or size <= 0:
            continue
        percent = 100 * use / size
        if percent >= VOLUME_WARN:
            severity = "high" if percent >= VOLUME_CRITICAL else "medium"
            found.append(Finding(f"volume.{descr}", severity, "volume", f"{descr} is {percent:.0f}% full"))
    return found


# --- alerting ---------------------------------------------------------------


def publish(finding, state_name):
    helper = shutil.which("ghostship-notify")
    if not helper:
        return False
    priority = PRIORITY.get(finding.severity, 3) if state_name == "firing" else 2
    argv = [
        helper, "--topic", TOPIC, "--priority", str(priority),
        "--title", f"[synology] {finding.source}: {finding.severity}",
        "--source", "synology", "--dedupe", f"synology.{finding.key}", "--state", state_name,
        "--tags", f"flame-mammoth,{finding.source}", finding.message,
    ]
    return subprocess.run(argv, capture_output=True).returncode == 0


def dispatch(state, findings, now, sender=publish):
    active = state.setdefault("active", {})
    current = {f.key: f for f in findings}
    for key, finding in current.items():
        record = active.get(key)
        # alerted None marks an undelivered alert, retried on the next run.
        if record is None or record["alerted"] is None or now - record["alerted"] >= REALERT_SECONDS:
            delivered = sender(finding, "firing")
            active[key] = {**finding.as_dict(), "first": (record or {}).get("first", now), "alerted": now if delivered else None}
    for key in [k for k in active if k not in current]:
        record = active.pop(key)
        sender(Finding(key, record["severity"], record["source"], f"resolved: {record['message']}"), "resolved")


def findings_for(state, host, credentials, run=subprocess.run):
    """Current findings; a failed poll keeps the earlier ones active."""
    try:
        return evaluate(poll(host, credentials, run))
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        held = [Finding(k, r["severity"], r["source"], r["message"])
                for k, r in state.get("active", {}).items() if k != "snmp.poll"]
        return [Finding("snmp.poll", "high", "snmp", f"Synology {host} health poll failed: {exc}"), *held]


def read_env(path):
    values = {}
    with open(path) as handle:
        for line in handle:
            key, sep, value = line.strip().partition("=")
            if sep:
                values[key.strip()] = value.strip().strip("'\"")
    return values


def load(path):
    try:
        with open(path) as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {}


def save(path, data):
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".health-")
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle, indent=1, sort_keys=True)
    os.replace(temporary, path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--credentials", required=True, help="env file with USER, AUTH_PASS, PRIV_PASS")
    parser.add_argument("--state", default="/var/lib/ghostship-synology-health/state.json")
    parser.add_argument("--dry-run", action="store_true", help="evaluate without publishing alerts")
    args = parser.parse_args(argv)
    credentials = read_env(args.credentials)
    missing = [k for k in ("USER", "AUTH_PASS", "PRIV_PASS") if not credentials.get(k)]
    if missing:
        raise SystemExit(f"synology-health: credentials missing {', '.join(missing)}")
    state = load(args.state)
    findings = findings_for(state, args.host, credentials)
    if not args.dry_run:
        dispatch(state, findings, int(time.time()))
        save(args.state, state)
    print(json.dumps({"findings": [dict(key=f.key, **f.as_dict()) for f in findings]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
