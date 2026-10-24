"""The OpenCode Go limit table, read from the provider's own page.

The Go page server-renders only the featured limit rows. The complete table is
the ``goModels`` array of the page's hashed JavaScript chunk, beside the Go Plus
figures in ``plusLimits``. The training/retention table is in the page HTML.
The chunk hash is resolved from the page on every refresh; a hash is never
hardcoded.

Every number here is published by OpenCode. A number the page does not publish
stays absent: an absent number is never a zero. A failed refresh keeps the last
dated values and marks them stale.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from util import http_request

PAGE_URL = "https://opencode.ai/go"
SCHEMA = "ghostship.opencode-go-limits/v1"
DEFAULT_STATE_PATH = "/var/lib/ghostship-ai-usage/opencode-go-limits.json"

# The page changes when OpenCode changes the lineup; a six-hour reading is
# recent enough for a five-minute collector and keeps the page traffic low.
MAX_AGE_SECONDS = 6 * 3600.0

# A failed refresh is retried after an hour, not on every five-minute
# collection. The last dated values are served in between, marked stale.
RETRY_AFTER_SECONDS = 3600.0

# The share of the monthly allowance each rolling window may spend. The page
# states them: 20% per 5 hours, 50% per week, 100% per month.
WINDOW_SHARES = (
    ("session", 5 * 3600.0, 0.20),
    ("weekly", 7 * 86400.0, 0.50),
    ("monthly", 30 * 86400.0, 1.00),
)

# Vendor evidence for a dated build the page does not name. It is published
# beside an assumed-latest binding, never instead of the page's own date.
VENDOR_EVIDENCE = {
    "deepseek-v4.1-flash": {
        "build": "1017",
        "published_at": "2026-10-19T16:34:00Z",
        "source": "https://x.com/opencode/status/2112220734768779441",
        "text": "DeepSeek V4.1 Flash updated to 1017 in OpenCode Go and Free",
    }
}

_CHUNK = re.compile(r"/_build/assets/index-[A-Za-z0-9_-]+\.js")
_ROW = re.compile(
    r"<tr\b[^>]*>\s*<td[^>]*>(?P<name>[^<]+)</td>\s*"
    r"<td[^>]*>(?P<training>[^<]+)</td>\s*"
    r"<td[^>]*>(?P<retention>[^<]+)</td>",
    re.IGNORECASE,
)


def _alnum(text: str) -> str:
    return "".join(character for character in str(text or "").lower() if character.isalnum())


def _page_html(body: bytes) -> str:
    return body.decode("utf-8", "replace")


def chunk_url(html: str) -> str:
    """The hashed chunk the page loads, resolved from the page itself."""
    match = _CHUNK.search(html or "")
    return f"https://opencode.ai{match.group(0)}" if match else ""


def _balanced(text: str, start: int, opener: str = "[", closer: str = "]") -> str:
    """The literal starting at ``start``, respecting quoted strings."""
    depth = 0
    quote = ""
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            continue
        if character in "\"'`":
            quote = character
        elif character == opener:
            depth += 1
        elif character == closer:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def _literal(text: str, name: str, opener: str, closer: str) -> str:
    marker = f"const {name} = {opener}"
    start = text.find(marker)
    if start < 0:
        return ""
    return _balanced(text, start + len(marker) - 1, opener, closer)


def _json_literal(text: str) -> Any:
    """Parse a JavaScript literal that is JSON apart from bare keys and Infinity."""
    if not text:
        return None
    value = re.sub(r"\bInfinity\b", "1e309", text)
    value = re.sub(r"([{,]\s*)([A-Za-z_][\w.-]*)\s*:", r'\1"\2":', value)
    try:
        return json.loads(value)
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    """A finite number, or None.

    The page writes ``Infinity`` for an unlimited route. It is a documented
    marker, not a number a calculation can spend, so it stays absent.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return float(value)


def _training(text: str) -> str:
    value = str(text or "").strip().lower()
    if value == "not used":
        return "not_used"
    if value == "used":
        return "used"
    return "unknown"


def _retention(text: str) -> Any:
    value = str(text or "").strip().lower()
    if value == "not zdr":
        return "not_zdr"
    match = re.fullmatch(r"(\d+)\s+days?", value)
    if match:
        return int(match.group(1))
    return "unknown"


def parse_models(chunk: str) -> dict[str, dict[str, Any]]:
    """The per-model Go and Go Plus figures from the page's chunk."""
    rows = _json_literal(_literal(chunk, "goModels", "[", "]"))
    plus = _json_literal(_literal(chunk, "plusLimits", "{", "}"))
    if not isinstance(rows, list) or not isinstance(plus, dict):
        return {}
    models: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = str(row.get("id") or "").strip()
        name = str(row.get("name") or "").strip()
        requests = _number(row.get("requests"))
        allowance = _number(row.get("allowance"))
        if not model_id or not name:
            continue
        plus_limits = plus.get(model_id)
        if not isinstance(plus_limits, list) or len(plus_limits) != 2:
            plus_limits = [None, None]
        plus_requests = _number(plus_limits[0])
        plus_allowance = _number(plus_limits[1])
        bonus = _number(row.get("bonus"))
        raw_requests = row.get("requests")
        unlimited = (
            isinstance(raw_requests, (int, float))
            and not isinstance(raw_requests, bool)
            and (raw_requests == float("inf") or raw_requests >= 1e308)
        )
        models[model_id] = {
            "id": model_id,
            "name": name,
            "go_requests_5h": requests,
            "go_allowance_usd": allowance,
            "plus_requests_5h": plus_requests,
            "plus_allowance_usd": plus_allowance,
            "bonus": bonus,
            "previous_go_requests_5h": (
                requests / bonus if requests is not None and bonus else None
            ),
            "limited_time": bool(row.get("limitedTime")),
            "regions": bool(row.get("regions")),
            "fresh": bool(row.get("fresh")),
            "unlimited": unlimited,
            "go_requests_month": (
                requests / WINDOW_SHARES[0][2] if requests is not None else None
            ),
            "plus_requests_month": (
                plus_requests / WINDOW_SHARES[0][2] if plus_requests is not None else None
            ),
        }
    return models


def parse_retention(html: str) -> dict[str, dict[str, Any]]:
    """The training/retention rows the page renders, by model name."""
    rows: dict[str, dict[str, Any]] = {}
    for match in _ROW.finditer(html or ""):
        name = match.group("name").strip()
        training = match.group("training").strip()
        retention = match.group("retention").strip()
        rows[name] = {
            "training": _training(training),
            "retention": _retention(retention),
            "retention_text": retention,
            "training_text": training,
        }
    return rows


def matches(entry: Mapping[str, Any], model: str) -> bool:
    """True when a collector model id names the page's model.

    The page's id and display name are both published identities; a collector
    id may use either spelling (``deepseek-flash`` or
    ``deepseek-v4.1-flash``). Only the complete alphanumeric identity is
    compared, so one model never borrows another's numbers.
    """
    wanted = _alnum(model)
    if not wanted:
        return False
    for candidate in (entry.get("id"), entry.get("name")):
        if candidate and _alnum(candidate) == wanted:
            return True
    return False


def lookup(state: Mapping[str, Any] | None, model: str) -> dict[str, Any] | None:
    """The dated record of one collector model id, or None."""
    if not isinstance(state, Mapping):
        return None
    models = state.get("models") or {}
    if not isinstance(models, Mapping):
        return None
    for entry in models.values():
        if isinstance(entry, Mapping) and matches(entry, model):
            record = dict(entry)
            record["source"] = state.get("source") or PAGE_URL
            record["checked_at"] = state.get("checked_at")
            record["stale"] = bool(state.get("stale"))
            record["page"] = state.get("page_url") or PAGE_URL
            return record
    return None


def vendor_evidence(model: str) -> list[dict[str, Any]]:
    """Vendor announcements that name a dated build of the model, if any."""
    wanted = _alnum(model)
    if not wanted:
        return []
    for name, entry in VENDOR_EVIDENCE.items():
        if _alnum(name) == wanted:
            return [dict(entry)]
    return []


def _load(path: str | os.PathLike[str] | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return document if isinstance(document, dict) else {}


def _save(path: str | os.PathLike[str] | None, state: Mapping[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(json.dumps(dict(state), indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, target)
    except OSError:
        pass


def _age(state: Mapping[str, Any], now: float) -> float | None:
    checked = state.get("checked_at_epoch")
    if isinstance(checked, bool) or not isinstance(checked, (int, float)):
        return None
    return float(now) - float(checked)


def _iso(now: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(float(now), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read(
    now: float,
    state_path: str | os.PathLike[str] | None = DEFAULT_STATE_PATH,
    *,
    max_age_seconds: float = MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """The dated Go table as last written.

    The collector only reads this file; the scheduled refresh writes it. A
    missing or old state is stale, and it carries no models until the refresh
    succeeds. This function never opens a socket.
    """
    state = _load(state_path)
    if not state or state.get("schema") != SCHEMA:
        return {
            "schema": SCHEMA,
            "source": PAGE_URL,
            "page_url": PAGE_URL,
            "chunk": "",
            "checked_at": None,
            "checked_at_epoch": None,
            "age_seconds": None,
            "stale": True,
            "reason": "no dated reading",
            "models": {},
        }
    age = _age(state, now)
    result = dict(state)
    result["age_seconds"] = age
    result["stale"] = bool(state.get("stale")) or age is None or age > max_age_seconds
    return result


def refresh(
    now: float,
    state_path: str | os.PathLike[str] | None = DEFAULT_STATE_PATH,
    *,
    http: Any = http_request,
    max_age_seconds: float = MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Refresh the dated Go table from the provider page.

    A fresh state is returned as it is. A refresh failure keeps the last dated
    values and marks them stale; with no last values the state says so and
    carries no models.
    """
    state = _load(state_path)
    age = _age(state, now)
    if state.get("models") and age is not None and not state.get("stale") and 0 <= age < max_age_seconds:
        return state
    if state.get("models") and state.get("stale"):
        attempted = state.get("last_attempt_epoch")
        if isinstance(attempted, (int, float)) and not isinstance(attempted, bool):
            if 0 <= float(now) - float(attempted) < RETRY_AFTER_SECONDS:
                return state

    failure = ""
    page = http(PAGE_URL)
    html = _page_html(page.body) if page.ok else ""
    chunk = chunk_url(html)
    if page.ok and chunk:
        script = http(chunk)
        if script.ok:
            models = parse_models(_page_html(script.body))
            if models:
                retention = parse_retention(html)
                for entry in models.values():
                    policy = retention.get(str(entry.get("name") or ""))
                    if policy:
                        entry.update(training=policy["training"], retention=policy["retention"],
                                     retention_text=policy["retention_text"],
                                     training_text=policy["training_text"])
                    else:
                        entry.update(training="unknown", retention="unknown",
                                     retention_text="", training_text="")
                    entry["sensitive_ok"] = _sensitive_ok(entry)
                fresh = {
                    "schema": SCHEMA,
                    "source": PAGE_URL,
                    "page_url": PAGE_URL,
                    "chunk": chunk,
                    "checked_at": _iso(now),
                    "checked_at_epoch": float(now),
                    "stale": False,
                    "reason": "",
                    "models": models,
                }
                _save(state_path, fresh)
                return fresh
            failure = "the Go limit table did not parse"
        else:
            failure = f"the Go chunk returned {script.status}"
    elif page.ok:
        failure = "the Go page did not name its chunk"
    else:
        failure = f"the Go page returned {page.status}"

    if state.get("models"):
        stale = dict(state)
        stale["stale"] = True
        stale["reason"] = failure
        # The last good reading keeps its own date; the failed attempt is a
        # separate moment and never rewrites the date as if it were fresh.
        stale["last_attempt_epoch"] = float(now)
        _save(state_path, stale)
        return stale
    return {
        "schema": SCHEMA,
        "source": PAGE_URL,
        "page_url": PAGE_URL,
        "chunk": "",
        "checked_at": None,
        "checked_at_epoch": None,
        "stale": True,
        "reason": failure,
        "models": {},
    }


def _sensitive_ok(entry: Mapping[str, Any]) -> bool | None:
    """Whether the model is acceptable for internal and sensitive work.

    The owner's rule is explicit: a model whose prompts are used for training
    or whose data is not zero-retention stays out. A table that does not state
    training or retention keeps the answer unknown, never a silent yes.
    """
    training = entry.get("training")
    retention = entry.get("retention")
    if training == "used" or retention == "not_zdr":
        return False
    if training == "not_used":
        return True
    return None


def window_budgets(entry: Mapping[str, Any], plan: str = "go") -> list[dict[str, Any]]:
    """The request budget of every Go window, from the monthly figure.

    The page publishes the five-hour request figure. The documented shares
    make the others arithmetic, not an estimate: the monthly figure is the
    five-hour figure divided by 20%, the weekly one is half of the monthly one,
    and the five-hour one is the published number itself.
    """
    monthly = entry.get("plus_requests_month" if plan == "plus" else "go_requests_month")
    monthly_usd = entry.get("plus_allowance_usd" if plan == "plus" else "go_allowance_usd")
    if monthly is None:
        return []
    budgets = []
    for kind, seconds, share in WINDOW_SHARES:
        budgets.append({
            "kind": kind,
            "length_seconds": seconds,
            "share_of_monthly": share,
            "requests": float(monthly) * share,
            "monthly_requests": float(monthly),
            "monthly_allowance_usd": monthly_usd,
            "unit": "requests",
            "estimate": False,
            "basis": "published",
            "source": PAGE_URL,
        })
    return budgets


def allowance_record(entry: Mapping[str, Any], plan: str = "go") -> dict[str, Any]:
    """The allowance a picker may weigh, with its date and data policy."""
    budgets = window_budgets(entry, plan)
    return {
        "plan": plan,
        "unit": "requests",
        "requests_5h": entry.get("plus_requests_5h" if plan == "plus" else "go_requests_5h"),
        "requests_month": entry.get("plus_requests_month" if plan == "plus" else "go_requests_month"),
        "allowance_usd_month": entry.get("plus_allowance_usd" if plan == "plus" else "go_allowance_usd"),
        "budgets": budgets,
        "unlimited": bool(entry.get("unlimited")),
        "limited_time": bool(entry.get("limited_time")),
        "regions": bool(entry.get("regions")),
        "bonus": entry.get("bonus"),
        "training": entry.get("training"),
        "retention": entry.get("retention"),
        "retention_text": entry.get("retention_text"),
        "sensitive_ok": entry.get("sensitive_ok"),
        "source": entry.get("source") or PAGE_URL,
        "checked_at": entry.get("checked_at"),
        "stale": bool(entry.get("stale")),
        "basis": "published OpenCode Go limit table",
        "vendor_evidence": (vendor_evidence(entry.get("id") or "")
                            or vendor_evidence(entry.get("name") or "")),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import time

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", default=DEFAULT_STATE_PATH)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)
    now = time.time()
    state = refresh(now, args.state) if args.refresh else read(now, args.state)
    print(json.dumps({
        "schema": state.get("schema"),
        "checked_at": state.get("checked_at"),
        "stale": state.get("stale"),
        "reason": state.get("reason"),
        "models": len(state.get("models") or {}),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
