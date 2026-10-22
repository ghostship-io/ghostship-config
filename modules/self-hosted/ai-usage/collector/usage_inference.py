"""Infer the capacity of the routes from the request records.

The providers that report no usage, and every free route, showed "Limits
unknown" on the Providers page. The owner rule (`ghostship-agent`'s
`config/agents/routing-policy.md`, section "Usage measurement") reads their
capacity from their limit failures instead: a route that runs until it is
refused shows its window, its budget and its remaining share in the refusals
it produced.

This module is the wiring between the two readers and that inference:

* the OpenCode reader reads the request records of the routes the agents
  use, and the pool reader reads the ledger of the free pool. Each reader
  opens its own record read only and caps itself; neither of them is
  touched here in any other way;
* the events of both reads are put on the routes of the collector's
  inventory. An event whose route is not in the inventory is counted and
  published: a reading never invents a route;
* the inference (`inference.py`) turns the events into the capacity of every
  route they touch, and this module turns that capacity into the quota
  window the ranking reads.

The collector is never held up by a reader. A read that fails contributes
no events, the routes it would have fed keep the basis they had, and the
source status says what happened.

The two reads run at the same time, so the pair costs one reader's wall
clock limit and not two.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterable, Mapping, Sequence

import codes
import inference as inference_module
import opencode_reader
import pool_reader
import ranking as ranking_module
from metrics import SourceResult

__all__ = [
    "EVENTS_CACHE_PATH",
    "Inference",
    "OPENCODE_DB_RELATIVE",
    "SOURCE_OPENCODE",
    "SOURCE_POOL",
    "STATE_EXHAUSTED",
    "STATE_IN_WINDOW",
    "STATE_NO_FAILURE",
    "basis_for",
    "detail_for",
    "infer",
    "key_for",
    "map_events",
    "quota_id_for",
    "read_and_infer",
    "read_records",
    "window_for",
]

# The OpenCode database, inside the T3 Code home. The collector's unit reads
# the home read only, and the reader opens the file read only as well.
OPENCODE_DB_RELATIVE = ".local/share/opencode/opencode.db"

# The collector's own cache of the OpenCode events, in its state directory.
# It is the reader's state, and it never holds the text of a provider's
# error.
EVENTS_CACHE_PATH = "/var/lib/ghostship-ai-usage/opencode-events.json"

# The two records, by the name their status is published under.
SOURCE_OPENCODE = "opencode_events"
SOURCE_POOL = "pool_events"

# The wall clock limit of the two reads together. Each reader caps itself
# at twenty seconds; they run at the same time, so the pair costs one cap.
READ_BUDGET_S = 20.0

# The three states an inferred capacity can be in. The names are the ones
# the owner rule uses.
STATE_IN_WINDOW = "in_window"
STATE_EXHAUSTED = "exhausted"
STATE_NO_FAILURE = "no_failure"

# The quota id of the window of an inferred route. The label says the
# window it was inferred from, and a route that was never refused says so.
QUOTA_ID_NO_FAILURE = "inferred:no-limit-seen"
QUOTA_ID_EXHAUSTED = "inferred:exhausted"
QUOTA_ID_PREFIX = "inferred:"

# The basis of an inferred window. It names the episodes the window was
# measured from, so a reader knows how much record stands behind it.
BASIS_NO_FAILURE = "inferred: no limit failure in the records"


class Inference:
    """What the request records imply, and how they were read."""

    def __init__(
        self,
        results: list[SourceResult] | None = None,
        capacities: dict[tuple[str, str], dict[str, Any]] | None = None,
        unmatched: Mapping[str, int] | None = None,
        records: Mapping[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self.results = list(results or [])
        # The capacity of every route the record touches, by the route the
        # collector knows it by.
        self.capacities = dict(capacities or {})
        # The events whose route is not in the inventory, per record.
        self.unmatched = dict(unmatched or {})
        # The events of every record, by the record they came from.
        self.records = {name: list(events) for name, events in (records or {}).items()}

    @property
    def unmatched_events(self) -> int:
        """Every event that could not be placed on a route."""
        return sum(self.unmatched.values())

    @property
    def events(self) -> int:
        """Every event the two records hold."""
        return sum(len(events) for events in self.records.values())


def _unreadable(source: str, reason: str, now: float, duration: float) -> SourceResult:
    """A source that could not be read, with its fixed reason code."""
    return SourceResult(
        source=source,
        status="unreadable",
        reason=reason,
        observed_at=now,
        duration_s=duration,
    )


def _result(source: str, reading: Mapping[str, Any], now: float, duration: float) -> SourceResult:
    """The status of one record, as the collector publishes it."""
    status = str(reading.get("status") or "unreadable")
    if status not in ("ok", "partial", "unreadable"):
        status = "unreadable"
    reason = str(reading.get("reason") or codes.UNKNOWN)
    return SourceResult(
        source=source,
        status=status,
        reason=reason,
        observed_at=now,
        duration_s=duration,
    )


def read_records(
    now: float,
    *,
    opencode_db: str,
    events_cache: str,
    pool_ledger: str | None,
    timeout_s: float = READ_BUDGET_S,
) -> Inference:
    """Read both records, and return the events they hold.

    The two reads run at the same time and each of them caps itself, so the
    pair never costs more than one reader's limit. A read that fails is
    reported as unreadable and contributes no events: the collector keeps
    running, and the routes that reader would have fed keep the basis they
    had.
    """
    started = time.monotonic()
    results: list[SourceResult] = []
    records: dict[str, list[dict[str, Any]]] = {SOURCE_OPENCODE: [], SOURCE_POOL: []}

    def read_opencode() -> tuple[dict[str, Any], float]:
        began = time.monotonic()
        try:
            reading = opencode_reader.collect_events(
                opencode_db, events_cache, float(now), timeout_s=float(timeout_s)
            )
        except Exception:  # pragma: no cover - the reader does not raise
            return ({"status": "unreadable", "reason": opencode_reader.REASON_UNREADABLE}, time.monotonic() - began)
        return (reading, time.monotonic() - began)

    def read_pool() -> tuple[dict[str, Any], float]:
        began = time.monotonic()
        if not pool_ledger:
            return ({"status": "unreadable", "reason": pool_reader.REASON_MISSING}, time.monotonic() - began)
        try:
            reading = pool_reader.read_events(
                pool_ledger, float(now), timeout_s=float(timeout_s)
            )
        except Exception:  # pragma: no cover - the reader does not raise
            return ({"status": "unreadable", "reason": pool_reader.REASON_UNREADABLE}, time.monotonic() - began)
        return (reading, time.monotonic() - began)

    with ThreadPoolExecutor(max_workers=2) as workers:
        opencode_future = workers.submit(read_opencode)
        pool_future = workers.submit(read_pool)
        opencode_reading, opencode_duration = opencode_future.result()
        pool_reading, pool_duration = pool_future.result()

    results.append(_result(SOURCE_OPENCODE, opencode_reading, float(now), opencode_duration))
    results.append(_result(SOURCE_POOL, pool_reading, float(now), pool_duration))
    for source, reading in ((SOURCE_OPENCODE, opencode_reading), (SOURCE_POOL, pool_reading)):
        for event in reading.get("events") or ():
            if isinstance(event, Mapping):
                records[source].append(dict(event))
    return Inference(results=results, records=records)


def _index(routes: Iterable[tuple[str, str]]) -> tuple[dict[tuple[str, str], tuple[str, str]], dict[tuple[str, str], set[str]]]:
    """The routes of the inventory, exactly and folded.

    The exact index is the route the collector knows. The folded index holds
    the routes whose ids differ only in their case: a provider may spell a
    route id in another case, and the case is not part of the route.
    """
    exact: dict[tuple[str, str], tuple[str, str]] = {}
    folded: dict[tuple[str, str], set[str]] = {}
    for provider, model in routes:
        name = str(provider)
        identifier = str(model)
        exact[(name, identifier)] = (name, identifier)
        folded.setdefault((name, identifier.lower()), set()).add(identifier)
    return exact, folded


def _match(
    provider: str,
    model: str,
    exact: Mapping[tuple[str, str], tuple[str, str]],
    folded: Mapping[tuple[str, str], set[str]],
) -> tuple[str, str] | None:
    """The route of the inventory an event belongs to, or None.

    The route is the one the collector knows, and the window it builds is
    keyed by that route. A route that is not in the inventory is not
    guessed: the event is counted and published as unmatched.
    """
    key = (str(provider), str(model))
    found = exact.get(key)
    if found is not None:
        return found
    candidates = folded.get((key[0], key[1].lower())) or set()
    if len(candidates) == 1:
        # One route of that provider differs only in its case: it is the
        # same route.
        return (key[0], next(iter(candidates)))
    # No route, or two routes that differ only in their case: a reading
    # never guesses which one it meant.
    return None


def map_events(
    events: Sequence[Mapping[str, Any]],
    routes: Iterable[tuple[str, str]],
) -> tuple[list[dict[str, Any]], int]:
    """Put the events on the routes of the inventory.

    The events come back with the model id the collector knows the route by.
    The second number is the count of the events whose route is not in the
    inventory.
    """
    exact, folded = _index(routes)
    mapped: list[dict[str, Any]] = []
    unmatched = 0
    for event in events:
        if not isinstance(event, Mapping):
            continue
        route = _match(
            str(event.get("provider") or ""),
            str(event.get("model") or ""),
            exact,
            folded,
        )
        if route is None:
            unmatched += 1
            continue
        mapped.append({**dict(event), "provider": route[0], "model": route[1]})
    return mapped, unmatched


def infer(
    events: Sequence[Mapping[str, Any]],
    now: float,
) -> dict[tuple[str, str], dict[str, Any]]:
    """The capacity the record implies for every route it touches."""
    capacities = inference_module.infer_capacity(events, float(now))
    return {route: capacity.as_dict() for route, capacity in capacities.items()}


def read_and_infer(
    now: float,
    *,
    opencode_db: str,
    events_cache: str,
    pool_ledger: str | None,
    routes: Iterable[tuple[str, str]],
    timeout_s: float = READ_BUDGET_S,
) -> Inference:
    """Read both records, put them on the routes, and infer the capacity.

    The events of the two records are one record: a route of the pool and a
    route of the OpenCode instance are separate routes, and the inference
    reads the account of each provider on its own.
    """
    reading = read_records(
        now,
        opencode_db=opencode_db,
        events_cache=events_cache,
        pool_ledger=pool_ledger,
        timeout_s=timeout_s,
    )
    unmatched: dict[str, int] = {}
    events: list[dict[str, Any]] = []
    for source, records_of_source in reading.records.items():
        mapped, missing = map_events(records_of_source, routes)
        unmatched[source] = missing
        events.extend(mapped)
    reading.unmatched = unmatched
    reading.capacities = infer(events, now)
    # Every record publishes the events it could not place on a route. The
    # count is published, so an event that is never read is never hidden.
    for result in reading.results:
        if result.source in unmatched:
            result.metrics.append(
                (
                    "ghostship_ai_inference_unmatched_events",
                    {"source": result.source},
                    float(unmatched[result.source]),
                )
            )
    return reading


def quota_id_for(capacity: Mapping[str, Any]) -> str:
    """The quota id of the window an inferred capacity means."""
    state = str(capacity.get("state") or "")
    if state == STATE_NO_FAILURE:
        return QUOTA_ID_NO_FAILURE
    if state == STATE_EXHAUSTED:
        return QUOTA_ID_EXHAUSTED
    window = str(capacity.get("window") or "")
    return f"{QUOTA_ID_PREFIX}{window}" if window else QUOTA_ID_NO_FAILURE


def basis_for(capacity: Mapping[str, Any]) -> str:
    """The basis of the window an inferred capacity means."""
    if str(capacity.get("state") or "") == STATE_NO_FAILURE:
        return BASIS_NO_FAILURE
    episodes = capacity.get("episodes")
    count = int(episodes) if isinstance(episodes, (int, float)) and not isinstance(episodes, bool) else 0
    return f"inferred from {count} limit episodes"


def detail_for(capacity: Mapping[str, Any]) -> dict[str, Any]:
    """The inference behind a capacity, as plain data."""
    weights = capacity.get("weights")
    return {
        "window": capacity.get("window"),
        "budget": capacity.get("budget"),
        "unit": str(capacity.get("unit") or ""),
        "scope": str(capacity.get("scope") or ""),
        "weights": dict(weights) if isinstance(weights, Mapping) else {},
        "weights_basis": str(capacity.get("weights_basis") or ""),
        "episodes": int(capacity.get("episodes") or 0),
        "state": str(capacity.get("state") or ""),
    }


def window_for(capacity: Mapping[str, Any], now: float) -> Any:
    """The quota window one inferred capacity means.

    The window reads like the window of a route the provider publishes as
    unlimited: it carries a state instead of no state, and a route that was
    never refused has all of its allowance and no pace.
    """
    state = str(capacity.get("state") or STATE_NO_FAILURE)
    left = capacity.get("left")
    share = float(left) if isinstance(left, (int, float)) and not isinstance(left, bool) else 1.0
    used_ratio = max(0.0, min(1.0, 1.0 - share))
    reset = capacity.get("reset_at")
    duration = capacity.get("window_seconds")
    if state == STATE_EXHAUSTED:
        used_ratio = 1.0
    elif state == STATE_NO_FAILURE:
        # Nothing was refused, so nothing is measured: the route has all of
        # its allowance and no pace is claimed.
        used_ratio = 0.0
        reset = None
        duration = None
    return ranking_module.QuotaWindow(
        kind="inferred",
        used_ratio=used_ratio,
        reset_epoch=float(reset) if isinstance(reset, (int, float)) and not isinstance(reset, bool) else None,
        applies_to=(),
        quota_id=quota_id_for(capacity),
        duration_seconds=(
            float(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None
        ),
        observed_at=float(now),
        basis=basis_for(capacity),
        ends_at=None,
        gating=True,
        inference=detail_for(capacity),
    )


def key_for(capacity: Mapping[str, Any]) -> str:
    """The key the window of an inferred capacity is filed under.

    A limit that belongs to the model is keyed by the route, and a limit
    that belongs to the account is keyed by the provider: an account-wide
    budget is shared by the models of that account.
    """
    provider = str(capacity.get("provider") or "")
    model = str(capacity.get("model") or "")
    if str(capacity.get("scope") or "") == "model":
        return f"{provider}/{model}"
    return provider
