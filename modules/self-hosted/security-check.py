#!/usr/bin/env python3
"""Host security checks for chill-penguin with deduplicated NTFY alerts.

Invariant checks (AppArmor, audit, firewall, container privilege) alert as soon
as they fail. Drift checks (listeners, SSH keys, persistence, SUID files) record
a baseline on first run and alert on later differences until the reviewer
accepts the new state. A reviewer who verified one change re-baselines one
drift category with --accept-drift CATEGORY, or accepts one reviewed flow
finding with --accept-flow KEY; the bare --accept re-baselines every category
and accepts every current flow finding. Findings are written to a root-only
state file; alert bodies carry identifiers only, never secrets or raw logs.
"""

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

PRIORITY = {"critical": 5, "high": 4, "medium": 3}
REALERT_SECONDS = 24 * 3600
SUID_ROOTS = ["/etc", "/root", "/home", "/var", "/tmp", "/opt", "/usr", "/bin", "/sbin"]
# find -path patterns; container image layers legitimately carry SUID files.
SUID_SKIP = ["/var/lib/containers", "*/.local/share/containers", "/nix", "/proc", "/sys", "/run"]
PERSISTENCE_DIRS = [
    "/run/systemd/system",
    "/etc/systemd/system",
    "/root/.config/systemd",
    "/var/spool/cron",
    "/etc/cron.d",
    "/etc/profile.d",
]
KEY_DIRS = ["/etc/ssh/authorized_keys.d", "/root/.ssh"]
# The drift categories a reviewer may re-baseline on their own.
DRIFT_CATEGORIES = ["listeners", "sshkeys", "persistence", "suid"]


def sh(argv, check=True):
    result = subprocess.run(argv, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"{argv[0]} failed: {result.stderr.strip()[:200]}")
    return result.stdout


class Finding:
    """A check result. Events (one-off log matches) alert once and never resolve."""

    def __init__(self, key, severity, source, message, event=False):
        self.key, self.severity, self.source, self.message = key, severity, source, message
        self.event = event

    def as_dict(self):
        return {"severity": self.severity, "source": self.source, "message": self.message}


# --- invariant checks -------------------------------------------------------


def check_apparmor(cfg, read=lambda p: open(p).read()):
    found = []
    try:
        enabled = read("/sys/module/apparmor/parameters/enabled").strip()
    except OSError:
        enabled = "N"
    if enabled != "Y":
        return [Finding("apparmor.disabled", "critical", "apparmor", "AppArmor is not enabled")]
    loaded = read("/sys/kernel/security/apparmor/profiles")
    names = {line.rsplit(" (", 1)[0] for line in loaded.splitlines()}
    for profile in cfg["expected_profiles"]:
        if profile not in names:
            found.append(Finding(f"apparmor.unloaded.{profile}", "critical", "apparmor", f"profile {profile} is not loaded"))
    return found


def check_container_labels(cfg, rows, read=lambda p: open(p).read(), walk=os.walk):
    """Every running container must carry its configured AppArmor label.

    Declared app profiles come from the config; the rest must match the
    profile Podman recorded at creation. A reload that unloads a profile
    silently leaves its containers unconfined, so the live label is compared.
    """
    found = []
    for row in rows:
        container = row["Name"].lstrip("/")
        profile = cfg["container_profiles"].get(container) or row.get("AppArmorProfile") or ""
        if profile in ("", "unconfined"):
            if container not in cfg["privileged_allow"]:
                found.append(
                    Finding(f"apparmor.label.{container}", "high", "apparmor", f"{container} was created without an AppArmor profile")
                )
            continue
        pid = row.get("State", {}).get("Pid") or 0
        if not pid:
            continue
        label = ""
        for path in (f"/proc/{pid}/attr/apparmor/current", f"/proc/{pid}/attr/current"):
            try:
                label = read(path).strip()
                break
            except OSError:
                continue
        if label != profile and not label.startswith((profile + " ", profile + "//")):
            found.append(
                Finding(f"apparmor.label.{container}", "critical", "apparmor", f"{container} runs as '{label or 'unknown'}', expected {profile}")
            )
        # Any process, not only PID 1: a policy reload that removes a complain-mode
        # null-* learning profile leaves the processes in it unconfined (agent-desktop
        # PulseAudio, 2026-10-21).
        unconfined = [p for p in container_pids(pid, read, walk) if label_of(p, read) == "unconfined"]
        if unconfined:
            found.append(
                Finding(f"apparmor.unconfined.{container}", "critical", "apparmor",
                        f"{len(unconfined)} process(es) in {container} run unconfined")
            )
    return found


def label_of(pid, read):
    for path in (f"/proc/{pid}/attr/apparmor/current", f"/proc/{pid}/attr/current"):
        try:
            return read(path).strip()
        except (OSError, KeyError):
            continue
    return ""  # exited


def container_pids(pid, read, walk=os.walk):
    """Every process in the container's cgroup tree (Podman nests a subgroup)."""
    try:
        relative = read(f"/proc/{pid}/cgroup").strip().split("::", 1)[-1]
    except (OSError, KeyError):
        return []
    root = "/sys/fs/cgroup" + relative
    # The scope's parent holds conmon and the container subgroup.
    if root.endswith("/container"):
        root = root[: -len("/container")]
    pids = []
    for directory, _, files in walk(root):
        if "cgroup.procs" in files:
            try:
                pids += [int(x) for x in read(f"{directory}/cgroup.procs").split()]
            except (OSError, KeyError, ValueError):
                continue
    return pids


def check_audit(cfg, state, status_text):
    found = []
    status = dict(line.split(" ", 1) for line in status_text.splitlines() if " " in line)
    if status.get("enabled", "0").strip() not in ("1", "2"):
        found.append(Finding("audit.disabled", "critical", "auditd", "kernel audit is disabled"))
    lost = int(status.get("lost", "0").strip() or 0)
    previous = state.get("audit_lost")
    if previous is not None and lost > previous:
        found.append(Finding("audit.lost", "high", "auditd", f"audit lost {lost - previous} events since last check", event=True))
    state["audit_lost"] = lost
    return found


def check_firewall(cfg, tables_text, filter_text):
    found = []
    tables = {" ".join(line.split()[1:3]) for line in tables_text.splitlines() if line.startswith("table ")}
    for table in cfg["expected_tables"]:
        if table not in tables:
            found.append(Finding(f"firewall.table.{table.replace(' ', '.')}", "critical", "firewall", f"nftables table {table} is missing"))
    if "chain nixos-fw " not in filter_text:
        found.append(Finding("firewall.nixos-fw", "critical", "firewall", "NixOS input firewall chain is missing"))
    return found


def check_containers(cfg, rows):
    found = []
    known = set(cfg["declared_containers"])
    for row in rows:
        name = row["Name"].lstrip("/")
        host = row.get("HostConfig", {})
        if host.get("Privileged") and name not in cfg["privileged_allow"]:
            found.append(Finding(f"container.privileged.{name}", "critical", "containers", f"{name} is running privileged"))
        allowed_caps = set(cfg["cap_add_allow"].get(name, []))
        extra = sorted(set(host.get("CapAdd") or []) - allowed_caps)
        if extra:
            found.append(Finding(f"container.caps.{name}", "high", "containers", f"{name} adds capabilities {','.join(extra)}"))
        if host.get("NetworkMode") == "host" or host.get("PidMode") == "host":
            found.append(Finding(f"container.hostns.{name}", "high", "containers", f"{name} shares a host namespace"))
        for mount in row.get("Mounts") or []:
            source = mount.get("Source", "")
            if re.search(r"(podman|docker|containerd)\.sock$|^/run/podman|^/var/run/docker", source) and source not in cfg["socket_mount_allow"]:
                found.append(Finding(f"container.socket.{name}", "critical", "containers", f"{name} mounts {source}"))
        if name not in known and not name.startswith(tuple(cfg["ephemeral_prefixes"])):
            found.append(Finding(f"container.undeclared.{name}", "high", "containers", f"undeclared container {name} is running"))
    return found


def container_addresses(rows, names):
    """Current addresses of the named containers; Podman reassigns them on recreation."""
    found = set()
    for row in rows:
        if row["Name"].lstrip("/") not in names:
            continue
        for net in (row.get("NetworkSettings", {}).get("Networks") or {}).values():
            for key in ("IPAddress", "GlobalIPv6Address"):
                if net.get(key):
                    found.add(ipaddress.ip_address(net[key]))
    return found


CLIENT_MEMORY_SECONDS = 24 * 3600


def remember_clients(state, current, now):
    """Current client addresses plus those held within the last day.

    Logins read from the journal can predate a client's recreation, which
    gives it new addresses; its previous addresses stay allowed for a day.
    """
    history = state.setdefault("ssh_clients", {})
    for address in current:
        history[str(address)] = now
    for address in [a for a, seen in history.items() if now - seen > CLIENT_MEMORY_SECONDS]:
        del history[address]
    return {ipaddress.ip_address(a) for a in history}


def check_ssh_logins(cfg, state, journal_lines, clients=frozenset()):
    logins = {}
    allowed = [ipaddress.ip_network(n) for n in cfg["ssh_allowed_sources"]]
    failures = 0
    for line in journal_lines:
        accepted = re.match(r"Accepted (\S+) for (\S+) from (\S+)", line)
        if accepted:
            method, user, source = accepted.groups()
            try:
                address = ipaddress.ip_address(source)
            except ValueError:
                continue
            if address not in clients and not any(address in net for net in allowed):
                key = f"ssh.login.{user}.{source}"
                count = logins.get(key, (0, method))[0] + 1
                logins[key] = (count, method)
        elif re.search(r"Failed |Invalid user|authentication failure", line):
            failures += 1
    found = [
        Finding(key, "critical", "sshd", f"{key.split('.', 3)[2]} logged in by {method} from unexpected {key.split('.', 3)[3]} ({count}x)", event=True)
        for key, (count, method) in logins.items()
    ]
    if failures >= cfg["ssh_failure_threshold"]:
        found.append(Finding("ssh.failures", "high", "sshd", f"{failures} failed SSH authentications since last check", event=True))
    return found


# --- drift checks -----------------------------------------------------------


def listeners(ss_text):
    current = set()
    for line in ss_text.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        proto, local = parts[0], parts[4]
        address, _, port = local.rpartition(":")
        # Container DNS resolvers move with network addresses; unconnected UDP
        # client sockets use the ephemeral range.
        if address.startswith("10.89.") and port == "53":
            continue
        if proto == "udp" and port.isdigit() and int(port) >= 32768:
            continue
        current.add(f"{proto} {address}:{port}")
    return current


def ssh_auth_files():
    """sshd configuration and authorized keys; known_hosts churn is ignored."""
    candidates = [os.path.realpath("/etc/ssh/sshd_config")]
    for root in KEY_DIRS:
        if os.path.isdir(root):
            candidates += [
                os.path.join(root, f)
                for f in os.listdir(root)
                if root != "/root/.ssh" or f.startswith("authorized_keys")
            ]
    digests = {}
    for path in candidates:
        try:
            with open(path, "rb") as handle:
                digests[path] = hashlib.sha256(handle.read()).hexdigest()
        except OSError:
            continue
    return digests


def persistence_entries():
    entries = {}
    for root in PERSISTENCE_DIRS:
        if not os.path.isdir(root):
            continue
        for directory, _, files in os.walk(root):
            for name in files:
                path = os.path.join(directory, name)
                target = os.path.realpath(path)
                # Store-backed unit links change with every generation; files do not.
                if target.startswith("/nix/store/"):
                    continue
                try:
                    with open(path, "rb") as handle:
                        entries[path] = hashlib.sha256(handle.read()).hexdigest()
                except OSError:
                    entries[path] = "unreadable"
    return entries


def suid_files():
    """SUID/SGID files on the root filesystem outside the store and containers."""
    prune = []
    for path in SUID_SKIP:
        prune += ["-path", path, "-o"]
    argv = ["find", *[r for r in SUID_ROOTS if os.path.isdir(r)], "-xdev", "(", *prune[:-1], ")", "-prune",
            "-o", "-type", "f", "-perm", "/6000", "-print"]
    return set(sh(argv, check=False).splitlines())


def drift(state, name, current, severity, source, describe):
    baseline = state.setdefault("baselines", {}).get(name)
    if baseline is None:
        state["baselines"][name] = current
        return []
    found = []
    if isinstance(current, dict):
        for path in sorted(set(current) | set(baseline)):
            if current.get(path) != baseline.get(path):
                change = "added" if path not in baseline else "removed" if path not in current else "changed"
                found.append(Finding(f"{name}.{path}", severity, source, describe(path, change)))
    else:
        for item in sorted(set(current) - set(baseline)):
            found.append(Finding(f"{name}.{item}", severity, source, describe(item, "added")))
    return found


# --- alerting ---------------------------------------------------------------


def publish(cfg, finding, state_name):
    helper = shutil.which("ghostship-notify")
    if not helper:
        return False
    priority = PRIORITY.get(finding.severity, 3) if state_name == "firing" else 2
    argv = [
        helper, "--topic", cfg["ntfy_topic"], "--priority", str(priority),
        "--title", f"[security] {finding.source}: {finding.severity}",
        "--source", finding.source, "--dedupe", finding.key, "--state", state_name,
        "--tags", f"chill-penguin,{finding.severity}", finding.message,
    ]
    return subprocess.run(argv, capture_output=True).returncode == 0


def dispatch(cfg, state, findings, now, sender=publish):
    active = state.setdefault("active", {})
    current = {f.key: f for f in findings}
    for key, finding in current.items():
        if finding.event:
            if finding.severity in PRIORITY:
                sender(cfg, finding, "firing")
            continue
        record = active.get(key)
        # alerted == 0 marks an undelivered alert, retried on the next run.
        if record is None or not record["alerted"] or now - record["alerted"] >= REALERT_SECONDS:
            delivered = finding.severity in PRIORITY and sender(cfg, finding, "firing")
            active[key] = {**finding.as_dict(), "first": (record or {}).get("first", now), "alerted": now if delivered else 0}
    for key in [k for k in active if k not in current]:
        record = active.pop(key)
        sender(cfg, Finding(key, record["severity"], record["source"], f"resolved: {record['message']}"), "resolved")


def load(path, default):
    try:
        with open(path) as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default


def save(path, data):
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".check-")
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle, indent=1, sort_keys=True)
    os.replace(temporary, path)


def observed_flow_findings(cfg, flows):
    """Every sensitive observed edge, before the accepted keys are applied."""
    found = []
    for key in flows.get("edges", {}):
        source, target, proto, port = key.split("|")
        if target == "host" and port == "22" and source not in cfg["host_ssh_clients"] and not source.startswith("lan:"):
            found.append(Finding(f"flow.hostssh.{source}", "high", "network", f"{source} opened SSH to the host"))
        owners = cfg["database_owners"].get(target)
        if owners is not None and source not in owners:
            found.append(Finding(f"flow.db.{source}.{target}", "high", "network", f"{source} connected to {target}:{port}"))
    return found


def flow_findings(cfg, flows, accepted):
    """Sensitive observed edges; reviewed edges are accepted by key."""
    return [f for f in observed_flow_findings(cfg, flows) if f.key not in accepted]


def run(args):
    cfg = load(args.config, None)
    state = load(args.state, {})
    now = int(time.time())
    ids = sh(["podman", "ps", "-q"]).split()
    rows = json.loads(sh(["podman", "inspect", *ids])) if ids else []
    since = state.get("last_run", now - 900)
    journal = sh(["journalctl", "-u", "sshd", "--since", f"@{since}", "--no-pager", "-o", "cat"], check=False).splitlines()
    findings = []
    findings += check_apparmor(cfg)
    findings += check_container_labels(cfg, rows)
    findings += check_audit(cfg, state, sh(["auditctl", "-s"], check=False))
    findings += check_firewall(cfg, sh(["nft", "list", "tables"]), sh(["nft", "list", "table", "ip", "filter"], check=False))
    findings += check_containers(cfg, rows)
    findings += check_ssh_logins(cfg, state, journal, remember_clients(state, container_addresses(rows, cfg["host_ssh_clients"]), now))
    flows_state = load(cfg["flows_state"], {})
    flows = flow_findings(cfg, flows_state, set(state.get("accepted_flows", [])))
    if args.accept:
        state.setdefault("baselines", {}).clear()
        state["accepted_flows"] = sorted(set(state.get("accepted_flows", [])) | {f.key for f in flows})
        flows = []
    else:
        # A scoped re-baseline drops one baseline, so drift() records it again
        # on this run. The other baselines stay as they are and keep alerting.
        baselines = state.get("baselines")
        if baselines:
            for category in args.accept_drift or []:
                baselines.pop(category, None)
        if args.accept_flow:
            known = {f.key for f in observed_flow_findings(cfg, flows_state)}
            unknown = [key for key in args.accept_flow if key not in known]
            if unknown:
                print(
                    f"unknown flow finding: {', '.join(unknown)}; "
                    f"current flow findings: {', '.join(sorted(known)) or 'none'}",
                    file=sys.stderr,
                )
                return 2
            state["accepted_flows"] = sorted(set(state.get("accepted_flows", [])) | set(args.accept_flow))
            accepted = set(args.accept_flow)
            flows = [f for f in flows if f.key not in accepted]
    findings += flows
    findings += drift(state, "listeners", sorted(listeners(sh(["ss", "-Hltnu"]))), "medium", "exposure", lambda i, c: f"new listener {i}")
    findings += drift(state, "sshkeys", ssh_auth_files(), "high", "sshd", lambda p, c: f"SSH auth file {p} {c}")
    findings += drift(state, "persistence", persistence_entries(), "medium", "persistence", lambda p, c: f"non-store unit/cron file {p} {c}")
    if args.suid or "suid" not in state.get("baselines", {}) or now - state.get("suid_scanned", 0) > 24 * 3600:
        findings += drift(state, "suid", sorted(suid_files()), "high", "persistence", lambda p, c: f"new SUID/SGID file {p}")
        state["suid_scanned"] = now
    if not args.dry_run:
        dispatch(cfg, state, findings, now)
    state["last_run"] = now
    state["last_findings"] = [dict(key=f.key, **f.as_dict()) for f in findings]
    save(args.state, state)
    print(json.dumps({"findings": state["last_findings"]}, indent=1))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--state", default="/var/lib/ghostship-security/check.json")
    parser.add_argument("--accept", action="store_true",
                        help="re-baseline EVERY drift category and accept EVERY current flow finding (prefer --accept-drift/--accept-flow)")
    parser.add_argument("--accept-drift", action="append", choices=DRIFT_CATEGORIES, metavar="CATEGORY",
                        help="re-baseline one drift category after review (repeatable): " + ", ".join(DRIFT_CATEGORIES))
    parser.add_argument("--accept-flow", action="append", metavar="KEY",
                        help="accept one current flow finding by key after review (repeatable)")
    parser.add_argument("--suid", action="store_true", help="force the SUID scan")
    parser.add_argument("--dry-run", action="store_true", help="evaluate without publishing alerts")
    args = parser.parse_args(argv)
    if args.accept and (args.accept_drift or args.accept_flow):
        parser.error("--accept cannot be combined with --accept-drift or --accept-flow; use the scoped flags")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
