#!/usr/bin/env python3
"""Collect private AppArmor evidence; stdout contains counts/status only.

State schema v1: evidence.json holds containers, samples, events and reviews.
Review with --review EVENT_ID --classification expected-denial|legitimate-needs-policy
--note TEXT. IDs are returned by the status report. Reviews never change policy.
"""
import argparse
from collections import Counter
import contextlib
import fcntl
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

DAY = 86400
# expected-denial: investigated and must stay disallowed. resolved-by-policy:
# legitimate and covered by a deployed policy change, cited as a PR reference.
CLEARED = {"expected-denial", "resolved-by-policy"}
MATCH_FIELDS = ("profile", "apparmor", "operation", "name", "name2", "requested_mask",
                "denied_mask", "comm", "peer", "family", "sock_type", "capname")
MAX_GAP = 26 * 3600
HEARTBEAT_PATH = "/proc/sys/kernel/random/boot_id"
FIELDS = re.compile(r'(\w+)=(?:"([^"\n]*)"|(\S+))')
AUDIT_LOSS = re.compile(
    r"audit_lost=[1-9][0-9]*|audit.*(?:backlog limit exceeded|rate limit exceeded)|"
    r"kauditd.*(?:suppressed|overflow)|(?:Suppressed|Dropped) [1-9][0-9]* messages|"
    r"(?:audit|apparmor)\S*: [1-9][0-9]* (?:callbacks|messages) suppressed", re.I)
# Evidence comes from VictoriaLogs (the SIEM store), filtered per profile on the
# server. The journal keeps only hours at audit flood rates, so a day-old
# continuity anchor was always rotated away, and reading a day of journal JSON
# took 9 GB. The heartbeat proves the full kernel -> journald -> Vector ->
# VictoriaLogs path for each container.
VICTORIALOGS = "http://127.0.0.1:9428"
JOURNAL_TIMEOUT = 600
HEARTBEAT_WAIT = 30
LOSS_QUERY = ('("audit_lost" OR "backlog limit exceeded" OR "rate limit exceeded" '
              'OR "suppressed" OR "overflow" OR "Dropped")')


def run(args, timeout=20):
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, timeout=timeout).stdout


def iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def vlogs(query, start, end, timeout=JOURNAL_TIMEOUT):
    """(epoch, message) rows from VictoriaLogs for [start, end]."""
    body = urllib.parse.urlencode({
        "query": f"_time:[{iso(start)}, {iso(end)}] {query} | fields _time, _msg"}).encode()
    request = urllib.request.Request(f"{VICTORIALOGS}/select/logsql/query", data=body, method="POST")
    rows = []
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for line in response:
            if not line.strip():
                continue
            row = json.loads(line)
            stamp = datetime.fromisoformat(row["_time"].replace("Z", "+00:00")).timestamp()
            if start <= stamp <= end:
                rows.append((stamp, row.get("_msg", "")))
    return rows


def profile_filter(profile):
    """The profile and its children; profile names are [A-Za-z0-9_-] (app registry)."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", profile):
        raise ValueError(f"unexpected profile name {profile!r}")
    return f'transport:="audit" (aa_profile:="{profile}" OR aa_profile:"{profile}//"*)'


def journal(start, end, profile=None):
    """AppArmor records for one profile (and its children), plus loss notices."""
    query = profile_filter(profile) if profile else 'transport:="audit" apparmor:*'
    return sorted(vlogs(query, start, end) + vlogs(LOSS_QUERY, start, end))


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
        "error", "info", "comm", "pid", "family", "sock_type", "protocol", "capname", "peer"
    ) if key in fields}
    identity = json.dumps([stamp, detail], sort_keys=True).encode()
    return {"id": hashlib.sha256(identity).hexdigest()[:24], "time": stamp, **detail}


def heartbeat_event(event):
    return (event.get("apparmor") in {"AUDIT", "ALLOWED"}
            and event.get("operation") == "open"
            and event.get("name") == HEARTBEAT_PATH
            and event.get("requested_mask") == "r"
            and event.get("denied_mask", "") in {"", "r"})


def policy_hash(source):
    """The profile file's own content. Includes are embedded by store path."""
    return hashlib.sha256(Path(source).read_bytes()).hexdigest()


def inspect_container(name, config):
    """Never request Config/Env or command arguments from podman."""
    result = {"healthy": False, "reasons": [], "profile": config["profile"], "mode": config["mode"], "source": config["source"]}
    try:
        result["policy_hash"] = policy_hash(config["source"])
        result["boot_id"] = Path(HEARTBEAT_PATH).read_text().strip()
        enabled = Path("/sys/module/apparmor/parameters/enabled").read_text().strip() == "Y"
        profiles = Path("/sys/kernel/security/apparmor/profiles").read_text().splitlines()
        result["enabled"] = enabled
        # A mixed policy enforces some domains; the rest keep the policy mode.
        modes = config.get("processModes", {})
        expected = {f'{label} ({modes.get(label, config["mode"])})'
                    for label in config.get("processProfiles", [config["profile"]])}
        required = {f'{label} ({modes.get(label, config["mode"])})'
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
        result["processes"] = []
        for pid in pids:
            try:
                label = Path(f"/proc/{pid}/attr/current").read_text().strip()
            except (FileNotFoundError, ProcessLookupError):
                continue  # exited between `podman top` and the read (cron, healthchecks)
            result["processes"].append({"pid": pid, "label": label})
        if not result["processes"]:
            raise ValueError("no container processes")
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


def heartbeat_command(name, spec):
    """Argv that reads HEARTBEAT_PATH inside the container; images without cat
    configure their own reader. "@entrypoint" names the image's entrypoint."""
    command = spec.get("heartbeat") or ["/bin/cat", HEARTBEAT_PATH]
    if "@entrypoint" in command:
        entrypoint = run(["podman", "inspect", "--format", "{{index .Config.Entrypoint 0}}", name]).strip()
        command = [entrypoint if part == "@entrypoint" else part for part in command]
    return command


def probe(name, profile, command):
    start = time.time()
    try:
        # Discard output and status; only the exact audit event proves the pipeline works.
        subprocess.run(["podman", "exec", name, *command],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=2)
        # Ingestion through Vector takes seconds; the event must reach the store.
        deadline = time.monotonic() + HEARTBEAT_WAIT
        query = profile_filter(profile) + f' aa_name:="{HEARTBEAT_PATH}"'
        while time.monotonic() < deadline:
            for stamp, message in vlogs(query, start, time.time() + 1, timeout=10):
                event = parse_event(stamp, message, profile)
                if event and heartbeat_event(event):
                    return event
            time.sleep(1)
        return None
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None


def advance(previous, observation, events, now, audit_ok):
    """Pure coverage transition, intentionally conservative after interruptions."""
    state = dict(previous or {})
    old_sample = state.get("last_sample")
    # The source path names the combined apparmor.d tree, which changes whenever
    # any profile does; identity is this profile's content hash instead.
    changed = (state.get("policy_hash"), state.get("image"), state.get("profile"), state.get("mode")) != (
        observation.get("policy_hash"), observation.get("image"), observation.get("profile"), observation.get("mode"))
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


def status(state, now, *, include_event_ids=True):
    baseline = state.get("coverage_start")
    reviews = state.get("reviews", {})
    blocking = (eid for eid in state.get("events", {})
                if reviews.get(eid, {}).get("classification") not in CLEARED)
    if include_event_ids:
        blocking = list(blocking)
        blocking_count = len(blocking)
    else:
        blocking_count = sum(1 for _ in blocking)
    samples = state.get("samples", [])
    # UTC-day buckets tolerate timer jitter. Elapsed time is checked separately:
    # eight calendar dates alone never substitute for seven full days.
    verified = {int(stamp // DAY) for stamp in samples}
    fresh = 0 <= now - state.get("last_sample", 0) <= MAX_GAP
    elapsed = max(0, state.get("last_sample", 0) - baseline) if baseline is not None else 0
    report = {"ready": bool(fresh and baseline is not None and elapsed >= 7 * DAY
                          and len(verified) >= 8 and not blocking_count and not state.get("reasons")),
            "coverage_days": elapsed / DAY, "verified_daily_samples": len(verified),
            "last_sample": state.get("last_sample"), "coverage_start": baseline,
            "last_policy_change": state.get("last_policy_change"),
            "fresh": fresh, "blocking_event_count": blocking_count,
            "event_count": len(state.get("events", {})), "reasons": state.get("reasons", [])}
    if include_event_ids:
        report["blocking_event_ids"] = blocking
    return report


def collect(config, previous, now):
    result = {"schema_version": 1, "containers": {}}
    prior = previous.get("containers", {})
    pending = []
    for name, spec in config["containers"].items():
        old = prior.get(name, {})
        observation = inspect_container(name, spec)
        heartbeat = None
        if observation["healthy"]:
            try:
                heartbeat = probe(name, spec["profile"], heartbeat_command(name, spec))
            except (OSError, subprocess.SubprocessError):
                heartbeat = None
        observation["heartbeat"] = heartbeat is not None
        end = time.time()
        # Include the probe window; next sample starts at the exact same boundary.
        start = old.get("last_sample", now - DAY)
        anchor = old.get("audit_anchor")
        if anchor:
            # Retain the previous heartbeat as a journal continuity anchor. Rotation
            # past it cannot silently turn a missing interval into a clean day.
            start = min(start, anchor["time"])
        pending.append((name, spec, old, observation, heartbeat, anchor, start, end))
    for name, spec, old, observation, heartbeat, anchor, start, end in pending:
        audit_ok, events = False, []
        try:
            window = journal(start, end, spec["profile"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"apparmor review: {name}: evidence query failed: {exc}", file=sys.stderr)
            window = None
        if window is not None:
            try:
                loss_seen = any(AUDIT_LOSS.search(message) for _, message in window)
                events = [event for stamp, message in window
                          if (event := parse_event(stamp, message, spec["profile"]))]
                observed_ids = {event["id"] for event in events}
                intentional_ids = {item["id"] for item in (anchor, heartbeat) if item}
                audit_ok = intentional_ids <= observed_ids and not loss_seen
                events = [event for event in events if event["id"] not in intentional_ids]
            except (ValueError, KeyError, TypeError):
                audit_ok, events = False, []
        entry = advance(old, observation, events, end, audit_ok)
        entry["audit_anchor"] = ({"id": heartbeat["id"], "time": heartbeat["time"]}
                                 if heartbeat else None)
        result["containers"][name] = entry
    return result


def comm_text(value):
    """The kernel hex-encodes comm values containing spaces."""
    if value and re.fullmatch(r"(?:[0-9A-F]{2})+", value):
        try:
            return bytes.fromhex(value).decode()
        except UnicodeDecodeError:
            return value
    return value


def event_matches(event, patterns):
    for key, pattern in patterns.items():
        values = {event.get(key, "")}
        if key == "comm":
            values.add(comm_text(event.get("comm", "")))
        if not any(fnmatch.fnmatchcase(value, pattern) for value in values):
            return False
    return True


def summarize(entry):
    """Unreviewed events grouped by their kept fields; digits are normalized."""
    reviews = entry.get("reviews", {})
    groups = {}
    for eid, event in entry.get("events", {}).items():
        if reviews.get(eid, {}).get("classification") in CLEARED:
            continue
        key = tuple((field, re.sub(r"[0-9]+", "N", comm_text(event[field]) if field == "comm" else event[field]))
                    for field in MATCH_FIELDS if field in event)
        group = groups.setdefault(key, {"count": 0, "first": event["time"], "last": event["time"]})
        group["count"] += 1
        group["first"], group["last"] = min(group["first"], event["time"]), max(group["last"], event["time"])
    return sorted(({**dict(key), **value} for key, value in groups.items()), key=lambda g: -g["count"])


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
    parser.add_argument("--brief", action="store_true",
                        help="aggregate status counts without container names or event IDs; collection is unchanged")
    parser.add_argument("--review", metavar="EVENT_ID")
    parser.add_argument("--classification",
                        choices=["expected-denial", "legitimate-needs-policy", "resolved-by-policy"])
    parser.add_argument("--note")
    parser.add_argument("--container", help="review every event of this container matching --match")
    parser.add_argument("--match", action="append", default=[], metavar="FIELD=GLOB")
    parser.add_argument("--summary", action="store_true", help="group unreviewed events; read-only")
    args = parser.parse_args(argv)
    if args.brief and args.summary:
        parser.error("--brief and --summary are different output formats")
    selected = bool(args.review) + bool(args.container)
    if selected > 1 or (args.match and not args.container):
        parser.error("use either --review EVENT_ID or --container NAME with --match")
    if any((args.review, args.container, args.classification, args.note)) and not (
            selected and args.classification and args.note and args.note.strip()):
        parser.error("review requires an event selection, --classification and a nonempty --note")
    patterns = {}
    for item in args.match:
        field, separator, pattern = item.partition("=")
        if not separator or field not in MATCH_FIELDS or field in patterns or not pattern:
            parser.error("--match takes one FIELD=GLOB per kept field")
        patterns[field] = pattern
    if args.container and not {"profile", "operation"} <= patterns.keys():
        parser.error("group review needs at least profile and operation matches")
    if args.classification == "resolved-by-policy" and not re.search(r"#[0-9]+", args.note or ""):
        parser.error("resolved-by-policy notes must cite the policy PR as #N")
    if (args.report_only or args.summary) and selected:
        parser.error("--report-only and --summary cannot review")
    args.report_only = args.report_only or args.summary
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
            elif args.container:
                entry = state["containers"].get(args.container)
                if entry is None:
                    raise ValueError("unknown container")
                chosen = [eid for eid, event in entry.get("events", {}).items()
                          if event_matches(event, patterns)]
                if not chosen:
                    raise ValueError("no matching events")
                stamp = time.time()
                for eid in chosen:
                    entry.setdefault("reviews", {})[eid] = {
                        "classification": args.classification, "note": args.note,
                        "match": patterns, "time": stamp}
                print(json.dumps({"reviewed": len(chosen)}), file=sys.stderr)
            elif not args.report_only:
                state = collect(config, state, time.time())
            if not args.report_only:
                write_state(directory, state)
            reports = {}
            for name, spec in config["containers"].items():
                entry = state["containers"].get(name, {})
                report = status(entry, time.time(), include_event_ids=not args.brief)
                try:
                    configured_hash = policy_hash(spec["source"])
                except OSError:
                    configured_hash = None
                if (entry.get("profile"), entry.get("mode"), entry.get("policy_hash")) != (
                        spec["profile"], spec["mode"], configured_hash):
                    report["ready"] = False
                    report["reasons"] = report["reasons"] + ["configuration-mismatch"]
                reports[name] = report
            if args.summary:
                print(json.dumps({"schema_version": 1, "groups": {
                    name: summarize(state["containers"].get(name, {})) for name in config["containers"]}}))
                return 0
            if args.brief:
                values = list(reports.values())
                output = {"schema_version": 1, "profiles": len(values),
                          "ready": sum(r["ready"] for r in values),
                          "fresh": sum(r["fresh"] for r in values),
                          "coverage_days_min": min(r["coverage_days"] for r in values),
                          "coverage_days_max": max(r["coverage_days"] for r in values),
                          "blocking_event_count": sum(r["blocking_event_count"] for r in values),
                          "reason_counts": dict(Counter(reason for r in values for reason in set(r["reasons"])))}
            else:
                output = {"schema_version": 1, "containers": reports}
            print(json.dumps(output, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        # Never echo exception strings: commands/config/audit paths can contain secrets.
        print("AppArmor review failed; inspect root-only configuration/state", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
