"""The observed availability of a route, out of the T3 Code state.

T3 Code records what happened when it ran a child. A child that could not
start, a provider that reported its allowance spent, a model that was
refused: these are observations of the route, and the collector reads them
so a route that is known to be broken does not win a tier.

The evidence is the T3 Code state database, read only, and only the rows
that are recent. Nothing here starts, stops or changes anything.

Every failure is scoped, because a failure is not always about one model:

* ``account`` - the account's own allowance is spent ("you have reached
  your session usage limit", "Go usage limit exceeded"). Every model of
  that account is unavailable.
* ``route`` - the provider's runtime could not start (a missing shared
  library, an MCP server that would not load). Every model that the
  provider instance serves is unavailable.
* ``model`` - the provider refused this model. Only that model is
  unavailable.

The reason is a code and a fixed label, never the raw text of the error:
a provider's own message can carry a name, an address or a token, and
none of it leaves this process.

A failure lasts until a later successful run of the same target: the route
works again, and the collector must not keep it unavailable.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping

# The scopes a failure can have.
SCOPE_ACCOUNT = "account"
SCOPE_ROUTE = "route"
SCOPE_MODEL = "model"

# The reason codes. A code and a fixed label, never the provider's text.
REASON_ACCOUNT_USAGE_LIMIT = "account_usage_limit"
REASON_ROUTE_STARTUP_FAILED = "route_startup_failed"
REASON_MODEL_REFUSED = "model_refused"
REASON_PROVIDER_ERROR = "provider_error"

REASON_LABELS = {
    REASON_ACCOUNT_USAGE_LIMIT: (
        "the account reported that its usage limit is spent; every model of "
        "the account is unavailable"
    ),
    REASON_ROUTE_STARTUP_FAILED: (
        "the provider's runtime could not start; every model the provider "
        "instance serves is unavailable"
    ),
    REASON_MODEL_REFUSED: (
        "the provider refused this model; only this model is unavailable"
    ),
    REASON_PROVIDER_ERROR: "the provider reported an error on this route",
}

# The markers of an allowance that is spent. The text is only read to pick
# the code; it is never published.
_USAGE_LIMIT_MARKERS = (
    "usage limit",
    "rate limit",
    "quota exceeded",
    "quota exhausted",
    "upgrade for higher limits",
    "add usage credits",
)

# The markers of a runtime that could not start.
_STARTUP_MARKERS = (
    "mcp load failed",
    "error while loading shared libraries",
    "could not start",
    "failed to construct executor",
    "shared object file",
)

# The markers of a model the provider named in its refusal.
_MODEL_REFUSED_MARKERS = (
    "bad request",
    "model not found",
    "no such model",
    "unsupported model",
)

# How far back the state is read. A failure older than this is a past
# event, not the state of a route.
MAX_AGE_SECONDS = 24 * 3600.0

# How many rows one read may look at. The state is read on every
# collection, so the read is bounded.
MAX_ROWS = 2000

# The tables the reader uses. A state database without them is not a state
# database, and the reader says so instead of guessing.
ATTEMPTS_TABLE = "orchestration_v2_projection_run_attempts"
RUNS_TABLE = "orchestration_v2_projection_runs"
SESSIONS_TABLE = "projection_thread_sessions"
RUNTIME_TABLE = "provider_session_runtime"

# The model prefix of the OpenCode instance names the account it serves.
_INSTANCE_ACCOUNTS = {
    "opencode-go": "opencode-go",
    "opencode": "opencode",
    "ollama-cloud": "ollama",
    "ollama": "ollama",
    "openrouter": "openrouter",
}


class RuntimeStateError(RuntimeError):
    """The T3 Code state could not be read."""


def _iso_epoch(value: Any) -> float | None:
    """An ISO-8601 timestamp as epoch seconds, or None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str) or not value:
        return None
    from datetime import datetime, timezone

    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def _connect(path: str | Path) -> sqlite3.Connection:
    """The state database, opened read only."""
    target = Path(path)
    if not target.exists():
        raise RuntimeStateError("the T3 Code state database is not there")
    try:
        return sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as error:
        raise RuntimeStateError(
            "the T3 Code state database could not be opened"
        ) from error


def _has_table(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _classify(text: str) -> str:
    """The reason code of an error text.

    The text is read to pick the code and is then dropped: a provider's own
    message can carry a name, an address or a token.
    """
    lowered = str(text or "").lower()
    if any(marker in lowered for marker in _USAGE_LIMIT_MARKERS):
        return REASON_ACCOUNT_USAGE_LIMIT
    if any(marker in lowered for marker in _STARTUP_MARKERS):
        return REASON_ROUTE_STARTUP_FAILED
    if any(marker in lowered for marker in _MODEL_REFUSED_MARKERS):
        return REASON_MODEL_REFUSED
    return REASON_PROVIDER_ERROR


def account_of_model(model: str) -> str:
    """The account a model of the OpenCode instance is charged to.

    The OpenCode instance serves several accounts, and the model id names
    which one: "ollama-cloud/..." is the Ollama account, "opencode-go/..."
    is the Go subscription, and a model without a prefix is the OpenCode
    account itself.
    """
    text = str(model or "").strip()
    if "/" not in text:
        return "opencode"
    prefix, _, _rest = text.partition("/")
    return _INSTANCE_ACCOUNTS.get(prefix, prefix)


def _named_model(text: str) -> str:
    """The model a provider's refusal names, or the empty string."""
    match = re.search(r'"model"\s*:\s*"([^"]+)"', str(text or ""))
    return match.group(1) if match else ""


def _attempts(
    connection: sqlite3.Connection, cutoff: float
) -> list[dict[str, Any]]:
    """The recent run attempts of the state, with their times and models."""
    rows = connection.execute(
        f"SELECT thread_id, run_id, provider, provider_instance_id, status, payload_json "
        f"FROM {ATTEMPTS_TABLE} LIMIT ?",
        (MAX_ROWS,),
    ).fetchall()
    attempts: list[dict[str, Any]] = []
    for thread_id, run_id, provider, instance, status, payload in rows:
        document: Mapping[str, Any] = {}
        if isinstance(payload, str):
            try:
                loaded = json.loads(payload)
            except ValueError:
                loaded = {}
            if isinstance(loaded, Mapping):
                document = loaded
        observed = _iso_epoch(document.get("completedAt")) or _iso_epoch(
            document.get("startedAt")
        )
        attempts.append(
            {
                "thread_id": str(thread_id or ""),
                "run_id": str(run_id or ""),
                "provider": str(provider or ""),
                "provider_instance_id": str(instance or ""),
                "status": str(status or ""),
                "observed_at": observed,
                "model": str(document.get("model") or ""),
            }
        )
    return attempts


def _runs(connection: sqlite3.Connection) -> dict[str, str]:
    """The model of every run, by run id."""
    if not _has_table(connection, RUNS_TABLE):
        return {}
    rows = connection.execute(
        f"SELECT run_id, payload_json FROM {RUNS_TABLE} LIMIT ?", (MAX_ROWS,)
    ).fetchall()
    runs: dict[str, str] = {}
    for run_id, payload in rows:
        if not isinstance(payload, str):
            continue
        try:
            document = json.loads(payload)
        except ValueError:
            continue
        if not isinstance(document, Mapping):
            continue
        selection = document.get("modelSelection")
        if not isinstance(selection, Mapping):
            continue
        runs[str(run_id)] = str(selection.get("model") or "")
    return runs


def _errors(connection: sqlite3.Connection) -> dict[str, str]:
    """The last error of every thread, by thread id."""
    if not _has_table(connection, SESSIONS_TABLE):
        return {}
    rows = connection.execute(
        f"SELECT thread_id, last_error FROM {SESSIONS_TABLE} "
        f"WHERE last_error IS NOT NULL AND last_error != '' LIMIT ?",
        (MAX_ROWS,),
    ).fetchall()
    return {str(thread_id): str(text) for thread_id, text in rows}


def _runtimes(connection: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """The model and the last error of every provider session."""
    if not _has_table(connection, RUNTIME_TABLE):
        return {}
    rows = connection.execute(
        f"SELECT thread_id, runtime_payload_json FROM {RUNTIME_TABLE} LIMIT ?",
        (MAX_ROWS,),
    ).fetchall()
    runtimes: dict[str, dict[str, str]] = {}
    for thread_id, payload in rows:
        if not isinstance(payload, str):
            continue
        try:
            document = json.loads(payload)
        except ValueError:
            continue
        if not isinstance(document, Mapping):
            continue
        runtimes[str(thread_id)] = {
            "model": str(document.get("model") or ""),
            "last_error": str(document.get("lastError") or ""),
        }
    return runtimes


def read_failures(path: str | Path, now: float) -> list[dict[str, Any]]:
    """The recent failures of the T3 Code state, with their scope.

    A failure is reported once per target: the account, the route or the
    model it is about, with the reason code, the fixed label and the
    moment it was observed. A failure that a later successful run has
    superseded is not reported: the route works again.
    """
    moment = float(now)
    cutoff = moment - MAX_AGE_SECONDS
    try:
        connection = _connect(path)
    except RuntimeStateError:
        return []
    try:
        if not _has_table(connection, ATTEMPTS_TABLE):
            return []
        attempts = _attempts(connection, cutoff)
        runs = _runs(connection)
        errors = _errors(connection)
        runtimes = _runtimes(connection)
    except sqlite3.Error:
        return []
    finally:
        connection.close()

    # The last failure and the last success of every target.
    failures: dict[tuple[str, str], dict[str, Any]] = {}
    successes: dict[tuple[str, str], float] = {}
    for attempt in attempts:
        observed = attempt.get("observed_at")
        if observed is None or observed < cutoff:
            continue
        instance = attempt["provider_instance_id"]
        thread_id = attempt["thread_id"]
        model = attempt["model"] or runs.get(attempt["run_id"], "")
        runtime = runtimes.get(thread_id) or {}
        model = model or runtime.get("model", "")
        status = attempt["status"]
        if status == "completed":
            # A successful run of the route clears its failures.
            for key in _targets_of(instance, model):
                successes[key] = max(successes.get(key, 0.0), float(observed))
            continue
        if status != "failed":
            continue
        error_text = (
            errors.get(thread_id)
            or runtime.get("last_error")
            or "the provider run did not finish"
        )
        reason = _classify(error_text)
        scope, target = _scope_of(reason, instance, model, error_text)
        key = (scope, target)
        existing = failures.get(key)
        if existing is not None and float(existing["observed_at"]) >= float(observed):
            continue
        failures[key] = {
            "scope": scope,
            "target": target,
            "reason": reason,
            "label": REASON_LABELS.get(reason, REASON_LABELS[REASON_PROVIDER_ERROR]),
            "observed_at": float(observed),
            "model": model,
            "provider_instance": instance,
        }
    # A later successful run of the same target clears the failure.
    for key in list(failures):
        cleared = successes.get(key)
        if cleared is not None and cleared > float(failures[key]["observed_at"]):
            failures.pop(key, None)
    return sorted(failures.values(), key=lambda entry: (entry["scope"], entry["target"]))


def _scope_of(
    reason: str, instance: str, model: str, error_text: str
) -> tuple[str, str]:
    """The scope and the target of a failure."""
    if reason == REASON_ACCOUNT_USAGE_LIMIT:
        return SCOPE_ACCOUNT, (account_of_model(model) if model else instance)
    if reason == REASON_MODEL_REFUSED:
        named = _named_model(error_text) or model
        return SCOPE_MODEL, (named or instance)
    return SCOPE_ROUTE, instance


def _targets_of(instance: str, model: str) -> list[tuple[str, str]]:
    """The keys a successful run clears."""
    targets: list[tuple[str, str]] = [(SCOPE_ROUTE, instance)]
    if model:
        targets.append((SCOPE_ACCOUNT, account_of_model(model)))
        targets.append((SCOPE_MODEL, model))
    return targets
