"""Public reset announcements: bounded Desktop checks, separate from usage truth."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SOURCE = "https://x.com/thsottiaux"
RELAY = "https://community.openai.com/search?q=reset%20%23announcements%20order%3Alatest"
PATH = "/var/lib/ghostship-ai-usage/announced-resets.json"
INTERVAL = 8 * 3600
POST_URL = re.compile(r"https://x\.com/thsottiaux/status/\d+$")
TOPIC_URL = re.compile(r"https://community\.openai\.com/t/[a-zA-Z0-9_-]+/\d+(?:/\d+)?(?:#announcement-\d+)?$")
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
        primary = POST_URL.fullmatch(str(entry.get("source_url", "")))
        confirmed = (entry.get("confidence") == "confirmed"
                     and TOPIC_URL.fullmatch(str(entry.get("source_url", "")))
                     and POST_URL.fullmatch(str(entry.get("primary_source_url", ""))))
        if (entry.get("scope") != "codex"
                or not ((entry.get("confidence") in {"high", "confirmed"} and primary) or confirmed)):
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


def confirm(document, source_url, reset_at, now):
    """An operator confirms a recorded relay and supplies its explicit reset time."""
    try:
        reset = datetime.fromisoformat(reset_at.replace("Z", "+00:00"))
        if reset.tzinfo is None or not now < reset.timestamp() <= now + 7 * 86400:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError("confirmation needs a future timezone-qualified reset within seven days") from None
    record = next((entry for entry in document.get("announcements", [])
                   if entry.get("source_url") == source_url), None)
    if (not record or not (POST_URL.fullmatch(source_url) or (TOPIC_URL.fullmatch(source_url)
            and POST_URL.fullmatch(str(record.get("primary_source_url", "")))))):
        raise ValueError("confirmation must identify a recorded announcement")
    record.update(confidence="confirmed", scope="codex", reason="operator_confirmed", confirmed_at=now,
                  reset_at=reset.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"))
    return document


def samples(document):
    """Public, bounded evidence rows for the dashboard, including unverified items."""
    from metrics import ExactLabel
    for entry in document.get("announcements", [])[-100:]:
        url = str(entry.get("source_url", ""))
        if len(url) > 512 or not (POST_URL.fullmatch(url) or TOPIC_URL.fullmatch(url)):
            continue
        confidence = entry.get("confidence")
        if confidence not in {"low", "high", "confirmed"}:
            continue
        reset_at = "time needs confirmation"
        try:
            reset = datetime.fromisoformat(entry["reset_at"].replace("Z", "+00:00"))
            if reset.tzinfo is not None:
                reset_at = reset.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except (KeyError, ValueError, TypeError, AttributeError):
            pass
        yield "ghostship_ai_announced_reset_info", {
            "source_url": ExactLabel(url), "confidence": confidence,
            "label": ExactLabel("announced (unverified)" if confidence == "low" else "announced reset"),
            "scope": "codex" if entry.get("scope") == "codex" else "unknown",
            "reset_at": ExactLabel(reset_at),
        }, 1.0


def notify_pending(document, command, now):
    """Retry failed notices; persist success and let the publisher dedupe crash retries."""
    attempts = 0
    for entry in reversed(document.get("announcements", [])[-100:]):
        url = str(entry.get("source_url", ""))
        if entry.get("confidence") != "low" or entry.get("notice_sent_at"):
            continue
        if not (POST_URL.fullmatch(url) or TOPIC_URL.fullmatch(url)):
            continue
        if attempts >= 3:
            break
        attempts += 1
        key = "codex-reset-" + hashlib.sha256(url.encode()).hexdigest()[:24]
        try:
            result = subprocess.run([command, "--topic", "operations", "--priority", "3",
                "--source", "ai-usage", "--dedupe", key,
                "--title", "Codex reset announcement needs confirmation",
                "announced (unverified)\n" + url + "\nConfirm the global Codex scope and reset time before pacing changes."],
                check=False, timeout=30, capture_output=True)
            if result.returncode == 0:
                entry["notice_sent_at"] = now
        except (OSError, subprocess.TimeoutExpired):
            pass
    return document


EXTRACT = r"""(() => ({
 blocked: /log in or sign up|sign in to|captcha|verify you are human/i.test(document.body.innerText),
 posts: [...document.querySelectorAll('article')].slice(0, 20).map(a => ({
   text: a.querySelector('[data-testid="tweetText"]')?.innerText || '',
   url: a.querySelector('a:has(time)')?.href || '',
   published_at: a.querySelector('time')?.dateTime || ''
 }))
}))()"""

RELAY_EXTRACT = r"""(() => ({
 blocked: /sign in to continue|log in to continue|captcha|verify you are human/i.test(document.body.innerText),
 posts: [...document.querySelectorAll('.cooked a[href*="x.com/thsottiaux/status/"]')].slice(-40).map(a => ({
   text: (a.closest('.cooked')?.innerText || a.innerText || '').slice(0, 3000),
   url: a.href.split('?')[0],
   published_at: ''
 }))
}))()"""


SEARCH_EXTRACT = r"""(() => ({
 blocked: /sign in to continue|log in to continue|captcha|verify you are human/i.test(document.body.innerText),
 topics: [...document.querySelectorAll('.fps-result')].map(row => ({
   title: row.querySelector('a.search-link')?.innerText || '',
   url: row.querySelector('a.search-link')?.href || ''
 })).filter(row => /\breset\b/i.test(row.title)).slice(0, 3).map(row => row.url.split('?')[0].split('#')[0])
}))()"""


def check(document, call, now):
    """One lease, three relay topics at most, and no wall bypass or HTTP mirrors."""
    if now - document.get("checked_at", 0) < INTERVAL:
        return document
    updated = {**document, "schema": 1, "checked_at": now, "source_url": SOURCE,
               "identity": "personal", "sources": []}
    records = {entry["source_url"]: dict(entry) for entry in document["announcements"]}
    window = None

    def read(url, selector, extract):
        state = {"source_url": url, "status": "unavailable"}
        updated["sources"].append(state)
        page = call("browser.op", window_id=window, steps=[
            {"action": "navigate", "url": url},
            {"action": "wait", "timeout": 15, "condition": {"js":
                "!!document.querySelector(" + json.dumps(selector) + ") || /log in or sign up|sign in to|log in to continue|captcha|verify you are human/i.test(document.body.innerText)"}},
            {"action": "extract", "name": "announcements", "js": extract},
        ])["extracts"]["announcements"]
        state["status"] = "blocked" if page["blocked"] else "ok"
        return page

    def remember(entry):
        previous = records.get(entry["source_url"], {})
        # A later scrape must not revoke an explicit operator confirmation
        # or cause a previously acknowledged item to push another notice.
        if previous.get("confidence") == "confirmed":
            entry.update({key: previous[key] for key in
                          ("confidence", "scope", "reason", "confirmed_at", "reset_at")})
        if previous.get("notice_sent_at"):
            entry["notice_sent_at"] = previous["notice_sent_at"]
        records[entry["source_url"]] = {**entry, "observed_at": now}

    try:
        window = call("browser.window", action="open")["window_id"]
        page = read(SOURCE, 'article', EXTRACT)
        for post in [] if page["blocked"] else page["posts"]:
            entry = parse(post)
            if entry:
                remember(entry)
        updated["status"] = "blocked" if page["blocked"] else "ok"
        if page["blocked"]:
            search = read(RELAY, '.fps-result', SEARCH_EXTRACT)
            if not search["blocked"]:
                updated["status"] = "partial"
                topics = dict.fromkeys(url for url in search.get("topics", [])
                                       if TOPIC_URL.fullmatch(str(url)) and "#" not in str(url))
                for url in list(topics)[:3]:
                    try:
                        relay = read(url, '.cooked', RELAY_EXTRACT)
                        for post in [] if relay["blocked"] else relay["posts"]:
                            entry = parse(post)
                            if entry:
                                entry.update(primary_source_url=entry["source_url"],
                                    source_url=url + "#announcement-" + entry["source_url"].rsplit('/', 1)[-1],
                                    confidence="low", reason="community_relay")
                                remember(entry)
                    except (OSError, ValueError, KeyError, TypeError):
                        continue
    except (OSError, ValueError, KeyError, TypeError):
        updated["status"] = "unavailable"
    finally:
        updated["announcements"] = list(records.values())[-100:]
        if window:
            try:
                call("browser.window", action="close", window_id=window)
            except (OSError, ValueError, KeyError):
                updated["status"] = "unavailable"
    return updated


async def mcp_call(session, operation, kwargs):
    result = await session.call_tool(operation.replace('.', '_'), {
        "identity": "personal", "idempotency_key": str(uuid.uuid4()), **kwargs})
    envelope = result.structuredContent
    if envelope is None:
        envelope = json.loads(next(block.text for block in result.content if block.type == "text"))
    for _ in range(3):
        if envelope.get("outcome") != "running":
            break
        pending = await session.call_tool("jobs", {"op": "status", "job_id": envelope["job_id"], "wait_s": 45})
        envelope = pending.structuredContent
        if envelope is None:
            envelope = json.loads(next(block.text for block in pending.content if block.type == "text"))
        envelope = envelope.get("data", {}).get("result") or envelope
    # Runtime wrappers can enclose the actual browser outcome. An outer
    # success with inner unavailable is not a working Desktop connection.
    if isinstance(envelope.get("data"), dict) and "outcome" in envelope["data"]:
        envelope = envelope["data"]
    if envelope.get("outcome") != "success":
        raise ValueError("desktop unavailable")
    return envelope["data"]


def desktop_check(document, command, now):
    # One persistent session uses the deployed backend's Desktop settings and
    # lease owner. No SSH credentials are copied into T3 or this service.
    import anyio
    from anyio.from_thread import start_blocking_portal
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def connect(*, task_status):
        async with stdio_client(StdioServerParameters(command=command[0], args=command[1:])) as streams:
            async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=90)) as session:
                await session.initialize()
                task_status.started(session)
                await anyio.sleep_forever()

    try:
        with start_blocking_portal() as portal:
            future, session = portal.start_task(connect)
            try:
                def call(op, **kwargs):
                    try:
                        return portal.call(mcp_call, session, op, kwargs)
                    except Exception:
                        raise ValueError("desktop unavailable") from None
                return check(document, call, now)
            finally:
                future.cancel()
    except Exception:
        return {**document, "checked_at": now, "identity": "personal", "status": "unavailable"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=PATH)
    parser.add_argument("--notify-command", help="Host notification publisher")
    parser.add_argument("--confirm", metavar="SOURCE_URL", help="Confirm a recorded announcement for global Codex limits (root only)")
    parser.add_argument("--reset-at", help="Confirmed future reset, with an explicit timezone")
    parser.add_argument("command", nargs="*", help="Deployed MCP stdio connection command")
    args = parser.parse_args()
    if args.confirm and (os.geteuid() != 0 or not args.reset_at):
        parser.error("confirmation requires root and --reset-at")
    if not args.confirm and not args.command:
        parser.error("a Desktop command is required")
    path = Path(args.output)
    def save(document):
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(document) + "\n")
        temporary.replace(path)
    with Path(str(path) + ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        document = load(path)
        now = time.time()
        if args.confirm:
            try:
                save(confirm(document, args.confirm, args.reset_at, now))
            except ValueError as error:
                parser.error(str(error))
            print("confirmed; the next collector run applies the announced reset")
            return
        if now - document.get("checked_at", 0) >= INTERVAL:
            # Reserve the check durably before browsing: a crash must not
            # turn service retries into repeated checks of the public site.
            save({**document, "checked_at": now, "status": "checking", "source_url": SOURCE})
            document = desktop_check(document, args.command, now)
            save(document)
        if args.notify_command:
            save(notify_pending(document, args.notify_command, now))
    print(document["status"])


if __name__ == "__main__":
    main()
