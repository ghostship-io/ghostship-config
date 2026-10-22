"""Read OpenCode's request records into usage events.

OpenCode records every model request in its own SQLite database: the
provider, the model, the tokens, the time, and, when the request failed, the
provider's own error. This module turns those records into the events the AI
usage collector infers a route's window and budget from.

The owner rule is in ghostship-agent's `config/agents/routing-policy.md`,
"Usage measurement": only a budget limit forms an episode. A concurrency
refusal, a per-minute refusal, a transient upstream refusal, a request that
was too large, an expired key and an aborted run spend no window, so they are
read as `other` and never as a limit.

Three rules keep the reading honest:

* the database is opened read only, with the `mode=ro` URI, and nothing in
  this module writes to it. The write ahead log is always read, because a
  database whose log holds the newest rows read as if the log were not
  there would be stale;
* the read is bounded three times over: every query is bound to the last 35
  days by `time_created`, the query asks only for the fields the reader
  uses, and the whole read is given a wall clock limit that aborts the
  query when it is reached;
* the text of a provider's error is read in memory to pick the outcome. It
  is never stored, never returned and never logged. A real limit message
  names the account it belongs to, and that name stays in the process.

The query extracts the fields it needs with SQLite's own JSON functions, so
the whole record never travels into Python. A record is about 27 KB, and a
35 day read of them is more than a gigabyte that Python would have to
receive and parse; extracting them in the database is about three times
faster.

The contract is fixed:

    {
        "status": "ok" | "unreadable",
        "reason": "ok" | "<a fixed reason code>",
        "events": [
            {
                "provider": "<the collector's provider name>",
                "model": "<the model id as recorded>",
                "at": <epoch seconds>,
                "outcome": "success" | "limit" | "other",
                "usage": <tokens> | None,
                "window_hint": None | "1m" | "1h" | "5h" | "1d" | "7d" | "30d",
            },
            ...
        ],
        "counts": {
            "rows_read": <int>,
            "rows_unmapped": <int>,
            "outcomes": {"success": <int>, "limit": <int>, "other": <int>},
        },
    }

`rows_read` counts every row the reader read, `rows_unmapped` counts the
rows whose provider is not in the mapping table, and `outcomes` counts the
emitted events. A row that cannot be placed is counted and not emitted: a
reading never invents an event.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import urllib.parse
from pathlib import Path
from typing import Any, Mapping

# The read window. The collector needs the recent history to infer a window
# and a budget, and the inference is about the last weeks; a 35 day bound
# keeps the read to what that inference can use.
READ_DAYS = 35
DAY_SECONDS = 24 * 3600.0

# The wall clock limit of one read. The read is bounded by the window above
# as well, but a slow disk or a busy database must not hold the collector:
# the query is aborted when the limit is reached and the reading is reported
# as unreadable.
READ_TIMEOUT_S = 20.0

# The busy timeout of the connection. A database that stays locked for
# longer than this is not waited for.
BUSY_TIMEOUT_S = 2.0

# How often the progress handler looks at the clock. The handler runs every
# so many instructions of the running query, so the limit is honoured well
# inside the wall clock it names.
PROGRESS_STEPS = 100

# The overlap of an incremental read. A row that OpenCode inserted at the
# start of a step and completed later carries the time of its insertion, so
# a window of two hours re-reads the rows a step may still have been
# writing.
OVERLAP_S = 2 * 3600

# The slice a backfill run reads: at most three days, walking back from the
# start of the complete history.
BACKFILL_DAYS = 3
BACKFILL_S = BACKFILL_DAYS * DAY_SECONDS

# The version of the cache file. A cache of another version is discarded.
CACHE_VERSION = 1

# The three statuses a reading has.
STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
STATUS_UNREADABLE = "unreadable"

# The reason codes. They are a closed set, and they never carry a message: a
# failure can name a path or carry a provider's own words.
REASON_OK = "ok"
REASON_MISSING = "database_missing"
REASON_UNREADABLE = "database_unreadable"
REASON_CORRUPT = "database_corrupt"
REASON_SCHEMA = "database_schema_missing"
REASON_TIMEOUT = "timeout"
REASON_CACHE = "cache_unwritten"

REASONS = frozenset(
    {
        REASON_OK,
        REASON_MISSING,
        REASON_UNREADABLE,
        REASON_CORRUPT,
        REASON_SCHEMA,
        REASON_TIMEOUT,
        REASON_CACHE,
    }
)

# The three outcomes of a request.
OUTCOME_SUCCESS = "success"
OUTCOME_LIMIT = "limit"
OUTCOME_OTHER = "other"

OUTCOMES = (OUTCOME_SUCCESS, OUTCOME_LIMIT, OUTCOME_OTHER)

# The window hints a failure may name. The inference uses the window the
# error names when it names one, and the timing estimate otherwise.
WINDOW_1M = "1m"
WINDOW_1H = "1h"
WINDOW_5H = "5h"
WINDOW_1D = "1d"
WINDOW_7D = "7d"
WINDOW_30D = "30d"

WINDOWS = (WINDOW_1M, WINDOW_1H, WINDOW_5H, WINDOW_1D, WINDOW_7D, WINDOW_30D)

# The finishes that mean the request completed. A request that stopped for
# one of these reasons used its budget and is a success, whatever the
# provider called the stop.
SUCCESS_FINISHES = frozenset({"stop", "tool-calls", "length", "content-filter"})

# The OpenCode provider ids, mapped onto the provider names the collector
# uses everywhere else. The table is committed, not guessed: a provider that
# is not in it is counted and not emitted.
PROVIDER_MAP = {
    "ollama-cloud": "ollama",
    "opencode-go": "opencode-go",
    "opencode": "opencode",
    "openrouter": "openrouter",
    "google": "google",
    "requesty": "requesty",
    "nvidia": "nvidia",
    "ovh": "ovh",
    "upstage": "upstage",
    "inception": "inception",
    "groq": "groq",
    "mistral": "mistral",
    "cohere": "cohere",
    "zai": "zai",
    "vercel": "vercel",
    "poolside": "poolside",
    "orcarouter": "orcarouter",
}

# The phrases that name a budget, and the window each one names. The order
# matters: the phrase that names its window is read before the phrase that
# names only a budget.
_BUDGET_PHRASES = (
    (("session usage limit",), WINDOW_5H),
    (("weekly usage limit",), WINDOW_7D),
    (("exceeded your current quota", "current quota"), None),
    (
        ("daily limit reached", "limit_rpd", "free-models-per-day"),
        WINDOW_1D,
    ),
    (("requires a positive account balance", "positive account balance"), None),
    (("requires a valid credit card", "valid credit card"), None),
    (("usage limit",), None),
)

# The refusals that are never a budget failure. They are read before the
# budget phrases: a concurrency refusal, a per-minute refusal and a
# transient upstream refusal all say "limit", and none of them spends a
# window.
_NEVER_LIMIT_PHRASES = (
    "too many concurrent requests",
    "concurrent request",
    "worker local total request limit",
    "free-models-per-min",
    "per minute",
    "per-minute",
    "tokens per minute",
    "request too large",
    "upstream",
    "api key has expired",
    "authentication token is invalid",
    "invalid api key",
    "unauthorized",
    "step interrupted",
    "timed out waiting for response headers",
    "timed out",
    "timeout",
    "provider returned error",
)

# The error types that are never a budget failure either, whatever the
# provider's own words say.
_NEVER_LIMIT_TYPES = ("abort", "timeout", "auth")

# The error type that states the request was refused against the account's
# allowance.
QUOTA_TYPES = frozenset({"provider.quota"})

# The words that make a quota refusal a budget refusal. Without one of them
# the refusal is not about the account's allowance.
_BUDGET_WORDS = ("rate limit", "quota", "usage limit", "limit exceeded")

_SPACES = re.compile(r"\s+")


def _normalise(text: str) -> str:
    """Lower-case the text and collapse its whitespace."""
    return _SPACES.sub(" ", str(text or "")).strip().lower()


def error_message(error: Mapping[str, Any]) -> str:
    """The provider's own words for a failure, or an empty string.

    The text is read in memory and never leaves this module.
    """
    if not isinstance(error, Mapping):
        return ""
    data = error.get("data")
    message = ""
    if isinstance(data, Mapping):
        candidate = data.get("message")
        if not candidate:
            candidate = data.get("error")
        if isinstance(candidate, str):
            message = candidate
    elif isinstance(data, str):
        message = data
    if not message:
        candidate = error.get("message")
        if isinstance(candidate, str):
            message = candidate
    return message


def _budget_window(message: str) -> tuple[bool, str | None]:
    """The window a message names, if it names a budget at all.

    The first element says whether the message is a budget refusal; the
    second is the window it names, or None when it names none.
    """
    text = _normalise(message)
    if not text:
        return (False, None)
    for phrases, window in _BUDGET_PHRASES:
        if any(phrase in text for phrase in phrases):
            return (True, window)
    return (False, None)


def _never_limit(message: str, kind: str) -> bool:
    """True when the refusal spends no window."""
    lowered = _normalise(kind)
    if any(marker in lowered for marker in _NEVER_LIMIT_TYPES):
        return True
    text = _normalise(message)
    if not text:
        return False
    return any(phrase in text for phrase in _NEVER_LIMIT_PHRASES)


def classify_error(error: Mapping[str, Any]) -> tuple[str, str | None]:
    """The outcome of a failed request, and the window it names."""
    kind = str(error.get("type") or "").strip().lower() if isinstance(error, Mapping) else ""
    message = error_message(error)
    if _never_limit(message, kind):
        return (OUTCOME_OTHER, None)
    matched, window = _budget_window(message)
    if matched:
        return (OUTCOME_LIMIT, window)
    text = _normalise(message)
    if kind in QUOTA_TYPES and any(word in text for word in _BUDGET_WORDS):
        # The provider refused against the account's allowance and said so.
        return (OUTCOME_LIMIT, None)
    return (OUTCOME_OTHER, None)


def classify(data: Mapping[str, Any]) -> tuple[str, str | None]:
    """The outcome of a request record, and the window it names."""
    if not isinstance(data, Mapping):
        return (OUTCOME_OTHER, None)
    error = data.get("error")
    if not isinstance(error, Mapping) or not error:
        finish = str(data.get("finish") or "").strip().lower()
        if finish in SUCCESS_FINISHES:
            return (OUTCOME_SUCCESS, None)
        # No error and no finish: the record does not say the request ran.
        return (OUTCOME_OTHER, None)
    return classify_error(error)


def usage_tokens(data: Mapping[str, Any]) -> int | None:
    """The tokens a request used, or None when the record has none.

    The count is the input, output and reasoning tokens. A record without a
    tokens object has no usage to report, and None says so; a record with a
    tokens object of zeros has used nothing and reports zero.
    """
    if not isinstance(data, Mapping):
        return None
    tokens = data.get("tokens")
    if not isinstance(tokens, Mapping):
        return None
    total = 0
    for key in ("input", "output", "reasoning"):
        value = tokens.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        total += int(value)
    return total


def model_of(data: Mapping[str, Any]) -> tuple[str, str]:
    """The provider id and the model id a request record carries."""
    if not isinstance(data, Mapping):
        return ("", "")
    model = data.get("model")
    if not isinstance(model, Mapping):
        return ("", "")
    provider = str(model.get("providerID") or "").strip()
    name = str(model.get("id") or "").strip()
    return (provider, name)


def provider_for(provider_id: str) -> str | None:
    """The collector's provider name, or None when the provider is unmapped."""
    return PROVIDER_MAP.get(str(provider_id or "").strip().lower())


# The fields the reader uses, and the paths they are read from.
EXTRACTED_FIELDS = ("model", "time", "finish", "error", "tokens", "retry")

# The query reads only the fields the reader uses. The whole record is never
# selected: it is about 27 KB a row, so a 35 day read of it is more than a
# gigabyte that Python would have to receive and parse. SQLite extracts the
# fields itself, in one pass over the record.
#
# `json_valid` keeps a record that does not parse from ending the query: the
# row is read, it carries no fields, and it is counted as a row the reader
# cannot place.
READ_SQL = (
    "SELECT time_created, "
    "json_extract(CASE WHEN json_valid(data) THEN data END, "
    "'$.model', '$.time', '$.finish', '$.error', '$.tokens', '$.retry') "
    "FROM session_message "
    "WHERE type = 'assistant' AND time_created >= ? "
    "ORDER BY time_created"
)

# The same read, bounded at both ends: a backfill slice reads the days
# before the complete history and nothing after it.
READ_SQL_UNTIL = (
    "SELECT time_created, "
    "json_extract(CASE WHEN json_valid(data) THEN data END, "
    "'$.model', '$.time', '$.finish', '$.error', '$.tokens', '$.retry') "
    "FROM session_message "
    "WHERE type = 'assistant' AND time_created >= ? AND time_created < ? "
    "ORDER BY time_created"
)


def record_from_extracted(payload: Any) -> dict[str, Any]:
    """The request record, from the fields the query extracted.

    The shape is the shape OpenCode writes, so the classifier reads the
    extracted fields exactly as it reads the whole record: the model, the
    time, the finish, the error, the tokens and the retry.
    """
    values: Any = payload
    if isinstance(values, (bytes, bytearray)):
        try:
            values = values.decode("utf-8")
        except UnicodeDecodeError:
            values = None
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except ValueError:
            values = None
    if not isinstance(values, list):
        return {}
    record: dict[str, Any] = {}
    for index, name in enumerate(EXTRACTED_FIELDS):
        if index >= len(values):
            break
        value = values[index]
        if value is None:
            continue
        record[name] = value
    return record


def _event_time(data: Mapping[str, Any], time_created: Any) -> float:
    """The instant of a request, in epoch seconds.

    The record's own creation time is preferred; the row's time is the
    fallback. Both are epoch milliseconds.
    """
    moment = None
    created = data.get("time") if isinstance(data, Mapping) else None
    if isinstance(created, Mapping):
        value = created.get("created")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            value = None
        if value is not None:
            moment = float(value) / 1000.0
    if moment is None:
        if isinstance(time_created, bool) or not isinstance(time_created, (int, float)):
            time_created = 0
        moment = float(time_created) / 1000.0
    return moment


def open_database(path: str | os.PathLike[str]) -> sqlite3.Connection:
    """Open the OpenCode database read only.

    The `mode=ro` URI is what makes the connection read only, and the busy
    timeout is short: a database that stays locked is not waited for. The
    write ahead log is always read, because a database whose log holds the
    newest rows read as if the log were not there would be stale.
    """
    location = Path(path)
    uri = "file:" + urllib.parse.quote(str(location), safe="/") + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_S)
    try:
        # The query guard makes the connection refuse a write even if the
        # file permissions say otherwise.
        connection.execute("PRAGMA query_only = 1")
    except BaseException:
        # A connection that never reaches the caller must not be left open.
        connection.close()
        raise
    return connection


def _empty_counts() -> dict[str, Any]:
    return {
        "rows_read": 0,
        "rows_unmapped": 0,
        "outcomes": {outcome: 0 for outcome in OUTCOMES},
    }


def _unreadable(reason: str) -> dict[str, Any]:
    return {
        "status": STATUS_UNREADABLE,
        "reason": reason if reason in REASONS else REASON_UNREADABLE,
        "events": [],
        "counts": _empty_counts(),
        "cursor": None,
    }


def _reason_for(error: Exception, path: str | os.PathLike[str]) -> str:
    """The fixed reason code of a failed open.

    The message of the failure is never used: it carries the path and the
    provider's own words.
    """
    if not Path(path).exists():
        return REASON_MISSING
    if isinstance(error, sqlite3.DatabaseError) and not isinstance(error, sqlite3.OperationalError):
        return REASON_CORRUPT
    return REASON_UNREADABLE


def _reason_for_read(error: Exception) -> str:
    """The fixed reason code of a failed read.

    A database whose shared memory file is missing on a read only mount
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


def read_events(
    path: str | os.PathLike[str],
    now: float,
    *,
    since: float | None = None,
    until: float | None = None,
    days: int = READ_DAYS,
    timeout_s: float = READ_TIMEOUT_S,
) -> dict[str, Any]:
    """Read the OpenCode request records into usage events.

    The reading never raises. A database that cannot be read is reported as
    unreadable with a fixed reason code and no events, because an unreadable
    reading is not a reading of zero usage.

    The read is bounded three times over: the query only asks for the last
    `days` days, `since` and `until` bound it further in epoch seconds, and
    the whole read is given `timeout_s` seconds of wall clock. A read that
    runs out of time aborts its query and is reported as unreadable with the
    reason `timeout`.

    The reading carries the cursor as well: the newest row time the read
    saw, in epoch milliseconds. That is where the next incremental read
    starts.
    """
    try:
        connection = open_database(path)
    except sqlite3.Error as error:
        return _unreadable(_reason_for(error, path))
    except (OSError, ValueError):
        return _unreadable(REASON_UNREADABLE)

    events: list[dict[str, Any]] = []
    counts = _empty_counts()
    cutoff = int((float(now) - float(days) * DAY_SECONDS) * 1000)
    lower = cutoff
    if since is not None:
        lower = max(lower, int(round(float(since) * 1000)))
    upper = None
    if until is not None:
        upper = int(round(float(until) * 1000))
    if upper is not None and upper <= lower:
        # The window is empty: there is nothing to read.
        connection.close()
        return {
            "status": STATUS_OK,
            "reason": REASON_OK,
            "events": events,
            "counts": counts,
            "cursor": None,
        }
    deadline = time.monotonic() + float(timeout_s)
    # The progress handler aborts the query when the read is out of time.
    connection.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, PROGRESS_STEPS)
    cursor: int | None = None
    try:
        if upper is None:
            cursor_rows = connection.execute(READ_SQL, (lower,))
        else:
            cursor_rows = connection.execute(READ_SQL_UNTIL, (lower, upper))
        for time_created, payload in cursor_rows:
            if time.monotonic() > deadline:
                # The read is out of time: the partial reading is dropped,
                # because a half reading is not a reading.
                return _unreadable(REASON_TIMEOUT)
            counts["rows_read"] += 1
            if isinstance(time_created, int) and not isinstance(time_created, bool):
                cursor = time_created if cursor is None else max(cursor, time_created)
            data = record_from_extracted(payload)
            provider_id, model = model_of(data)
            provider = provider_for(provider_id)
            if provider is None:
                # An unmapped provider is counted and not emitted: the
                # collector does not publish a route it cannot name.
                counts["rows_unmapped"] += 1
                continue
            outcome, window_hint = classify(data)
            events.append(
                {
                    "provider": provider,
                    "model": model,
                    "at": _event_time(data, time_created),
                    "outcome": outcome,
                    "usage": usage_tokens(data),
                    "window_hint": window_hint,
                }
            )
            counts["outcomes"][outcome] += 1
    except sqlite3.Error as error:
        return _unreadable(_reason_for_read(error))
    finally:
        # The connection is closed on every path, so no read transaction is
        # left open to hold back the writer's checkpoints.
        connection.close()
    return {
        "status": STATUS_OK,
        "reason": REASON_OK,
        "events": events,
        "counts": counts,
        "cursor": cursor,
    }



def _event_outcomes(events: list[Mapping[str, Any]]) -> dict[str, int]:
    """The number of events per outcome."""
    counts = {outcome: 0 for outcome in OUTCOMES}
    for event in events:
        outcome = str(event.get("outcome") or "")
        if outcome in counts:
            counts[outcome] += 1
    return counts


def _remaining(deadline: float) -> float:
    """The seconds left before a deadline."""
    return max(0.0, deadline - time.monotonic())


def load_cache(path: str | os.PathLike[str], now: float) -> dict[str, Any] | None:
    """The cached events, or None when there is no usable cache.

    A cache that cannot be read, does not parse, or does not carry the
    shape the reader expects is discarded: the reader starts over rather
    than trust it.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        cache = json.loads(text)
    except ValueError:
        return None
    if not isinstance(cache, Mapping):
        return None
    complete_since = cache.get("complete_since")
    if isinstance(complete_since, bool) or not isinstance(complete_since, (int, float)):
        return None
    cursor = cache.get("cursor")
    if cursor is not None and (
        isinstance(cursor, bool) or not isinstance(cursor, (int, float))
    ):
        return None
    events = cache.get("events")
    if not isinstance(events, list):
        return None
    kept: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        moment = event.get("at")
        if isinstance(moment, bool) or not isinstance(moment, (int, float)):
            continue
        if moment > float(now):
            # A cache is never trusted for an event that is dated in the
            # future.
            continue
        kept.append(dict(event))
    return {
        "complete_since": min(float(complete_since), float(now)),
        "cursor": int(cursor) if cursor is not None else None,
        "events": kept,
    }


def save_cache(path: str | os.PathLike[str], cache: Mapping[str, Any]) -> None:
    """Write the cache, atomically.

    The file is written beside itself and renamed over the old one, so a
    reader never sees half a cache.
    """
    location = Path(path)
    location.parent.mkdir(parents=True, exist_ok=True)
    temporary = location.with_name(location.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(cache, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, location)


def collect_events(
    path: str | os.PathLike[str],
    cache_path: str | os.PathLike[str],
    now: float,
    *,
    days: int = READ_DAYS,
    timeout_s: float = READ_TIMEOUT_S,
) -> dict[str, Any]:
    """Read the events, with the cache that keeps the history.

    The cache is the collector's own state: a file in its state directory
    that holds the compact events, the cursor and the instant the history
    is complete from. It never holds the text of a provider's error.

    A run reads the rows the last run may not have seen, with two hours of
    overlap so a row OpenCode completed after it inserted it is read again,
    and it replaces the events of that window with the ones it read. The
    events older than the window are pruned, and the cursor moves to the
    newest row the run saw.
    """
    deadline = time.monotonic() + float(timeout_s)
    now = float(now)
    horizon = now - float(days) * DAY_SECONDS
    cache = load_cache(cache_path, now)
    if cache is None:
        complete_since = now - BACKFILL_S
        cursor: int | None = None
        cached: list[dict[str, Any]] = []
    else:
        complete_since = float(cache["complete_since"])
        cursor = cache["cursor"]
        cached = list(cache["events"])

    # The incremental read: the rows since the last run, with the overlap
    # that catches a row a step completed after it inserted it.
    if cursor is None:
        since = complete_since
    else:
        since = cursor / 1000.0 - OVERLAP_S
    fresh = read_events(path, now, since=since, days=days, timeout_s=_remaining(deadline))
    if fresh["status"] != STATUS_OK:
        # The cache is left alone: the next run reads the same window again.
        return _unreadable(fresh["reason"])

    # The events of the window the read covers are replaced by the ones the
    # read found; the rest of the history stays.
    merged = [
        event for event in cached if float(event.get("at") or 0.0) < since
    ] + list(fresh["events"])
    # The history the collector keeps is the window itself.
    merged = [event for event in merged if float(event.get("at") or 0.0) >= horizon]

    if fresh["cursor"] is not None:
        cursor = fresh["cursor"] if cursor is None else max(cursor, fresh["cursor"])

    written = True
    try:
        save_cache(
            cache_path,
            {
                "version": CACHE_VERSION,
                "complete_since": complete_since,
                "cursor": cursor,
                "events": merged,
            },
        )
    except OSError:
        written = False

    counts = fresh["counts"]
    counts["outcomes"] = _event_outcomes(merged)
    return {
        "status": STATUS_OK if written else STATUS_PARTIAL,
        "reason": REASON_OK if written else REASON_CACHE,
        "events": merged,
        "counts": counts,
        "complete_since": complete_since,
        "cursor": cursor,
    }
