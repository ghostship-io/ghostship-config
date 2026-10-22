"""Read the free inference pool's job ledger into usage events.

The free inference pool records every request it dispatches in a durable
ledger: one reservation row per dispatched request, and one attempt per
attempted route on the job's receipt. This module turns those records into
the events the AI usage collector infers a free route's window and budget
from.

The owner rule is in ghostship-agent's `config/agents/routing-policy.md`,
"Usage measurement": a route that reports no usage is measured from its
limit failures. The pool's own limits are admission caps and are never a
capacity reading; what the ledger holds is the use of the route.

Three rules keep the reading honest:

* the ledger belongs to the running pool, so it is opened read only, with
  the `mode=ro` URI, and nothing in this module writes to it. The write
  ahead log is always read, because a ledger whose log holds the newest
  reservations read as if the log were not there would be stale;
* the estimate the pool writes before a dispatch is not consumption. A
  failed attempt contributes no usage at all, and only a success carries
  the usage the pool settled onto its reservation;
* the read is bounded twice over: every query is bound to the last 35 days
  of reservations, so the work of the reading stays bounded as the ledger
  grows, and the whole read is given a wall clock limit that aborts the
  query when it is reached;
* the reading never raises. A ledger that cannot be read is reported as
  unreadable with a fixed reason code, because an unreadable reading is
  not a reading of zero usage.

The contract is fixed:

    {
        "status": "ok" | "unreadable",
        "reason": "ok" | "<a fixed reason code>",
        "events": [
            {
                "provider": "<the pool provider name>",
                "model": "<the model id as recorded>",
                "at": <epoch seconds>,
                "outcome": "success" | "limit" | "other",
                "usage": <tokens> | None,
                "window_hint": None | "1d",
            },
            ...
        ],
        "counts": {
            "attempts_read": <int>,
            "probes_read": <int>,
            "attempts_without_reservation": <int>,
            "outcomes": {"success": <int>, "limit": <int>, "other": <int>},
        },
    }

`attempts_read` counts the attempts on the job receipts, `probes_read`
counts the reservations of the requests that have no receipt,
`attempts_without_reservation` counts the attempts that had no reservation
to pair with, and `outcomes` counts the emitted events. An attempt that cannot be placed is counted and
not emitted: a reading never invents an event.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.parse
from pathlib import Path
from typing import Any

# The read window. The collector needs the recent history to infer a window
# and a budget, and the inference is about the last weeks; a 35 day bound
# keeps the read to what that inference can use.
READ_DAYS = 35
DAY_SECONDS = 24 * 3600.0

# The wall clock limit of one read. The read is bounded by the window above
# as well, but a slow disk or a busy ledger must not hold the collector:
# the query is aborted when the limit is reached and the reading is
# reported as unreadable.
READ_TIMEOUT_S = 20.0

# The busy timeout of the connection. A ledger that stays locked for longer
# than this is not waited for.
BUSY_TIMEOUT_S = 2.0

# How often the progress handler looks at the clock. The handler runs every
# so many instructions of the running query, so the limit is honoured well
# inside the wall clock it names.
PROGRESS_STEPS = 100

# The two statuses a reading has.
STATUS_OK = "ok"
STATUS_UNREADABLE = "unreadable"

# The reason codes. They are a closed set, and they never carry a message:
# a failure can name a path.
REASON_OK = "ok"
REASON_MISSING = "ledger_missing"
REASON_UNREADABLE = "ledger_unreadable"
REASON_CORRUPT = "ledger_corrupt"
REASON_SCHEMA = "ledger_schema_missing"
REASON_TIMEOUT = "timeout"

REASONS = frozenset(
    {
        REASON_OK,
        REASON_MISSING,
        REASON_UNREADABLE,
        REASON_CORRUPT,
        REASON_SCHEMA,
        REASON_TIMEOUT,
    }
)

# The three outcomes of a request.
OUTCOME_SUCCESS = "success"
OUTCOME_LIMIT = "limit"
OUTCOME_OTHER = "other"

OUTCOMES = (OUTCOME_SUCCESS, OUTCOME_LIMIT, OUTCOME_OTHER)

# The window a limit may name. The daily exhaustion of the free allowance
# is a limit of the day; a quota exhaustion names no window.
WINDOW_1D = "1d"

# The kind of the pool's job rows.
JOB_KIND = "inference.task"

# The attempt categories that are a limit of the route, and the window each
# one names. Every other category is not a limit of the route: a rate
# limit, an upstream error, an unavailable model, a context limit, a
# credential failure and an unexpected tool are all something else.
LIMIT_CATEGORIES = {
    "quota_exhausted": None,
    "free_daily_exhausted": WINDOW_1D,
}

# How many job identifiers one membership query carries.
CHUNK = 400

# The columns of a reservation row, in the order they are read.
RESERVATION_ID = 0
RESERVATION_JOB = 1
RESERVATION_PROVIDER = 2
RESERVATION_MODEL = 3
RESERVATION_AT = 4
RESERVATION_INPUT = 5
RESERVATION_OUTPUT = 6


def _empty_counts() -> dict[str, Any]:
    return {
        "attempts_read": 0,
        "probes_read": 0,
        "attempts_without_reservation": 0,
        "outcomes": {outcome: 0 for outcome in OUTCOMES},
    }


def _unreadable(reason: str) -> dict[str, Any]:
    return {
        "status": STATUS_UNREADABLE,
        "reason": reason if reason in REASONS else REASON_UNREADABLE,
        "events": [],
        "counts": _empty_counts(),
    }


def _reason_for(error: Exception, path: str | os.PathLike[str]) -> str:
    """The fixed reason code of a failed open.

    The message of the failure is never used: it carries the path.
    """
    if not Path(path).exists():
        return REASON_MISSING
    if isinstance(error, sqlite3.DatabaseError) and not isinstance(error, sqlite3.OperationalError):
        return REASON_CORRUPT
    return REASON_UNREADABLE


def _reason_for_read(error: Exception) -> str:
    """The fixed reason code of a failed read.

    A ledger whose shared memory file is missing on a read only directory
    cannot be read at all: the reader reports that, and never a reading of
    zero usage.
    """
    text = str(error).lower()
    if "no such table" in text:
        return REASON_SCHEMA
    if "interrupted" in text:
        # The query was aborted because the read ran out of time.
        return REASON_TIMEOUT
    return REASON_UNREADABLE


def open_ledger(path: str | os.PathLike[str]) -> sqlite3.Connection:
    """Open the pool's ledger read only.

    The `mode=ro` URI is what makes the connection read only, and the busy
    timeout is short: a ledger that stays locked is not waited for. The
    write ahead log is always read, because a ledger whose log holds the
    newest reservations read as if the log were not there would be stale.
    """
    location = Path(path)
    uri = "file:" + urllib.parse.quote(str(location), safe="/") + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_S)


def _parse(raw: Any) -> Any:
    """The record's own JSON, or None when it does not parse."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _attempts(result: Any) -> list[dict[str, Any]]:
    """The attempts recorded on one job receipt."""
    if isinstance(result, dict):
        document = result
    elif isinstance(result, (bytes, bytearray, str)):
        document = _parse(result)
    else:
        return []
    if not isinstance(document, dict):
        return []
    attempts = document.get("attempts")
    if not isinstance(attempts, list):
        return []
    return [attempt for attempt in attempts if isinstance(attempt, dict)]


def _tokens(inside: Any, outside: Any) -> int | None:
    """The tokens of a reservation, or None when the ledger holds none."""
    if inside is None or outside is None:
        return None
    try:
        return int(inside) + int(outside)
    except (TypeError, ValueError):
        return None


def _outcome(category: str) -> tuple[str, str | None]:
    """The outcome of an attempt category, and the window it names."""
    if category == OUTCOME_SUCCESS:
        return OUTCOME_SUCCESS, None
    if category in LIMIT_CATEGORIES:
        return OUTCOME_LIMIT, LIMIT_CATEGORIES[category]
    return OUTCOME_OTHER, None


def _reservations_by_route(reservations: list[Any]) -> dict[tuple[str, str, str], list[Any]]:
    """Group the reservations by their job and route, oldest first."""
    grouped: dict[tuple[str, str, str], list[Any]] = {}
    for reservation in reservations:
        route = (
            str(reservation[RESERVATION_JOB] or ""),
            str(reservation[RESERVATION_PROVIDER] or ""),
            str(reservation[RESERVATION_MODEL] or ""),
        )
        grouped.setdefault(route, []).append(reservation)
    for rows in grouped.values():
        rows.sort(key=lambda row: (float(row[RESERVATION_AT] or 0.0), str(row[RESERVATION_ID])))
    return grouped


def _known_jobs(connection: sqlite3.Connection, reservations: list[Any]) -> set[str]:
    """The identifiers of the jobs the reservations belong to.

    A reservation whose job has no receipt is a probe: the pool's own
    check of a route, which it never puts on a job.
    """
    identifiers = sorted(
        {str(row[RESERVATION_JOB]) for row in reservations if row[RESERVATION_JOB]}
    )
    known: set[str] = set()
    for start in range(0, len(identifiers), CHUNK):
        chunk = identifiers[start : start + CHUNK]
        placeholders = ",".join("?" * len(chunk))
        rows = connection.execute(
            f"SELECT id FROM jobs WHERE id IN ({placeholders})", chunk
        ).fetchall()
        known.update(str(row[0]) for row in rows)
    return known


def _attempt_event(attempt: dict[str, Any], reservation: Any) -> dict[str, Any]:
    """The event of one attempted route."""
    outcome, window_hint = _outcome(str(attempt.get("category") or ""))
    usage = 0
    if outcome == OUTCOME_SUCCESS:
        # A success carries the usage the pool settled onto its
        # reservation. A failure keeps the estimate the pool wrote before
        # the dispatch, and an estimate is not consumption.
        usage = _tokens(reservation[RESERVATION_INPUT], reservation[RESERVATION_OUTPUT])
    return {
        "provider": str(attempt.get("provider") or ""),
        "model": str(attempt.get("model") or ""),
        "at": float(reservation[RESERVATION_AT] or 0.0),
        "outcome": outcome,
        "usage": usage,
        "window_hint": window_hint,
    }


def _probe_event(reservation: Any) -> dict[str, Any]:
    """The event of a request without a job receipt.

    The probe consumed the route's allowance and its outcome is unknown,
    so it is an `other` with the usage the ledger holds.
    """
    return {
        "provider": str(reservation[RESERVATION_PROVIDER] or ""),
        "model": str(reservation[RESERVATION_MODEL] or ""),
        "at": float(reservation[RESERVATION_AT] or 0.0),
        "outcome": OUTCOME_OTHER,
        "usage": _tokens(reservation[RESERVATION_INPUT], reservation[RESERVATION_OUTPUT]),
        "window_hint": None,
    }


def read_events(
    path: str | os.PathLike[str],
    now: float,
    *,
    days: int = READ_DAYS,
    timeout_s: float = READ_TIMEOUT_S,
) -> dict[str, Any]:
    """Read the pool's ledger into usage events.

    The reading never raises. A ledger that cannot be read is reported as
    unreadable with a fixed reason code and no events, because an
    unreadable reading is not a reading of zero usage.

    The read is bounded twice over: the query only asks for the last `days`
    days, and the whole read is given `timeout_s` seconds of wall clock. A
    read that runs out of time aborts its query and is reported as
    unreadable with the reason `timeout`.
    """
    try:
        connection = open_ledger(path)
    except sqlite3.Error as error:
        return _unreadable(_reason_for(error, path))
    except (OSError, ValueError):
        return _unreadable(REASON_UNREADABLE)

    events: list[dict[str, Any]] = []
    counts = _empty_counts()
    cutoff = float(now) - float(days) * DAY_SECONDS
    deadline = time.monotonic() + float(timeout_s)
    # The progress handler aborts the query when the read is out of time.
    connection.set_progress_handler(
        lambda: 1 if time.monotonic() > deadline else 0, PROGRESS_STEPS
    )
    try:
        reservations = connection.execute(
            "SELECT id, job, provider, model, at, input, output "
            "FROM inference_reservations WHERE at >= ?",
            (cutoff,),
        ).fetchall()
        receipts = connection.execute(
            "SELECT id, result FROM jobs WHERE kind = ? AND updated_at >= ?",
            (JOB_KIND, cutoff),
        ).fetchall()
        if time.monotonic() > deadline:
            # The read is out of time: the partial reading is dropped,
            # because a half reading is not a reading.
            return _unreadable(REASON_TIMEOUT)
        by_route = _reservations_by_route(reservations)
        known = _known_jobs(connection, reservations)
        matched: dict[tuple[str, str, str], int] = {}
        for job_id, result in receipts:
            for attempt in _attempts(result):
                counts["attempts_read"] += 1
                route = (
                    job_id,
                    str(attempt.get("provider") or ""),
                    str(attempt.get("model") or ""),
                )
                # The k-th attempt of a job and route takes the k-th
                # reservation of that job and route, in time order.
                index = matched.get(route, 0)
                rows = by_route.get(route) or []
                if index >= len(rows):
                    counts["attempts_without_reservation"] += 1
                    continue
                matched[route] = index + 1
                event = _attempt_event(attempt, rows[index])
                events.append(event)
                counts["outcomes"][event["outcome"]] += 1
        for reservation in reservations:
            job_id = reservation[RESERVATION_JOB]
            if job_id is not None and job_id in known:
                continue
            counts["probes_read"] += 1
            event = _probe_event(reservation)
            events.append(event)
            counts["outcomes"][event["outcome"]] += 1
        if time.monotonic() > deadline:
            return _unreadable(REASON_TIMEOUT)
    except sqlite3.Error as error:
        return _unreadable(_reason_for_read(error))
    finally:
        # The connection is closed on every path, so no read transaction is
        # left open to hold back the writer's checkpoints.
        connection.close()
    events.sort(key=lambda event: (event["at"], event["provider"], event["model"]))
    return {
        "status": STATUS_OK,
        "reason": REASON_OK,
        "events": events,
        "counts": counts,
    }
