"""Inferred capacity for the routes that report no usage.

Some providers publish nothing: no usage API, no balance, no rate-limit
headers. Every free route is in the same position. The owner rule
(`config/agents/routing-policy.md`, section "Usage measurement") reads their
capacity from the failures instead: a route that runs until it is refused
shows its window, its budget and its remaining share in the refusals it
produced.

This module is the computation and nothing else. It takes the events of a
record and returns, per route, the capacity that the record implies. It reads
no file, no database and no network, and it is not wired into the collector
yet: the readers and the publication come later, against this interface.

The record is a list of events, each with a provider, a model, a time, an
outcome (`success`, `limit` or `other`), the usage it carried (tokens, or
None when the run reported none) and an optional window hint.

    events = [
        {"provider": "acme", "model": "sonnet", "at": 1767571200.0,
         "outcome": "success", "usage": 200000.0, "window_hint": None},
        ...
    ]
    capacity = inference.infer_capacity(events, now=1767572400.0)
    capacity[("acme", "sonnet")].left

The rules, in short:

* An episode runs from the first use after the previous recovery (`s`) to the
  first limit (`f`) to the first success after that limit (`r`). An episode
  without a recovery is open and counts for nothing. A refusal that opens the
  record of a group is the refusal of the group itself, so the episode starts
  at that refusal: the use before it is not in the record.
* The window `W` is the hint on the limit when it names one, otherwise the
  time from `s` to `r` snapped to the nearest standard window. Over the last
  five episodes the most common window wins.
* The budget `B` is the median usage of `[s, f)` over the episodes of that
  window.
* The share left is `1 - u / B`, where `u` is the usage since the start of
  the current window, and the share a perfectly even spend would have left is
  `1 - (now - start) / W`. Their difference is the Paced Availability.
* The scope says whether the limit belongs to the model or to the account. The
  evidence is the episodes of the account group, the open one included: a
  route that was refused and never recovered has an episode too, and the use
  of another model of the provider after that refusal says that the limit was
  the model's own. The span of a completed episode starts at its refusal, and
  the span of an open episode starts after it, so a refusal is never evidence
  of the scope by itself. A scope of `unknown` is computed across the account
  and labelled unknown.
* Only the routes that were refused join an account group. A route that was
  never refused has no limit of its own: it is measured on its own, with its
  whole allowance and no pace, and its use never ends the episode of another
  route.
* An account-wide budget is shared between the models of the provider, either
  with equal weights or with weights fitted from the episodes. The weights are
  fitted only when the episodes of the account involve at least two models with
  usage and there are more episodes than those models. An account that carries
  usage in a single model is never fitted: it has nothing to share, and its
  budget stays the median usage of its episodes in its own unit.

The names, the states and the fields follow the owner rule; the tests in
`tests/test_ai_usage_inference.py` pin every worked value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "RouteCapacity",
    "STANDARD_WINDOWS",
    "UsageEvent",
    "WINDOW_SECONDS",
    "infer_capacity",
    "snap_window",
]

# The standard windows a limit is snapped to. The labels are the ones the
# limit hints use, so a hint and a snapped window never read differently.
STANDARD_WINDOWS: tuple[tuple[str, float], ...] = (
    ("1m", 60.0),
    ("1h", 3600.0),
    ("5h", 18000.0),
    ("1d", 86400.0),
    ("7d", 604800.0),
    ("30d", 2592000.0),
)
WINDOW_SECONDS: Mapping[str, float] = dict(STANDARD_WINDOWS)

# How many of the last episodes decide the window and the scope.
EPISODE_HISTORY = 5

# A group is measured in tokens when at least this share of its successes
# carry a usage reading; otherwise it is measured in requests.
TOKEN_COVERAGE = 0.95

# The fit enumerates the subsets of the models, so it is only run while the
# mix is small. A wider mix falls back to a projected gradient.
FIT_MODEL_LIMIT = 12


@dataclass(frozen=True)
class UsageEvent:
    """One recorded use of a route."""

    provider: str
    model: str
    at: float
    outcome: str = "success"
    usage: float | None = None
    window_hint: str | None = None


@dataclass(frozen=True)
class RouteCapacity:
    """The capacity one route's record implies."""

    provider: str
    model: str
    basis: str = "inferred"
    state: str = "no_failure"
    left: float = 1.0
    expected_left: float | None = None
    paced_availability: float | None = None
    window: str | None = None
    window_seconds: float | None = None
    start_at: float | None = None
    reset_at: float | None = None
    budget: float | None = None
    unit: str = "requests"
    scope: str = "unknown"
    weights: Mapping[str, float] = field(default_factory=dict)
    weights_basis: str = "assumed"
    episodes: int = 0
    share: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """The result as plain data."""
        return {
            "provider": self.provider,
            "model": self.model,
            "basis": self.basis,
            "state": self.state,
            "left": self.left,
            "expected_left": self.expected_left,
            "paced_availability": self.paced_availability,
            "window": self.window,
            "window_seconds": self.window_seconds,
            "start_at": self.start_at,
            "reset_at": self.reset_at,
            "budget": self.budget,
            "unit": self.unit,
            "scope": self.scope,
            "weights": dict(self.weights),
            "weights_basis": self.weights_basis,
            "episodes": self.episodes,
            "share": self.share,
        }

    def keys(self) -> tuple[str, ...]:
        return tuple(self.as_dict())

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.as_dict().get(key, default)


@dataclass(frozen=True)
class _Event:
    provider: str
    model: str
    at: float
    outcome: str
    usage: float | None
    window_hint: str | None
    order: int


@dataclass
class _Episode:
    """One run of a route up to its limit and back."""

    start_at: float
    limit_at: float
    recovery_at: float | None
    window: str
    window_seconds: float
    per_model: dict[str, float]
    usage: float


def snap_window(duration_seconds: float) -> str:
    """The standard window nearest to a duration, by ratio.

    The distance is measured on the logarithm, so a duration sits between two
    windows where their ratios are closest. A tie keeps the shorter window.
    """
    return _snap(duration_seconds)[0]


def _snap(duration_seconds: float) -> tuple[str, float]:
    try:
        duration = float(duration_seconds)
    except (TypeError, ValueError):
        return ("1m", 60.0)
    if not math.isfinite(duration) or duration <= 0:
        return ("1m", 60.0)
    best: tuple[tuple[float, float], str, float] | None = None
    for label, seconds in STANDARD_WINDOWS:
        key = (abs(math.log(duration / seconds)), seconds)
        if best is None or key < best[0]:
            best = (key, label, seconds)
    assert best is not None
    return (best[1], best[2])


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _get(source: Any, name: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def _normalize(raw: Any, order: int) -> _Event | None:
    provider = _get(raw, "provider")
    model = _get(raw, "model")
    at = _get(raw, "at")
    if provider is None or model is None or at is None:
        return None
    try:
        moment = float(at)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(moment):
        return None
    outcome = _get(raw, "outcome") or "success"
    usage = _get(raw, "usage")
    if usage is not None:
        try:
            usage = float(usage)
        except (TypeError, ValueError):
            usage = None
        if usage is not None and not math.isfinite(usage):
            usage = None
    hint = _get(raw, "window_hint")
    hint = str(hint) if hint else None
    if hint not in WINDOW_SECONDS:
        hint = None
    return _Event(
        provider=str(provider),
        model=str(model),
        at=moment,
        outcome=str(outcome),
        usage=usage,
        window_hint=hint,
        order=order,
    )


def _unit_of(events: Sequence[_Event]) -> str:
    """Tokens when nearly every success carries a usage, requests otherwise."""
    successes = [event for event in events if event.outcome == "success"]
    if not successes:
        return "requests"
    measured = sum(1 for event in successes if event.usage is not None)
    return "tokens" if measured / len(successes) >= TOKEN_COVERAGE else "requests"


def _episode_usage(events: Sequence[_Event], unit: str) -> tuple[float, dict[str, float]]:
    """The usage of a span, and its share per model."""
    if unit == "tokens":
        total = 0.0
        per_model: dict[str, float] = {}
        for event in events:
            if event.usage is None:
                continue
            total += event.usage
            per_model[event.model] = per_model.get(event.model, 0.0) + event.usage
        return total, per_model
    total = 0.0
    per_model = {}
    for event in events:
        if event.outcome != "success":
            continue
        total += 1.0
        per_model[event.model] = per_model.get(event.model, 0.0) + 1.0
    return total, per_model


def _scan_episodes(events: Sequence[_Event], unit: str) -> tuple[list[_Episode], _Episode | None]:
    """The completed episodes of a group and its open one, if it has one.

    An `other` outcome (a concurrency error, a transient upstream failure)
    starts and ends nothing, so it is skipped when the start of an episode is
    looked for.

    A refusal that opens the record of a group is the refusal of the group
    itself: the use before it is not in the record, so the episode starts at
    the refusal and the refusal of one route is the refusal of the account
    for the routes that did not produce it.
    """
    completed: list[_Episode] = []
    open_episode: _Episode | None = None
    index = 0
    total = len(events)
    while index < total:
        while index < total and events[index].outcome == "other":
            index += 1
        if index >= total:
            break
        start = events[index]
        if start.outcome == "limit":
            limit_index = index
        else:
            limit_index = index + 1
            while limit_index < total and events[limit_index].outcome != "limit":
                limit_index += 1
            if limit_index >= total:
                break
        limit = events[limit_index]
        recovery_index = limit_index + 1
        while recovery_index < total and events[recovery_index].outcome != "success":
            recovery_index += 1
        span = [event for event in events if start.at <= event.at < limit.at]
        usage, per_model = _episode_usage(span, unit)
        if limit.window_hint:
            label = limit.window_hint
            seconds = WINDOW_SECONDS[label]
        else:
            if recovery_index >= total:
                label, seconds = ("", 0.0)
            else:
                label, seconds = _snap(events[recovery_index].at - start.at)
        if recovery_index >= total:
            open_episode = _Episode(
                start_at=start.at,
                limit_at=limit.at,
                recovery_at=None,
                window=label,
                window_seconds=seconds,
                per_model=per_model,
                usage=usage,
            )
            break
        recovery = events[recovery_index]
        completed.append(
            _Episode(
                start_at=start.at,
                limit_at=limit.at,
                recovery_at=recovery.at,
                window=label,
                window_seconds=seconds,
                per_model=per_model,
                usage=usage,
            )
        )
        index = recovery_index + 1
    return completed, open_episode


def _choose_window(episodes: Sequence[_Episode]) -> tuple[str | None, float | None]:
    """The window of the last episodes: the most common one wins.

    A tie keeps the window of the most recent episode.
    """
    if not episodes:
        return (None, None)
    recent = episodes[-EPISODE_HISTORY:]
    counts: dict[str, int] = {}
    for episode in recent:
        counts[episode.window] = counts.get(episode.window, 0) + 1
    best = max(counts.values())
    chosen = recent[-1].window
    for episode in reversed(recent):
        if counts.get(episode.window, 0) == best:
            chosen = episode.window
            break
    return (chosen, WINDOW_SECONDS.get(chosen))


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (float(ordered[middle - 1]) + float(ordered[middle])) / 2.0


def _solve_linear(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    """Solve a small dense system, or None when it has no unique answer."""
    size = len(matrix)
    scale = max((abs(value) for row in matrix for value in row), default=0.0)
    if scale <= 0.0:
        return None
    rows = [list(matrix[index]) + [rhs[index]] for index in range(size)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda row: abs(rows[row][col]))
        if abs(rows[pivot][col]) <= 1e-12 * scale:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        head = rows[col][col]
        for row in range(size):
            if row == col:
                continue
            factor = rows[row][col] / head
            if factor == 0.0:
                continue
            for column in range(col, size + 1):
                rows[row][column] -= factor * rows[col][column]
    return [rows[index][size] / rows[index][index] for index in range(size)]


def _non_negative_least_squares(rows: Sequence[Sequence[float]], target: float) -> list[float]:
    """The weights that fit `target` from the usage rows, never below zero.

    The mix is small, so every subset of the models is tried and the best
    answer that is non-negative and satisfies the optimality conditions
    wins. A wider mix falls back to a projected gradient.
    """
    if not rows:
        return []
    models = len(rows[0])
    if models == 0:
        return []
    if models > FIT_MODEL_LIMIT:
        return _projected_gradient(rows, target)
    gram = [
        [sum(row[left] * row[right] for row in rows) for right in range(models)]
        for left in range(models)
    ]
    moment = [sum(row[left] * target for row in rows) for left in range(models)]
    best: tuple[tuple[int, float], list[float]] | None = None
    for mask in range(1 << models):
        chosen = [index for index in range(models) if (mask >> index) & 1]
        weights = [0.0] * models
        if chosen:
            solution = _solve_linear(
                [[gram[left][right] for right in chosen] for left in chosen],
                [moment[index] for index in chosen],
            )
            if solution is None:
                continue
            if any(value < -1e-9 for value in solution):
                continue
            for index, value in zip(chosen, solution):
                weights[index] = max(0.0, value)
        objective = 0.0
        gradient = [0.0] * models
        for row in rows:
            predicted = sum(weights[index] * row[index] for index in range(models))
            residual = predicted - target
            objective += residual * residual
            for index in range(models):
                gradient[index] += row[index] * residual
        optimal = all(
            gradient[index] >= -1e-9 for index in range(models) if index not in chosen
        )
        key = (0 if optimal else 1, objective)
        if best is None or key < best[0]:
            best = (key, weights)
    return best[1] if best is not None else [0.0] * models


def _projected_gradient(rows: Sequence[Sequence[float]], target: float) -> list[float]:
    """A slow but safe fallback for a mix that is too wide to enumerate."""
    models = len(rows[0])
    weights = [0.0] * models
    limit = 2.0 * sum(
        row[left] * row[right]
        for row in rows
        for left in range(models)
        for right in range(models)
    )
    if limit <= 0.0:
        return weights
    step = 1.0 / limit
    for _ in range(100000):
        gradient = [0.0] * models
        for row in rows:
            predicted = sum(weights[index] * row[index] for index in range(models))
            residual = predicted - target
            for index in range(models):
                gradient[index] += row[index] * residual
        moved = 0.0
        for index in range(models):
            updated = max(0.0, weights[index] - step * gradient[index])
            moved = max(moved, abs(updated - weights[index]))
            weights[index] = updated
        if moved < 1e-12:
            break
    return weights


class _Group:
    """The events of one route, or of one whole provider, and what they say."""

    def __init__(self, events: Sequence[_Event], now: float) -> None:
        self.events = list(events)
        self.now = now
        self.unit = _unit_of(self.events)
        self.completed, self.open_episode = _scan_episodes(self.events, self.unit)
        self.window, self.window_seconds = _choose_window(self.completed)
        self.models = sorted({event.model for event in self.events})
        self.weights: dict[str, float] = {model: 1.0 for model in self.models}
        self.weights_basis = "assumed"

    # -- the episodes -----------------------------------------------------

    def weighted_episode_usage(self, episode: _Episode) -> float:
        return sum(
            self.weights.get(model, 0.0) * value
            for model, value in episode.per_model.items()
        )

    def budget(self) -> float | None:
        """The median usage of the episodes of the chosen window.

        A fitted group carries a normalised budget: the weights are fitted so
        that each episode of the account adds up to one budget, so the budget
        of the group is one and the share left is read against it.
        """
        if not self.completed or self.window is None:
            return None
        if self.weights_basis == "fitted":
            return 1.0
        values = [
            self.weighted_episode_usage(episode)
            for episode in self.completed
            if episode.window == self.window
        ]
        if not values:
            return None
        return _median(values)

    # -- the current window ----------------------------------------------

    def _last_recovery(self) -> float | None:
        recoveries = [
            episode.recovery_at
            for episode in self.completed
            if episode.recovery_at is not None
        ]
        return max(recoveries) if recoveries else None

    def _window_events(self, recovery: float | None) -> list[_Event]:
        if recovery is None:
            return [event for event in self.events if event.at <= self.now]
        return [
            event
            for event in self.events
            if recovery < event.at <= self.now
        ]

    def current_usage(self, events: Sequence[_Event], start: float) -> tuple[float, dict[str, float]]:
        """The usage since the start of the current window, and per model."""
        total = 0.0
        per_model: dict[str, float] = {}
        if self.unit == "tokens":
            for event in events:
                if event.at < start or event.usage is None:
                    continue
                total += event.usage
                per_model[event.model] = per_model.get(event.model, 0.0) + event.usage
        else:
            for event in events:
                if event.at < start or event.outcome != "success":
                    continue
                total += 1.0
                per_model[event.model] = per_model.get(event.model, 0.0) + 1.0
        return total, per_model

    def tile(self, start: float, events: Sequence[_Event]) -> float:
        """Move the start of the window forward over the windows that ended."""
        if self.window_seconds is None:
            return start
        current = start
        while self.now >= current + self.window_seconds:
            following = [
                event.at for event in events if event.at >= current + self.window_seconds
            ]
            if following:
                current = min(following)
                continue
            # No use in the window that ended: the window still rolled over.
            current += self.window_seconds
        return current

    def state(self) -> str:
        limits = [event.at for event in self.events if event.outcome == "limit"]
        if not limits:
            return "no_failure"
        successes = [event.at for event in self.events if event.outcome == "success"]
        if not successes or max(limits) > max(successes):
            return "exhausted"
        return "in_window"

    def current_window(self) -> tuple[float, list[_Event]]:
        """The start of the current window and the events inside it."""
        recovery = self._last_recovery()
        events = self._window_events(recovery)
        if events:
            return events[0].at, events
        if recovery is not None:
            return recovery, events
        return (self.events[0].at if self.events else self.now), events


def _route_scope(group: _Group, provider_events: Sequence[_Event], model: str) -> str:
    """Whether the limit of a route belongs to its model or to its account.

    The evidence is the episodes of the account group the route belongs to,
    the open one included: a route that was refused and never recovered has
    an episode too, and the use of the other models after that refusal is the
    evidence that the refusal was the model's own.

    The span of an episode runs from its refusal to its recovery, and the
    span of an open episode runs from after its refusal to the reading.
    Another model of the provider that succeeds inside the span means the
    limit was the model's own. Other models that only fail in that span mean
    the limit was the account's. No other model in the span means the scope
    is unknown, which is measured across the account and labelled unknown.

    The span of a completed episode starts at the refusal itself: the
    refusal of the group is the refusal of another model for the routes that
    did not produce it, and two models that are refused at the same instant
    share the allowance. The span of an open episode starts after its
    refusal, so the refusal itself is never evidence of the scope.

    The scope of the route is the most common over the last five episodes of
    the group, the open one included. A tie reads as account.
    """
    episodes = list(group.completed)
    if group.open_episode is not None:
        episodes.append(group.open_episode)
    if not episodes:
        return "unknown"
    counts: dict[str, int] = {}
    for episode in episodes[-EPISODE_HISTORY:]:
        if episode.recovery_at is None:
            span = [
                event
                for event in provider_events
                if episode.limit_at < event.at <= group.now
                and event.model != model
            ]
        else:
            span = [
                event
                for event in provider_events
                if episode.limit_at <= event.at < episode.recovery_at
                and event.model != model
            ]
        if any(event.outcome == "success" for event in span):
            scope = "model"
        elif span and all(event.outcome == "limit" for event in span):
            scope = "account"
        else:
            scope = "unknown"
        counts[scope] = counts.get(scope, 0) + 1
    best = max(counts.values())
    tied = [scope for scope, count in counts.items() if count == best]
    if len(tied) == 1:
        return tied[0]
    return "account"


def _fit_account_weights(group: _Group) -> None:
    """The weights of an account-wide budget.

    While there are fewer episodes than models in the mix the weights are
    equal, and the basis says so. Once there are more episodes the weights
    are fitted, never below zero, so that each episode of the account adds up
    to one budget.

    An account that carries usage in a single model is never fitted: there is
    nothing to share between the models, and the budget of such an account
    stays the median usage of its episodes in its own unit, exactly like the
    budget of a route that carries its own limit.
    """
    models = group.models
    used = [
        model
        for model in models
        if sum(episode.per_model.get(model, 0.0) for episode in group.completed) > 0
    ]
    if len(used) >= 2 and len(group.completed) > len(used):
        rows = [
            [episode.per_model.get(model, 0.0) for model in used]
            for episode in group.completed
        ]
        fitted = _non_negative_least_squares(rows, 1.0)
        weights = {model: 0.0 for model in models}
        for index, model in enumerate(used):
            weights[model] = max(0.0, fitted[index]) if index < len(fitted) else 0.0
        group.weights = weights
        group.weights_basis = "fitted"
    else:
        group.weights = {model: 1.0 for model in models}
        group.weights_basis = "assumed"


def _capacity_of(
    group: _Group,
    provider: str,
    model: str,
    scope: str,
    share_model: str | None,
) -> RouteCapacity:
    """The capacity one group implies for one route.

    `share_model` is the model whose share of the account is reported. It is
    None for a route whose limit is its own, because such a route shares no
    budget with the other models of the provider.
    """
    state = group.state()
    start, window_events = group.current_window()
    budget = group.budget()
    if scope == "model":
        weights = {model: 1.0}
        weights_basis = "assumed"
    else:
        weights = dict(group.weights)
        weights_basis = group.weights_basis

    window = group.window
    window_seconds = group.window_seconds
    reset_at: float | None = None
    expected_left: float | None = None
    paced: float | None = None
    left = 1.0

    if state == "in_window" and window_seconds is not None:
        # The window that ended while nobody used the route is over: the
        # start moves to the next use.
        start = group.tile(start, window_events)

    _, per_model = group.current_usage(window_events, start)
    weighted = {
        name: weights.get(name, 0.0) * value for name, value in per_model.items()
    }
    usage = sum(weighted.values())

    if state == "no_failure":
        # Nothing was refused, so nothing is measured: the route has all of
        # its allowance and no pace is claimed.
        window = None
        window_seconds = None
        budget = None
    elif state == "exhausted":
        # The last refusal has no recovery behind it: the route is spent.
        # The window that is spent is the open episode's own window, so the
        # reset is the end of that episode's window.
        if group.open_episode is not None:
            start = group.open_episode.start_at
        left = 0.0
        if window_seconds is not None:
            reset_at = start + window_seconds
            expected_left = _clamp01(1.0 - (group.now - start) / window_seconds)
            paced = left - expected_left
    else:
        if budget is not None and budget > 0:
            left = max(0.0, 1.0 - usage / budget)
        if window_seconds is not None:
            reset_at = start + window_seconds
            expected_left = _clamp01(1.0 - (group.now - start) / window_seconds)
            paced = left - expected_left

    share: float | None = None
    if share_model is not None and usage > 0:
        share = weighted.get(share_model, 0.0) / usage

    return RouteCapacity(
        provider=provider,
        model=model,
        basis="inferred",
        state=state,
        left=left,
        expected_left=expected_left,
        paced_availability=paced,
        window=window,
        window_seconds=window_seconds,
        start_at=start,
        reset_at=reset_at,
        budget=budget,
        unit=group.unit,
        scope=scope,
        weights=weights,
        weights_basis=weights_basis,
        episodes=len(group.completed),
        share=share,
    )


def infer_capacity(events: Iterable[Any], now: float) -> dict[tuple[str, str], RouteCapacity]:
    """The capacity the record implies for every route it touches.

    `events` is a list of recorded uses. Each one carries a provider, a
    model, a time, an outcome (`success`, `limit` or `other`), the usage it
    carried and an optional window hint. `now` is the instant the reading is
    taken at; the events after it are not part of the record yet.

    The result maps every route that has at least one event to the capacity
    that route's record implies.
    """
    moment = float(now)
    prepared: list[_Event] = []
    for order, raw in enumerate(events):
        normalized = _normalize(raw, order)
        if normalized is None:
            continue
        if normalized.at > moment:
            continue
        prepared.append(normalized)
    prepared.sort(key=lambda event: (event.at, event.order))

    provider_events: dict[str, list[_Event]] = {}
    route_events: dict[tuple[str, str], list[_Event]] = {}
    for event in prepared:
        provider_events.setdefault(event.provider, []).append(event)
        route_events.setdefault((event.provider, event.model), []).append(event)

    # Only the routes that were refused join an account group. A route that
    # was never refused has no limit of its own: it is measured on its own,
    # and its use never ends the episode of another route.
    refused = {
        key
        for key, events_of_route in route_events.items()
        if any(event.outcome == "limit" for event in events_of_route)
    }

    account_groups: dict[str, _Group] = {}
    for provider in provider_events:
        merged = [
            event
            for key, events_of_route in route_events.items()
            if key[0] == provider and key in refused
            for event in events_of_route
        ]
        merged.sort(key=lambda event: (event.at, event.order))
        group = _Group(merged, moment)
        _fit_account_weights(group)
        account_groups[provider] = group

    results: dict[tuple[str, str], RouteCapacity] = {}
    for (provider, model), events_of_route in route_events.items():
        route_group = _Group(events_of_route, moment)
        if (provider, model) not in refused:
            # A route that was never refused is measured on its own: it has
            # all of its allowance and it never joins an account.
            results[(provider, model)] = _capacity_of(
                route_group, provider, model, "unknown", None
            )
            continue
        account_group = account_groups[provider]
        scope = _route_scope(account_group, provider_events[provider], model)
        if scope == "model":
            results[(provider, model)] = _capacity_of(
                route_group, provider, model, scope, None
            )
            continue
        results[(provider, model)] = _capacity_of(
            account_group, provider, model, scope, model
        )
    return results
