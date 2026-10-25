"""How well a free route's published limit reading predicted its refusals.

The owner's trust bar (`ghostship-agent` issue #462) is simple: a limit
reading is only trustworthy if it predicted the refusals that happened. This
module reads the same request record the inference reads and replays it: just
before every observed refusal and every observed run of successes, it asks
what the reading said, and it counts the two ways the reading can be wrong.

* A **false available** is a refusal that happened while the reading showed
  headroom. The route was offered and it refused.
* A **false exhausted** is a request that succeeded while the reading showed
  the route spent. The route was withheld and it worked.

The replay uses the inference itself (`inference.infer_capacity`) on the
record up to the observed request, so a change to the reading changes the
calibration with it. The counts are bucketed per day in the collector's own
zone, and the window is bounded: the trust view is the last two weeks.

The acceptance rule is checked daily: a route fails when its false-available
count is non-zero on the latest complete day. Earlier days remain in the
published history, but do not keep a route failing after a clean day.

This module reads no file and no network. It returns plain data.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

import inference

try:  # pragma: no cover - zoneinfo is present on NixOS
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

__all__ = [
    "ACCEPTANCE_SCHEMA",
    "DAY_ZONE",
    "WINDOW_DAYS",
    "build",
    "probe",
]

# The day boundary of the counts. It is the zone the collector's own usage
# buckets use, so a "day" reads the same on every page.
DAY_ZONE = "Pacific/Honolulu"

# The trust view covers two weeks: long enough for a streak and a trend, short
# enough that the replay stays a few seconds on a busy record.
WINDOW_DAYS = 14

# A bound on the replays of one provider: a record that holds more refusals
# than this is read at the newest ones, and the truncation is published.
MAX_OBSERVATIONS = 1500

ACCEPTANCE_SCHEMA = "ghostship.free-route-calibration/v1"

# The state a route's calibration can be in.
STATE_OK = "ok"
STATE_WARN = "warn"
STATE_FAIL = "fail"
STATE_UNMEASURED = "unmeasured"


def _zone(name: str):
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def _day(epoch: float, zone) -> str:
    return datetime.fromtimestamp(float(epoch), tz=zone).strftime("%Y-%m-%d")


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _blank_day() -> dict[str, int]:
    return {
        "refusals": 0,
        "successes": 0,
        "false_available": 0,
        "false_exhausted": 0,
    }


def _route_key(provider: str, model: str) -> str:
    return f"{provider}/{model}"


def _observations(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The points where the reading could be wrong.

    A refusal is one observation. A run of successes is one observation that
    carries how many requests it holds; it is evaluated at its first success,
    which is the request that can contradict a spent reading (the success
    itself corrects the reading).
    """
    ordered = sorted(
        (event for event in events if isinstance(event, Mapping)),
        key=lambda event: float(event.get("at") or 0.0),
    )
    points: list[dict[str, Any]] = []
    index = 0
    while index < len(ordered):
        event = ordered[index]
        outcome = str(event.get("outcome") or "")
        at = float(event.get("at") or 0.0)
        if outcome == "limit":
            points.append({"at": at, "kind": "limit", "count": 1})
            index += 1
            continue
        if outcome == "success":
            run_start = at
            run_count = 0
            while index < len(ordered):
                current = ordered[index]
                if str(current.get("outcome") or "") != "success":
                    break
                run_count += 1
                index += 1
            points.append({"at": run_start, "kind": "success", "count": run_count})
            continue
        index += 1
    return points


def _prediction(
    provider: str,
    model: str,
    prefix: Sequence[Mapping[str, Any]],
    moment: float,
) -> dict[str, Any] | None:
    """What the reading said about the route just before `moment`."""
    capacities = inference.infer_capacity(prefix, float(moment))
    capacity = capacities.get((provider, model))
    if capacity is None:
        return None
    return {"state": capacity.state, "left": capacity.left, "window": capacity.window}


def _provider_counts(
    provider: str,
    models: Iterable[str],
    events_by_model: Mapping[str, Sequence[Mapping[str, Any]]],
    zone,
    since: float,
) -> dict[str, dict[str, Any]]:
    """The daily and window counts of every free route of one provider.

    The replay is provider-wide: the reading of a route can depend on the
    other routes of its account, so the prefix the inference sees holds every
    route of the provider, and only the observed route is evaluated.
    """
    ordered = sorted(
        (
            event
            for events in events_by_model.values()
            for event in events
            if isinstance(event, Mapping)
        ),
        key=lambda event: float(event.get("at") or 0.0),
    )
    observations: list[tuple[float, str, dict[str, Any]]] = []
    truncated: dict[str, bool] = {}
    for model in models:
        points = [
            point
            for point in _observations(events_by_model.get(model) or ())
            if float(point["at"]) >= since
        ]
        truncated[model] = len(points) > MAX_OBSERVATIONS
        if truncated[model]:
            points = points[-MAX_OBSERVATIONS:]
        for point in points:
            observations.append((float(point["at"]), model, point))
    observations.sort(key=lambda item: (item[0], item[1]))

    days: dict[str, dict[str, dict[str, int]]] = {
        model: {} for model in events_by_model
    }
    totals: dict[str, dict[str, int]] = {
        model: _blank_day() for model in events_by_model
    }
    prefix: list[Mapping[str, Any]] = []
    cursor = 0
    for at, model, point in observations:
        while cursor < len(ordered) and float(ordered[cursor].get("at") or 0.0) < at:
            prefix.append(ordered[cursor])
            cursor += 1
        prediction = _prediction(provider, model, prefix, at)
        bucket = days[model].setdefault(_day(at, zone), _blank_day())
        counts = totals[model]
        if point["kind"] == "limit":
            counts["refusals"] += 1
            bucket["refusals"] += 1
            # A refusal met a reading that offered the route. A prediction
            # with no count at all (no reading yet) is not a claim of
            # headroom, so it is not counted against the reading.
            if prediction is not None and prediction["state"] in (
                "no_failure",
                "in_window",
            ):
                left = prediction.get("left")
                if left is None or float(left) > 0.0:
                    counts["false_available"] += 1
                    bucket["false_available"] += 1
            continue
        counts["successes"] += point["count"]
        bucket["successes"] += point["count"]
        if prediction is not None and prediction["state"] == "exhausted":
            # Only the first success of a run can contradict the reading: the
            # success itself is the recovery, so every later request of the
            # run met a reading that had already been corrected.
            counts["false_exhausted"] += 1
            bucket["false_exhausted"] += 1
    return {
        model: {
            "days": days.get(model) or {},
            "totals": totals.get(model) or _blank_day(),
            "truncated": bool(truncated.get(model)),
        }
        for model in events_by_model
    }


def _streak(day_keys: Sequence[str], days: Mapping[str, Mapping[str, int]]) -> int:
    """The consecutive complete days with a false available, ending latest."""
    streak = 0
    for day in reversed(list(day_keys)):
        if (days.get(day) or {}).get("false_available", 0) > 0:
            streak += 1
        else:
            break
    return streak


def _complete_days(now: float, zone, window_days: int) -> list[str]:
    """The day keys of the window, oldest first, ending with the last complete one."""
    today = _day(now, zone)
    keys: list[str] = []
    moment = now
    for _ in range(window_days + 1):
        key = _day(moment, zone)
        if key != today:
            keys.append(key)
        moment -= 86400.0
    return list(reversed(keys))


def build(
    events: Iterable[Mapping[str, Any]],
    routes: Iterable[tuple[str, str]],
    now: float,
    *,
    window_days: int = WINDOW_DAYS,
    day_zone: str = DAY_ZONE,
) -> dict[str, Any]:
    """The calibration of every free route the collector publishes.

    `events` is the mapped request record (the same events the inference
    reads), `routes` the free routes of the inventory, `now` the reading
    instant. Every route in the inventory is published, even one with no
    evidence: it reads `unmeasured`, never `ok`.
    """
    zone = _zone(day_zone)
    moment = float(now)
    since = moment - float(window_days) * 86400.0
    by_provider: dict[str, dict[tuple[str, str], list[Mapping[str, Any]]]] = {}
    for event in events or ():
        if not isinstance(event, Mapping):
            continue
        at = event.get("at")
        if isinstance(at, bool) or not isinstance(at, (int, float)):
            continue
        if float(at) < since or float(at) > moment:
            continue
        provider = str(event.get("provider") or "")
        model = str(event.get("model") or "")
        by_provider.setdefault(provider, {}).setdefault((provider, model), []).append(event)

    complete = _complete_days(moment, zone, window_days)
    checked_days = complete[-1:]
    checked_day = checked_days[0] if checked_days else None
    published: dict[str, Any] = {}
    failed: list[str] = []
    routes_by_provider: dict[str, set[str]] = {}
    for provider, model in routes or ():
        routes_by_provider.setdefault(str(provider), set()).add(str(model))
    for provider in sorted(routes_by_provider):
        models = routes_by_provider[provider]
        events_by_model = {
            model: by_provider.get(provider, {}).get((provider, model), [])
            for model in models
        }
        counted_by_model = _provider_counts(
            provider, models, events_by_model, zone, since
        )
        for model in sorted(models):
            counted = counted_by_model.get(model) or {
                "days": {},
                "totals": _blank_day(),
                "truncated": False,
            }
            day_rows = counted["days"]
            totals = counted["totals"]
            streak = _streak(complete, day_rows)
            observed = totals["refusals"] + totals["successes"]
            if checked_day and (day_rows.get(checked_day) or {}).get("false_available", 0) > 0:
                state = STATE_FAIL
                failed.append(_route_key(provider, model))
            elif totals["false_available"] or totals["false_exhausted"]:
                state = STATE_WARN
            elif observed == 0:
                state = STATE_UNMEASURED
            else:
                state = STATE_OK
            published[_route_key(provider, model)] = {
                "provider": provider,
                "model": model,
                "state": state,
                "days": {day: day_rows[day] for day in sorted(day_rows)},
                "window": dict(totals),
                "false_available_streak_days": streak,
                "truncated": bool(counted["truncated"]),
            }

    if failed:
        acceptance = {
            "state": "fail",
            "reason": "a free route refused while it read available on the latest complete day",
            "failed_routes": sorted(failed),
            "checked_days": checked_days,
        }
    else:
        acceptance = {
            "state": "ok",
            "reason": "",
            "failed_routes": [],
            "checked_days": checked_days,
        }
    return {
        "schema": ACCEPTANCE_SCHEMA,
        "generated_at": _iso(moment),
        "day_zone": day_zone,
        "window_days": int(window_days),
        "days": complete,
        "routes": published,
        "acceptance": acceptance,
    }


def probe(document: Mapping[str, Any] | None) -> tuple[bool, str]:
    """Whether the published calibration passes the owner's acceptance rule.

    The probe fails when the acceptance state is not `ok`, including when the
    document carries no calibration at all: a reading that cannot be checked
    is not a passing one.
    """
    if not isinstance(document, Mapping):
        return (False, "no calibration in the snapshot")
    calibration = document.get("free_calibration")
    if not isinstance(calibration, Mapping):
        return (False, "no free calibration in the snapshot")
    acceptance = calibration.get("acceptance")
    if not isinstance(acceptance, Mapping):
        return (False, "the calibration carries no acceptance")
    if str(acceptance.get("state") or "") != "ok":
        routes = ", ".join(str(route) for route in acceptance.get("failed_routes") or ())
        reason = str(acceptance.get("reason") or "the acceptance rule failed")
        return (False, f"{reason}: {routes}" if routes else reason)
    return (True, "every free route's refusals matched its reading")
