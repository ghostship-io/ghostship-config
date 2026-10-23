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
import reset_events

SOURCE = "https://x.com/thsottiaux"
PATH = "/var/lib/ghostship-ai-usage/announced-resets.json"
INTERVAL = 3600
BACKOFF = 8 * 3600
POST_URL = reset_events.POST_URL
TOPIC_URL = re.compile(r"https://community\.openai\.com/t/[a-zA-Z0-9_-]+/\d+(?:/\d+)?(?:#announcement-\d+)?$")


def load(path=PATH):
    try:
        value = json.loads(Path(path).read_text())
        if not isinstance(value, dict) or value.get("schema") != 1 or not isinstance(value.get("announcements"), list):
            raise ValueError("invalid announcement cache")
        # Old keyword matches have no announcement evidence. Re-read their
        # primary posts once, preserving notice receipts independently.
        records = value["announcements"]
        receipts = dict(value.get("notice_receipts") or {})
        pending = list(value.get("recheck_urls") or [])
        events = {}
        for entry in records:
            if not isinstance(entry, dict):
                continue
            url = notice_url(entry)
            if url and entry.get("notice_sent_at"):
                receipts[url] = entry["notice_sent_at"]
            if reset_events.valid(entry):
                events[entry["source_url"]] = entry
            elif url and POST_URL.fullmatch(url):
                pending.append(url)
        value.pop("relay_checked_at", None)
        value.update(announcements=list(events.values())[-100:],
                     notice_receipts=receipts,
                     recheck_urls=list(dict.fromkeys(pending))[-100:])
        return value
    except FileNotFoundError:
        return {"schema": 1, "status": "not_checked", "announcements": []}
    except (OSError, ValueError):
        return {"schema": 1, "status": "unavailable", "announcements": []}


def parse(post):
    return reset_events.parse(post)


def overrides(results, document, now):
    """Future resets affect only the product, plans and windows announced."""
    overrides = []
    for result in results:
        for window in result.windows:
            candidates = []
            for entry in document.get("announcements", []):
                reset = reset_events.timestamp(entry.get("reset_at"))
                if reset_events.matches(entry, window) and reset and now < reset.timestamp() <= now + 7 * 86400:
                    candidates.append((reset.timestamp(), entry))
            if not candidates or not window.get("quotaId"):
                continue
            reset, entry = min(candidates, key=lambda pair: pair[0])
            if isinstance(window.get("resetEpoch"), (int, float)) and window["resetEpoch"] <= reset:
                continue
            overrides.append({"provider": window["provider"], "quota_id": window["quotaId"],
                "model": str(window.get("model") or "*"), "reset_at": entry["reset_at"],
                "reset_source": "announced", "source_url": entry["source_url"]})
    return overrides


def confirm(document, source_url, reset_at, now):
    """An operator confirms a scoped announcement without broadening its scope."""
    try:
        reset = datetime.fromisoformat(reset_at.replace("Z", "+00:00"))
        if reset.tzinfo is None or not now < reset.timestamp() <= now + 7 * 86400:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError("confirmation needs a future timezone-qualified reset within seven days") from None
    record = next((entry for entry in document.get("announcements", [])
                   if entry.get("source_url") == source_url), None)
    if (not record or not reset_events.valid(record) or 'unknown' in record['windows']
            or (len(record['products']) > 1 and len(record['windows']) > 1)):
        raise ValueError("confirmation must identify a recorded announcement")
    record.update(confidence="confirmed", reason="operator_confirmed", confirmed_at=now,
                  reset_at=reset.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"))
    return document


def samples(document):
    """Public, bounded evidence rows for the dashboard, including unverified items."""
    from metrics import ExactLabel
    for entry in document.get("announcements", [])[-100:]:
        if not reset_events.valid(entry):
            continue
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
        for product in entry["products"]:
            yield "ghostship_ai_announced_reset_info", {
                "source_url": ExactLabel(url), "confidence": confidence,
                "label": ExactLabel("announced (unverified)" if confidence == "low" else "announced reset"),
                "scope": ExactLabel(entry["scope"]),
                "provider": product,
                "plans": ExactLabel(",".join(entry["plans"])),
                "windows": ExactLabel(",".join(entry["windows"])),
                "published_at": ExactLabel(entry["published_at"]),
                "quote": ExactLabel(entry["quote"]),
                "reset_at": ExactLabel(reset_at),
            }, 1.0


def primary_blocked(document):
    return any(row.get("source_url") == SOURCE and row.get("status") == "blocked"
               for row in document.get("sources", []))


def due(document, now):
    deadline = document.get("next_check_at", document.get("checked_at", 0) +
                            (BACKOFF if primary_blocked(document) else INTERVAL))
    return now >= deadline


def notice_url(entry):
    """Relays and direct discoveries acknowledge the same primary status URL."""
    url = str(entry.get("source_url", ""))
    if POST_URL.fullmatch(url):
        return url
    if TOPIC_URL.fullmatch(url):
        primary = str(entry.get("primary_source_url", ""))
        return primary if POST_URL.fullmatch(primary) else url
    return None


def notify_pending(document, command, now):
    """Retry failures and share durable receipts across primary/relay aliases."""
    def publish(key, title, body):
        try:
            result = subprocess.run([command, "--topic", "operations", "--priority", "3",
                "--source", "ai-usage", "--dedupe", key, "--title", title, body],
                check=False, timeout=10, capture_output=True)
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    if primary_blocked(document) and not document.get("blocked_notice_sent_at"):
        since = document.setdefault("blocked_since", document.get("checked_at", now))
        key = "codex-reset-blocked-" + hashlib.sha256(str(since).encode()).hexdigest()[:24]
        if publish(key, "Codex announcement monitoring blocked",
                   SOURCE + "\nX showed a sign-in wall or challenge. Monitoring stopped; "
                   "the next read is in eight hours. Please check the personal Desktop profile."):
            document["blocked_notice_sent_at"] = now

    records = document.get("announcements", [])[-100:]
    receipts = dict(document.get("notice_receipts") or {})
    receipts.update({notice_url(entry): entry["notice_sent_at"] for entry in records
                     if notice_url(entry) and entry.get("notice_sent_at")})
    attempted = set()
    for entry in reversed(records):
        url = notice_url(entry)
        if not url or not reset_events.valid(entry):
            continue
        if url in receipts:
            entry.setdefault("notice_sent_at", receipts[url])
            continue
        if url in attempted or len(attempted) >= 20:
            continue
        attempted.add(url)
        key = "codex-reset-" + hashlib.sha256(url.encode()).hexdigest()[:24]
        low = entry["confidence"] == "low"
        product = " / ".join("Codex" if name == "codex" else "ChatGPT" for name in entry["products"])
        title = product + (" reset announcement needs confirmation" if low else " reset announced")
        body = ("announced (unverified)\n" if low else "announced reset\n") + entry["source_url"]
        body += "\n" + entry["quote"]
        body += "\nScope: " + entry["scope"] + "; " + ",".join(entry["plans"]) + "; " + ",".join(entry["windows"])
        body += "\nReset: " + (entry.get("reset_at") or "time needs confirmation")
        if url != entry["source_url"]:
            body += "\n" + url
        if low:
            body += "\nConfirm the announced scope and reset time before pacing changes."
        if publish(key, title, body):
            entry["notice_sent_at"] = now
            receipts[url] = now
    document["notice_receipts"] = receipts
    return document


EXTRACT = r"""(() => {
 const blocked = /log in or sign up|sign in to|log in to continue|captcha|verify you are human/i.test(document.body.innerText);
 if (blocked) return {blocked: true, posts: []};
 return {blocked: false, posts: [...document.querySelectorAll('article')].slice(0, 20).map(a => ({
   text: a.querySelector('[data-testid="tweetText"]')?.innerText || '',
   url: a.querySelector('a:has(time)')?.href || '',
   published_at: a.querySelector('time')?.dateTime || ''
 }))};
})()"""


def check(document, call, now):
    """One primary timeline, bounded legacy rechecks, and no wall handling or mirrors."""
    if not due(document, now):
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
        if (previous.get("reason") == "operator_confirmed" and all(
                previous.get(key) == entry.get(key) for key in ("products", "plans", "windows"))):
            entry.update({key: previous[key] for key in
                          ("confidence", "reason", "confirmed_at", "reset_at")})
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
            elif POST_URL.fullmatch(str(post.get("url", ""))):
                records.pop(post["url"], None)
        pending = list(document.get("recheck_urls") or [])
        if not page["blocked"]:
            for url in pending[:5]:
                if not POST_URL.fullmatch(str(url)):
                    pending.remove(url)
                    continue
                recheck = read(url, 'article', EXTRACT)
                if recheck["blocked"]:
                    page = recheck
                    break
                for post in recheck.get("posts", []):
                    if post.get("url") == url:
                        entry = parse(post)
                        if entry:
                            remember(entry)
                        else:
                            records.pop(url, None)
                if any(post.get("url") == url for post in recheck.get("posts", [])):
                    pending.remove(url)
        updated["recheck_urls"] = pending
        updated["status"] = "blocked" if page["blocked"] else "ok"
        if page["blocked"]:
            updated["sources"][0]["status"] = "blocked"
            updated.setdefault("blocked_since", now)
        else:
            updated.pop("blocked_since", None)
            updated.pop("blocked_notice_sent_at", None)
    except (OSError, ValueError, KeyError, TypeError):
        updated["status"] = "unavailable"
    finally:
        updated["next_check_at"] = now + (BACKOFF if primary_blocked(updated) else INTERVAL)
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
        return {**document, "checked_at": now, "identity": "personal", "status": "unavailable",
                "next_check_at": now + (BACKOFF if primary_blocked(document) else INTERVAL)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=PATH)
    parser.add_argument("--notify-command", help="Host notification publisher")
    parser.add_argument("--confirm", metavar="SOURCE_URL", help="Confirm a recorded announcement without broadening its parsed scope (root only)")
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
        if due(document, now):
            # Reserve the check durably before browsing: a crash must not
            # turn service retries into repeated checks of the public site.
            save({**document, "checked_at": now, "status": "checking", "source_url": SOURCE,
                  "next_check_at": now + BACKOFF})
            document = desktop_check(document, args.command, now)
            save(document)
        if args.notify_command:
            save(notify_pending(document, args.notify_command, now))
    print(document["status"])


if __name__ == "__main__":
    main()
