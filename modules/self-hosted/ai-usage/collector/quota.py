"""The pace of a subscription window, and the metrics that publish it.

A window has a length and a reset. The share of the window that has elapsed
is the share of the allowance a perfectly even spend would have used by now:

    expected = clamp(1 - (reset - now) / duration, 0, 1)

A seven day window that resets in five days has used 1 - 5/7 = 2/7, so an
even spend would be at 28.57% used. The pace is the difference between that
line and the measured usage:

    pace = expected - used

A positive pace means the account is behind the line (it has spare budget); a
negative pace means it is ahead of the line (it is spending faster than the
window refills).

The rules:

* a window without a length, without a reset, with a stale reading, or with a
  reset in the past has no pace: no pace is invented, and an unknown pace is
  never published as zero;
* when several windows apply, the most constraining one is the smallest pace,
  because that is the window that runs out first (the stock client takes the
  same elapsed share; see packages/shared/src/usageLimits.ts);
* the labels are the ones the quota metrics already use: provider, account,
  model, window, quota, source, so a window is never mixed with another.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

# A reading older than this has no pace: the collector reads every five
# minutes, and half an hour is a generous bound.
STALE_AFTER_SECONDS = 1800.0

# A reading from the future is not a reading.
FUTURE_TOLERANCE_SECONDS = 60.0


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _get(item: Any, *names: str) -> Any:
    for name in names:
        value = getattr(item, name, None)
        if value is None and isinstance(item, Mapping):
            value = item.get(name)
        if value is not None:
            return value
    return None


def window_pace(window: Any, now: float) -> dict[str, Any] | None:
    """The pace of one window, or None when it cannot be known."""
    duration = _finite(_get(window, "duration_seconds", "durationSeconds"))
    reset = _finite(_get(window, "reset_epoch", "resetEpoch"))
    used = _finite(_get(window, "used_ratio", "usedRatio"))
    observed = _finite(_get(window, "observed_at", "observedAtEpoch"))
    if duration is None or duration <= 0 or reset is None or used is None:
        return None
    if observed is None or (now - observed) > STALE_AFTER_SECONDS:
        return None
    if observed > now + FUTURE_TOLERANCE_SECONDS:
        return None
    if reset <= now:
        # The window has already reset: the reading belongs to a window that
        # is over.
        return None
    expected = max(0.0, min(1.0, 1.0 - (reset - now) / duration))
    return {
        "provider": str(_get(window, "provider") or ""),
        "account": str(_get(window, "account") or "default"),
        "model": str(_get(window, "model") or "*"),
        "window": str(_get(window, "kind") or "other"),
        "quota": str(_get(window, "quota_id", "quotaId") or "default"),
        "source": str(_get(window, "source") or ""),
        "duration_seconds": duration,
        "expected_used_ratio": expected,
        "used_ratio": used,
        "pace_delta_ratio": expected - used,
        "reset_epoch": reset,
        "observed_at": observed,
    }


def model_pace(windows: Iterable[Any], now: float) -> dict[str, Any] | None:
    """The most constraining pace among the windows that apply to a model.

    The most constraining window is the one with the smallest pace: it is the
    window that runs out first, even when another window has a higher usage.
    """
    paces = [pace for pace in (window_pace(window, now) for window in windows or ()) if pace]
    if not paces:
        return None
    return min(paces, key=lambda pace: pace["pace_delta_ratio"])


def quota_pace_samples(windows: Iterable[Any], now: float) -> list[tuple[str, dict[str, str], float]]:
    """The pace metrics of every measured window, under the quota labels.

    A window can be read by more than one source, for example the provider's
    own API and the T3 Code status. The freshest reading of one window wins,
    so a series is never doubled.
    """
    freshest: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for window in windows or ():
        pace = window_pace(window, now)
        if pace is None:
            continue
        key = (
            pace["provider"],
            pace["account"],
            pace["model"],
            pace["window"],
            pace["quota"],
        )
        current = freshest.get(key)
        if current is None or pace["observed_at"] >= current["observed_at"]:
            freshest[key] = pace
    samples: list[tuple[str, dict[str, str], float]] = []
    for pace in freshest.values():
        labels = {
            "provider": pace["provider"],
            "account": pace["account"],
            "model": pace["model"],
            "window": pace["window"],
            "quota": pace["quota"],
            "source": pace["source"],
        }
        samples.append(("ghostship_ai_quota_duration_seconds", labels, pace["duration_seconds"]))
        samples.append(
            ("ghostship_ai_quota_expected_used_ratio", labels, pace["expected_used_ratio"])
        )
        samples.append(
            ("ghostship_ai_quota_pace_delta_ratio", labels, pace["pace_delta_ratio"])
        )
    return samples
