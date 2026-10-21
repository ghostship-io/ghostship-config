"""Observe newsletter outcomes independently of T3 turns and newsletter timers.

The newsletter owns its due times, artifact checks and Gmail delivery ledger.
Run its read-only monitor as the newsletter user, then pass only outcome codes
to the existing host notifier/incident spool. Never forward source text or logs.
"""
import argparse
import json
import re
import subprocess
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


def reconcile(state, problem, notify):
    """Retry failed delivery; one firing and one resolution per observed episode."""
    if problem:
        # Persist the episode before sending: a crash or ntfy failure may retry
        # the same stable incident key, which the coordinator already coalesces.
        state["firing"] = True
        if not state.get("notified"):
            state["notified"] = notify("firing", problem)
    elif state.get("firing"):
        if notify("resolved", "daily runtime and last due delivery are healthy"):
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
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state))
        temporary.replace(path)

    def notify(status, message):
        save()
        command = [config["notify"], "--topic", "operations", "--source", "newsletter",
                   "--state", status, "--dedupe", "newsletter-runtime",
                   "--priority", "4" if status == "firing" else "2",
                   "--title", f"Ghostship AM runtime {status}"]
        if status == "firing":
            command.append("--incident")
        command.append(f"{message}. Inspect ghostship-am-monitor-status --runtime-only in "
                       "/workspace/ghostship-newsletter and the newsletter user service logs. "
                       "Delivery ledger records Gmail send/reconciliation, not recipient receipt.")
        try:
            return subprocess.run(command, check=False, timeout=60).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    reconcile(state, problem, notify)
    save()
    print(f"newsletter health: {problem or 'healthy'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
