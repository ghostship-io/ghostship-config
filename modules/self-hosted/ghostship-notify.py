"""Publish one Ghostship notification to ntfy.

Topics are security, operations and informational. Priority 5 means act now,
4 an actionable threat or failure, 3 attention today, 2 informational (the
default, silent on the phone) and 1 digest. The first two tags are the source
and the state; --dedupe suppresses a repeat of the same key and state for an
hour, while a state change always publishes. --incident also queues a firing
alert for the GitHub coordinator, which starts a bounded T3 repair thread; it is
queued even when ntfy is down.

--incident-only --incident-id ID acknowledges only a durable spool write, without
publishing to ntfy. Retrying the same ID preserves the coordinator event identity,
even if the coordinator already consumed the file. Keep the ID across retries;
use a new one for a later episode.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

TOPICS = ("security", "operations", "informational")
DEDUPE_WINDOW = 3600
STATE_DIR = Path(os.environ.get("GHOSTSHIP_NOTIFY_STATE", "/var/lib/ghostship-notify"))
SECRETS = os.environ.get("GHOSTSHIP_NOTIFY_SECRETS", "@secrets@")
INCIDENTS = os.environ.get("GHOSTSHIP_NOTIFY_INCIDENTS", "@incidents@")


def password() -> str:
    for line in Path(SECRETS).read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "NTFY_PUBLISH_PASSWORD":
            return value.strip().strip("'\"")
    raise SystemExit("ghostship-notify: NTFY_PUBLISH_PASSWORD missing from the monitoring projection")


def server() -> str:
    if os.environ.get("GHOSTSHIP_NOTIFY_URL"):
        return os.environ["GHOSTSHIP_NOTIFY_URL"].rstrip("/")
    podman = ["@podman@"]
    if os.environ.get("CONTAINER_HOST"):
        podman.append("--remote")
    address = subprocess.run(
        [*podman, "inspect", "ntfy", "--format",
         '{{(index .NetworkSettings.Networks "ghostship_net").IPAddress}}'],
        capture_output=True, text=True, check=True, timeout=15).stdout.strip()
    return f"http://{address}:8080"


def _state_path(key: str) -> Path:
    return STATE_DIR / (hashlib.sha256(key.encode()).hexdigest() + ".json")


def duplicate(key: str, state: str) -> bool:
    """True when this key last published the same state within the window."""
    try:
        last = json.loads(_state_path(key).read_text())
    except (OSError, ValueError):
        return False
    return last.get("state") == state and time.time() - last.get("at", 0) < DEDUPE_WINDOW


def record(key: str, state: str) -> None:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = _state_path(key)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"state": state, "at": time.time()}))
    temporary.replace(path)


def queue_incident(key: str, title: str, message: str, incident_id: str | None = None) -> bool:
    """Hand a firing alert to the coordinator's incident spool, if this host has one."""
    if not INCIDENTS or not Path(INCIDENTS).is_dir():
        return False
    now = time.time()
    name = (f"incident-{hashlib.sha256(incident_id.encode()).hexdigest()}" if incident_id
            else f"{int(now * 1000)}-{hashlib.sha256(key.encode()).hexdigest()[:12]}")
    fd, temporary = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=INCIDENTS)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o640)
            json.dump({"key": key, "title": title, "message": message,
                       "host": os.uname().nodename, "at": now}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, Path(INCIDENTS) / f"{name}.json")
        directory = os.open(INCIDENTS, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ghostship-notify", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--topic", choices=TOPICS, required=True)
    parser.add_argument("--priority", type=int, choices=range(1, 6), default=2)
    parser.add_argument("--title", required=True)
    parser.add_argument("--source", required=True, help="stable subsystem name, e.g. apparmor")
    parser.add_argument("--state", choices=("firing", "resolved"), default="firing")
    parser.add_argument("--tags", default="", help="comma-separated extra tags")
    parser.add_argument("--dedupe", help="suppress a repeat of this key and state for an hour")
    incident_mode = parser.add_mutually_exclusive_group()
    incident_mode.add_argument("--incident", action="store_true",
                        help="also start a T3 repair thread for a firing alert")
    incident_mode.add_argument("--incident-only", action="store_true",
                              help="queue only; exit zero only after the incident spool write is durable")
    parser.add_argument("--incident-id", help="stable event ID for retries of --incident-only")
    parser.add_argument("--click", help="https URL opened when the notification is tapped")
    parser.add_argument("message", nargs="*", help="message text; read from stdin when omitted")
    args = parser.parse_args(argv)
    message = " ".join(args.message) if args.message else sys.stdin.read()
    if args.incident_only:
        if not args.incident_id or args.state != "firing":
            parser.error("--incident-only requires --incident-id and a firing state")
        try:
            if queue_incident(args.dedupe or args.title, args.title, message[:4000], args.incident_id):
                return 0
            print("ghostship-notify: incident spool is unavailable", file=sys.stderr)
        except OSError as exc:
            print(f"ghostship-notify: queueing the incident failed: {exc}", file=sys.stderr)
        return 1
    if args.incident_id:
        parser.error("--incident-id requires --incident-only")
    key = f"{args.topic}:{args.dedupe}" if args.dedupe else None
    if key and duplicate(key, args.state):
        return 0
    if args.click and not args.click.startswith("https://"):
        parser.error("--click must be an https URL")
    if args.incident and args.state == "firing":
        try:
            queue_incident(args.dedupe or args.title, args.title, message[:4000])
        except OSError as exc:
            print(f"ghostship-notify: queueing the incident failed: {exc}", file=sys.stderr)
    tags = [args.source, args.state, *(t.strip() for t in args.tags.split(",") if t.strip())]
    payload = {"topic": args.topic, "title": args.title[:250], "message": message[:4000] or args.title,
               "priority": args.priority, "tags": tags}
    if args.click:
        payload["click"] = args.click
    body = json.dumps(payload).encode()
    credential = base64.b64encode(f"publisher:{password()}".encode()).decode()
    request = urllib.request.Request(server(), data=body, method="POST", headers={
        "Authorization": f"Basic {credential}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15):
            pass
    except (urllib.error.URLError, OSError) as exc:
        print(f"ghostship-notify: publish to {args.topic} failed: {exc}", file=sys.stderr)
        return 1
    if key:
        record(key, args.state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
