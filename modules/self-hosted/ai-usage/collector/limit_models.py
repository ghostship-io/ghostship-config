"""One limit model per provider, and the capacity a candidate can still spend.

The model resolves in the owner's order:

1. **discovered** limits, the provider's own truth: a measured window the
   provider or the T3 reader reports, the published allowance table, or a
   per-model request limit;
2. **measured** usage when no limit is discovered: the observed remaining share
   and any budget the inference measured, with low confidence;
3. **cost** as a rough guide when neither exists: the published price relative
   to a fixed reference;
4. **unknown**, which is never a zero.

Every record carries its source and the date it was read. A number the provider
does not publish stays absent, and an estimate is labelled as one.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from allowance import (
    DEFAULT_WEIGHTS,
    _number,
    capacity_term,
    window_kind,
    weights,
)
import command_code

CHECKED_AT = "2026-10-24"
UNITS = {"requests", "tokens", "share"}

# The price a cost-guide term of 1.0 stands for: USD per million output tokens.
COST_REFERENCE_USD_PER_MTOK = 10.0

SOURCES = {
    "opencode-go": "https://opencode.ai/go",
    "commandCode": "https://commandcode.ai/docs/plans/goat",
    "ollama": "https://docs.ollama.com/cloud",
    "codex": "T3 Code provider windows",
    "claude": "T3 Code provider windows",
    "antigravity": "Google cloudcode quota endpoints",
    "grok": "T3 Code provider windows",
    "free_pool": "provider documentation and pool response headers",
}

WINDOWS = {
    "opencode-go": [
        {"kind": "session", "share_of_monthly": 0.20, "length_seconds": 5 * 3600, "unit": "requests"},
        {"kind": "weekly", "share_of_monthly": 0.50, "length_seconds": 7 * 86400, "unit": "requests"},
        {"kind": "monthly", "share_of_monthly": 1.00, "length_seconds": 30 * 86400, "unit": "requests"},
    ],
    "commandCode": [
        {"kind": "session", "length_seconds": 5 * 3600, "unit": "requests"},
        {"kind": "weekly", "length_seconds": 7 * 86400, "unit": "requests"},
        {"kind": "monthly", "length_seconds": 30 * 86400, "unit": "requests"},
    ],
    "ollama": [
        {"kind": "session", "length_seconds": 5 * 3600, "unit": "requests"},
        {"kind": "weekly", "length_seconds": 7 * 86400, "unit": "requests"},
    ],
    "codex": [
        {"kind": "session", "length_seconds": 5 * 3600, "unit": "share"},
        {"kind": "weekly", "length_seconds": 7 * 86400, "unit": "share"},
    ],
    "claude": [
        {"kind": "weekly", "length_seconds": 7 * 86400, "unit": "share", "shared": True},
    ],
    "antigravity": [
        {"kind": "session", "length_seconds": 5 * 3600, "unit": "share", "shared": True},
        {"kind": "weekly", "length_seconds": 7 * 86400, "unit": "share", "per_model": "runtime-limit:<model>"},
    ],
    "grok": [
        {"kind": "weekly", "length_seconds": 7 * 86400, "unit": "share"},
    ],
}

# The published per-model request examples. They are estimates: the vendor
# calls them example mixes, not measured limits.
PER_MODEL = {
    "commandCode": {
        "deepseek/deepseek-v4.1-flash": {"session": 41000.0, "weekly": 103000.0, "monthly": 205000.0},
    },
}

# A sub-cap inside a shared pool. Fable is a member of Claude's weekly pool,
# not a separate account.
SUB_CAPS = {
    "claude": {"fable": {"kind": "weekly", "basis": "sub-cap inside the shared weekly pool"}},
}

# Free-pool routes publish per-minute, per-day and daily-token limits, and a
# cooldown after a refusal. The table is in pool_limits; this record says which
# window the picker reads.
FREE_POOL_WINDOWS = [
    {"kind": "minute", "length_seconds": 60, "unit": "requests"},
    {"kind": "daily", "length_seconds": 86400, "unit": "requests"},
    {"kind": "daily", "length_seconds": 86400, "unit": "tokens", "id": "tokens"},
]


def _iso(now: float) -> str:
    return datetime.fromtimestamp(float(now), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _per_model(provider: str, model: str) -> dict[str, float]:
    table = PER_MODEL.get(str(provider or "")) or {}
    return dict(table.get(str(model or "")) or {})


def _published(provider: str, model: str, page_limits: Sequence[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The static windows of a provider, with a per-model budget when known.

    A dated row a free-pool extraction read from the provider's page overrides
    the static budget of the same window. A row the static table does not list
    is added, so a newly published window is never dropped.
    """
    model_budget = _per_model(provider, model)
    source = WINDOWS.get(str(provider or ""))
    if source is None and provider == "free_pool":
        source = FREE_POOL_WINDOWS
    rows = []
    used = set()
    for window in source or []:
        row = dict(window)
        if window["unit"] == "requests":
            row["budget"] = model_budget.get(window["kind"])
            row["estimate"] = row["budget"] is not None
        else:
            row["budget"] = None
            row["estimate"] = False
        row["source"] = SOURCES.get(str(provider or ""))
        row["checked_at"] = CHECKED_AT
        for page in page_limits or ():
            if (str(page.get("window")) == row["kind"] and str(page.get("unit")) == row["unit"]
                    and page.get("budget") is not None):
                row.update(budget=_number(page.get("budget")), estimate=bool(page.get("estimate")),
                           source=page.get("source") or row["source"],
                           checked_at=page.get("checked_at") or row["checked_at"])
                used.add((page.get("window"), page.get("unit")))
        rows.append(row)
    for page in page_limits or ():
        key = (page.get("window"), page.get("unit"))
        if key in used or str(page.get("unit")) not in UNITS:
            continue
        rows.append({
            "kind": str(page.get("window")),
            "unit": str(page.get("unit")),
            "budget": _number(page.get("budget")),
            "estimate": bool(page.get("estimate")),
            "source": page.get("source") or SOURCES.get(str(provider or "")),
            "checked_at": page.get("checked_at") or CHECKED_AT,
        })
    return rows


def _overlay(rows: list[dict[str, Any]], windows: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Overlay the measured windows of the account on the published ones."""
    measured: dict[str, Mapping[str, Any]] = {}
    for window in windows or ():
        if not isinstance(window, Mapping) or window.get("not_used"):
            continue
        kind = window_kind(window)
        ratio = _number(window.get("remaining_ratio"))
        if kind and ratio is not None and kind not in measured:
            measured[kind] = window
    result = []
    seen = set()
    for row in rows:
        kind = row["kind"]
        seen.add(kind)
        found = measured.get(kind)
        if found is None:
            result.append(row)
            continue
        ratio = max(0.0, min(1.0, float(_number(found.get("remaining_ratio")) or 0.0)))
        updated = dict(row)
        updated.update({
            "remaining_ratio": ratio,
            "reset_at": found.get("reset_at"),
            "seconds_to_reset": _number(found.get("seconds_to_reset")),
            "pace_state": found.get("pace_state") or "unknown",
            "pace_delta": _number(found.get("pace_delta")),
            "basis": "discovered",
            "measured": True,
        })
        result.append(updated)
    for kind, found in measured.items():
        if kind in seen:
            continue
        checked = found.get("check_at")
        ratio = max(0.0, min(1.0, float(_number(found.get("remaining_ratio")) or 0.0)))
        result.append({
            "kind": kind, "unit": "share", "budget": None, "empty": True,
            "remaining_ratio": ratio, "reset_at": found.get("reset_at"),
            "seconds_to_reset": _number(found.get("seconds_to_reset")),
            "pace_state": found.get("pace_state") or "unknown",
            "pace_delta": _number(found.get("pace_delta")),
            "source": found.get("source") or SOURCES.get(str(found.get("provider") or "")),
            "checked_at": (_iso(checked) if isinstance(checked, (int, float))
                           and not isinstance(checked, bool)
                           else (str(checked) if checked else CHECKED_AT)),
            "basis": "discovered", "measured": True,
        })
    return result


def _inferred(provider: Any, capacity: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The budget and remaining share an inference measured, if any."""
    inference = (capacity or {}).get("inference") if isinstance(capacity, Mapping) else None
    if not isinstance(inference, Mapping):
        return None
    budget = _number(inference.get("budget"))
    remaining = _number((capacity or {}).get("remaining_ratio"))
    unit = str(inference.get("unit") or "")
    if budget is None and remaining is None:
        return None
    return {"budget": budget, "remaining_ratio": remaining, "unit": unit,
            "window": inference.get("window"), "scope": inference.get("scope"),
            "weights": inference.get("weights"), "episodes": inference.get("episodes")}


def _cost_term(price: Mapping[str, Any] | None) -> float | None:
    """A 0..1 cost guide from a published output price, or None."""
    if not isinstance(price, Mapping):
        return None
    output = _number(price.get("output"))
    if output is None or output < 0:
        return None
    return 1.0 / (1.0 + output / COST_REFERENCE_USD_PER_MTOK)


def _sub_cap(provider: str, model: str) -> dict[str, Any] | None:
    """The sub-cap a model holds inside a shared pool, when it holds one."""
    for name, cap in (SUB_CAPS.get(provider) or {}).items():
        if name in str(model or "").lower():
            return dict(cap)
    return None


def resolve(
    provider: str,
    model: str,
    *,
    now: float,
    windows: Sequence[Mapping[str, Any]] | None = None,
    allowance: Mapping[str, Any] | None = None,
    capacity: Mapping[str, Any] | None = None,
    price: Mapping[str, Any] | None = None,
    page_limits: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """The capacity of one candidate, with its basis and binding window.

    A published allowance is the richest discovered record and is used first.
    The measured windows of the account then overlay it. Without any window the
    measured inference is used, and without that the published price is a rough
    guide. Unknown stays unknown.
    """
    provider = str(provider or "")
    model = str(model or "")
    rows: list[dict[str, Any]] = []
    estimate = False
    if isinstance(allowance, Mapping) and allowance.get("budgets"):
        for budget in allowance.get("budgets") or []:
            if isinstance(budget, Mapping):
                rows.append(dict(budget))
        estimate = bool(allowance.get("stale"))
    else:
        rows = _published(provider, model, page_limits)
        estimate = any(bool(row.get("estimate")) for row in rows)
    rows = _overlay(rows, windows)

    inferred = _inferred(provider, capacity)
    affordable = []
    for row in rows:
        budget = _number(row.get("budget"))
        if budget is None:
            budget = _number(row.get("requests"))
        ratio = _number(row.get("remaining_ratio"))
        if budget is not None and ratio is not None:
            value = budget * ratio
            unit = row.get("unit") or "requests"
        elif budget is not None:
            value = budget
            unit = row.get("unit") or "requests"
        elif ratio is not None:
            value = None
            unit = "share"
        else:
            value = None
            unit = row.get("unit") or "unknown"
        affordable.append({
            "kind": row.get("kind"),
            "id": row.get("id"),
            "per_model": row.get("per_model"),
            "budget": budget,
            "remaining_ratio": ratio,
            "affordable": value,
            "unit": unit,
            "reset_at": row.get("reset_at"),
            "seconds_to_reset": row.get("seconds_to_reset"),
            "pace_state": row.get("pace_state") or "unknown",
            "pace_delta": row.get("pace_delta"),
            "basis": str(row.get("basis") or ("discovered" if ratio is not None else "published")),
            "estimate": bool(row.get("estimate")),
            "source": row.get("source"),
            "checked_at": row.get("checked_at") or CHECKED_AT,
        })

    known = [row for row in affordable if row["affordable"] is not None]
    if known:
        binding = min(known, key=lambda row: (row["affordable"], row["kind"]))
        tasks = binding["affordable"]
        basis = "discovered"
    elif affordable and any(row["remaining_ratio"] is not None for row in affordable):
        binding = min(
            (row for row in affordable if row["remaining_ratio"] is not None),
            key=lambda row: (row["remaining_ratio"], row["kind"]))
        tasks = None
        basis = "measured"
    else:
        binding = None
        tasks = None
        basis = "unknown"

    inferred_affordable = None
    if inferred and inferred.get("budget") is not None and inferred.get("remaining_ratio") is not None:
        inferred_affordable = inferred["budget"] * inferred["remaining_ratio"]
        if basis == "unknown":
            basis = "measured"
            tasks = inferred_affordable
            binding = {"kind": inferred.get("window") or "measured", "affordable": inferred_affordable,
                       "unit": inferred.get("unit") or "unknown", "basis": "measured",
                       "confidence": "low", "source": "inference"}

    cost = _cost_term(price)
    if basis == "unknown" and cost is not None:
        basis = "cost"

    capacity_value = None
    if tasks is not None:
        capacity_value = capacity_term(tasks)
    elif binding is not None and binding.get("remaining_ratio") is not None:
        capacity_value = binding["remaining_ratio"]
    elif cost is not None:
        capacity_value = cost

    return {
        "provider": provider,
        "model": model,
        "source": SOURCES.get(provider) or "provider",
        "checked_at": CHECKED_AT,
        "estimate": bool(estimate or (binding or {}).get("estimate")),
        "basis": basis,
        "windows": affordable,
        "affordable": {
            "tasks": tasks,
            "unit": (binding or {}).get("unit") or (inferred or {}).get("unit") or "unknown",
            "basis": basis,
            "estimate": bool((binding or {}).get("estimate") or inferred is not None),
            "binding_window": (binding or {}).get("kind"),
            "reset_at": (binding or {}).get("reset_at"),
            "seconds_to_reset": (binding or {}).get("seconds_to_reset"),
            "pace_state": (binding or {}).get("pace_state", "unknown"),
            "pace_delta": (binding or {}).get("pace_delta"),
            "cost_index": cost,
            "inference": inferred,
        },
        "capacity_term": capacity_value,
        "sub_cap": _sub_cap(provider, model),
        "pricing": (command_code.rates(now) if provider == command_code.INSTANCE else None),
        "free_pool": FREE_POOL_WINDOWS if provider == "free_pool" else None,
    }


def attach(snapshot: Mapping[str, Any], now: float,
           page_limits: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Attach the limit model to every candidate and summarize the providers.

    The account windows are the ones the snapshot already published. A page
    row the free pool extracted for this route is passed through, so a
    published budget it read is used instead of a static estimate.
    """
    accounts = ((snapshot.get("quota") or {}).get("accounts") or {}) if isinstance(snapshot, Mapping) else {}
    summary: dict[str, Any] = {}
    for candidate in (snapshot.get("candidates") or []) if isinstance(snapshot, Mapping) else []:
        provider = str(candidate.get("provider") or "")
        model = str(candidate.get("model") or "")
        windows = [window for window in accounts.get(provider) or []
                   if isinstance(window, Mapping) and not window.get("not_used")]
        rows = []
        if page_limits:
            try:
                import limit_pages
                rows = limit_pages.rows_for(page_limits, provider, model)
            except ImportError:  # pragma: no cover - a trimmed collector image
                rows = []
        candidate["page_limits"] = rows
        candidate["limit_model"] = resolve(
            provider, model, now=now, windows=windows,
            allowance=candidate.get("allowance"), capacity=candidate.get("capacity"),
            price=candidate.get("price"), page_limits=rows)
        summary[provider] = {
            "source": SOURCES.get(provider) or "provider",
            "checked_at": CHECKED_AT,
            "estimate": bool(candidate["limit_model"].get("estimate")),
        }
    return summary


def score(
    quality: float | None,
    limit_model: Mapping[str, Any] | None,
    *,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """The weighted quality and capacity score of a candidate."""
    if not isinstance(limit_model, Mapping):
        return None
    capacity_value = _number(limit_model.get("capacity_term"))
    quality_value = _number(quality)
    if capacity_value is None and quality_value is None:
        return None
    configured = weights(policy)
    if capacity_value is None:
        value = quality_value
        basis = "quality only: capacity unknown"
    elif quality_value is None:
        value = capacity_value
        basis = "capacity only: quality unknown"
    else:
        value = configured["quality"] * quality_value + configured["capacity"] * capacity_value
        basis = "quality + " + str(limit_model.get("basis") or "capacity")
    return {
        "score": value,
        "quality_term": quality_value,
        "capacity_term": capacity_value,
        "weights": configured,
        "basis": basis,
        "allowance": None,
        "binding_window": (limit_model.get("affordable") or {}).get("binding_window"),
        "affordable_requests": (limit_model.get("affordable") or {}).get("tasks"),
        "capacity_basis": limit_model.get("basis"),
    }


def reason(breakdown: Mapping[str, Any] | None, limit_model: Mapping[str, Any] | None) -> str:
    """A bounded, auditable sentence naming the basis and binding window."""
    if not isinstance(breakdown, Mapping):
        return ""
    configured = breakdown.get("weights") or DEFAULT_WEIGHTS
    parts = []
    quality_value = _number(breakdown.get("quality_term"))
    if quality_value is not None:
        parts.append(f"quality {quality_value * 100:.1f} x {configured.get('quality')}")
    capacity_value = _number(breakdown.get("capacity_term"))
    if capacity_value is not None:
        parts.append(f"capacity {capacity_value:.3f} x {configured.get('capacity')}")
    affordable = (limit_model or {}).get("affordable") or {}
    tasks = _number(affordable.get("tasks"))
    if tasks is not None:
        parts.append(f"affordable {tasks:,.0f} {affordable.get('unit') or ''}".strip())
    elif affordable.get("cost_index") is not None:
        parts.append("cost guide")
    window = affordable.get("binding_window")
    if window:
        parts.append(f"binding {window}")
    if limit_model:
        parts.append(f"basis {limit_model.get('basis')}")
        if limit_model.get("estimate"):
            parts.append("estimate")
    return "; ".join(parts)
