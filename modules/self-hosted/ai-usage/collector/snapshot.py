"""The canonical routing snapshot.

The collector writes one JSON file that is the canonical answer for anything
that has to choose a model: where a model sits in a tier, what the rank is
made of, the measured quota behind it, whether it can be used right now, and
where every number came from. The file is written atomically, so a reader
never sees half of it.

The contract (schema version 1)::

    schema_version       1
    schema              "ghostship.ai-usage.routing"
    generated_at        UTC ISO-8601, the moment the snapshot was written
    max_age_seconds     how long a consumer may trust the snapshot
    partial             true when a source failed or reported nothing
    coverage            the sources and how they fared
    policy              the owner's direction, kept apart from the readings
    tiers               the ordered members of every tier
    quota               the measured windows, once per account
    candidates          one row per model a consumer may act on
    pending             the models that wait for their evaluation window
    counts              how much was left out

Every candidate row keeps three kinds of statement apart, and never mixes
them:

* `policy` - what the owner decided.
* `measured` - what a provider reported: a usage share, a reset time, a
  request count. A reading that is missing, malformed, or stale stays
  unknown; it never becomes headroom and never becomes zero.
* `prior` - what the collector believes from the catalog and the model name:
  the quality of a lineage, the 3D skill of a model. A prior is labelled as a
  prior, and there is no numerical quality claim without a source.

The native identity of a model - the T3 Code provider instance, the model id
inside that instance, and the options that instance offers - is copied from
the live instance catalog. A model whose native identity is not proven is
marked `mapped: false` and is not eligible.

Nothing in the snapshot identifies a person: no credentials, no account
names, no email addresses, no file paths, no prompts, and no raw
diagnostics. Only provider names, model ids, window kinds, ratios, and
timestamps.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from aa import lookup as aa_lookup

SCHEMA = "ghostship.ai-usage.routing"
SCHEMA_VERSION = 1

# How long a consumer may trust the snapshot before it has to read a new one.
DEFAULT_MAX_AGE_SECONDS = 900

# The states a candidate can be in.
QUOTA_AVAILABLE = "available"
QUOTA_EXHAUSTED = "exhausted"
QUOTA_UNKNOWN = "unknown"

# The roles the owner gave the tiers.
ROLE_PRIME = "prime"
ROLE_DELEGATE = "delegate"


def _finite(value: Any) -> float | None:
    """A finite float, or None. A NaN or an infinity is never published."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _key(provider: str, model: str) -> str:
    return f"{provider}:{model}"


def _window_record(window: Any, now: float) -> dict[str, Any]:
    """One measured quota window, with its provenance and its check time."""
    def _get(name: str, default: Any = None) -> Any:
        value = getattr(window, name, None)
        if value is None and isinstance(window, Mapping):
            value = window.get(name)
        return default if value is None else value

    kind = str(_get("kind", "other"))
    quota_id = str(_get("quota_id", ""))
    used = _get("used_ratio")
    reset = _get("reset_epoch")
    duration = _get("duration_seconds")
    applies = _get("applies_to", ())
    observed = _get("observed_at")

    used_value = _finite(used)
    known = used_value is not None and 0.0 <= used_value <= 1.0
    if used_value is not None and not known:
        used_value = None
    reset_value = _finite(reset)
    duration_value = _finite(duration)
    observed_value = _finite(observed)
    expired = reset_value is not None and reset_value <= now
    evidence = "provider_reported" if known and not expired else "unknown"

    record: dict[str, Any] = {
        "quota_id": quota_id,
        "kind": kind,
        "evidence": evidence,
        "used_ratio": round(used_value, 4) if known and not expired else None,
        "remaining_ratio": (
            round(max(0.0, 1.0 - used_value), 4) if known and not expired else None
        ),
        "reset_at": _iso(reset_value) if reset_value is not None else None,
        "seconds_to_reset": (
            int(round(reset_value - now)) if reset_value is not None else None
        ),
        "duration_seconds": (
            int(duration_value) if duration_value is not None and duration_value > 0 else None
        ),
        # The check time is the moment the provider reported the window. It
        # is never the moment the snapshot was written.
        "check_at": _iso(observed_value) if observed_value is not None else None,
        "provenance": "collector",
    }
    if applies:
        record["applies_to"] = [str(token) for token in applies]
    return record


def _pace_record(
    window: Any, now: float, remaining: float | None
) -> tuple[float | None, float | None]:
    """The expected usage of a window by now and the measured usage."""
    def _get(name: str, default: Any = None) -> Any:
        value = getattr(window, name, None)
        if value is None and isinstance(window, Mapping):
            value = window.get(name)
        return default if value is None else value

    duration = _get("duration_seconds")
    reset = _get("reset_epoch")
    if not duration or float(duration) <= 0 or not isinstance(reset, (int, float)):
        return None, None
    start = float(reset) - float(duration)
    expected = min(1.0, max(0.0, (now - start) / float(duration)))
    actual = None if remaining is None else max(0.0, min(1.0, 1.0 - remaining))
    return expected, actual


def _native_record(
    provider: str, model: str, native: Mapping[str, Any] | None
) -> dict[str, Any]:
    """The native identity of a model, when it is proven.

    The identity is copied from the live T3 Code instance catalog. A model
    that the collector only knows from the free pool has no native instance
    and is reported as unmapped, so no consumer may pick it for agent work.
    """
    if not native:
        return {
            "provider_instance_id": None,
            "model_id": None,
            "options": [],
            "mapped": False,
            "provenance": "no live instance catalog entry",
        }
    return {
        "provider_instance_id": str(native.get("providerInstance") or ""),
        "model_id": str(native.get("modelId") or ""),
        "options": [
            {"id": str(option.get("id")), "current_value": option.get("currentValue")}
            for option in (native.get("options") or [])
            if isinstance(option, Mapping) and option.get("id")
        ],
        "mapped": True,
        "provenance": "live T3 Code instance catalog",
    }


def _quota_state(remaining: float | None, windows: list[dict[str, Any]]) -> str:
    """The state of the capacity behind a model."""
    if not windows:
        return QUOTA_UNKNOWN
    if any(window["evidence"] == "unknown" for window in windows):
        return QUOTA_UNKNOWN
    if remaining is None:
        return QUOTA_UNKNOWN
    if remaining <= 0.0:
        return QUOTA_EXHAUSTED
    return QUOTA_AVAILABLE


def _eligibility(
    provider: str,
    model: str,
    tiers: Iterable[str],
    native: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """The policy flags of a model, kept apart from what was measured."""
    tier_list = list(tiers)
    model_text = model.lower()
    prime_models = [str(item).lower() for item in policy.get("frontierPrimeModels") or ()]
    allowed_gpt = [str(item).lower() for item in policy.get("allowedGptModels") or ()]
    background = [
        str(item).lower() for item in policy.get("backgroundProviderInstances") or ()
    ]
    is_gpt = model_text.startswith("gpt")
    gpt_allowed = (not is_gpt) or any(item in model_text for item in allowed_gpt)
    mapped = bool(native.get("mapped"))
    return {
        "frontier_prime": {
            "allowed": mapped and any(item in model_text for item in prime_models),
            "basis": "policy:owner",
        },
        "delegate": {
            "allowed": mapped and bool(tier_list) and gpt_allowed,
            "basis": "policy:owner+native+tier",
        },
        "background": {
            "allowed": mapped
            and str(native.get("provider_instance_id") or "").lower() in set(background),
            "basis": "policy:owner",
        },
        "gpt_model_allowed": {"allowed": gpt_allowed, "basis": "policy:owner"},
    }


def _intelligence_record(
    cache: Mapping[str, Any] | None, model: str
) -> dict[str, Any]:
    """The Artificial Analysis record of one model, or the coverage gap.

    The feed is an external quality input. A model the feed does not list is
    unknown, not bad, and the version and the age of the feed are published
    with the record.
    """
    if not cache:
        return {"state": "no_cache", "source": "artificialanalysis"}
    if cache.get("status") != "ok":
        return {
            "state": str(cache.get("status") or "missing"),
            "reason": str(cache.get("reason") or ""),
            "source": "artificialanalysis",
            "index_version": cache.get("index_version"),
            "fetched_at": cache.get("fetched_at"),
            "age_seconds": cache.get("age_seconds"),
        }
    record = aa_lookup(cache, model)
    if record is None:
        return {
            "state": "not_listed",
            "source": "artificialanalysis",
            "index_version": cache.get("index_version"),
            "fetched_at": cache.get("fetched_at"),
            "age_seconds": cache.get("age_seconds"),
        }
    return {
        "state": "measured",
        "source": "artificialanalysis",
        "index_version": record.get("index_version"),
        "fetched_at": record.get("fetched_at"),
        "indices": record.get("indices") or {},
        "cost_per_task": record.get("cost_per_task"),
        "median_performance": record.get("median_performance"),
        "token_prices": record.get("prices") or {},
        "note": (
            "the token prices and the cost per task are different things: "
            "the price is per million tokens, the cost per task is what a "
            "measured task costs"
        ),
    }


def _candidate(
    provider: str,
    model: str,
    entries: list[Any],
    now: float,
    native: Mapping[str, Any] | None,
    policy: Mapping[str, Any],
    aa_cache: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One candidate row."""
    tiers: list[str] = []
    ranks: dict[str, int] = {}
    scores: dict[str, float] = {}
    reasons: list[str] = []
    windows: list[dict[str, Any]] = []
    quality = 0.0
    remaining: float | None = None
    expires_in: float | None = None
    available = False
    settled = True
    pending_reason = ""
    used_tokens = 0.0
    three_d_prior: float | None = None
    three_d_tokens = 0.0
    account = ""
    pace: float | None = None
    expected: float | None = None
    actual: float | None = None
    raw_windows: list[Any] = []
    surplus: dict[str, Any] = {}

    for entry in entries:
        if entry.tier:
            tiers.append(entry.tier)
            ranks[entry.tier] = entry.rank
            scores[entry.tier] = round(float(entry.score), 3)
        quality = float(entry.quality)
        if entry.remaining is not None:
            remaining = float(entry.remaining)
        if entry.expires_in_seconds is not None:
            expires_in = float(entry.expires_in_seconds)
        available = bool(entry.available)
        settled = bool(entry.settled)
        pending_reason = entry.pending_reason
        used_tokens = float(entry.used_tokens)
        three_d_prior = entry.three_d_prior
        three_d_tokens = float(entry.three_d_tokens)
        account = entry.account or account
        pace = getattr(entry, "pace", pace)
        surplus = getattr(entry, "frontier_surplus", None) or surplus
        for reason in entry.reasons:
            if reason not in reasons:
                reasons.append(reason)
        raw_windows = list(entry.windows)
    for window in raw_windows:
        record = _window_record(window, now)
        if record not in windows:
            windows.append(record)
    if pace is None and raw_windows:
        binding = min(
            (w for w in raw_windows if _window_record(w, now)["evidence"] == "provider_reported"),
            key=lambda w: _window_record(w, now)["remaining_ratio"] or 0.0,
            default=None,
        )
        if binding is not None:
            expected, actual = _pace_record(
                binding, now, _window_record(binding, now)["remaining_ratio"]
            )

    native_record = _native_record(provider, model, native)
    quota_state = _quota_state(remaining, windows)
    capacity_measured = bool(windows) and all(
        window["evidence"] == "provider_reported" for window in windows
    )

    return {
        "provider": provider,
        "model": model,
        "native": native_record,
        "role": ROLE_PRIME if "frontier" in tiers else ROLE_DELEGATE,
        "frontier_required": "frontier" in tiers,
        "tiers": sorted(tiers),
        "rank": ranks,
        "score": scores,
        "reasons": reasons,
        "available": bool(quota_state == QUOTA_AVAILABLE),
        "availability": {
            "state": "available" if quota_state == QUOTA_AVAILABLE else "unavailable",
            "evidence": "measured" if capacity_measured else "unknown",
            "reason": (
                "every applicable window has headroom"
                if quota_state == QUOTA_AVAILABLE
                else (
                    "a window is spent"
                    if quota_state == QUOTA_EXHAUSTED
                    else "a window is unknown, stale, or missing"
                )
            ),
        },
        "quota_state": quota_state,
        "account": account,
        "quota_account": account,
        "quality": {
            "value": round(quality, 2),
            "source": "prior",
            "measured": False,
            "basis": "lineage prior, release age, context window, capabilities",
        },
        "capacity": {
            "remaining_ratio": None if remaining is None else round(remaining, 4),
            "source": "measured" if capacity_measured else "unknown",
            "measured": capacity_measured,
            "expires_in_seconds": None if expires_in is None else int(round(expires_in)),
            "expected_used_ratio": None if expected is None else round(expected, 4),
            "measured_used_ratio": None if actual is None else round(actual, 4),
            "pace_delta": None if pace is None else round(pace, 4),
            "pace_basis": "measured against the line the window draws by now",
        },
        "usage": {
            "tokens_7d": round(used_tokens, 1),
            "source": "measured" if used_tokens > 0 else "none",
            "measured": used_tokens > 0,
            "basis": "token volume, not task success",
        },
        "three_d": {
            "prior": None if three_d_prior is None else round(three_d_prior, 3),
            "usage_tokens": round(three_d_tokens, 1),
            "source": "prior" if three_d_tokens <= 0 else "prior+measured",
        },
        "intelligence": _intelligence_record(aa_cache, model),
        "eligibility": _eligibility(provider, model, tiers, native_record, policy),
        "frontier_surplus": {
            "available": bool(surplus.get("available")),
            "reason": str(surplus.get("reason") or ""),
            "expires_in_seconds": surplus.get("expires_in_seconds"),
            "surplus_ratio": surplus.get("surplus_ratio"),
            "reserve_ratio": surplus.get("reserve_ratio"),
            "pace_delta": surplus.get("pace_delta"),
            # The entitlement the surplus comes from: its kind, its length, and
            # its reset. A weekly or a monthly allowance that resets within a
            # day is not the same thing as a session window that resets in a
            # few hours.
            "entitlement_kind": surplus.get("entitlement_kind"),
            "entitlement_duration_seconds": surplus.get("entitlement_duration_seconds"),
            "entitlement_reset_at": surplus.get("entitlement_reset_at"),
            "entitlement_quota_id": surplus.get("entitlement_quota_id"),
            "basis": "an allowance that resets within a day, and the reserve the review keeps",
        },
        "admission": {
            "state": "settled" if settled else "pending",
            "reason": pending_reason,
        },
        "provenance": {
            "source": "collector",
            "observed_at": _iso(now),
        },
    }


# The workload classes. A free route may carry the work it can do well, and
# nothing else: a research or metadata task does not need the frontier, and
# the frontier review of a complex change must not be downgraded to a free
# route because it is cheap.
WORKLOAD_CLASSES = (
    {
        "id": "research",
        "free_eligible": True,
        "private_data": False,
        "complexity": "low",
        "description": "reading, searching, and open research",
    },
    {
        "id": "simple",
        "free_eligible": True,
        "private_data": False,
        "complexity": "low",
        "description": "small, cheap, and easy changes",
    },
    {
        "id": "metadata",
        "free_eligible": True,
        "private_data": False,
        "complexity": "low",
        "description": "bulk metadata and bookkeeping updates",
    },
    {
        "id": "engineering",
        "free_eligible": False,
        "private_data": True,
        "complexity": "high",
        "description": "engineering work on private code",
    },
    {
        "id": "review",
        "free_eligible": False,
        "private_data": True,
        "complexity": "high",
        "description": "the frontier review of a change, and its security and integration checks",
    },
)


def _display_tier(tiers: list[str]) -> str:
    """The tier that describes a recommendation best."""
    for tier in ("frontier", "bulk", "free", "3d"):
        if tier in tiers:
            return tier
    return (tiers or [""])[0]


def _recommendations(
    candidates: list[dict[str, Any]], classes: tuple[dict[str, Any], ...]
) -> dict[str, Any]:
    """The recommended model for every workload class.

    A class that a free route may serve prefers a free model, but the
    preference is a preference and not an infinite bonus: when no free route
    is available, the best paid route is recommended and the reason says so.
    A class that handles private data never takes a route that is not
    mapped to a native instance, and the review class never takes a free
    route at all.
    """
    result: dict[str, Any] = {}
    for entry in classes:
        name = entry["id"]
        eligible = [
            row
            for row in candidates
            if (row.get("availability") or {}).get("state") == "available"
            and row.get("rank")
            and (row.get("admission") or {}).get("state") == "settled"
        ]
        if not entry["free_eligible"] or entry.get("complexity") == "high":
            # The role cap does not depend on the measured quality: a free
            # route never carries high complexity work.
            eligible = [
                row for row in eligible if not row["tiers"] or "free" not in row["tiers"]
            ]
        if entry["private_data"]:
            eligible = [row for row in eligible if row["native"]["mapped"]]
        preferred = [row for row in eligible if "free" in row["tiers"]]
        # A mapped free route is preferred over a read only pool route: it can
        # also carry a delegate, and a pool route never can.
        choice_pool = sorted(
            preferred,
            key=lambda row: (
                1 if row["native"]["mapped"] else 0,
                max(row["score"].values()) if row["score"] else 0.0,
            ),
            reverse=True,
        )
        if entry["free_eligible"] and choice_pool:
            chosen = choice_pool[0]
            result[name] = {
                "provider": chosen["provider"],
                "model": chosen["model"],
                "tier": "free",
                "native": chosen["native"],
                "role": chosen["role"],
                "reason": (
                    "a free route is preferred for this class; it is a read only "
                    "research route and may not carry private work"
                    if not chosen["native"]["mapped"]
                    else "a free route is preferred for this class"
                ),
                "delegate": bool(chosen["native"]["mapped"]),
                "private_data": bool(entry["private_data"]),
            }
            continue
        if name == "review":
            # The review is the frontier's job. When the frontier is not
            # available the class waits, visibly, instead of taking another
            # model.
            frontier_rows = [
                row
                for row in eligible
                if "frontier" in row["tiers"]
                and row["native"]["mapped"]
                and (row.get("eligibility") or {}).get("frontier_prime", {}).get("allowed")
            ]
            if not frontier_rows:
                result[name] = {
                    "provider": None,
                    "model": None,
                    "tier": None,
                    "native": None,
                    "role": None,
                    "reason": (
                        "no frontier model is available; the review waits for "
                        "the frontier authority instead of taking another model"
                    ),
                    "delegate": False,
                    "private_data": bool(entry["private_data"]),
                }
                continue
            chosen = max(
                frontier_rows,
                key=lambda row: max(row["score"].values()) if row["score"] else 0.0,
            )
            result[name] = {
                "provider": chosen["provider"],
                "model": chosen["model"],
                "tier": "frontier",
                "native": chosen["native"],
                "role": chosen["role"],
                "reason": "the frontier authority reviews the change",
                "delegate": bool(chosen["native"]["mapped"]),
                "private_data": bool(entry["private_data"]),
            }
            continue
        if eligible:
            chosen = max(
                eligible,
                key=lambda row: max(row["score"].values()) if row["score"] else 0.0,
            )
            result[name] = {
                "provider": chosen["provider"],
                "model": chosen["model"],
                "tier": _display_tier(chosen["tiers"]),
                "native": chosen["native"],
                "role": chosen["role"],
                "reason": (
                    "no free route is available for this class"
                    if entry["free_eligible"]
                    else "this class needs a mapped instance and never takes a free route"
                ),
                "delegate": bool(chosen["native"]["mapped"]),
                "private_data": bool(entry["private_data"]),
            }
            continue
        result[name] = {
            "provider": None,
            "model": None,
            "tier": None,
            "native": None,
            "role": None,
            "reason": "no model is available for this class right now",
            "delegate": False,
            "private_data": bool(entry["private_data"]),
        }
    return result


def build_snapshot(
    *,
    now: float,
    sources: Iterable[Mapping[str, Any]],
    ranked: Iterable[Any],
    native_models: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
    policy: Mapping[str, Any] | None = None,
    aa_cache: Mapping[str, Any] | None = None,
    measured_windows: Iterable[Mapping[str, Any]] | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Build the routing snapshot from the ranked models and the readings."""
    native_models = native_models or {}
    policy = dict(policy or {})
    entries: dict[tuple[str, str], list[Any]] = {}
    for entry in ranked:
        entries.setdefault((entry.provider, entry.model), []).append(entry)

    candidates: list[dict[str, Any]] = []
    tiers: dict[str, list[str]] = {}
    pending: list[dict[str, Any]] = []
    accounts: dict[str, list[dict[str, Any]]] = {}
    omitted = 0
    # The account section carries the windows the provider reported, even the
    # ones that do not gate a model of that account.
    for measured in measured_windows or ():
        account = str(measured.get("provider") or "")
        if not account:
            continue
        record = _window_record(measured, now)
        known = accounts.setdefault(account, [])
        if record not in known:
            known.append(record)
    for (provider, model), model_entries in sorted(entries.items()):
        row = _candidate(
            provider,
            model,
            model_entries,
            now,
            native_models.get((provider, model)),
            policy,
            aa_cache,
        )
        for tier in row["tiers"]:
            tiers.setdefault(tier, []).append(_key(provider, model))
        account = str(row.get("account") or "")
        if account:
            # The measured windows are published once per account, not once
            # per model of that account.
            windows = row.get("quotaWindows") or []
            known = accounts.setdefault(account, [])
            for window in windows:
                if window not in known:
                    known.append(window)
            row["quotaRef"] = f"accounts/{account}"
        row.pop("quotaWindows", None)
        if row["admission"]["state"] == "pending":
            pending.append(
                {
                    "provider": provider,
                    "model": model,
                    "reason": row["admission"]["reason"],
                }
            )
        if row["rank"] or row["admission"]["state"] == "pending" or row["quota_state"] != "unknown":
            candidates.append(row)
        else:
            omitted += 1
    for tier, members in tiers.items():
        order = {
            _key(entry.provider, entry.model): entry.rank
            for entry in ranked
            if entry.tier == tier
        }
        tiers[tier] = sorted(set(members), key=lambda key: (order.get(key, 0), key))

    source_records = []
    for source in sources:
        record = dict(source)
        observed = record.get("observed_at_epoch")
        record["age_seconds"] = (
            None if observed is None else int(round(now - float(observed)))
        )
        source_records.append(record)
    failed = [record for record in source_records if record.get("status") not in ("ok", "partial")]

    # Whether a frontier prime is available right now. When it is not, the
    # consumer has to wait visibly: the reason and the reset time are here,
    # so a required frontier is never quietly replaced by a delegate.
    frontier_rows = [
        row
        for row in candidates
        if "frontier" in row["tiers"] and row["quota_state"] == "available"
    ]
    frontier_models = [
        f"{row['native']['provider_instance_id'] or row['provider']}:{row['native']['model_id'] or row['model']}"
        for row in frontier_rows
    ]
    blocked = [
        row
        for row in candidates
        if "frontier" in row["tiers"] and row["quota_state"] != "available"
    ]
    frontier_reason = ""
    if not frontier_rows and blocked:
        first = blocked[0]
        frontier_reason = (
            f"{first['model']} is in the frontier tier but its quota is "
            f"{first['quota_state']}"
        )
    elif not frontier_rows:
        frontier_reason = "no model holds the frontier tier right now"

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(now),
        "max_age_seconds": max_age_seconds,
        "partial": bool(failed),
        "coverage": {
            "sources_total": len(source_records),
            "sources_ok": sum(1 for r in source_records if r.get("status") == "ok"),
            "sources_partial": sum(
                1 for r in source_records if r.get("status") == "partial"
            ),
            "sources_failed": len(failed),
            "sources": source_records,
            "frontier": {
                "available": bool(frontier_rows),
                "models": frontier_models,
                "reason": frontier_reason,
                "wait_for": "the frontier model becomes available again",
            },
        },
        "policy": {
            "frontier_prime_models": list(policy.get("frontierPrimeModels") or ()),
            "allowed_gpt_models": list(policy.get("allowedGptModels") or ()),
            "background_provider_instances": list(
                policy.get("backgroundProviderInstances") or ()
            ),
            "frontier_review": {
                "required": True,
                "fail_closed": True,
                "authority": dict(policy.get("frontierReviewAuthority") or {}),
                "rule": (
                    "an implementation by a bulk model needs a frontier review "
                    "before it is integrated; a bulk review is never a final "
                    "approval"
                ),
            },
            "basis": str(policy.get("basis") or ""),
        },
        "tiers": tiers,
        "quota": {"accounts": accounts},
        "quality_feed": {
            "source": "artificialanalysis",
            "status": str((aa_cache or {}).get("status") or "no_cache"),
            "reason": str((aa_cache or {}).get("reason") or ""),
            "intelligence_index_version": (aa_cache or {}).get("index_version"),
            "fetched_at": (aa_cache or {}).get("fetched_at"),
            "age_seconds": (aa_cache or {}).get("age_seconds"),
            "records": len((aa_cache or {}).get("records") or []),
            "attribution": (
                "Quality indices, cost per task, and median performance come "
                "from Artificial Analysis. The token prices are the prices of "
                "the feed and are not a subscription bill."
            ),
        },
        "workload_policy": {
            "classes": [dict(entry) for entry in WORKLOAD_CLASSES],
            "free_rule": (
                "a free route is the lowest intelligence tier and carries only "
                "low complexity work: bounded research, cheap and easy tasks, "
                "and bulk metadata updates with checks. It never holds the "
                "frontier, never carries private work, and never decides a "
                "complex engineering, security, or integration question, "
                "whatever its measured quality is"
            ),
            "complexity_ceiling": (
                "a free route is capped at the low complexity classes "
                "independently of any quality score"
            ),
        },
        "recommendations": _recommendations(candidates, WORKLOAD_CLASSES),
        "candidates": candidates,
        "pending": pending,
        "counts": {
            "candidates": len(candidates),
            "ranked": sum(1 for row in candidates if row["rank"]),
            "pending": len(pending),
            "omitted": omitted,
        },
    }


def write_snapshot(path: str | os.PathLike[str], snapshot: Mapping[str, Any]) -> None:
    """Write the snapshot atomically, so a reader never sees half a file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".new")
    payload = json.dumps(
        snapshot, indent=1, sort_keys=False, default=str, allow_nan=False
    )
    temporary.write_text(payload + "\n", encoding="utf-8")
    os.chmod(temporary, 0o644)
    os.replace(temporary, target)


def snapshot_age(path: str | os.PathLike[str]) -> float | None:
    """The age of the snapshot on disk, or None when it is not there."""
    try:
        return max(0.0, time.time() - os.stat(path).st_mtime)
    except OSError:
        return None
