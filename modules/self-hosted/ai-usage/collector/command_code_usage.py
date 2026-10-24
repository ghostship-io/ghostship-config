"""The Command Code account usage page, read through the browser path.

The page is private: it needs the owner's signed-in profile. A browser check
writes this state file; the collector only reads it. The workspace slug and
any account identifier stay in the runtime state and never reach a label, a
snapshot field or a log line.

The page reports the three usage windows and per-model requests, tokens and
per-request cost. Those are discovered limits, not estimates. A missing or
stale file keeps the provider's other evidence; it never becomes a zero.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

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


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _kind(text: Any) -> str:
    kind = str(text or "").strip().lower()
    return WINDOW_ALIASES.get(kind, kind)


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
        "source": document.get("source") or "the owner's signed-in Command Code usage page",
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
        rows.append({
            "provider": PROVIDER,
            "account": "default",
            "model": "*",
            "kind": kind,
            "quotaId": kind,
            "remaining_ratio": max(0.0, min(1.0, remaining)),
            "remainingRatio": max(0.0, min(1.0, remaining)),
            "usedRatio": max(0.0, min(1.0, 1.0 - remaining)),
            "resetEpoch": None,
            "durationSeconds": WINDOW_KINDS.get(kind),
            "source": "command_code_usage",
            "observedAtEpoch": checked,
            "basis": "provider_reported",
        })
    return rows
