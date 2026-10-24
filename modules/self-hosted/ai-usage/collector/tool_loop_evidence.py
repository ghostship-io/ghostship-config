"""The recorded per-route T3 tool-loop proof, read directly from the store.

The collector's policy source pins an older agent package whose evidence
validator accepts only bench/work rows, while the picker's probe receipts are
the proof that matters for a free T3 route. This reader is deliberately small
and independent: it validates the fields the collector uses, keeps the latest
event per native route, and lets a newer provider-schema or invalid-request
failure revoke an older pass. It reads no prompt, no thread id and no account.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

MAX_AGE_SECONDS = 30 * 86400.0
MAX_BYTES = 8 * 1024 * 1024
FAILURE_REASONS = ("provider_schema", "invalid_request")


def default_path() -> Path:
    override = os.environ.get("GHOSTSHIP_MODEL_EVIDENCE_PATH")
    if override:
        return Path(override)
    return Path.home() / ".local" / "state" / "ghostship" / "model-evidence.jsonl"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def read(
    now: float | None = None,
    path: str | os.PathLike[str] | None = None,
) -> list[dict[str, Any]] | None:
    """The latest tool-loop event per route.

    ``None`` means the store could not be read at all. An empty list means it
    was read and held no event. The collector must not treat the first as
    proof that no route exists.
    """
    moment = time.time() if now is None else float(now)
    target = Path(path) if path else default_path()
    try:
        text = target.read_text(encoding="utf-8", errors="replace")[:MAX_BYTES]
    except OSError:
        return None
    latest: dict[tuple[str, str], tuple[float, int, Mapping[str, Any]]] = {}
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, Mapping) or row.get("schema_version") != 1:
            continue
        if str(row.get("source") or "") not in ("probe", "bench", "work"):
            continue
        provider = str(row.get("provider") or "")
        model = str(row.get("model") or "")
        passed = row.get("passed")
        date = _number(row.get("date"))
        if not provider or not model or not isinstance(passed, bool) or date is None:
            continue
        if not 0 <= moment - date <= MAX_AGE_SECONDS:
            continue
        reason = str(row.get("reason") or "")
        if reason in FAILURE_REASONS:
            state = "failed"
            rank = 1
        elif passed:
            state = "proven"
            rank = 0
        else:
            continue
        identity = (provider, model)
        current = latest.get(identity)
        if current is None or (date, rank) >= (current[0], current[1]):
            latest[identity] = (date, rank, {
                "provider": provider,
                "model": model,
                "state": state,
                "passed": passed,
                "reason": reason or None,
                "source": str(row.get("source") or ""),
                "date": date,
            })
    return [event for _date, _rank, event in latest.values()]


def read_with_state(
    now: float | None = None,
    path: str | os.PathLike[str] | None = None,
) -> tuple[list[dict[str, Any]] | None, str]:
    """The events and the store state: ok, empty or unreadable."""
    rows = read(now, path)
    if rows is None:
        return None, "unreadable"
    return rows, ("ok" if rows else "empty")
