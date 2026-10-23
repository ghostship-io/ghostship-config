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

* session, hourly and daily windows never have a pace; only weekly/monthly
  periods have an even-spend line, including inferred periods of that length;
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
import pools
from typing import Any, Iterable, Mapping

# A reading older than this has no pace: the collector reads every five
# minutes, and half an hour is a generous bound.
STALE_AFTER_SECONDS = 1800.0

# A reading from the future is not a reading.
FUTURE_TOLERANCE_SECONDS = 60.0

# The scope of a quota window: the model families it applies to. A window
# that names a family only applies to the models of that family; every
# other window applies to the whole account.
WINDOW_SCOPES = (
    ("3p-", ("claude", "gpt")),
    ("gemini-", ("gemini",)),
    ("fable", ("fable",)),
    ("sonnet", ("sonnet",)),
    ("opus", ("opus",)),
    ("haiku", ("haiku",)),
    ("sol", ("sol",)),
    ("astra", ("astra",)),
)

# The model families a reading the provider reports for one model belongs
# to. A provider that reports a window per model names the family in the
# model id, and the family is the scope of the reading.
MODEL_FAMILY_SCOPES = (
    ("gemini-", ("gemini",)),
    ("claude-", ("claude",)),
    ("gpt-", ("gpt",)),
)

# The names the scope of a window is written with. A scope names a family
# of models, and the family is written the way its models are named.
SCOPE_NAMES = {
    "claude": "Claude",
    "gpt": "GPT",
    "gemini": "Gemini",
    "fable": "Fable",
    "sonnet": "Sonnet",
    "opus": "Opus",
    "haiku": "Haiku",
    "sol": "Sol",
    "astra": "Astra",
}


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


def window_scope(quota_id: str) -> tuple[str, ...]:
    """The model families a quota window applies to.

    The scope of a window is the name of the window: a window whose id
    names a model family applies to the models of that family, and every
    other window applies to the whole account.
    """
    text = str(quota_id or "").lower()
    for marker, families in WINDOW_SCOPES:
        if marker in text:
            return families
    return ()


# The name the lookup had where the table lived before it moved here, so
# the collector keeps one name for the scope of a window.
_window_scope = window_scope


def model_scope(model_id: str) -> tuple[str, ...]:
    """The model families a reading of one model belongs to.

    A provider that reports a window per model names the family in the
    model id. A model id that names no family is not a route of the
    account but an internal name of the provider.
    """
    text = str(model_id or "").strip().lower()
    for marker, families in MODEL_FAMILY_SCOPES:
        if text == marker[:-1] or text.startswith(marker):
            return families
    return ()


def measured_scope(measured: Any) -> tuple[str, ...] | None:
    """The scope of a measured reading, or None when it is not a window.

    A reading of the whole account is scoped by the name of its window,
    which is the scope the ranking gives it. A reading of one model is
    scoped by the family of that model, and a model id that names no
    family is not a route of the account: such a reading is not a window
    of the account, because it would read as a window of the whole
    account.
    """
    scope = _get(measured, "applies_to", "appliesTo")
    if scope:
        return tuple(str(token) for token in scope)
    model = str(_get(measured, "model") or "*")
    if model == "*":
        return window_scope(str(_get(measured, "quota_id", "quotaId") or ""))
    return model_scope(model) or None


def is_paced_window(window: Any) -> bool:
    """Only weekly/monthly periods have an even-spend line."""
    if pools.not_used_window(str(_get(window, 'provider') or ''), window):
        return False
    kind = str(_get(window, "kind") or "").lower()
    if any(token in kind for token in ("session", "hour", "daily", "minute")):
        return False
    if "week" in kind or "month" in kind:
        return True
    duration = _finite(_get(window, "duration_seconds", "durationSeconds"))
    return duration == 7 * 86400 or (duration is not None and 28 * 86400 <= duration <= 31 * 86400)


def current_reading(window: Any, now: float) -> bool:
    """Quota usage can be current even when its period is unpaced."""
    used = _finite(_get(window, "used_ratio", "usedRatio"))
    reset = _finite(_get(window, "reset_epoch", "resetEpoch"))
    observed = _finite(_get(window, "observed_at", "observedAtEpoch"))
    return (used is not None and 0 <= used <= 1 and observed is not None
            and now - STALE_AFTER_SECONDS <= observed <= now + FUTURE_TOLERANCE_SECONDS
            and (reset is None or reset > now))


def window_pace(window: Any, now: float) -> dict[str, Any] | None:
    """The pace of one window, or None when it cannot be known."""
    duration = _finite(_get(window, "duration_seconds", "durationSeconds"))
    reset = _finite(_get(window, "reset_epoch", "resetEpoch"))
    used = _finite(_get(window, "used_ratio", "usedRatio"))
    observed = _finite(_get(window, "observed_at", "observedAtEpoch"))
    if not is_paced_window(window) or duration is None or duration <= 0 or reset is None or used is None:
        return None
    if not current_reading(window, now):
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


# The verified alias of the OpenCode Go quota ids. The T3 status surface names
# the same three windows go_monthly/go_rolling/go_weekly that the Go usage
# endpoint names monthly/rolling/weekly. The pairing is published, and no
# reading is dropped.
QUOTA_ALIASES = {
    "go_monthly": "monthly",
    "go_rolling": "rolling",
    "go_weekly": "weekly",
}

# Why a headroom is unknown. The codes are fixed, so the dashboard can group
# them, and the texts say it in words. An unknown headroom without a reason
# is a gap a reader cannot explain, so a reason is always there.
UNKNOWN_REASON_NO_WINDOW = "no_window"
UNKNOWN_REASON_WINDOW_UNKNOWN = "window_unknown"

UNKNOWN_REASON_TEXT = {
    UNKNOWN_REASON_NO_WINDOW: (
        "the provider publishes no quota window for this account"
    ),
    UNKNOWN_REASON_WINDOW_UNKNOWN: (
        "the provider's window was not read, is stale, or has already reset"
    ),
}


def unknown_reason_code(windows: Iterable[Any], remaining: Any) -> str:
    """The code of the reason a headroom is unknown, or an empty string.

    A headroom that is known has no reason to give: it is measured. A
    headroom that is unknown always has one, so a consumer never has to
    guess why a window is missing.
    """
    if isinstance(remaining, (int, float)) and not isinstance(remaining, bool):
        return ""
    return UNKNOWN_REASON_WINDOW_UNKNOWN if list(windows or ()) else UNKNOWN_REASON_NO_WINDOW


def _entitlement_parts(window: Any) -> dict[str, str]:
    def get(name: str, default: str = "") -> str:
        value = window.get(name) if isinstance(window, Mapping) else getattr(window, name, None)
        return default if value is None else str(value)

    provider = get("provider")
    account = get("account") or "default"
    model = get("model") or "*"
    kind = get("kind") or get("window")
    quota = get("quota_id") or get("quotaId") or get("quota")
    canonical = QUOTA_ALIASES.get(quota, quota)
    return {
        "provider": provider,
        "account": account,
        "model": model,
        "window": kind,
        "quota": quota,
        "canonical_quota": canonical,
        "source": get("source"),
        "entitlement": f"{provider}:{account}:{model}:{kind}:{canonical}",
        "observed_at": _get(window, "observed_at", "observedAtEpoch", "observed_at_epoch"),
        "used_ratio": _get(window, "used_ratio", "usedRatio"),
        "reset_at": _get(window, "reset_at", "resetAt", "resetEpoch", "reset_epoch"),
        # The basis of the numbers of the window, and the end of its
        # entitlement when the provider publishes one.
        "basis": str(get("basis") or ""),
        "ends_at": _get(window, "ends_at", "endsAt", "ends_at_epoch"),
    }


def entitlements(windows: Iterable[Any], now: float | None = None) -> list[dict[str, Any]]:
    """The entitlement of every reading, with the canonical display reading.

    Two readings that name the same verified entitlement (provider, account,
    model, window and canonical quota) are grouped, and each keeps its own
    source and quota id. The display reading is the current usable reading
    with the highest used share (the least remaining); its reset, expected
    and pace are the same reading's values, never extrema from another one.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for window in windows or ():
        parts = _entitlement_parts(window)
        if not parts["provider"] or not parts["window"]:
            continue
        pace = window_pace(window, now) if now is not None else None
        entry = grouped.setdefault(
            parts["entitlement"],
            {
                "entitlement": parts["entitlement"],
                "provider": parts["provider"],
                "account": parts["account"],
                "model": parts["model"],
                "window": parts["window"],
                "canonical_quota": parts["canonical_quota"],
                "readings": [],
            },
        )
        entry["readings"].append(
            {
                "source": parts["source"],
                "quota": parts["quota"],
                "used_ratio": parts["used_ratio"],
                "reset_at": parts["reset_at"],
                "observed_at": parts["observed_at"],
                "basis": parts["basis"],
                "ends_at": parts["ends_at"],
                "usable": now is not None and current_reading(window, now),
                "expected_used_ratio": None if pace is None else pace["expected_used_ratio"],
                "pace_delta_ratio": None if pace is None else pace["pace_delta_ratio"],
            }
        )
    result = []
    for entry in grouped.values():
        sources = sorted({str(reading["source"] or "") for reading in entry["readings"]})
        entry["sources"] = sources
        entry["relationship"] = (
            "same_entitlement_independent_readings"
            if len(sources) > 1
            else "single_reading"
        )
        entry["alias"] = any(
            str(reading["quota"]) != entry["canonical_quota"]
            for reading in entry["readings"]
        )
        usable = [
            reading
            for reading in entry["readings"]
            if reading["usable"] and isinstance(reading["used_ratio"], (int, float))
        ]
        if usable:
            chosen = max(
                usable,
                key=lambda reading: (
                    float(reading["used_ratio"]),
                    str(reading["observed_at"] or ""),
                    str(reading["source"] or ""),
                ),
            )
            entry["display"] = {
                "source": chosen["source"],
                "quota": entry["canonical_quota"],
                "used_ratio": chosen["used_ratio"],
                "expected_used_ratio": chosen["expected_used_ratio"],
                "pace_delta_ratio": chosen["pace_delta_ratio"],
                "reset_at": chosen["reset_at"],
                "observed_at": chosen["observed_at"],
                "basis": chosen["basis"],
                "ends_at": chosen["ends_at"],
                "state": "measured",
                "selection": "the current usable reading with the least remaining",
            }
        else:
            chosen = None
            entry["display"] = None
            entry["display_state"] = "unknown"
        # The basis of the entitlement and the end of it. An entitlement
        # without a usable numeric reading still has an identity, so the
        # basis comes from its freshest reading: a route the provider
        # publishes as a promotion is a promotion, measured or not.
        freshest = max(
            entry["readings"],
            key=lambda reading: (
                _epoch(reading["observed_at"]) or 0.0,
                str(reading["source"] or ""),
            ),
        )
        entry["basis"] = str(
            (chosen or freshest)["basis"] or ""
        )
        entry["ends_at"] = (chosen or freshest)["ends_at"]
        result.append(entry)
    return sorted(result, key=lambda entry: entry["entitlement"])


def entitlement_display_samples(
    windows: Iterable[Any], now: float
) -> list[tuple[str, dict[str, str], float]]:
    """The canonical display family: one reading per entitlement.

    The info series is emitted even when the entitlement has no usable
    numeric reading, so an unknown allowance stays visible. A numeric series
    is emitted only from the chosen reading and only when that value is
    known; nothing is filled with zero or one.
    """
    samples: list[tuple[str, dict[str, str], float]] = []
    for entry in entitlements(windows, now):
        display = entry.get("display")
        labels = {
            "provider": entry["provider"],
            "account": entry["account"],
            "model": entry["model"],
            "window": entry["window"],
            "quota": entry["canonical_quota"],
            "source": str((display or {}).get("source") or ""),
            "entitlement": entry["entitlement"],
            # The basis of the numbers of the entitlement, and the end of it
            # when the provider publishes one. An end that is not published
            # is unknown, and an unknown end is an empty label and never a
            # zero.
            "basis": str(entry.get("basis") or ""),
            "ends_at": _iso_label(entry.get("ends_at")),
        }
        samples.append(("ghostship_ai_entitlement_info", dict(labels), 1.0))
        if not isinstance(display, Mapping):
            continue
        if isinstance(display.get("used_ratio"), (int, float)):
            samples.append(
                ("ghostship_ai_entitlement_used_ratio", dict(labels), float(display["used_ratio"]))
            )
        reset = _epoch(display.get("reset_at"))
        if reset is not None:
            samples.append(
                (
                    "ghostship_ai_entitlement_reset_timestamp_seconds",
                    dict(labels),
                    reset,
                )
            )
        if isinstance(display.get("expected_used_ratio"), (int, float)):
            samples.append(
                (
                    "ghostship_ai_entitlement_expected_used_ratio",
                    dict(labels),
                    float(display["expected_used_ratio"]),
                )
            )
        if isinstance(display.get("pace_delta_ratio"), (int, float)):
            samples.append(
                (
                    "ghostship_ai_entitlement_pace_delta_ratio",
                    dict(labels),
                    float(display["pace_delta_ratio"]),
                )
            )
        observed = _epoch(display.get("observed_at"))
        if observed is not None:
            samples.append(
                (
                    "ghostship_ai_entitlement_observed_timestamp_seconds",
                    dict(labels),
                    observed,
                )
            )
    return samples


def _iso_label(value: Any) -> str:
    """The end of an entitlement as a label, or an empty string.

    An end that the provider does not publish is unknown, and an unknown end
    is an empty label: it is never a zero and never a guess.
    """
    moment = _epoch(value)
    if moment is None:
        return ""
    from datetime import datetime, timezone

    return datetime.fromtimestamp(moment, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            from datetime import datetime, timezone

            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            return moment.timestamp()
        except ValueError:
            return None
    return None


def entitlement_samples(
    windows: Iterable[Any], now: float | None = None
) -> list[tuple[str, dict[str, str], float]]:
    """One info sample per reading, with the shared entitlement label."""
    samples: list[tuple[str, dict[str, str], float]] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in entitlements(windows, now):
        for reading in entry["readings"]:
            key = (entry["entitlement"], str(reading["source"]), str(reading["quota"]))
            if key in seen:
                continue
            seen.add(key)
            labels = {
                "provider": entry["provider"],
                "account": entry["account"],
                "model": entry["model"],
                "window": entry["window"],
                "quota": str(reading["quota"] or ""),
                "source": str(reading["source"] or ""),
                "entitlement": entry["entitlement"],
                "relationship": entry["relationship"],
            }
            samples.append(("ghostship_ai_quota_entitlement", labels, 1.0))
    return samples
