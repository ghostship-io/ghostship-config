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

    known = isinstance(used, (int, float)) and not isinstance(used, bool)
    if known and (float(used) < 0.0 or float(used) > 1.0):
        known = False
    expired = isinstance(reset, (int, float)) and float(reset) <= now
    evidence = "provider_reported" if known and not expired else "unknown"

    record: dict[str, Any] = {
        "quota_id": quota_id,
        "kind": kind,
        "evidence": evidence,
        "used_ratio": round(float(used), 4) if known and not expired else None,
        "remaining_ratio": (
            round(max(0.0, 1.0 - float(used)), 4) if known and not expired else None
        ),
        "reset_at": _iso(float(reset)) if isinstance(reset, (int, float)) else None,
        "seconds_to_reset": (
            int(round(float(reset) - now)) if isinstance(reset, (int, float)) else None
        ),
        "duration_seconds": int(duration) if isinstance(duration, (int, float)) and duration else None,
        "check_at": _iso(float(observed)) if isinstance(observed, (int, float)) else _iso(now),
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


def _candidate(
    provider: str,
    model: str,
    entries: list[Any],
    now: float,
    native: Mapping[str, Any] | None,
    policy: Mapping[str, Any],
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
        "quota_state": quota_state,
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
        "eligibility": _eligibility(provider, model, tiers, native_record, policy),
        "frontier_surplus": {
            "available": bool(surplus.get("available")),
            "reason": str(surplus.get("reason") or ""),
            "expires_in_seconds": surplus.get("expires_in_seconds"),
            "surplus_ratio": surplus.get("surplus_ratio"),
            "reserve_ratio": surplus.get("reserve_ratio"),
            "pace_delta": surplus.get("pace_delta"),
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


def build_snapshot(
    *,
    now: float,
    sources: Iterable[Mapping[str, Any]],
    ranked: Iterable[Any],
    native_models: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
    policy: Mapping[str, Any] | None = None,
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
    for (provider, model), model_entries in sorted(entries.items()):
        row = _candidate(
            provider,
            model,
            model_entries,
            now,
            native_models.get((provider, model)),
            policy,
        )
        for tier in row["tiers"]:
            tiers.setdefault(tier, []).append(_key(provider, model))
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
    payload = json.dumps(snapshot, indent=1, sort_keys=False, default=str)
    temporary.write_text(payload + "\n", encoding="utf-8")
    os.chmod(temporary, 0o644)
    os.replace(temporary, target)


def snapshot_age(path: str | os.PathLike[str]) -> float | None:
    """The age of the snapshot on disk, or None when it is not there."""
    try:
        return max(0.0, time.time() - os.stat(path).st_mtime)
    except OSError:
        return None
