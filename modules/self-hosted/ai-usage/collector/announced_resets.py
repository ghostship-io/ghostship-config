"""Public reset announcements: bounded Desktop checks, separate from usage truth."""
from __future__ import annotations

import argparse
import fcntl
import json
import re
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SOURCE = "https://x.com/thsottiaux"
PATH = "/var/lib/ghostship-ai-usage/announced-resets.json"
INTERVAL = 8 * 3600
POST_URL = re.compile(r"https://x\.com/thsottiaux/status/\d+$")
GLOBAL_CODEX = re.compile(
    r"\b(?:all\s+(?:paid\s+)?codex\s+(?:(?:usage|rate)\s+)?(?:limits|quotas|users|accounts)"
    r"|global\s+codex\s+reset|codex\s+(?:limits|usage|quotas)\s+(?:will\s+)?reset\s+for\s+(?:all|everyone))\b",
    re.I,
)


def load(path=PATH):
    try:
        value = json.loads(Path(path).read_text())
        if not isinstance(value, dict) or value.get("schema") != 1 or not isinstance(value.get("announcements"), list):
            raise ValueError("invalid announcement cache")
        return value
    except FileNotFoundError:
        return {"schema": 1, "status": "not_checked", "announcements": []}
    except (OSError, ValueError):
        return {"schema": 1, "status": "unavailable", "announcements": []}


def parse(post):
    """Accept only an explicit global Codex reset with an unambiguous PT time.

    Hints and banked/manual resets remain visible at low confidence. They
    cannot change pacing. No page prose is retained in runtime projections.
    """
    url = str(post.get("url", ""))
    text = str(post.get("text", ""))[:8000]
    if not POST_URL.fullmatch(url) or not re.search(r"\breset\b", text, re.I):
        return None
    result = {"source_url": url, "scope": "unknown", "reset_at": None,
              "confidence": "low", "reason": "ambiguous_announcement"}
    if (not GLOBAL_CODEX.search(text)
            or re.search(r"\b(banked|manual|before|by|maybe|might|not|no)\b|\?", text, re.I)):
        return result
    result["scope"] = "codex"
    clock = re.search(r"\b(1[0-2]|[1-9])(?::([0-5]\d))?\s*(am|pm)\s*(PT|PDT|PST)\b", text, re.I)
    day = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    try:
        if day:
            date = datetime.strptime(day[1], "%Y-%m-%d").date()
        else:
            published = datetime.fromisoformat(post["published_at"].replace("Z", "+00:00"))
            if published.tzinfo is None:
                return result
            date = published.astimezone(ZoneInfo("America/Los_Angeles")).date()
            if re.search(r"\btomorrow\b", text, re.I):
                date += timedelta(days=1)
            elif not re.search(r"\btoday\b", text, re.I):
                return result
        if not clock:
            return result
        hour = int(clock[1]) % 12 + (12 if clock[3].lower() == "pm" else 0)
        zone = ZoneInfo("America/Los_Angeles")
        at = datetime.combine(date, datetime.min.time(), zone).replace(hour=hour, minute=int(clock[2] or 0))
        # PT follows local daylight saving. Explicit PST/PDT must agree.
        if clock[4].upper() != "PT" and clock[4].upper() != at.tzname():
            return result
        if at.fold or at.replace(fold=1).utcoffset() != at.utcoffset():
            return result
        result.update(reset_at=at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                      confidence="high", reason="explicit_global_reset")
    except (KeyError, ValueError, TypeError):
        pass
    return result


def overrides(results, document, now):
    """Resolve scope against actual quota IDs, then reuse custom-reset application."""
    active = []
    for entry in document.get("announcements", []):
        if (entry.get("confidence") != "high" or entry.get("scope") != "codex"
                or not POST_URL.fullmatch(str(entry.get("source_url", "")))):
            continue
        try:
            reset = datetime.fromisoformat(entry["reset_at"].replace("Z", "+00:00")).timestamp()
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
        if now < reset <= now + 7 * 86400:
            active.append((reset, entry))
    if not active:
        return []
    reset, entry = min(active, key=lambda pair: pair[0])
    return [{"provider": "codex", "quota_id": window["quotaId"],
             "model": str(window.get("model") or "*"), "reset_at": entry["reset_at"],
             "reset_source": "announced", "source_url": entry["source_url"]}
            for result in results for window in result.windows
            if window.get("provider") == "codex" and window.get("quotaId")
            and (not isinstance(window.get("resetEpoch"), (int, float))
                 or window["resetEpoch"] > reset)]


EXTRACT = r"""(() => ({
 blocked: /log in or sign up|sign in to|captcha|verify you are human/i.test(document.body.innerText),
 posts: [...document.querySelectorAll('article')].slice(0, 20).map(a => ({
   text: a.querySelector('[data-testid="tweetText"]')?.innerText || '',
   url: a.querySelector('a:has(time)')?.href || '',
   published_at: a.querySelector('time')?.dateTime || ''
 }))
}))()"""


def check(document, call, now):
    """One lease, no wall bypass, no independent HTTP fetches or search mirrors."""
    if now - document.get("checked_at", 0) < INTERVAL:
        return document
    updated = {**document, "schema": 1, "checked_at": now, "source_url": SOURCE}
    window = None
    try:
        window = call("browser.window", action="open")["window_id"]
        page = call("browser.op", window_id=window, steps=[
            {"action": "navigate", "url": SOURCE},
            {"action": "wait", "timeout": 15, "condition": {"js":
                "!!document.querySelector('article') || /log in or sign up|sign in to|captcha|verify you are human/i.test(document.body.innerText)"}},
            {"action": "extract", "name": "announcements", "js": EXTRACT},
        ])["extracts"]["announcements"]
        if page["blocked"]:
            updated["status"] = "blocked"
            return updated
        records = {entry["source_url"]: entry for entry in document["announcements"]}
        for post in page["posts"]:
            entry = parse(post)
            if entry:
                records[entry["source_url"]] = {**entry, "observed_at": now}
        updated.update(status="ok", announcements=list(records.values())[-100:])
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        updated["status"] = "unavailable"
    finally:
        if window:
            try:
                call("browser.window", action="close", window_id=window)
            except (OSError, ValueError, KeyError, subprocess.SubprocessError):
                updated["status"] = "unavailable"
    return updated


def cli_call(prefix, operation, **kwargs):
    command = [*prefix, operation, "--identity", "agent", "--json",
               "--idempotency-key", str(uuid.uuid4())]
    for key, value in kwargs.items():
        command += ["--" + key.replace("_", "-"), json.dumps(value) if isinstance(value, list) else value]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90, check=True)
    envelope = json.loads(result.stdout)
    # A pending job is not page evidence. Finish it before extracting anything.
    for _ in range(3):
        if envelope.get("outcome") != "running":
            break
        pending = subprocess.run([*prefix, "runtime.job_status", "--job-id", envelope["job_id"],
                                  "--wait-s", "45", "--json"],
                                 capture_output=True, text=True, timeout=60, check=True)
        envelope = json.loads(pending.stdout)
        envelope = envelope.get("data", {}).get("result") or envelope
    if envelope.get("outcome") != "success":
        raise ValueError("desktop unavailable")
    return envelope["data"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=PATH)
    parser.add_argument("command", nargs="+", help="Desktop capability CLI and optional command prefix")
    args = parser.parse_args()
    path = Path(args.output)
    def save(document):
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(document) + "\n")
        temporary.replace(path)
    with Path(str(path) + ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        document = load(path)
        now = time.time()
        if now - document.get("checked_at", 0) >= INTERVAL:
            # Reserve the check durably before browsing: a crash must not
            # turn service retries into repeated checks of the public site.
            save({**document, "checked_at": now, "status": "checking", "source_url": SOURCE})
            document = check(document, lambda op, **kw: cli_call(args.command, op, **kw), now)
            save(document)
    print(document["status"])


if __name__ == "__main__":
    main()
