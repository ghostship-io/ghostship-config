#!/usr/bin/env python3
"""Collect private AppArmor evidence; stdout contains counts/status only.

State schema v1: evidence.json holds containers, samples, events and reviews.
Review with --review EVENT_ID --classification expected-denial|legitimate-needs-policy
--note TEXT. IDs are returned by the status report. Reviews never change policy.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

DAY = 86400
MAX_GAP = 26 * 3600
HEARTBEAT_PATH = "/proc/sys/kernel/random/boot_id"
FIELDS = re.compile(r'(\w+)=(?:"([^"\n]*)"|(\S+))')
AUDIT_LOSS = re.compile(
    r"audit_lost=[1-9][0-9]*|audit.*(?:backlog limit exceeded|rate limit exceeded)|"
    r"kauditd.*(?:suppressed|overflow)|(?:Suppressed|Dropped) [1-9][0-9]* messages|"
    r"(?:audit|apparmor)\S*: [1-9][0-9]* (?:callbacks|messages) suppressed", re.I)
# AppArmor records only (AVC, or the 1501-1507 AppArmor types), every kernel
# message for loss notices, and journald's own rate-limit reports. Exec and
# service audit records from other rules are hundreds of MB a day.
APPARMOR_TYPES = ["_AUDIT_TYPE=1400", *(f"_AUDIT_TYPE={n}" for n in range(1501, 1508))]
JOURNAL_MATCHES = ["_TRANSPORT=audit", *APPARMOR_TYPES, "+", "_TRANSPORT=kernel"]
JOURNAL_TIMEOUT = 120


def run(args, timeout=20):
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, timeout=timeout).stdout


def journal(start, end):
    output = run(["journalctl", "--no-pager", "--output=json", "--since", f"@{start:.6f}",
                  "--until", f"@{end:.6f}", *JOURNAL_MATCHES,
                  "+", "SYSLOG_IDENTIFIER=systemd-journald"], timeout=JOURNAL_TIMEOUT)
    rows = []
    for line in output.splitlines():
        row = json.loads(line)
        stamp = int(row["__REALTIME_TIMESTAMP"]) / 1_000_000
        if start <= stamp <= end:
            rows.append((stamp, row.get("MESSAGE", "")))
    return rows


def parse_event(stamp, message, profile):
    fields = {key: quoted or bare for key, quoted, bare in FIELDS.findall(message)}
    label = fields.get("profile", "")
    if (label != profile and not label.startswith(profile + "//")) or fields.get("apparmor") not in {
            "ALLOWED", "DENIED", "AUDIT", "ERROR"}:
        return None
    # Keep only audit fields useful for review; no arguments, environment or raw message.
    detail = {key: fields[key] for key in (
        "profile",
        "apparmor", "operation", "name", "name2", "requested_mask", "denied_mask",
        "error", "info", "comm", "pid", "family", "sock_type", "protocol", "capname"
    ) if key in fields}
    identity = json.dumps([stamp, detail], sort_keys=True).encode()
    return {"id": hashlib.sha256(identity).hexdigest()[:24], "time": stamp, **detail}


def heartbeat_event(event):
    return (event.get("apparmor") in {"AUDIT", "ALLOWED"}
            and event.get("operation") == "open"
            and event.get("name") == HEARTBEAT_PATH
            and event.get("requested_mask") == "r"
            and event.get("denied_mask", "") in {"", "r"})


def inspect_container(name, config):
    """Never request Config/Env or command arguments from podman."""
    result = {"healthy": False, "reasons": [], "profile": config["profile"], "mode": config["mode"], "source": config["source"]}
    try:
        result["policy_hash"] = hashlib.sha256(Path(config["source"]).read_bytes()).hexdigest()
        result["boot_id"] = Path(HEARTBEAT_PATH).read_text().strip()
        enabled = Path("/sys/module/apparmor/parameters/enabled").read_text().strip() == "Y"
        profiles = Path("/sys/kernel/security/apparmor/profiles").read_text().splitlines()
        result["enabled"] = enabled
        expected = {f'{label} ({config["mode"]})'
                    for label in config.get("processProfiles", [config["profile"]])}
        required = {f'{label} ({config["mode"]})'
                    for label in config.get("requiredProcessProfiles",
                                            config.get("processProfiles", [config["profile"]]))}
        result["loaded"] = expected <= set(profiles)
        projection = json.loads(run([
            "podman", "inspect", "--format",
            '{"image":{{json .Image}},"running":{{json .State.Running}},'
            '"profile":{{json .AppArmorProfile}}}', name]))
        result["image"] = projection["image"]
        result["running"] = projection["running"] is True
        result["configured_profile"] = projection["profile"]
        lines = run(["podman", "top", name, "hpid"]).splitlines()
        if not lines or lines[0].strip().upper() != "HPID":
            raise ValueError("missing hpid header")
        pids = [int(line.strip()) for line in lines[1:] if line.strip()]
        if not pids:
            raise ValueError("no container processes")
        result["processes"] = [{"pid": pid, "label": Path(f"/proc/{pid}/attr/current").read_text().strip()}
                               for pid in pids]
        observed_labels = {p["label"] for p in result["processes"]}
        lost = re.search(r"^lost\s+(\d+)\s*$", run(["auditctl", "-s"]), re.M)
        if not lost:
            raise ValueError("missing kernel audit loss counter")
        result["audit_lost"] = int(lost[1])
        checks = {"apparmor-disabled": enabled, "loaded-mode-mismatch": result["loaded"],
                  "container-stopped": result["running"],
                  "configured-profile-mismatch": projection["profile"] == config["profile"],
                  "process-profile-mismatch": required <= observed_labels <= expected}
        result["reasons"] = [reason for reason, ok in checks.items() if not ok]
        result["healthy"] = not result["reasons"]
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        result["reasons"].append("inspection-failed")
    return result


def probe(name, profile):
    start = time.time()
    try:
        # Discard boot ID; only the exact audit event proves the pipeline works.
        subprocess.run(["podman", "exec", name, "/bin/cat", HEARTBEAT_PATH],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=2)
        deadline = time.monotonic() + 2.5
        while True:
            # Bound each poll too: total probe time is at most five seconds.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            output = subprocess.run([
                "journalctl", "--no-pager", "--output=json", "--since", f"@{start:.6f}",
                *JOURNAL_MATCHES], check=True, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=min(remaining, 1))
            end = time.time()
            for line in output.stdout.splitlines():
                row = json.loads(line)
                stamp = int(row["__REALTIME_TIMESTAMP"]) / 1_000_000
                event = parse_event(stamp, row.get("MESSAGE", ""), profile)
                if start <= stamp <= end and event and heartbeat_event(event):
                    return event
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None


def advance(previous, observation, events, now, audit_ok):
    """Pure coverage transition, intentionally conservative after interruptions."""
    state = dict(previous or {})
    old_sample = state.get("last_sample")
    changed = (state.get("policy_hash"), state.get("image"), state.get("profile"), state.get("mode"), state.get("source")) != (
        observation.get("policy_hash"), observation.get("image"), observation.get("profile"), observation.get("mode"), observation.get("source"))
    if state.get("boot_id") != observation.get("boot_id"):
        changed = True
    reasons = list(observation.get("reasons", []))
    if not audit_ok:
        reasons.append("audit-collection-failed")
    if not observation.get("heartbeat"):
        reasons.append("audit-heartbeat-missing")
    if old_sample is not None and not 0 < now - old_sample <= MAX_GAP:
        reasons.append("collection-gap-or-clock-regression")
    previous_lost = state.get("observation", {}).get("audit_lost", 0)
    if observation.get("audit_lost", 0) != previous_lost:
        reasons.append("kernel-audit-loss-counter-changed")
    if changed:
        state.update(policy_hash=observation.get("policy_hash"), image=observation.get("image"),
                     boot_id=observation.get("boot_id"),
                     profile=observation.get("profile"), mode=observation.get("mode"), source=observation.get("source"),
                     last_policy_change=now, coverage_start=None, samples=[])
    if reasons or not observation.get("healthy"):
        state.update(coverage_start=None, samples=[])
    else:
        if state.get("coverage_start") is None:
            state["coverage_start"] = now
        state["samples"] = state.get("samples", []) + [now]
    ledger = dict(state.get("events", {}))
    for event in events:
        ledger[event["id"]] = event
    state.update(events=ledger, last_sample=now, observation=observation, reasons=reasons)
    return state


def status(state, now):
    baseline = state.get("coverage_start")
    reviews = state.get("reviews", {})
    blocking = [eid for eid in state.get("events", {})
                if reviews.get(eid, {}).get("classification") != "expected-denial"]
    samples = state.get("samples", [])
    # UTC-day buckets tolerate timer jitter. Elapsed time is checked separately:
    # eight calendar dates alone never substitute for seven full days.
    verified = {int(stamp // DAY) for stamp in samples}
    fresh = 0 <= now - state.get("last_sample", 0) <= MAX_GAP
    elapsed = max(0, state.get("last_sample", 0) - baseline) if baseline is not None else 0
    return {"ready": bool(fresh and baseline is not None and elapsed >= 7 * DAY
                          and len(verified) >= 8 and not blocking and not state.get("reasons")),
            "coverage_days": elapsed / DAY, "verified_daily_samples": len(verified),
            "last_sample": state.get("last_sample"), "coverage_start": baseline,
            "last_policy_change": state.get("last_policy_change"),
            "fresh": fresh, "blocking_event_ids": blocking,
            "event_count": len(state.get("events", {})), "reasons": state.get("reasons", [])}


def collect(config, previous, now):
    result = {"schema_version": 1, "containers": {}}
    prior = previous.get("containers", {})
    for name, spec in config["containers"].items():
        old = prior.get(name, {})
        observation = inspect_container(name, spec)
        heartbeat = probe(name, spec["profile"]) if observation["healthy"] else None
        observation["heartbeat"] = heartbeat is not None
        end = time.time()
        # Include the probe window; next sample starts at the exact same boundary.
        start = old.get("last_sample", now - DAY)
        anchor = old.get("audit_anchor")
        if anchor:
            # Retain the previous heartbeat as a journal continuity anchor. Rotation
            # past it cannot silently turn a missing interval into a clean day.
            start = min(start, anchor["time"])
        audit_ok = True
        try:
            rows = journal(start, end)
            loss_seen = any(AUDIT_LOSS.search(message) for _, message in rows)
            events = [event for stamp, message in rows
                      if (event := parse_event(stamp, message, spec["profile"]))]
            observed_ids = {event["id"] for event in events}
            intentional_ids = {item["id"] for item in (anchor, heartbeat) if item}
            audit_ok = intentional_ids <= observed_ids and not loss_seen
            events = [event for event in events if event["id"] not in intentional_ids]
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            audit_ok, events = False, []
        entry = advance(old, observation, events, end, audit_ok)
        entry["audit_anchor"] = ({"id": heartbeat["id"], "time": heartbeat["time"]}
                                 if heartbeat else None)
        result["containers"][name] = entry
    return result


def write_state(directory, state):
    fd, temporary = tempfile.mkstemp(prefix=".evidence-", dir=directory)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(state, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / "evidence.json")
        dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_state(directory):
    path = directory / "evidence.json"
    if path.is_symlink():
        raise ValueError("symlink state")
    if not path.exists():
        return {"schema_version": 1, "containers": {}}
    if path.stat().st_mode & 0o077 or path.stat().st_uid != 0:
        raise ValueError("state must be root-only")
    state = json.loads(path.read_text())
    if state.get("schema_version") != 1:
        raise ValueError("unsupported state schema")
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--review", metavar="EVENT_ID")
    parser.add_argument("--classification", choices=["expected-denial", "legitimate-needs-policy"])
    parser.add_argument("--note")
    args = parser.parse_args(argv)
    if any((args.review, args.classification, args.note)) and not (
            args.review and args.classification and args.note and args.note.strip()):
        parser.error("review requires --review, --classification and a nonempty --note")
    if args.report_only and args.review:
        parser.error("--report-only cannot review")
    if os.geteuid() != 0:
        parser.error("root required")
    try:
        config = json.loads(args.config.read_text())
        if not config["containers"]:
            raise ValueError("empty configuration")
        for name, spec in config["containers"].items():
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
                raise ValueError("invalid container name")
            if spec["mode"] not in {"complain", "enforce"} or not spec["profile"]:
                raise ValueError("invalid profile")
        directory = args.state_dir
        if not args.report_only:
            directory.mkdir(mode=0o700, exist_ok=True)
        if directory.exists() and (directory.is_symlink() or directory.stat().st_uid != 0
                                   or directory.stat().st_mode & 0o077):
            raise ValueError("state directory must be root-only")
        with contextlib.ExitStack() as stack:
            if not args.report_only:
                fd = os.open(directory / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                lock = stack.enter_context(os.fdopen(fd, "w"))
                fcntl.flock(lock, fcntl.LOCK_EX)
            state = read_state(directory)
            if args.review:
                matches = [entry for entry in state["containers"].values()
                           if args.review in entry.get("events", {})]
                if len(matches) != 1:
                    raise ValueError("unknown or ambiguous event")
                matches[0].setdefault("reviews", {})[args.review] = {
                    "classification": args.classification, "note": args.note, "time": time.time()}
            elif not args.report_only:
                state = collect(config, state, time.time())
            if not args.report_only:
                write_state(directory, state)
            reports = {}
            for name, spec in config["containers"].items():
                entry = state["containers"].get(name, {})
                report = status(entry, time.time())
                if (entry.get("profile"), entry.get("mode"), entry.get("source")) != (
                        spec["profile"], spec["mode"], spec["source"]):
                    report["ready"] = False
                    report["reasons"] = report["reasons"] + ["configuration-mismatch"]
                reports[name] = report
            print(json.dumps({"schema_version": 1, "containers": reports}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        # Never echo exception strings: commands/config/audit paths can contain secrets.
        print("AppArmor review failed; inspect root-only configuration/state", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
