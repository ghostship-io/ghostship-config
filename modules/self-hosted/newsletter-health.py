"""Observe newsletter outcomes independently of T3 turns and newsletter timers.

The newsletter owns its due times, artifact checks and Gmail delivery ledger.
Run its read-only monitor as the newsletter user, then pass only outcome codes
to the existing host notifier/incident spool. Never forward source text or logs.
"""
import argparse
import json
import os
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def observe(command, now=None):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
        now = now or datetime.now(timezone.utc)
        report = json.loads(result.stdout)
        checked = datetime.fromisoformat(report["checked_at"])
        if (result.returncode not in (0, 4) or type(report["healthy"]) is not bool
                or report["healthy"] != (result.returncode == 0)
                or report["issue_date"] != now.astimezone(ZoneInfo("Pacific/Honolulu")).date().isoformat()
                or not -60 <= (now - checked).total_seconds() <= 300
                or report["last_due_delivery"]["status"] not in ("current", "missing")
                or (report["healthy"] and report["last_due_delivery"]["status"] != "current")):
            raise ValueError("invalid outcome")
        reasons = report["unhealthy_reasons"]
        if (not isinstance(reasons, list) or bool(reasons) == report["healthy"]
                or not all(isinstance(reason, str) and re.fullmatch(r"[a-z_]{1,80}", reason)
                           for reason in reasons)):
            raise ValueError("invalid outcome codes")
        return ", ".join(sorted(set(reasons)))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return "monitor_unavailable"


def reconcile(state, problem, incident, notify, save):
    """Acknowledge the incident independently of notification delivery."""
    if not problem and not state.get("firing"):
        return
    state["firing"] = True
    state.setdefault("incident_id", uuid.uuid4().hex)
    # Persist the identity before handing anything off. A lost response retries
    # the same coordinator event ID, including after its spool file was consumed.
    save()
    if not state.get("incident_queued"):
        state["incident_queued"] = incident(
            state["incident_id"], problem or "runtime recovered after an observed failure")
        save()
    if problem:
        if state.pop("resolved", False):
            state["notified"] = False
        if not state.get("notified"):
            state["notified"] = notify("firing", problem)
    else:
        if not state.get("resolved"):
            state["resolved"] = notify("resolved", "daily runtime and last due delivery are healthy")
        if state["resolved"] and state["incident_queued"]:
            state.clear()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text())
    path = Path(config["state"])
    state = json.loads(path.read_text()) if path.exists() else {}
    problem = observe(config["command"])

    def save():
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(state, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def send(status, message, incident_id=None):
        command = [config["notify"], "--topic", "operations", "--source", "newsletter",
                   "--state", status, "--dedupe", "newsletter-runtime",
                   "--priority", "4" if status == "firing" else "2",
                   "--title", f"Ghostship AM runtime {status}"]
        if incident_id:
            command.extend(["--incident-only", "--incident-id", incident_id])
        command.append(f"{message}. Inspect ghostship-am-monitor-status --runtime-only in "
                       "/workspace/ghostship-newsletter and the newsletter user service logs. "
                       "Delivery ledger records Gmail send/reconciliation, not recipient receipt.")
        try:
            return subprocess.run(command, check=False, timeout=60).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    reconcile(state, problem, lambda event_id, message: send("firing", message, event_id), send, save)
    save()
    print(f"newsletter health: {problem or 'healthy'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
