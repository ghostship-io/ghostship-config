"""The Command Code account usage page, read through the browser path.

The page is private: it needs the owner's signed-in profile. A browser check
writes this state file; the collector only reads it. The workspace slug and
any account identifier stay in the runtime state and never reach a label, a
snapshot field or a log line.

The page reports the three usage windows and per-model requests, tokens and
per-request cost. Those are discovered limits, not estimates. A missing or
stale file keeps the provider's other evidence; it never becomes a zero.

The check reads the same internal endpoints the signed-in Studio page calls,
in the page's own origin, so the session cookie stays in the browser profile
and never reaches the collector. The response carries the credit windows
(five-hour, weekly and the monthly credit balance) and the per-model usage.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from util import iso_to_epoch

SCHEMA = "ghostship.command-code-usage/v1"
DEFAULT_PATH = "/var/lib/ghostship-ai-usage/command-code-usage.json"
PROVIDER = "commandCode"
MAX_AGE_SECONDS = 1800.0
WINDOW_KINDS = {
    "session": 5 * 3600.0,
    "five_hour": 5 * 3600.0,
    "weekly": 7 * 86400.0,
    "monthly": 30 * 86400.0,
}
WINDOW_ALIASES = {"five_hour": "session", "5h": "session"}
BLADEBRO_URL = "https://commandcode.ai/studio/"
API_BASE = "https://api.commandcode.ai"
SOURCE = "the owner's signed-in Command Code usage page"
TOOL_ROWS = frozenset({"web_search", "web_fetch", "web-search", "web-fetch"})
MAX_MODELS = 200
# The page's own requests, evaluated in its origin. The cookie stays in the
# profile; the result is the three JSON bodies the Studio page already reads.
CHECK_SCRIPT = """(async () => {
  const base = %s;
  const get = async (path) => {
    const response = await fetch(base + path, {credentials: 'include'});
    if (!response.ok) throw new Error(String(response.status));
    return await response.json();
  };
  const credits = await get('/internal/billing/credits?');
  const subscription = await get('/internal/billing/subscriptions');
  const byModel = await get('/internal/usage/by-model?').catch(() => null);
  return JSON.stringify({credits, subscription, by_model: byModel});
})()""" % json.dumps(API_BASE)


class UsageError(RuntimeError):
    """The browser check failed; the message is a fixed safe code."""

    def __init__(self, code: str) -> None:
        super().__init__(str(code))
        self.code = str(code)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _kind(text: Any) -> str:
    kind = str(text or "").strip().lower()
    return WINDOW_ALIASES.get(kind, kind)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ms_to_iso(value: Any) -> str | None:
    milliseconds = _number(value)
    if milliseconds is None or milliseconds <= 0:
        return None
    return _iso(milliseconds / 1000.0)


def _ratio(remaining: float) -> float:
    return max(0.0, min(1.0, remaining))


def load(path: str | os.PathLike[str] | None = DEFAULT_PATH) -> dict[str, Any]:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return document if isinstance(document, dict) else {}


def read(now: float, path: str | os.PathLike[str] | None = DEFAULT_PATH,
         max_age_seconds: float = MAX_AGE_SECONDS) -> dict[str, Any]:
    """The dated usage page, with the browser check's health."""
    document = load(path)
    if document.get("schema") != SCHEMA:
        return {"schema": SCHEMA, "provider": PROVIDER, "status": "not_checked",
                "checked_at": None, "stale": True, "windows": [], "models": []}
    checked = _number(document.get("checked_at_epoch"))
    age = None if checked is None else max(0.0, float(now) - checked)
    windows = []
    for window in document.get("windows") or []:
        if not isinstance(window, Mapping):
            continue
        kind = _kind(window.get("kind"))
        if kind not in ("session", "weekly", "monthly"):
            continue
        remaining = _number(window.get("remaining_ratio"))
        if remaining is None:
            continue
        windows.append({
            "kind": kind,
            "remaining_ratio": max(0.0, min(1.0, remaining)),
            "reset_at": window.get("reset_at"),
            "duration_seconds": _number(window.get("duration_seconds")),
        })
    models = []
    for row in document.get("models") or []:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("model") or "").strip()
        if not name or len(name) > 120:
            continue
        models.append({
            "model": name,
            "requests": _number(row.get("requests")),
            "tokens": _number(row.get("tokens")),
            "cost_usd": _number(row.get("cost_usd")),
        })
    return {
        "schema": SCHEMA,
        "provider": PROVIDER,
        "status": str(document.get("status") or "ok"),
        "checked_at": document.get("checked_at"),
        "checked_at_epoch": checked,
        "age_seconds": age,
        "stale": bool(document.get("stale")) or age is None or age > max_age_seconds,
        "source": document.get("source") or SOURCE,
        "windows": windows,
        "models": models,
    }


def windows(state: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """The measured windows in the collector's window shape."""
    if not isinstance(state, Mapping) or state.get("stale"):
        return []
    checked = _number(state.get("checked_at_epoch"))
    rows = []
    for window in state.get("windows") or []:
        if not isinstance(window, Mapping):
            continue
        kind = _kind(window.get("kind"))
        remaining = _number(window.get("remaining_ratio"))
        if kind not in ("session", "weekly", "monthly") or remaining is None:
            continue
        remaining = max(0.0, min(1.0, remaining))
        duration = _number(window.get("duration_seconds"))
        rows.append({
            "provider": PROVIDER,
            "account": "default",
            "model": "*",
            "kind": kind,
            "quotaId": kind,
            "remaining_ratio": remaining,
            "remainingRatio": remaining,
            "usedRatio": max(0.0, min(1.0, 1.0 - remaining)),
            "resetEpoch": iso_to_epoch(window.get("reset_at")),
            "durationSeconds": duration if duration and duration > 0 else WINDOW_KINDS.get(kind),
            "source": "command_code_usage",
            "observedAtEpoch": checked,
            "basis": "provider_reported",
        })
    return rows


def _window_from_credits(entry: Any, kind: str, duration: float) -> dict[str, Any] | None:
    if not isinstance(entry, Mapping):
        return None
    used = _number(entry.get("used"))
    cap = _number(entry.get("cap"))
    if used is None or cap is None or cap <= 0:
        return None
    return {
        "kind": kind,
        "remaining_ratio": _ratio(1.0 - used / cap),
        "reset_at": _ms_to_iso(entry.get("resetAt")),
        "duration_seconds": duration,
    }


def _models(rows: Any) -> list[dict[str, Any]]:
    """The per-model rows, without tool rows or account identifiers."""
    kept = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("model") or "").strip()
        if not name or len(name) > 120 or name.lower() in TOOL_ROWS:
            continue
        requests = _number(row.get("requests"))
        tokens = _number(row.get("tokensTotal"))
        cost = _number(row.get("creditsTotal"))
        kept.append({
            "model": name,
            "requests": requests,
            "tokens": tokens,
            "cost_usd": cost,
        })
        if len(kept) >= MAX_MODELS:
            break
    return kept


def document_from_usage(
    credits: Any,
    subscription: Any,
    by_model: Any,
    *,
    now: float,
) -> dict[str, Any]:
    """The dated state document from the Studio page's own responses.

    The document carries only the three windows, the model usage and the
    check time. The workspace, user and subscription identifiers the page
    needs stay out of it.
    """
    credit_block = credits.get("credits") if isinstance(credits, Mapping) else None
    window_block = credits.get("windowLimits") if isinstance(credits, Mapping) else None
    windows: list[dict[str, Any]] = []
    session = _window_from_credits(
        (window_block or {}).get("fiveHour") if isinstance(window_block, Mapping) else None,
        "session",
        5 * 3600.0,
    )
    if session:
        windows.append(session)
    weekly = _window_from_credits(
        (window_block or {}).get("weekly") if isinstance(window_block, Mapping) else None,
        "weekly",
        7 * 86400.0,
    )
    if weekly:
        windows.append(weekly)
    granted = _number((credit_block or {}).get("monthlyCreditsGranted")
                      if isinstance(credit_block, Mapping) else None)
    remaining_credits = _number((credit_block or {}).get("monthlyCredits")
                                if isinstance(credit_block, Mapping) else None)
    period_end = None
    if isinstance(subscription, Mapping):
        period_end = (subscription.get("data") or {}).get("currentPeriodEnd")
    if granted and granted > 0 and remaining_credits is not None:
        windows.append({
            "kind": "monthly",
            "remaining_ratio": _ratio(remaining_credits / granted),
            "reset_at": period_end,
            "duration_seconds": 30 * 86400.0,
        })
    return {
        "schema": SCHEMA,
        "status": "ok" if windows else "partial",
        "checked_at": _iso(now),
        "checked_at_epoch": float(now),
        "source": SOURCE,
        "windows": windows,
        "models": _models((by_model or {}).get("data") if isinstance(by_model, Mapping) else []),
    }


def write(path: str | os.PathLike[str], document: Mapping[str, Any]) -> None:
    """Write the state atomically, mode 0600."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".new")
    temporary.write_text(json.dumps(dict(document), indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(target)


def parse_check_output(text: str) -> dict[str, Any]:
    """The three bodies of one browser check, from the launcher's envelope."""
    decoder = json.JSONDecoder()
    try:
        envelope, _end = decoder.raw_decode(str(text or "").lstrip())
    except ValueError as error:
        raise UsageError("invalid_check_output") from error
    if not isinstance(envelope, Mapping) or envelope.get("ok") is not True:
        raise UsageError("browser_check_failed")
    result = envelope.get("result")
    # The launcher may hand back the page's JSON string as text, as a JSON
    # string, or as both (a quoted JSON string), and it appends an advisory
    # note after the value. Unwrap at most three levels and ignore the note.
    for _ in range(3):
        if not isinstance(result, str):
            break
        try:
            result, _end = decoder.raw_decode(result.strip())
        except ValueError as error:
            raise UsageError("invalid_check_output") from error
    if not isinstance(result, Mapping):
        raise UsageError("invalid_check_output")
    return dict(result)


def bladebro_runner(bladebro: str, *, timeout: float = 120.0,
                    run: Callable[..., subprocess.CompletedProcess] = subprocess.run
                    ) -> Callable[[], dict[str, Any]]:
    """A check that runs the signed-in Studio page in the owner's profile."""

    def run_check() -> dict[str, Any]:
        command = [
            bladebro,
            "--identity", "personal",
            "--url", BLADEBRO_URL,
            "--request", json.dumps({"op": "eval", "script": CHECK_SCRIPT}),
        ]
        try:
            result = run(command, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as error:
            raise UsageError("browser_check_unavailable") from error
        if result.returncode != 0:
            raise UsageError("browser_check_failed")
        return parse_check_output(str(result.stdout or ""))

    return run_check


def refresh(
    now: float,
    path: str | os.PathLike[str],
    runner: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    """Run the browser check and replace the state only with a usable reading."""
    payload = runner()
    if not isinstance(payload, Mapping):
        raise UsageError("invalid_check_output")
    document = document_from_usage(
        payload.get("credits"),
        payload.get("subscription"),
        payload.get("by_model"),
        now=now,
    )
    if not document["windows"]:
        raise UsageError("no_usage_windows")
    write(path, document)
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true",
                        help="Read the signed-in Studio page and write the state.")
    parser.add_argument("--state", default=DEFAULT_PATH,
                        help="Where the dated usage state is written.")
    parser.add_argument("--bladebro", default="ghostship-bladebro",
                        help="The Agent Desktop browser launcher.")
    parser.add_argument("--now", type=float, default=None,
                        help="Override the current time.")
    parser.add_argument("--timeout", type=float, default=120.0,
                        help="Bound one browser check.")
    args = parser.parse_args(argv)
    if not args.refresh:
        parser.error("--refresh is required")
    now = time.time() if args.now is None else args.now
    try:
        document = refresh(now, args.state, bladebro_runner(args.bladebro, timeout=args.timeout))
    except UsageError as error:
        print(f"command-code-usage: {error.code}", file=sys.stderr)
        return 1
    print(f"command-code-usage: wrote {len(document['windows'])} windows to {args.state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
