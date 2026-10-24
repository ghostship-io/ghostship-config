"""Weight quality against the allowance an allowance-billed route can spend.

A route that is billed by an allowance is not ranked on quality alone: a
slightly better model that costs ten times the requests can empty the
allowance long before it earns its score. The weights are configuration with
an explicit default, and every row publishes its own breakdown so the pick can
be audited.

Only a published allowance is scored here. A route without one keeps the
quality order it had; an unknown capacity is never read as a zero.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

# The default weights. Quality is the larger term because the owner picks a
# model to do the work; capacity is the term that stops a costly model from
# consuming the allowance the work needs.
DEFAULT_WEIGHTS = {"quality": 0.6, "capacity": 0.4}

# The request volume a capacity term of 1.0 stands for. It is a fixed scale,
# not a provider limit: every allowance is compared against the same reference
# so two models of one account are comparable.
CAPACITY_REFERENCE_REQUESTS = 50000.0

WINDOW_KINDS = ("session", "weekly", "monthly")
WINDOW_ALIASES = {
    "session": "session",
    "5h": "session",
    "five_hour": "session",
    "rolling": "session",
    "weekly": "weekly",
    "week": "weekly",
    "monthly": "monthly",
    "month": "monthly",
}


def weights(policy: Mapping[str, Any] | None = None) -> dict[str, float]:
    """The configured weights, or the stated default.

    An override must carry both terms as finite, non-negative numbers and
    total more than zero; anything else is ignored, so a malformed policy
    cannot silently reorder the picker.
    """
    selection = (policy or {}).get("model_selection") or {}
    override = selection.get("ranking_weights") if isinstance(selection, Mapping) else None
    if isinstance(override, Mapping):
        quality = _number(override.get("quality"))
        capacity = _number(override.get("capacity"))
        if quality is not None and capacity is not None and quality + capacity > 0:
            return {"quality": quality, "capacity": capacity}
    return dict(DEFAULT_WEIGHTS)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def window_kind(window: Mapping[str, Any]) -> str:
    kind = str(window.get("kind") or "").strip().lower()
    return WINDOW_ALIASES.get(kind, kind)


def budgets(allowance: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The published budgets of an allowance, in window order."""
    rows = allowance.get("budgets")
    if not isinstance(rows, list):
        return []
    ordered = []
    for kind in WINDOW_KINDS:
        for row in rows:
            if isinstance(row, Mapping) and window_kind(row) == kind:
                ordered.append(dict(row))
    return ordered


def affordable(
    allowance: Mapping[str, Any] | None,
    windows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """How many requests the route can spend before each reset.

    A measured remaining share multiplies the published budget of its own
    window. Without a measured window the published budget stands as the cap
    before that window resets, and the basis says it is published, not
    measured. The binding window is the one with the smallest affordable
    volume; a route with no published budget is unknown.
    """
    if not isinstance(allowance, Mapping):
        return {"state": "unknown", "basis": "unknown", "unit": "", "windows": []}
    published = budgets(allowance)
    if not published:
        return {"state": "unknown", "basis": "unknown", "unit": "requests", "windows": []}
    remaining = {}
    for window in windows or ():
        if not isinstance(window, Mapping) or window.get("not_used"):
            continue
        kind = window_kind(window)
        ratio = _number(window.get("remaining_ratio"))
        if kind in WINDOW_KINDS and ratio is not None:
            remaining[kind] = {
                "remaining_ratio": max(0.0, min(1.0, ratio)),
                "reset_at": window.get("reset_at"),
                "seconds_to_reset": _number(window.get("seconds_to_reset")),
                "pace_state": window.get("pace_state"),
                "pace_delta": _number(window.get("pace_delta")),
                "source": window.get("source"),
            }
    rows = []
    for budget in published:
        kind = window_kind(budget)
        requests = _number(budget.get("requests"))
        if requests is None:
            continue
        measured = remaining.get(kind)
        ratio = measured["remaining_ratio"] if measured else 1.0
        rows.append({
            "kind": kind,
            "requests_budget": requests,
            "remaining_ratio": measured["remaining_ratio"] if measured else None,
            "affordable_requests": requests * ratio,
            "reset_at": measured.get("reset_at") if measured else None,
            "seconds_to_reset": measured.get("seconds_to_reset") if measured else None,
            "pace_state": (measured.get("pace_state") if measured else None) or "unknown",
            "pace_delta": measured.get("pace_delta") if measured else None,
            "basis": "discovered+measured" if measured else "discovered",
            "estimate": bool(budget.get("estimate")),
            "source": budget.get("source") or allowance.get("source"),
        })
    if not rows:
        return {"state": "unknown", "basis": "unknown", "unit": "requests", "windows": []}
    binding = min(rows, key=lambda row: (row["affordable_requests"], WINDOW_KINDS.index(row["kind"])))
    return {
        "state": "known",
        "basis": "discovered+measured" if binding["remaining_ratio"] is not None else "discovered",
        "unit": "requests",
        "affordable_requests": binding["affordable_requests"],
        "binding_window": binding["kind"],
        "binding_window_requests": binding["requests_budget"],
        "binding_remaining_ratio": binding["remaining_ratio"],
        "binding_reset_at": binding["reset_at"],
        "binding_seconds_to_reset": binding["seconds_to_reset"],
        "binding_pace_state": binding["pace_state"],
        "binding_pace_delta": binding["pace_delta"],
        "estimate": any(row["estimate"] for row in rows),
        "windows": rows,
    }


def capacity_term(affordable_requests: float | None) -> float | None:
    """The log-scaled capacity term, 0..1 against the fixed reference."""
    value = _number(affordable_requests)
    if value is None or value < 0:
        return None
    return math.log10(1.0 + value) / math.log10(1.0 + CAPACITY_REFERENCE_REQUESTS)


def score(
    quality: float | None,
    allowance: Mapping[str, Any] | None,
    windows: Sequence[Mapping[str, Any]] | None,
    *,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """The weighted quality and capacity score of an allowance-billed route.

    A missing quality keeps a capacity-only score and says so; a missing
    allowance returns None and the route keeps the quality order. Neither is
    ever treated as zero.
    """
    if not isinstance(allowance, Mapping):
        return None
    capacity = affordable(allowance, windows)
    if capacity.get("state") != "known":
        return None
    quality_value = _number(quality)
    capacity_value = capacity_term(capacity.get("affordable_requests"))
    if capacity_value is None:
        return None
    configured = weights(policy)
    if quality_value is None:
        value = capacity_value
        basis = "capacity only: quality unknown"
    else:
        value = configured["quality"] * quality_value + configured["capacity"] * capacity_value
        basis = "quality + allowance capacity"
    return {
        "score": value,
        "quality_term": quality_value,
        "capacity_term": capacity_value,
        "weights": configured,
        "basis": basis,
        "allowance": capacity,
        "binding_window": capacity.get("binding_window"),
        "affordable_requests": capacity.get("affordable_requests"),
    }


def reason(breakdown: Mapping[str, Any] | None, allowance: Mapping[str, Any] | None,
           quality: float | None) -> str:
    """A bounded, auditable sentence for the picker row."""
    if not isinstance(breakdown, Mapping):
        return ""
    configured = breakdown.get("weights") or DEFAULT_WEIGHTS
    parts = []
    quality_value = _number(breakdown.get("quality_term"))
    capacity_value = _number(breakdown.get("capacity_term"))
    if quality_value is not None:
        parts.append(f"quality {quality_value * 100:.1f} x {configured.get('quality')}")
    requests = _number(breakdown.get("affordable_requests"))
    if requests is not None:
        parts.append(f"allowance {requests:,.0f} requests x {configured.get('capacity')}")
    window = str(breakdown.get("binding_window") or "")
    if window:
        parts.append(f"binding {window}")
    if quality is None:
        parts.append("quality unknown")
    if isinstance(allowance, Mapping) and allowance.get("stale"):
        parts.append("allowance reading stale")
    return "; ".join(parts)
