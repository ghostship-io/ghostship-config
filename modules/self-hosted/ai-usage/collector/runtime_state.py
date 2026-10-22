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

A retired model is a model of its own: the provider said the model is
deprecated or retired, and it does not serve it again. The retirement is
scoped to that one route, and the collector remembers it beyond the window
of a failure, because a model that was retired yesterday is still retired
today.

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
# A model the provider retired. The route is gone, not broken: it does not
# come back with a new allowance, and it is not the account that is spent.
REASON_MODEL_RETIRED = "model_retired"

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
    # The published reason of a retired route is its code. A reader matches
    # it against the state file and the routing snapshot, and a code never
    # carries a provider's own words.
    REASON_MODEL_RETIRED: "model_retired",
}

# The markers of an allowance that is spent. The text is only read to pick
# the code; it is never published.
#
# The payment markers are there because a provider that refuses a request
# with "402 Payment Required" and a spent balance is an exhausted account,
# not a broken route: every model of that account is unavailable until a
# later run of it succeeds.
_USAGE_LIMIT_MARKERS = (
    "usage limit",
    "rate limit",
    "quota exceeded",
    "quota exhausted",
    "upgrade for higher limits",
    "add usage credits",
    "payment required",
    "usage balance exhausted",
)

# The status of a refused payment, in the shape a provider writes it: the
# status code with its name, or the code with the reason it carries. A bare
# "402" is not a marker: a count of processed items, a line number, or a
# model id may carry the same three digits without anything being wrong.
_PAYMENT_STATUS = re.compile(
    r"\b(?:HTTP|status|code)\D{0,12}402\b|\b402\s+Payment Required\b", re.I
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

# The markers of a model the provider retired. A provider that retired a
# model does not serve it again, so the failure is not a broken route and
# not a spent account: the model itself is gone. The text is read to pick
# the code and is then dropped, like every other error text.
#
# "free launch period" covers the wording of a free tier that ended: the
# free variant of a model is retired when the launch period is over.
_RETIREMENT_MARKERS = (
    "has been deprecated",
    "has been retired",
    "free launch period",
    "reached its end of life",
    "is no longer available",
)

# How far back the state is read. A failure older than this is a past
# event, not the state of a route. The window is configurable, because the
# age of a state that matters is the owner's decision.
MAX_AGE_SECONDS = 24 * 3600.0

# How many rows one read may look at. The state is read on every
# collection, so the read is bounded.
MAX_ROWS = 2000

# How many identifiers one statement may bind. A statement with thousands
# of them is slow to prepare and slow to run.
MAX_BINDINGS = 200

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

# The account of a native provider instance. The instance names the account
# it serves, and the ranking knows the same names. The OpenCode instance
# serves several accounts; a model without a prefix is the OpenCode account
# itself.
INSTANCE_ACCOUNTS = {
    "codex": "codex",
    "claudeAgent": "claude",
    "grok": "grok",
    "antigravity": "antigravity",
    "cursor": "cursor",
    "pi": "pi",
    "muse": "muse",
    "opencode": "opencode",
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
    if any(marker in lowered for marker in _RETIREMENT_MARKERS):
        # A retirement is read first: a provider that says the model is
        # retired has said more about the route than any other text, and
        # the route is not coming back with a new allowance.
        return REASON_MODEL_RETIRED
    if any(marker in lowered for marker in _USAGE_LIMIT_MARKERS):
        return REASON_ACCOUNT_USAGE_LIMIT
    if _PAYMENT_STATUS.search(str(text or "")):
        return REASON_ACCOUNT_USAGE_LIMIT
    if any(marker in lowered for marker in _STARTUP_MARKERS):
        return REASON_ROUTE_STARTUP_FAILED
    if any(marker in lowered for marker in _MODEL_REFUSED_MARKERS):
        return REASON_MODEL_REFUSED
    return REASON_PROVIDER_ERROR


def _bare_model(model: str) -> str:
    """The model name without the account prefix the instance carries.

    The T3 Code state names a model of the OpenCode instance with the
    account it is charged to: "opencode-go/minimax-m3.1-flash-free". The
    ranking knows the same model without the prefix, and the retirement of
    a route is recorded under the name the ranking uses.
    """
    text = str(model or "")
    prefix, separator, rest = text.partition("/")
    return rest if separator and rest else text


def account_of_model(model: str, instance: str = "") -> str:
    """The account a model of a provider instance is charged to.

    The OpenCode instance serves several accounts, and the model id names
    which one: "ollama-cloud/..." is the Ollama account, "opencode-go/..."
    is the Go subscription, and a model without a prefix is the OpenCode
    account itself. A model of another instance is charged to the account
    that instance serves, so a Grok route is the Grok account and not the
    OpenCode one.
    """
    text = str(model or "").strip()
    if "/" not in text:
        if not text:
            return "opencode"
        name = str(instance or "")
        if not name:
            return "opencode"
        return INSTANCE_ACCOUNTS.get(name, name)
    prefix, _, _rest = text.partition("/")
    return _INSTANCE_ACCOUNTS.get(prefix, prefix)


# The window our own requests are counted in, for a provider that publishes
# a per-minute limit and does not report it.
REQUEST_COUNT_SECONDS = 60.0


def read_request_counts(
    path: str | Path, now: float, *, age_seconds: float = REQUEST_COUNT_SECONDS
) -> dict[str, int]:
    """The number of requests we made per account in the last window.

    The count is our own: the runs of the T3 Code state inside the window,
    grouped by the account that was charged for them. It is never a reading
    of the provider: it counts what we sent, and a provider that publishes a
    per-minute limit is measured against it.
    """
    moment = float(now)
    cutoff = moment - float(age_seconds)
    try:
        connection = _connect(path)
    except RuntimeStateError:
        return {}
    try:
        if not _has_table(connection, RUNS_TABLE):
            return {}
        runs = _recent_runs(connection, cutoff, moment)
        if not runs:
            return {}
        attempts = _attempts_of_runs(connection, [run["run_id"] for run in runs])
    except sqlite3.Error:
        return {}
    finally:
        connection.close()
    counts: dict[str, int] = {}
    for run in runs:
        for attempt in attempts.get(run["run_id"]) or [run]:
            observed = attempt.get("observed_at") or run.get("observed_at")
            if observed is None or observed < cutoff:
                continue
            model = attempt.get("model") or run.get("model") or ""
            account = (
                account_of_model(model, str(run.get("provider_instance_id") or ""))
                if model
                else str(run.get("provider_instance_id") or "")
            )
            if not account:
                continue
            counts[account] = counts.get(account, 0) + 1
    return counts


def _named_model(text: str) -> str:
    """The model a provider's refusal names, or the empty string."""
    match = re.search(r'"model"\s*:\s*"([^"]+)"', str(text or ""))
    return match.group(1) if match else ""


def _recent_runs(
    connection: sqlite3.Connection, cutoff: float, now: float
) -> list[dict[str, Any]]:
    """The runs of the state that are recent enough to matter.

    The runs carry their own times, so the read is bounded by the window
    and it is ordered newest first. The attempts table carries no time of
    its own, so it is never read on its own: an unbounded read of it
    returns the oldest rows, and today's failures would be missed.
    """
    from datetime import datetime, timezone

    window = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    rows = connection.execute(
        f"SELECT run_id, thread_id, provider, provider_instance_id, status, "
        f"requested_at, completed_at, payload_json "
        f"FROM {RUNS_TABLE} "
        f"WHERE datetime(COALESCE(completed_at, requested_at)) >= datetime(?) "
        f"ORDER BY datetime(COALESCE(completed_at, requested_at)) DESC LIMIT ?",
        (window, MAX_ROWS),
    ).fetchall()
    runs: list[dict[str, Any]] = []
    for run_id, thread_id, provider, instance, status, requested, completed, payload in rows:
        document: Mapping[str, Any] = {}
        if isinstance(payload, str):
            try:
                loaded = json.loads(payload)
            except ValueError:
                loaded = {}
            if isinstance(loaded, Mapping):
                document = loaded
        selection = document.get("modelSelection")
        model = ""
        if isinstance(selection, Mapping):
            model = str(selection.get("model") or "")
        runs.append(
            {
                "run_id": str(run_id or ""),
                "thread_id": str(thread_id or ""),
                "provider": str(provider or ""),
                "provider_instance_id": str(instance or ""),
                "status": str(status or ""),
                "observed_at": _iso_epoch(completed) or _iso_epoch(requested),
                "model": model,
            }
        )
    return runs


def _attempts_of_runs(
    connection: sqlite3.Connection, run_ids: Iterable[str]
) -> dict[str, list[dict[str, Any]]]:
    """The attempts of the given runs, by run id."""
    identifiers = [str(run_id) for run_id in run_ids if str(run_id)]
    if not identifiers:
        return {}
    attempts: dict[str, list[dict[str, Any]]] = {}
    # The number of identifiers is bounded by the number of recent runs, so
    # the statement stays small and the read stays bounded.
    for start in range(0, len(identifiers), MAX_BINDINGS):
        chunk = identifiers[start:start + MAX_BINDINGS]
        placeholders = ",".join("?" for _ in chunk)
        rows = connection.execute(
            f"SELECT thread_id, run_id, provider, provider_instance_id, status, "
            f"payload_json FROM {ATTEMPTS_TABLE} "
            f"WHERE run_id IN ({placeholders}) LIMIT ?",
            (*chunk, MAX_ROWS),
        ).fetchall()
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
            attempts.setdefault(str(run_id or ""), []).append(
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


def _errors(
    connection: sqlite3.Connection, thread_ids: Iterable[str]
) -> dict[str, str]:
    """The last error of the given threads, by thread id."""
    identifiers = [str(thread_id) for thread_id in thread_ids if str(thread_id)]
    if not identifiers:
        return {}
    found: dict[str, str] = {}
    for start in range(0, len(identifiers), MAX_BINDINGS):
        chunk = identifiers[start:start + MAX_BINDINGS]
        placeholders = ",".join("?" for _ in chunk)
        rows = connection.execute(
            f"SELECT thread_id, last_error FROM {SESSIONS_TABLE} "
            f"WHERE thread_id IN ({placeholders}) "
            f"AND last_error IS NOT NULL AND last_error != '' LIMIT ?",
            (*chunk, MAX_ROWS),
        ).fetchall()
        for thread_id, text in rows:
            found[str(thread_id)] = str(text)
    return found


def _runtimes(
    connection: sqlite3.Connection, thread_ids: Iterable[str]
) -> dict[str, dict[str, str]]:
    """The model and the last error of the given provider sessions."""
    identifiers = [str(thread_id) for thread_id in thread_ids if str(thread_id)]
    if not identifiers:
        return {}
    runtimes: dict[str, dict[str, str]] = {}
    for start in range(0, len(identifiers), MAX_BINDINGS):
        chunk = identifiers[start:start + MAX_BINDINGS]
        placeholders = ",".join("?" for _ in chunk)
        rows = connection.execute(
            f"SELECT thread_id, runtime_payload_json FROM {RUNTIME_TABLE} "
            f"WHERE thread_id IN ({placeholders}) LIMIT ?",
            (*chunk, MAX_ROWS),
        ).fetchall()
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


def read_failures(
    path: str | Path, now: float, *, age_seconds: float | None = None
) -> list[dict[str, Any]]:
    """The recent failures of the T3 Code state, with their scope.

    A failure is reported once per target: the account, the route or the
    model it is about, with the reason code, the fixed label and the
    moment it was observed. A failure that a later successful run has
    superseded is not reported: the route works again.
    """
    return read_observations(path, now, age_seconds=age_seconds)["failures"]


def read_observations(
    path: str | Path,
    now: float,
    *,
    age_seconds: float | None = None,
    success_age_seconds: float | None = None,
) -> dict[str, Any]:
    """The failures of the window and the successful runs of the routes.

    The failures are the ones of the window, with their scope, their reason
    code and the moment they were observed. The successes are the last
    successful run of every route, and they are read over their own window:
    a retirement outlives the window of the failure that reported it, and a
    successful run that is older than the window still clears the
    retirement when it is newer than the retirement.

    The read is bounded by the window: the runs of the window are read
    newest first, and only their attempts are read with them. The attempts
    table carries no time of its own, so it is never read on its own.
    """
    moment = float(now)
    window = MAX_AGE_SECONDS if age_seconds is None else float(age_seconds)
    success_window = (
        window if success_age_seconds is None else float(success_age_seconds)
    )
    cutoff = moment - window
    success_cutoff = moment - success_window
    empty: dict[str, Any] = {"failures": [], "successes": {}}
    try:
        connection = _connect(path)
    except RuntimeStateError:
        return empty
    try:
        if not _has_table(connection, RUNS_TABLE):
            return empty
        runs = _recent_runs(connection, min(cutoff, success_cutoff), moment)
        if not runs:
            return empty
        attempts = _attempts_of_runs(connection, [run["run_id"] for run in runs])
        thread_ids = {run["thread_id"] for run in runs if run["thread_id"]}
        for entries in attempts.values():
            for attempt in entries:
                if attempt["thread_id"]:
                    thread_ids.add(attempt["thread_id"])
        errors = _errors(connection, thread_ids)
        runtimes = _runtimes(connection, thread_ids)
    except sqlite3.Error:
        return empty
    finally:
        connection.close()

    # The last failure and the last success of every target.
    failures: dict[tuple[str, str], dict[str, Any]] = {}
    successes: dict[tuple[str, str], float] = {}
    for run in runs:
        entries = attempts.get(run["run_id"]) or []
        for attempt in entries or [run]:
            observed = attempt.get("observed_at") or run.get("observed_at")
            if observed is None:
                continue
            instance = attempt.get("provider_instance_id") or run["provider_instance_id"]
            thread_id = attempt.get("thread_id") or run["thread_id"]
            model = attempt.get("model") or run.get("model") or ""
            runtime = runtimes.get(thread_id) or {}
            model = model or runtime.get("model", "")
            status = attempt.get("status") or run.get("status") or ""
            if status == "completed":
                if float(observed) >= success_cutoff:
                    # A successful run of the route clears its failures.
                    for key in _targets_of(instance, model):
                        successes[key] = max(successes.get(key, 0.0), float(observed))
                continue
            if float(observed) < cutoff:
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
            record = {
                "scope": scope,
                "target": target,
                "reason": reason,
                "label": REASON_LABELS.get(reason, REASON_LABELS[REASON_PROVIDER_ERROR]),
                "observed_at": float(observed),
                "model": model,
                "provider_instance": instance,
            }
            if reason == REASON_MODEL_RETIRED:
                # A retirement names one route: the id the state carries, the
                # account the route is charged to and the model without the
                # account prefix, which is the name the ranking knows it by.
                record["route"] = model
                record["provider"] = account_of_model(model, instance)
                record["model"] = _bare_model(model)
            failures[key] = record
    # A later successful run of the same target clears the failure.
    for key in list(failures):
        cleared = successes.get(key)
        if cleared is not None and cleared > float(failures[key]["observed_at"]):
            failures.pop(key, None)
    return {
        "failures": sorted(
            failures.values(), key=lambda entry: (entry["scope"], entry["target"])
        ),
        # The last successful run of every route, by the id of the route.
        "successes": {
            target: float(observed)
            for (scope, target), observed in successes.items()
            if scope == SCOPE_MODEL
        },
    }


def _scope_of(
    reason: str, instance: str, model: str, error_text: str
) -> tuple[str, str]:
    """The scope and the target of a failure."""
    if reason == REASON_ACCOUNT_USAGE_LIMIT:
        return SCOPE_ACCOUNT, (account_of_model(model, instance) if model else instance)
    if reason == REASON_MODEL_RETIRED:
        # The retirement is about one route, and the target is the id of
        # that route.
        return SCOPE_MODEL, (model or instance)
    if reason == REASON_MODEL_REFUSED:
        named = _named_model(error_text) or model
        return SCOPE_MODEL, (named or instance)
    return SCOPE_ROUTE, instance


def _targets_of(instance: str, model: str) -> list[tuple[str, str]]:
    """The keys a successful run clears."""
    targets: list[tuple[str, str]] = [(SCOPE_ROUTE, instance)]
    if model:
        targets.append((SCOPE_ACCOUNT, account_of_model(model, instance)))
        targets.append((SCOPE_MODEL, model))
    return targets
