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
    routing             the owner's routing switch and where it came from
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
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import aa_3d
import aa_bind as bind_module
import facts as facts_module
import outcomes as outcomes_module
import quota as quota_module
import ranking as ranking_module
import usage_inference
import value_policy

try:  # pragma: no cover - the collector always ships metrics.py
    from metrics import ExactLabel, MAX_LABEL_LENGTH
except ImportError:  # pragma: no cover - standalone use
    class ExactLabel(str):  # pragma: no cover - standalone use
        """A label value that is published exactly as it is."""

    MAX_LABEL_LENGTH = 120

SCHEMA = "ghostship.ai-usage.routing"
SCHEMA_VERSION = 1

# Where the routing switch comes from. The switch is the owner's decision,
# read from the NixOS option, and the snapshot says so instead of leaving a
# consumer to guess.
ROUTING_SOURCE = "nixos-option"

# How long a consumer may trust the snapshot before it has to read a new one.
DEFAULT_MAX_AGE_SECONDS = 900

# The states a candidate can be in.
QUOTA_AVAILABLE = "available"
QUOTA_EXHAUSTED = "exhausted"
QUOTA_UNKNOWN = "unknown"

# Why a route the instance does not offer is unusable. The ranking decides
# that the route is not offered; the catalog says whether the model behind
# it is deprecated, and the reason names both facts. A route without a
# catalog status keeps the bare fact, and a reader never sees an unavailable
# route with an empty reason.
NOT_OFFERED_REASON = "not offered by the T3 instance"
NOT_OFFERED_DEPRECATED_REASON = (
    "not offered by the T3 instance (deprecated in the catalog)"
)

# Why a route the free pool parked is unusable. The pool marks a route
# unavailable for a future cooldown, or when the account's policy does not
# let it serve development work, and it publishes no reason of its own. The
# snapshot names the two cases: a route whose cooldown has not run out yet
# says when it cools down, and a route without one says that the pool does
# not offer it. A reader never sees a parked route with an empty reason.
POOL_COOLDOWN_REASON = "cooling down in the free pool until {cooldown}"
POOL_NOT_OFFERED_REASON = (
    "the free pool does not offer the route for development work"
)

# The roles the owner gave the tiers.
ROLE_PRIME = "prime"
ROLE_DELEGATE = "delegate"

# The tiers the snapshot reports, in the order the dashboard reads them.
TIER_NAMES = ("frontier", "bulk", "free", "3d")

# The task type of every tier. The trust of a model is read for the task
# type of the tier it holds, and the outcomes of a model are the rounds of
# that task type: the work of the frontier, the bulk and the free tiers is
# implementation work, and the work of the 3D tier is CAD execution.
TIER_TASK_TYPES = {
    "frontier": "implementation",
    "bulk": "implementation",
    "free": "implementation",
    "3d": "cad-execution",
}

# The provider reservations of the runtime policy name a T3 Code provider
# instance; the collector names the same provider by its account. A route of
# a reserved provider is not a worker of the tiers outside its workload: it
# follows every unreserved route of its trust group, and it says why.
RESERVATION_PROVIDERS = {"claudeAgent": "claude", "codex": "codex", "grok": "grok"}
RESERVATION_TIERS = {"review-roles": ("frontier",), "3d": ("3d",)}
RESERVATION_IN_FORCE = ("active", "interim")

# The visible label of a window whose state the provider publishes rather
# than reports. The OpenCode Go documentation lists the free routes as
# unlimited "for a limited time", so the label says that it is a promotion
# and not a permanent entitlement.
WINDOW_LABELS = {
    "free-unlimited": "unlimited (limited-time promotion)",
}


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
    def _get(*names: str, default: Any = None) -> Any:
        for name in names:
            value = getattr(window, name, None)
            if value is None and isinstance(window, Mapping):
                value = window.get(name)
            if value is not None:
                return value
        return default

    kind = str(_get("kind", default="other"))
    quota_id = str(_get("quota_id", "quotaId", default=""))
    used = _get("used_ratio", "usedRatio")
    reset = _get("reset_epoch", "resetEpoch")
    duration = _get("duration_seconds", "durationSeconds")
    applies = _get("applies_to", "appliesTo", default=())
    observed = _get("observed_at", "observedAtEpoch")
    basis = str(_get("basis", default="") or "")
    ends = _finite(_get("ends_at", "endsAt"))
    # The provider's own status of the window, when it publishes one. A
    # window it does not state a status for carries no status key.
    status = _get("status")

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
        # Where the numbers of the window come from. A published limit and a
        # reading the provider reported are never mixed, and the label says
        # which one a reader is looking at.
        "basis": basis,
        "label": WINDOW_LABELS.get(quota_id, ""),
        # When the entitlement of the window ends. A promotion without a
        # published end has none, and that is unknown rather than zero.
        "ends_at": _iso(ends) if ends is not None else None,
        # The check time is the moment the provider reported the window. It
        # is never the moment the snapshot was written.
        "check_at": _iso(observed_value) if observed_value is not None else None,
        "provenance": "collector",
    }
    if applies:
        record["applies_to"] = [str(token) for token in applies]
    if isinstance(status, str) and status:
        record["status"] = status
    return record


def _inferred_window_record(
    window: Any, now: float, applies_to: Iterable[str] = ()
) -> dict[str, Any]:
    """One inferred window, as the account section publishes it.

    The numbers are the inference's own: a limit failure measured the
    window, the budget and the episode, and the evidence says so. An
    inferred window is never published as a reading the provider reported,
    and it never replaces one. A limit that belongs to a model keeps that
    model as its scope, so a reader sees which family it constrains.
    """
    record = _window_record(window, now)
    inference = getattr(window, "inference", None)
    if inference is None and isinstance(window, Mapping):
        inference = window.get("inference")
    inference = dict(inference) if isinstance(inference, Mapping) else {}
    record["kind"] = "inferred"
    record["evidence"] = "inferred"
    record["inference"] = {
        "window": inference.get("window"),
        "budget": inference.get("budget"),
        "unit": inference.get("unit") or None,
        "scope": inference.get("scope") or None,
        "weights": dict(inference.get("weights") or {}),
        "weights_basis": inference.get("weights_basis") or None,
        "episodes": inference.get("episodes"),
        "state": inference.get("state") or None,
        "rolling": bool(inference.get("rolling")),
    }
    scope = [str(token) for token in applies_to or ()]
    if scope:
        record["applies_to"] = scope
    return record


def _pace_record(
    window: Any, now: float, remaining: float | None
) -> tuple[float | None, float | None]:
    """The expected usage of a window by now and the measured usage."""
    def _get(*names: str, default: Any = None) -> Any:
        for name in names:
            value = getattr(window, name, None)
            if value is None and isinstance(window, Mapping):
                value = window.get(name)
            if value is not None:
                return value
        return default

    duration = _get("duration_seconds", "durationSeconds")
    reset = _get("reset_epoch", "resetEpoch")
    if not duration or float(duration) <= 0 or not isinstance(reset, (int, float)):
        return None, None
    start = float(reset) - float(duration)
    expected = min(1.0, max(0.0, (now - start) / float(duration)))
    actual = None if remaining is None else max(0.0, min(1.0, 1.0 - remaining))
    return expected, actual


def _native_option(option: Mapping[str, Any]) -> dict[str, Any]:
    """One native option, with every descriptor value the stock catalog gave.

    A descriptor that lists the allowed values is what makes an alignment
    checkable. The keys are kept as the catalog spells them; no global option
    name is assumed.
    """
    current = option.get("currentValue", option.get("current_value"))
    record: dict[str, Any] = {
        "id": str(option.get("id")),
        "current_value": current,
        "current_published": current is not None,
    }
    for key in ("values", "allowed", "allowedValues", "choices", "enum"):
        value = option.get(key)
        if isinstance(value, (list, tuple)) and 0 < len(value) <= 64:
            cleaned = [
                item
                for item in value
                if isinstance(item, (str, int, float, bool))
            ]
            if cleaned:
                record["values"] = cleaned
                break
    if "values" not in record:
        choices = option.get("options")
        if isinstance(choices, list) and 0 < len(choices) <= 64:
            cleaned = [
                entry.get("id")
                for entry in choices
                if isinstance(entry, Mapping) and isinstance(entry.get("id"), str)
            ]
            if cleaned:
                record["values"] = cleaned
    return record


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
        "options": [_native_option(option) for option in (native.get("options") or []) if isinstance(option, Mapping) and option.get("id")],
        "mapped": True,
        "provenance": "live T3 Code instance catalog",
    }


def _quota_state(remaining: float | None, windows: list[dict[str, Any]]) -> str:
    """The state of the capacity behind a model.

    A window that is known to be spent decides the state, whatever else is
    unknown: an unknown window never hides an exhausted allowance. Only when
    no window is known to be spent does an unknown window make the state
    unknown.
    """
    if not windows:
        return QUOTA_UNKNOWN
    spent = [
        window
        for window in windows
        if window.get("evidence") == "provider_reported"
        and isinstance(window.get("remaining_ratio"), (int, float))
        and not isinstance(window.get("remaining_ratio"), bool)
        and float(window["remaining_ratio"]) <= 0.0
    ]
    if spent:
        return QUOTA_EXHAUSTED
    if any(window.get("evidence") == "unknown" for window in windows):
        return QUOTA_UNKNOWN
    if remaining is None:
        return QUOTA_UNKNOWN
    if remaining <= 0.0:
        return QUOTA_EXHAUSTED
    return QUOTA_AVAILABLE


def _unknown_reason(
    windows: list[dict[str, Any]], remaining: float | None, quota_state: str
) -> str:
    """Why the headroom is unknown, in words.

    An unknown headroom always says why it is unknown: a reader never has
    to guess whether the provider published no window, or whether the window
    it published could not be read.
    """
    if quota_state != QUOTA_UNKNOWN:
        return ""
    code = quota_module.unknown_reason_code(windows, remaining)
    return quota_module.UNKNOWN_REASON_TEXT.get(code, "")


def unknown_headroom_violations(
    candidates: Iterable[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """The rows whose headroom is unknown without a reason.

    The owner rule: an unknown headroom always says why it is unknown. A
    row that is unknown and silent is a gap, and this is what finds it. An
    empty list is the proof that the rule holds.
    """
    violations: list[dict[str, str]] = []
    for row in candidates or ():
        if not isinstance(row, Mapping):
            continue
        if str(row.get("quota_state") or "") != QUOTA_UNKNOWN:
            continue
        if str(row.get("unknown_reason") or "").strip():
            continue
        violations.append(
            {
                "provider": str(row.get("provider") or ""),
                "model": str(row.get("model") or ""),
            }
        )
    return violations


def _exact_model_match(model: str, allowed: Iterable[str]) -> bool:
    """True when the model is exactly one of the allowed models.

    The match is exact: a model whose name only contains an allowed name, or
    only starts with it, is a different model and does not inherit the
    permission.
    """
    text = _normalise_model(model)
    if not text:
        return False
    return any(text == _normalise_model(item) for item in allowed)


def _normalise_model(name: str) -> str:
    """The exact model id, lowercased, without its provider prefix.

    The punctuation is kept: "gpt-6.1-sol" and "gpt-61-sol" are different
    model ids, and one of them must not inherit the permission of the other.
    """
    text = str(name or "").strip().lower()
    if "/" in text:
        text = text.rsplit("/", 1)[1]
    return text


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
    prime_models = [str(item) for item in policy.get("frontierPrimeModels") or ()]
    allowed_gpt = [str(item) for item in policy.get("allowedGptModels") or ()]
    background = [
        str(item).lower() for item in policy.get("backgroundProviderInstances") or ()
    ]
    is_gpt = model_text.startswith("gpt")
    gpt_allowed = (not is_gpt) or _exact_model_match(model, allowed_gpt)
    mapped = bool(native.get("mapped"))
    return {
        "frontier_prime": {
            "allowed": mapped and _exact_model_match(model, prime_models),
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


# The access classes of a model. The class says how the model is reached and
# what it costs, never what it can do: capability and workload admission are a
# separate statement.
ACCESS_DEDICATED_FREE = "dedicated_free"
ACCESS_PROVIDER_PROMO = "provider_promo"
ACCESS_PROVIDER_PAID = "provider_paid"
ACCESS_UNKNOWN = "unknown"

# The billing classes of a route. The class says how the route is paid for:
# a subscription the owner already has, a route that costs nothing by
# construction, a route that costs nothing right now because of a promotion,
# a route that is paid per token, or a route whose billing is not known.
# It is derived from the access class, never guessed from the price.
BILLING_SUBSCRIPTION = "subscription"
BILLING_FREE = "free"
BILLING_PROMOTION = "promotion"
BILLING_PAY_PER_TOKEN = "pay_per_token"
BILLING_UNKNOWN = "unknown"

# Every billing class a route may carry. A route outside this set is a bug
# in the collector, not a new class.
BILLING_CLASSES = (
    BILLING_SUBSCRIPTION,
    BILLING_FREE,
    BILLING_PROMOTION,
    BILLING_PAY_PER_TOKEN,
    BILLING_UNKNOWN,
)

# The providers whose paid routes are covered by a subscription the owner
# already pays for. The route is not billed per token.
SUBSCRIPTION_PROVIDERS = (
    "claude",
    "codex",
    "antigravity",
    "cursor",
    "ollama",
    "opencode-go",
)

# The providers whose paid routes are billed per token. The subscription of
# another provider does not pay for them.
PAY_PER_TOKEN_PROVIDERS = (
    "grok",
    "openrouter",
    "vercel",
    "requesty",
)


def _billing_class(kind: str, provider: str) -> str:
    """How the route is paid for, from its access class and its provider.

    The access class is the source: a dedicated free route is free, a
    promotional route is a promotion, and a route with no known access is
    unknown. A paid route is a subscription only when its provider is one the
    owner pays a subscription for, and a pay per token route only when its
    provider bills that way. A paid route of a provider we do not know how
    the owner pays for is unknown: it never becomes a subscription.
    """
    if kind == ACCESS_DEDICATED_FREE:
        return BILLING_FREE
    if kind == ACCESS_PROVIDER_PROMO:
        return BILLING_PROMOTION
    if kind != ACCESS_PROVIDER_PAID:
        return BILLING_UNKNOWN
    name = str(provider or "").strip().lower()
    if name in SUBSCRIPTION_PROVIDERS:
        return BILLING_SUBSCRIPTION
    if name in PAY_PER_TOKEN_PROVIDERS:
        return BILLING_PAY_PER_TOKEN
    return BILLING_UNKNOWN


def _access_record(
    provider: str,
    model: str,
    free_models: set[tuple[str, str]],
    promo_models: set[tuple[str, str]],
    prices: Mapping[str, Any] | None,
    native_mapped: bool = False,
) -> dict[str, Any]:
    """How a model is reached, and what it costs.

    The promotional zero price is checked first: a paid provider's route
    that costs nothing right now is a paid route, and it competes in bulk.
    The dedicated free routes are the ones that cost nothing by
    construction: the free inference pool's own integrations, and the routes
    a provider lists at no cost. The two are not the same thing, and a
    model that is in both sets is a promotional route.

    A free route that the live instance catalog proves is a native route
    runs as a provider-native thread; a free route the collector only knows
    from the pool runs as an inference job.
    """
    pair = (provider, model)
    if pair in promo_models:
        kind = ACCESS_PROVIDER_PROMO
        basis = "a paid provider route that costs nothing right now"
    elif pair in free_models:
        kind = ACCESS_DEDICATED_FREE
        basis = (
            "a free route: the dedicated free inference pool, or a route the "
            "provider lists at no cost"
        )
    elif isinstance(prices, Mapping) and any(
        isinstance(value, (int, float)) for value in prices.values()
    ):
        kind = ACCESS_PROVIDER_PAID
        basis = "the provider's own listing"
    else:
        kind = ACCESS_UNKNOWN
        basis = "no published price"
    return {
        "kind": kind,
        "basis": basis,
        # How the route is paid for. The class is derived from the access
        # class above, so the two never disagree.
        "billing": _billing_class(kind, provider),
        "price": dict(prices or {}),
        "execution": (
            "provider_native"
            if native_mapped or kind != ACCESS_DEDICATED_FREE
            else "inference_job"
        ),
    }


def _cache_is_usable(cache: Mapping[str, Any] | None, now: float | None) -> bool:
    """True when the feed cache may be read as the current evidence."""
    if not isinstance(cache, Mapping) or cache.get("status") != "ok":
        return False
    if not str(cache.get("index_version") or "").strip():
        return False
    if now is None:
        return True
    fetched = cache.get("fetched_at_epoch")
    if not isinstance(fetched, (int, float)) or isinstance(fetched, bool):
        return False
    if fetched != fetched or fetched in (float("inf"), float("-inf")):
        return False
    if fetched > now + 300.0:
        return False
    return (now - float(fetched)) <= 36 * 3600.0


def _intelligence_record(
    cache: Mapping[str, Any] | None,
    provider: str,
    model: str,
    native_options: Any = None,
    now: float | None = None,
) -> dict[str, Any]:
    """The Artificial Analysis record of one model, or the coverage gap.

    The feed is an external quality input. A model the feed does not list is
    unknown, not bad, and the version and the age of the feed are published
    with the record.
    """
    if not cache:
        return {"state": "no_cache", "source": "artificialanalysis"}
    if not _cache_is_usable(cache, now):
        return {
            "state": "stale" if cache.get("status") == "ok" else str(cache.get("status") or "missing"),
            "source": "artificialanalysis",
            "index_version": cache.get("index_version"),
            "fetched_at": cache.get("fetched_at"),
        }
    if cache.get("status") != "ok":
        return {
            "state": str(cache.get("status") or "missing"),
            "reason": str(cache.get("reason") or ""),
            "source": "artificialanalysis",
            "index_version": cache.get("index_version"),
            "fetched_at": cache.get("fetched_at"),
            "age_seconds": cache.get("age_seconds"),
        }
    binding = bind_module.resolve(
        cache.get("records") or [], provider, model, mode="reference"
    )
    if binding.get("state") != "measured":
        return {
            "state": str(binding.get("state") or "missing"),
            "reason": str(binding.get("reason") or ""),
            "source": "artificialanalysis",
            "index_version": cache.get("index_version"),
            "fetched_at": cache.get("fetched_at"),
            "age_seconds": cache.get("age_seconds"),
            "provenance": {
                "provider": provider,
                "model": model,
                "native_variant": binding.get("variant") or "",
            },
        }
    record = binding["record"]
    return {
        "reference": binding.get("reference"),
        "alternatives": binding.get("alternatives") or [],
        "value_missing": binding.get("value_missing") or [],
        "state": "measured",
        "source": "artificialanalysis",
        "index_version": cache.get("index_version"),
        "fetched_at": cache.get("fetched_at"),
        "age_seconds": cache.get("age_seconds"),
        "id": binding.get("id") or "",
        "slug": binding.get("slug") or "",
        "name": binding.get("name") or "",
        "indices": record.get("indices") or {},
        "cost_per_task": record.get("cost_per_task"),
        "median_performance": record.get("median_performance"),
        "token_prices": record.get("prices") or {},
        "release_date": binding.get("release_date"),
        "measured_variant": binding.get("measured_variant") or "",
        "native_variant": binding.get("native_variant") or "",
        "variant_match": binding.get("variant_match") or "",
        "variant_mismatch": bool(binding.get("variant_mismatch")),
        "reference": binding.get("reference"),
        "alternatives": binding.get("alternatives") or [],
        "condition_confirmed": bool(binding.get("condition_confirmed")),
        "condition_unknown": bool(binding.get("condition_unknown")),
        "identity_match": binding.get("identity_match") or "",
        "variants": binding.get("variants") or [],
        "matched_by": binding.get("matched_by") or "",
        "checkpoint": binding.get("checkpoint") or "",
        "text_only": bind_module.is_text_only(record),
        "provenance": binding.get("provenance") or {},
        "note": (
            "the token prices and the cost per task are different things: "
            "the price is per million tokens, the cost per task is what a "
            "measured task costs"
        ),
    }


def _not_offered_reason(catalog: Any, provider: str, model: str) -> str:
    """Why a route the instance does not offer is unusable, in words.

    The ranking decides that the route is not offered. The catalog is the
    only source that says whether the model behind the route is deprecated,
    so the reason names the retirement when it is published and stays at the
    bare fact when it is not.
    """
    entry = None
    if catalog is not None:
        getter = getattr(catalog, "model_entry", None)
        if callable(getter):
            try:
                entry = getter(provider, model)
            except Exception:  # pragma: no cover - a catalog without the model
                entry = None
    status = ""
    if isinstance(entry, Mapping):
        status = str(entry.get("status") or "")
    if status.strip().lower() == "deprecated":
        return NOT_OFFERED_DEPRECATED_REASON
    return NOT_OFFERED_REASON


def _pool_parked_reason(
    evidence: Mapping[str, Any] | None, now: float
) -> str:
    """Why a route the free pool parked is unusable, in words.

    The pool publishes no reason of its own: it says a route is unavailable,
    and it publishes the moment the route cools down. A cooldown that has
    not run out yet names the moment it ends, and a route without one is not
    offered for development work.
    """
    cooldown = None
    if isinstance(evidence, Mapping):
        value = evidence.get("cooldown_until")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            cooldown = float(value)
    if cooldown is not None and cooldown > now:
        moment = _iso(cooldown)
        if moment:
            return POOL_COOLDOWN_REASON.format(cooldown=moment)
    return POOL_NOT_OFFERED_REASON


def _candidate(
    provider: str,
    model: str,
    entries: list[Any],
    now: float,
    native: Mapping[str, Any] | None,
    policy: Mapping[str, Any],
    aa_cache: Mapping[str, Any] | None = None,
    free_set: set[tuple[str, str]] | None = None,
    promo_set: set[tuple[str, str]] | None = None,
    catalog: Any = None,
    pool_evidence: Mapping[str, Any] | None = None,
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
    not_offered = False
    parked = False
    settled = True
    pending_reason = ""
    used_tokens = 0.0
    three_d_tokens = 0.0
    account = ""
    pace: float | None = None
    expected: float | None = None
    actual: float | None = None
    raw_windows: list[Any] = []
    surplus: dict[str, Any] = {}
    observed_failure: dict[str, Any] = {}
    capacity_basis = ""
    capacity_inference: dict[str, Any] = {}

    for entry in entries:
        if entry.tier:
            tiers.append(entry.tier)
            ranks[entry.tier] = entry.rank
            scores[entry.tier] = round(float(entry.score), 3)
        quality = None if entry.quality is None else float(entry.quality)
        if entry.remaining is not None:
            remaining = float(entry.remaining)
        if entry.expires_in_seconds is not None:
            expires_in = float(entry.expires_in_seconds)
        available = bool(entry.available)
        # The ranking decides that a route is not offered; the snapshot keeps
        # that judgement so the published reason can say it instead of
        # rebuilding an empty one from the windows.
        not_offered = not_offered or (
            str(getattr(entry, "availability_reason", "") or "")
            == ranking_module.REASON_NOT_OFFERED
        )
        # The ranking decides that the free pool parked the route; the
        # snapshot keeps that judgement so the published reason can say it
        # instead of rebuilding an empty one from the windows.
        parked = parked or (
            str(getattr(entry, "availability_reason", "") or "")
            == ranking_module.REASON_ROUTE_PARKED
        )
        settled = bool(entry.settled)
        pending_reason = entry.pending_reason
        used_tokens = float(entry.used_tokens)
        three_d_tokens = float(entry.three_d_tokens)
        account = entry.account or account
        pace = getattr(entry, "pace", pace)
        surplus = getattr(entry, "frontier_surplus", None) or surplus
        capacity_basis = getattr(entry, "capacity_basis", "") or capacity_basis
        capacity_inference = dict(
            getattr(entry, "capacity_inference", None) or capacity_inference
        )
        for reason in entry.reasons:
            if reason not in reasons:
                reasons.append(reason)
        raw_windows = list(entry.windows)
        failure = getattr(entry, "observed_failure", None)
        if failure:
            observed_failure = dict(failure)
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

    # The pace state of the row: where the share left sits on the line of the
    # most constraining window, in points. The line of that window is the
    # share left minus the Paced Availability, so the state is the one the
    # published number draws; a row with no line, or with nothing left, says
    # so instead of guessing.
    expected_left = None
    if remaining is not None and pace is not None:
        expected_left = remaining - pace
    elif expected is not None:
        expected_left = 1.0 - expected
    pace_state = value_policy.pace_state(remaining, expected_left)

    native_record = _native_record(provider, model, native)
    # The owner's lists, read once from the runtime policy. Every consumer
    # of them reads this block, so a policy change has one effect.
    workhorses = policy.get(POLICY_WORKHORSES)
    excluded = policy.get(POLICY_EXCLUDED)
    selection = {
        "frontier_workhorse": _frontier_workhorse(model, workhorses),
        "excluded": _selection_excluded(model, excluded),
        "workhorses": [
            str(name) for name in (workhorses if isinstance(workhorses, (list, tuple)) else FRONTIER_WORKHORSES)
        ],
        "excluded_models": [
            str(name)
            for name in (
                excluded if isinstance(excluded, (list, tuple)) else SELECTION_EXCLUDED_MODELS
            )
        ],
        "basis": "the runtime policy of the owner",
    }
    quota_state = _quota_state(remaining, windows)
    capacity_measured = bool(windows) and all(
        window["evidence"] == "provider_reported" for window in windows
    )
    # Why the headroom is unknown, when it is. An unknown headroom always
    # says why: a reader never has to guess why a window is missing.
    unknown_reason = _unknown_reason(windows, remaining, quota_state)

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
        "quota_windows_applied": _applied_windows(
            getattr(entries[0], "applied_windows", ()) if entries else ()
        ),
        "quota_scope_basis": (
            "a window is shared when the provider does not scope it to a model "
            "family, and a subordinate when its own scope names one; the scope "
            "comes from the provider's window identity, and the most "
            "constraining of every window that applies decides the model"
        ),
        # The availability is the ranking's own judgement: a model of an
        # account that reports no quota at all is usable, with an unknown
        # headroom. The quota state keeps the three window states.
        "available": bool(available),
        "availability": {
            "state": "available" if available else "unavailable",
            "evidence": (
                "observed"
                if observed_failure
                else ("measured" if capacity_measured else "unknown")
            ),
            "reason": (
                str(observed_failure.get("label") or "")
                if observed_failure
                else (
                    # The pool parked the route. The pool publishes no
                    # reason of its own, so the snapshot names the two
                    # cases: a cooldown that has not run out, and a route
                    # the pool does not offer for development work.
                    _pool_parked_reason(pool_evidence, now)
                    if parked
                    else (
                        "every applicable window has headroom"
                        if available and capacity_measured
                        else (
                            "a window is spent"
                            if quota_state == QUOTA_EXHAUSTED
                            else (
                                _not_offered_reason(catalog, provider, model)
                                if not_offered
                                else unknown_reason
                            )
                        )
                    )
                )
            ),
            # The observed failure of the route, when there is one. The
            # reason is a code and a fixed label; the provider's own text
            # never leaves the collector.
            "observed_failure": (
                {
                    "scope": str(observed_failure.get("scope") or ""),
                    "target": str(observed_failure.get("target") or ""),
                    "reason": str(observed_failure.get("reason") or ""),
                    "label": str(observed_failure.get("label") or ""),
                    "observed_at": observed_failure.get("observed_at"),
                }
                if observed_failure
                else None
            ),
        },
        "quota_state": quota_state,
        # The reason the headroom is unknown, or an empty string when it is
        # known. An unknown headroom without a reason is a gap.
        "unknown_reason": unknown_reason,
        "account": account,
        "quota_account": account,
        "quality": {
            "value": None if quality is None else round(quality, 2),
            "source": "unknown" if quality is None else "measured",
            "measured": quality is not None,
            "basis": (
                "the verified Artificial Analysis intelligence index"
                if quality is not None
                else "no verified record; the model awaits the feed"
            ),
        },
        "capacity": {
            "remaining_ratio": None if remaining is None else round(remaining, 4),
            "source": "measured" if capacity_measured else "unknown",
            "measured": capacity_measured,
            "expires_in_seconds": None if expires_in is None else int(round(expires_in)),
            # The capacity binding is the window with the least headroom.
            "capacity_binding": _binding_record(
                getattr(entries[0], "capacity_binding", None) if entries else None
            ),
            # The basis of the numbers of the binding window, and the end of
            # its entitlement when the provider publishes one. A promotion
            # without a published end has none, and that is unknown.
            "basis": _binding_basis(
                getattr(entries[0], "capacity_binding", None) if entries else None
            ),
            # Where the capacity of the route comes from: a reading the
            # provider reported, an inference from the limit failures of the
            # route, a statement the provider publishes, or nothing at all.
            "capacity_basis": str(capacity_basis or ""),
            # The inference behind the capacity, when the capacity was
            # inferred: the window it was measured over, the budget, the
            # unit, the scope, the weights, the episode count and the state.
            # A route that reports its usage has none of these.
            "inference": {
                "window": capacity_inference.get("window"),
                "budget": capacity_inference.get("budget"),
                "unit": capacity_inference.get("unit") or None,
                "scope": capacity_inference.get("scope") or None,
                "weights": dict(capacity_inference.get("weights") or {}),
                "weights_basis": capacity_inference.get("weights_basis") or None,
                "episodes": capacity_inference.get("episodes"),
                "state": capacity_inference.get("state") or None,
                "rolling": bool(capacity_inference.get("rolling")),
            },
            "ends_at": _binding_ends_at(
                getattr(entries[0], "capacity_binding", None) if entries else None
            ),
            # The pace binding is the window that runs out first, and it is
            # not necessarily the same window.
            "expected_used_ratio": None if expected is None else round(expected, 4),
            "measured_used_ratio": None if actual is None else round(actual, 4),
            "pace_delta": None if pace is None else round(pace, 4),
            "scope": dict(
                (getattr(entries[0], "quota_scope", None) or {}) if entries else {}
            ),
            "capacity_binding_id": _binding_id(
                getattr(entries[0], "capacity_binding", None) if entries else None
            ),
            "pace_binding_id": _binding_id(
                getattr(entries[0], "pace_binding", None) if entries else None
            ),
            "pace_binding": _binding_record(
                getattr(entries[0], "pace_binding", None) if entries else None
            ),
            "pace_basis": (
                "expected = clamp(1 - (reset - now) / duration, 0, 1); a positive "
                "pace is behind the line, and the most constraining window is the "
                "smallest pace"
            ),
            # The owner's name for the same number: the Paced Availability is
            # the share left minus the expected share left in the most
            # constraining window. It is the pace delta of that window.
            "paced_availability": (
                None if pace is None else round(pace, 4)
            ),
            "paced_availability_window": _binding_id(
                getattr(entries[0], "pace_binding", None) if entries else None
            ),
            # The band the Paced Availability falls in: ahead, on_pace,
            # behind, far_behind, spent or unknown. The Providers page colours
            # a route by this state instead of drawing its own band, so the
            # collector and the page cannot disagree about where a route is.
            "pace_state": pace_state,
        },
        "usage": {
            "tokens_7d": round(used_tokens, 1),
            "source": "measured" if used_tokens > 0 else "none",
            "measured": used_tokens > 0,
            "basis": "token volume, not task success",
        },
        "three_d": {
            # No 3D prior exists: the tier is admitted on explicit visual
            # capability and a verified workload admission, and its rank is
            # the measured record. The usage is displayed beside that.
            "usage_tokens": round(three_d_tokens, 1),
            "source": "measured" if three_d_tokens > 0 else "none",
            "basis": "our own 3D printing session history, last 30 days",
        },
        "intelligence": _intelligence_record(
            aa_cache, provider, model, native_record.get("options"), now
        ),
        "access": {
            "kind": ACCESS_UNKNOWN,
            "basis": "",
            "billing": BILLING_UNKNOWN,
            "price": {},
            "execution": "provider_native",
        },
        "price": {
            "input": None,
            "output": None,
            "cache_read": None,
            "source": "provider listing",
            "relative_index": None,
        },
        "value": {
            "strength": round(quality, 2) if quality is not None else None,
            "strength_source": "prior",
            "relative_cost": None,
            "value": None,
            "formula": CALCULATION["value"]["formula"],
        },
        "eligibility": _eligibility(provider, model, tiers, native_record, policy),
        "selection": selection,
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
        "free_pool": _free_pool_record(None),
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
        "free_eligible": True,
        "private_data": True,
        "complexity": "high",
        "description": "engineering work on private code",
    },
    {
        "id": "review",
        "free_eligible": True,
        "private_data": True,
        "complexity": "high",
        "description": "the frontier review of a change, and its security and integration checks",
    },
)


def _admitted_for(row: Mapping[str, Any], workload: str) -> bool:
    """True when a row has admission evidence for one workload class."""
    for entry in _admission_entries(row):
        if str(entry.get("workload") or "") == workload and entry.get("admitted") is True:
            return True
    return False


def _admission_entries(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Every admission entry of a row: the durable fact and the free pool."""
    entries: list[Mapping[str, Any]] = []
    evidence = row.get("admission_evidence")
    if isinstance(evidence, list):
        entries.extend(entry for entry in evidence if isinstance(entry, Mapping))
    pool = row.get("free_pool") or {}
    admission = pool.get("admission")
    if isinstance(admission, list):
        entries.extend(entry for entry in admission if isinstance(entry, Mapping))
    return entries


def _admitted_for_any(row: Mapping[str, Any]) -> bool:
    """True when a row has an admission for at least one workload."""
    return any(entry.get("admitted") is True for entry in _admission_entries(row))


def _is_pool_route(row: Mapping[str, Any]) -> bool:
    """True when the route runs as a pool inference job, not as a native one.

    A dedicated free route the live instance catalog proves is a native
    route runs as a provider-native thread and may carry a delegate. A route
    the collector only knows from the free pool has no native instance, so
    it runs as an inference job and needs a current admission.
    """
    access = row.get("access") or {}
    if access.get("kind") != ACCESS_DEDICATED_FREE:
        return False
    return not bool((row.get("native") or {}).get("mapped"))


def _free_pool_record(evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    """The free pool's own evidence about one route.

    The limits keep the basis they were read with: the provider's own
    documentation, the pool's own setting, an observation of the provider's
    response headers, or unknown. A cooldown that cannot be true is an
    issue, not a block: the route stays usable and the issue is published.
    """
    empty = {
        "state": "not_a_pool_route",
        "basis": "the route is not one of the free pool's integrations",
        "admission": [],
        "limits": [],
        "cooldown_until": None,
        "cooldown_basis": None,
        "last_used": None,
        "issues": [],
    }
    if not isinstance(evidence, Mapping):
        return empty
    admission = []
    for entry in evidence.get("admission") or ():
        if not isinstance(entry, Mapping):
            continue
        admission.append(
            {
                "workload": str(entry.get("workload") or ""),
                "admitted": entry.get("admitted") is True,
            }
        )
    limits = []
    for entry in evidence.get("limits") or ():
        if not isinstance(entry, Mapping):
            continue
        limits.append(
            {
                "limit": str(entry.get("limit") or ""),
                "value": entry.get("value"),
                "scope": str(entry.get("scope") or "account"),
                "basis": str(entry.get("basis") or "unknown"),
            }
        )
    issues = [str(issue) for issue in evidence.get("issues") or ()]
    cooldown = evidence.get("cooldown_until")
    cooldown_value = None
    if isinstance(cooldown, (int, float)) and not isinstance(cooldown, bool):
        cooldown_value = float(cooldown)
    last_used = evidence.get("last_used")
    last_used_value = None
    if isinstance(last_used, (int, float)) and not isinstance(last_used, bool):
        last_used_value = float(last_used)
    return {
        "state": "pool_route",
        "basis": (
            "the free pool's own limits, admissions and cooldown; the limits "
            "keep the basis they were read with"
        ),
        "admission": admission,
        "limits": limits,
        "cooldown_until": cooldown_value,
        "cooldown_basis": (
            "invalid" if "invalid_cooldown" in issues else (
                "pool" if cooldown_value is not None else None
            )
        ),
        # When the pool last sent a job to this route. The least recently
        # used route breaks the tie inside the quality band.
        "last_used": last_used_value,
        "issues": issues,
    }


def _display_tier(tiers: list[str]) -> str:
    """The tier that describes a recommendation best."""
    for tier in ("frontier", "bulk", "free", "3d"):
        if tier in tiers:
            return tier
    return (tiers or [""])[0]


def _published_value(row: Mapping[str, Any]) -> float:
    """The published value of a row, or zero when it has none.

    The recommendation is chosen by the value the owner's policy defines,
    never by a blended score: a name suffix, a catalog price, a capacity
    term and a pace term are not in the decision, so they are not in the
    choice either.
    """
    value = (row.get("value") or {}).get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


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
            and not (row.get("selection") or {}).get("excluded")
        ]
        if entry.get("complexity") == "high":
            # A dedicated free route needs admission evidence for the workload
            # before it may take a high complexity class, mapped or not. A
            # paid route is considered, and the role and private data gates
            # below still apply.
            eligible = [
                row
                for row in eligible
                if (row.get("access") or {}).get("kind") != ACCESS_DEDICATED_FREE
                or _admitted_for(row, name)
            ]
        if entry["private_data"]:
            eligible = [row for row in eligible if row["native"]["mapped"]]
        elif entry.get("complexity") != "high":
            # A low complexity class keeps a dedicated free route with no
            # admission evidence; a promotional zero-price paid route is not a
            # dedicated free one, so it does not take the free preference.
            eligible = [
                row
                for row in eligible
                if (row.get("native") or {}).get("mapped")
                or (row.get("access") or {}).get("kind") == ACCESS_DEDICATED_FREE
            ]
        preferred = [
            row
            for row in eligible
            if (row.get("access") or {}).get("kind") == ACCESS_DEDICATED_FREE
        ]
        # A mapped free route is preferred over a read only pool route: it can
        # also carry a delegate, and a pool route never can.
        choice_pool = sorted(
            preferred,
            key=lambda row: (
                1 if row["native"]["mapped"] else 0,
                _published_value(row),
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
                    "a dedicated free route is preferred for this class; it "
                    "runs as an inference job through the existing pool"
                    if not chosen["native"]["mapped"]
                    else "a dedicated free route is preferred for this class"
                ),
                "delegate": bool(chosen["native"]["mapped"]),
                "route": {
                    "kind": (
                        "inference_job"
                        if not chosen["native"]["mapped"]
                        else "provider_native"
                    ),
                    "execution": "the existing free inference pool",
                    "gap": (
                        "the route has no native T3 model; it runs as an "
                        "inference job, not as a provider-native thread"
                        if not chosen["native"]["mapped"]
                        else ""
                    ),
                },
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
            chosen = max(frontier_rows, key=_published_value)
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
            chosen = max(eligible, key=_published_value)
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


# The owner's transparent policy: the measured intelligence and the measured
# cost per task, and nothing else. The weights and the transform live in
# one place, value_policy, so a lead can set them without a change anywhere
# else.
VALUE_WEIGHTS = dict(value_policy.VALUE_WEIGHTS)
VALUE_3D_WEIGHTS = dict(value_policy.VALUE_3D_WEIGHTS)
VALUE_TRANSFORMS = {
    "intelligence": "I = the Artificial Analysis intelligence index / 100",
    "cost_per_task": "E = 1 / (1 + the Artificial Analysis cost per task in USD)",
}
# The transform of the cost input that is in force. It is swappable, and
# the one in force is published with the snapshot and the metrics.
COST_TRANSFORM = value_policy.DEFAULT_COST_TRANSFORM
VALUE_POLICY = {
    "formula": "0.70 * I + 0.30 * E",
    "weights": dict(VALUE_WEIGHTS),
    "transforms": dict(VALUE_TRANSFORMS),
    "units": {
        "intelligence": "the feed's index, 0 to 100, scaled to 0..1",
        "cost_per_task": "US dollars per measured task, scaled to 0..1",
    },
    "requires": "both measurements; a missing cost per task leaves the value unknown",
    "not_aa_claim": "the weights are an owner policy; the inputs are the feed's",
    "cost_transform": COST_TRANSFORM,
    "cost_transforms": dict(value_policy.COST_TRANSFORMS),
    "basis": (
        "both measurements are required and nothing is renormalized: a missing "
        "input leaves the value unknown"
    ),
}

# The calculation of a winner, published with the snapshot so every number
# can be checked and a suggestion can be made about it.
CALCULATION = {
    "winner_rule": (
        "one winner per provider and tier; the tiers do not rank the whole "
        "catalog"
    ),
    "strength": {
        "formula": "the verified Artificial Analysis intelligence index",
        "weights": {"intelligence": 1.0},
        "fallback": (
            "none; a model without a measured, fresh, current-version record "
            "has no strength and is unranked, awaiting the feed"
        ),
    },
    "value": {
        "formula": VALUE_POLICY["formula"],
        "weights": dict(VALUE_WEIGHTS),
        "transforms": dict(VALUE_TRANSFORMS),
        "units": dict(VALUE_POLICY["units"]),
        "requires": VALUE_POLICY["requires"],
        "not_aa_claim": VALUE_POLICY["not_aa_claim"],
        "cost_transform": COST_TRANSFORM,
        "cost_transforms": dict(value_policy.COST_TRANSFORMS),
        "components": {
            "intelligence": "the verified intelligence index over 100",
            "cost_per_task": "the efficiency of the measured cost per task",
        },
        "visible_not_ranked": {
            "coding": "the verified coding index, shown and not weighted",
            "agentic": "the verified agentic index, shown and not weighted",
            "engineering": "the verified engineering index, shown and not weighted",
            "speed": "the median output tokens per second, shown and not weighted",
            "released_at": "release metadata, shown and never a bonus",
        },
        "provider_order": (
            "the tiers are ordered by the pace of the provider's own window; "
            "the value orders the candidates within one provider only"
        ),
    },
    "value_3d": {
        "formula": "0.45 * I + 0.25 * T + 0.30 * E",
        "weights": dict(VALUE_3D_WEIGHTS),
        "components": {
            "intelligence": "the verified intelligence index over 100",
            "three_d": (
                "the AA-3D Elo under the source's own published normalization, "
                "min-max over the complete AA-3D snapshot"
            ),
            "cost_per_task": "the efficiency of the measured cost per task",
        },
        "cost_transform": COST_TRANSFORM,
        "requires": (
            "all three measurements; a missing capability or a missing cost "
            "leaves the value unknown"
        ),
        "note": (
            "the AA-3D capability is beside the intelligence, not a "
            "replacement for it: the owner asked for the two together for CAD "
            "selection"
        ),
    },
    "cost_transforms": dict(value_policy.COST_TRANSFORMS),
    "cost_transform_in_force": COST_TRANSFORM,
    "relative_cost": {
        "formula": "3 * input + output + 0.1 * cache_read, per million tokens",
        "floor": 0.01,
        "scope": "within one provider; the prices are the provider's own listing",
        "note": (
            "the cost per task of the feed is published next to it and is "
            "never mixed with a token price"
        ),
    },
    "provider_order": {
        "formula": (
            "the providers are ordered by their Paced Availability: the one "
            "with the most share left over the share it was expected to have "
            "left comes first"
        ),
        "source": "Paced Availability of the account window",
    },
    "paced_availability": {
        "name": "Paced Availability",
        "formula": (
            "the share left minus the expected share left in the most "
            "constraining window of the provider"
        ),
        "sign": (
            "positive means the provider is ahead of the pace the window "
            "draws, negative means it is behind it; a higher number ranks "
            "first"
        ),
        "equivalence": (
            "this is the pace delta of the most constraining window: the "
            "expected used share minus the measured used share is the same "
            "number as the share left minus the expected share left"
        ),
        "window": (
            "the most constraining window: the one whose own line the "
            "provider is furthest behind"
        ),
    },
    "gates": {
        "frontier": (
            "the owner's explicit workhorses only: GPT-6.1 Sol and Claude "
            "Opus 5.5; another model never takes the tier over"
        ),
        "frontier_surplus": (
            "a frontier model may carry volume work only when a weekly or "
            "monthly allowance resets within a day and the session window is "
            "not ahead of the line"
        ),
        "free": (
            "a free route is an access and cost classification, not a "
            "capability tier: a workload takes it only with the admission "
            "evidence that workload requires, and the private data and "
            "frontier review gates still apply"
        ),
        "review": (
            "the review class waits for the frontier authority; it never takes "
            "another model"
        ),
        "unavailable": (
            "a winner that is exhausted or unavailable is replaced by the next "
            "eligible model of the same provider at the next fresh snapshot"
        ),
    },
}

# The blended price of one model, the provider's own listing.
PRICE_WEIGHTS = {"input": 3.0, "output": 1.0, "cache_read": 0.1}
PRICE_FLOOR = 0.01



def _relative_cost(prices: Mapping[str, Any] | None) -> float | None:
    """The blended token price of a model, per million tokens."""
    if not isinstance(prices, Mapping):
        return None
    total = 0.0
    seen = False
    for kind, weight in PRICE_WEIGHTS.items():
        value = prices.get(kind)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total += float(value) * weight
            seen = True
    return total if seen else None


def _median(values: list[float]) -> float | None:
    """The median of a list of numbers, or None when it is empty."""
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _calibrate_values(candidates: list[dict[str, Any]]) -> None:
    """The combined value: the measured intelligence and the measured cost.

    The policy is 0.70 * I + 0.30 * E with I the intelligence index over 100
    and E the efficiency of the measured cost per task. Both measurements
    are required: a model with no cost per task has an unknown efficiency
    and no combined value, while its raw measured intelligence stays
    visible. Nothing is filled from a cohort median and nothing is
    renormalized.

    The cost transform is the one in force in the policy, and the evidence
    it was built from is published with the value.
    """
    # The cohort the relative transforms need: the known costs of the
    # models this snapshot compares.
    cohort = value_policy.cost_cohort(
        (row.get("_components") or {}).get("cost_per_task_raw")
        for row in candidates
    )
    for row in candidates:
        components = row.get("_components") or {}
        value_block = row.get("value") or {}
        # The efficiency of the measured cost, under the transform that is in
        # force. The transform and its evidence are published with the
        # value.
        raw = (components.get("cost_per_task_raw") or {}).get("value")
        efficiency, evidence = value_policy.cost_transform(
            raw, cohort, COST_TRANSFORM
        )
        published = {}
        for name in VALUE_WEIGHTS:
            component = components.get(name) or {}
            value = component.get("value")
            if name == "cost_per_task":
                # The efficiency is the transform of the measured cost, not
                # the raw cost and not a default.
                value = efficiency
            published[name] = {
                "value": (
                    round(float(value), 4)
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                    else None
                ),
                "source": str(component.get("source") or "unknown"),
            }
        value_block["components"] = published
        value_block["weights"] = dict(VALUE_WEIGHTS)
        value_block["transforms"] = dict(VALUE_TRANSFORMS)
        value_block["cohort"] = {"basis": "", "values": {}}
        value_block["cost_transform"] = COST_TRANSFORM
        value_block["cost_transform_evidence"] = evidence
        intelligence = published["intelligence"]["value"]
        efficiency = published["cost_per_task"]["value"]
        if not isinstance(intelligence, (int, float)) or not isinstance(
            efficiency, (int, float)
        ):
            known = int(isinstance(intelligence, (int, float))) + int(
                isinstance(efficiency, (int, float))
            )
            value_block["coverage"] = known / len(VALUE_WEIGHTS)
            value_block["uncertainty"] = 1.0 - known / len(VALUE_WEIGHTS)
            value_block["value"] = None
            value_block["missing"] = [
                name for name in VALUE_WEIGHTS if published[name]["value"] is None
            ]
            value_block["strength"] = (
                round(float(intelligence) * 100.0, 4)
                if isinstance(intelligence, (int, float))
                else None
            )
            value_block["strength_source"] = published["intelligence"]["source"]
            row["value"] = value_block
            row.pop("_components", None)
            continue
        combined = VALUE_WEIGHTS["intelligence"] * float(
            intelligence
        ) + VALUE_WEIGHTS["cost_per_task"] * float(efficiency)
        value_block["coverage"] = 1.0
        value_block["uncertainty"] = 0.0
        value_block["missing"] = []
        value_block["value"] = round(combined, 6)
        value_block["strength"] = round(float(intelligence) * 100.0, 4)
        value_block["strength_source"] = published["intelligence"]["source"]
        row["value"] = value_block
        row.pop("_components", None)


def _applied_windows(windows: Iterable[Any]) -> list[dict[str, Any]]:
    """The windows that apply to a model, with their scope.

    A shared window applies to every model of the account; a model scoped
    window names the family it belongs to. The most constraining of them
    decides the availability, so a subordinate sublimit is never read as an
    independent allowance.
    """
    records: list[dict[str, Any]] = []
    for window in windows or ():
        scope = getattr(window, "applies_to", ()) or ()
        used = getattr(window, "used_ratio", None)
        reset = getattr(window, "reset_epoch", None)
        quota_id = str(getattr(window, "quota_id", "") or "default")
        basis = str(getattr(window, "basis", "") or "")
        ends = getattr(window, "ends_at", None)
        records.append(
            {
                "quota": quota_id,
                "kind": str(getattr(window, "kind", "") or "other"),
                "scope": "model" if scope else "shared",
                "applies_to": [str(token) for token in scope],
                # The label of a window whose state the provider publishes
                # rather than reports, so a reader sees what it is.
                "label": WINDOW_LABELS.get(quota_id, ""),
                # The basis of the numbers of the window, and the end of its
                # entitlement when the provider publishes one.
                "basis": basis,
                "ends_at": (
                    _iso(float(ends))
                    if isinstance(ends, (int, float)) and not isinstance(ends, bool)
                    else None
                ),
                "remaining_ratio": (
                    round(max(0.0, 1.0 - float(used)), 4)
                    if isinstance(used, (int, float)) and not isinstance(used, bool)
                    else None
                ),
                "reset_at": _iso(float(reset)) if isinstance(reset, (int, float)) else None,
            }
        )
    return records


def _binding_record(window: Any) -> dict[str, Any] | None:
    """The identity of the window a binding came from."""
    if window is None:
        return None
    kind = getattr(window, "kind", None)
    quota = getattr(window, "quota_id", None)
    duration = getattr(window, "duration_seconds", None)
    reset = getattr(window, "reset_epoch", None)
    return {
        "kind": None if kind is None else str(kind),
        "quota": None if quota is None else str(quota),
        "duration_seconds": int(duration) if isinstance(duration, (int, float)) else None,
        "reset_at": _iso(reset) if isinstance(reset, (int, float)) else None,
    }


def _binding_basis(window: Any) -> str:
    """The basis of the numbers of the window a binding came from."""
    if window is None:
        return ""
    basis = getattr(window, "basis", None)
    if basis is None and isinstance(window, Mapping):
        basis = window.get("basis")
    return str(basis or "")


def _binding_ends_at(window: Any) -> str | None:
    """The end of the entitlement of the window a binding came from."""
    if window is None:
        return None
    ends = getattr(window, "ends_at", None)
    if ends is None and isinstance(window, Mapping):
        ends = window.get("ends_at")
    if not isinstance(ends, (int, float)) or isinstance(ends, bool):
        return None
    return _iso(float(ends))


def _binding_id(window: Any) -> str | None:
    """The exact id of the window a binding came from, or None."""
    if window is None:
        return None
    kind = getattr(window, "kind", None)
    quota = getattr(window, "quota_id", None)
    if kind is None and quota is None:
        return None
    return f"{kind or 'window'}:{quota or 'primary'}"


def _bindings_differ(row: Mapping[str, Any]) -> bool:
    """True when the hard capacity and the pace bind different windows."""
    capacity = row.get("capacity") or {}
    return bool(capacity.get("capacity_binding_id")) and bool(
        capacity.get("pace_binding_id")
    ) and capacity.get("capacity_binding_id") != capacity.get("pace_binding_id")


def _visual_capable(entry: Any) -> bool:
    """True when the catalog proves the model accepts image input."""
    if not isinstance(entry, Mapping):
        return False
    modalities = entry.get("modalities")
    if not isinstance(modalities, Mapping):
        return False
    inputs = modalities.get("input")
    if not isinstance(inputs, list):
        return False
    return any(str(value).lower() == "image" for value in inputs)


def _three_d_state(row: Mapping[str, Any], entry: Any) -> dict[str, Any]:
    """The AA-3D evidence of a row: the measured Elo, or pending.

    The tier ranks Artificial Analysis' AA-3D Elo and nothing else. The
    general intelligence index, a family prior and token volume are never a
    3D score. The catalog must still prove image input, because the
    benchmark's interactive-scene work needs it.
    """
    visual = _visual_capable(entry)
    text_only = bool((row.get("aa") or {}).get("text_only"))
    measured = row.get("_aa_3d") or {}
    if measured.get("state") == "measured" and visual and not text_only:
        state = "measured"
        reason = "a measured AA-3D Elo and a proven image input"
    elif text_only:
        state = "ineligible"
        reason = "the official record is text only"
    elif not visual:
        state = "ineligible"
        reason = "the catalog does not prove image input"
    else:
        state = "pending"
        reason = str(measured.get("reason") or "no measured AA-3D Elo")
    return {
        "state": state,
        "reason": reason,
        "visual": visual,
        "elo": measured.get("elo") if state == "measured" else None,
        "elo_interval": measured.get("elo_interval") if state == "measured" else {},
        "cost_per_task": measured.get("cost_per_task") if state == "measured" else None,
        "normalized": measured.get("normalized") if state == "measured" else None,
        "normalization": measured.get("normalization") if state == "measured" else None,
        "normalization_state": measured.get("normalization_state")
        if state == "measured"
        else "unknown",
        "authority": "artificialanalysis-aa-3d",
        "source": measured.get("source") if state == "measured" else None,
        "benchmark": measured.get("benchmark") if state == "measured" else None,
        "conditions": measured.get("conditions") if state == "measured" else {},
        "observed_at": measured.get("observed_at") if state == "measured" else None,
        "task_count": measured.get("task_count") if state == "measured" else None,
        "note": (
            "an AA-3D Elo measures interactive 3D scene work, not CAD or "
            "printable geometry, and not general intelligence"
        ),
    }


def _row_variant(row: Mapping[str, Any]) -> str:
    """The reasoning variant a model is run with, when it is known.

    The variant is the value of the option that changes the reasoning of a
    model. A model without such an option has the empty variant.
    """
    options = (row.get("native") or {}).get("options") or []
    parts: list[str] = []
    for option in options:
        if not isinstance(option, Mapping):
            continue
        name = str(option.get("id") or "").lower()
        value = option.get("current_value")
        if name in ("variant", "reasoningeffort", "effort", "thinking") and isinstance(
            value, (str, int, float, bool)
        ):
            parts.append(f"{name}={value}")
    return ",".join(parts)


def _pending_identities(
    candidates: list[dict[str, Any]], facts: Mapping[str, Any], now: float
) -> list[dict[str, Any]]:
    """The models that have no usable fact yet, bounded to the tiered ones.

    The list is the compact signal a trigger may act on: the exact identity,
    the reason, and the moment a pending research is checked again. It never
    carries a score, and the producer does not research anything itself.
    """
    pending: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in candidates:
        if not row.get("tiers") and (row.get("aa") or {}).get("state") == "measured":
            # A verified model that no tier admitted is not a research target.
            continue
        provider = str(row.get("provider") or "")
        model = str(row.get("model") or "")
        variant = _row_variant(row)
        fact = facts_module.lookup_by_model(
            facts, provider, model, variant, now=now
        )
        if fact is not None:
            continue
        identity = facts_module.identity_key(provider, model, variant)
        if identity in seen:
            continue
        seen.add(identity)
        existing = None
        for candidate_key, candidate_fact in (facts or {}).items():
            if not isinstance(candidate_fact, Mapping):
                continue
            if facts_module.identity_key(
                str(candidate_fact.get("provider") or ""),
                str(candidate_fact.get("model") or ""),
                str(candidate_fact.get("variant") or ""),
            ) != identity:
                continue
            if str(candidate_fact.get("status") or "") == "pending":
                existing = candidate_fact
                break
            if str(candidate_key) == identity:
                existing = candidate_fact
                break
        pending.append(
            {
                "identity": identity,
                "provider": provider,
                "model": model,
                "variant": variant,
                "status": "pending",
                # A pending research keeps the reason and the moment it said it
                # would be checked: the backoff is preserved, not reset to a
                # generic value on the next snapshot.
                "pending_reason": (
                    str(existing.get("pending_reason") or "")
                    if existing is not None
                    else "no usable fact for this identity"
                )
                or "no usable fact for this identity",
                "next_check_at": (
                    existing.get("next_check_at") if existing is not None else None
                ),
            }
        )
    return pending


def _component_value(components: dict[str, float | None]) -> tuple[float | None, dict[str, float]]:
    """The combined value of the measured inputs, and the weights used.

    Both inputs are required. A missing input means no combined value rather
    than a renormalized score over the inputs that happen to exist.
    """
    for name in VALUE_WEIGHTS:
        value = components.get(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None, {}
    value = sum(VALUE_WEIGHTS[name] * float(components[name]) for name in VALUE_WEIGHTS)
    return value, dict(VALUE_WEIGHTS)


def _fill_value(
    row: dict[str, Any],
    catalog: Any,
    fact: Mapping[str, Any] | None = None,
    now: float | None = None,
    free_set: set[tuple[str, str]] | None = None,
    promo_set: set[tuple[str, str]] | None = None,
    aa_3d_cache: Mapping[str, Any] | None = None,
    inventory: Iterable[Any] | None = None,
) -> None:
    """The strength, the relative price, and the value of one model."""
    provider = row.get("provider") or ""
    model = row.get("model") or ""
    prices = None
    if catalog is not None:
        try:
            prices = catalog.price_for(provider, model)
        except Exception:  # pragma: no cover - a catalog without the model
            prices = None
    relative = _relative_cost(prices)
    if isinstance(prices, Mapping):
        row["price"] = {
            "input": prices.get("input"),
            "output": prices.get("output"),
            "cache_read": prices.get("cache_read"),
            "source": "provider listing",
            "relative_index": None,
        }
    if isinstance(fact, Mapping) and isinstance(fact.get("admission_evidence"), list):
        allowed_workloads = tuple(getattr(facts_module, "PUBLIC_WORKLOADS", ()))
        row["admission_evidence"] = [
            entry
            for entry in fact["admission_evidence"]
            if isinstance(entry, Mapping)
            and str(entry.get("workload") or "") in allowed_workloads
        ]
    intelligence = dict(row.get("intelligence") or {})
    indices = dict(intelligence.get("indices") or {})
    # The verified record of the exact model: the current feed when it lists
    # the model, otherwise the durable fact that was built from the feed.
    if not indices.get("intelligence_index") and isinstance(fact, Mapping):
        fact_indices = fact.get("indices") or {}
        if isinstance(fact_indices.get("intelligence_index"), (int, float)):
            indices = dict(fact_indices)
            intelligence = {
                "state": "measured",
                "indices": indices,
                "index_version": fact.get("benchmark_version"),
                "fetched_at": fact.get("fetched_at"),
            }
    measured = intelligence.get("state") == "measured"
    # The quality is the verified Artificial Analysis record, and nothing
    # else. There is no prior, no blend and no fallback: a model without a
    # record has no quality, and it is not ranked.
    strength: float | None = None
    source = "unknown"
    if measured:
        index = indices.get("intelligence_index")
        if isinstance(index, (int, float)) and not isinstance(index, bool):
            strength = float(index)
            source = "measured"
    if strength is None:
        # No verified record: the model is unranked and waits for the feed.
        # The ranking's tier is dropped here, at the public decision layer.
        row["tiers"] = []
        row["rank"] = {}
        row["score"] = {}
        row["role"] = "unranked"
    measured_variant = str(intelligence.get("measured_variant") or "")
    variant_mismatch = bool(intelligence.get("variant_mismatch"))
    condition_exact = (
        str(intelligence.get("variant_match") or "") in ("exact", "default")
        and not intelligence.get("condition_unknown")
    )
    runtime = _runtime_reasoning(row)
    alignment = dict(runtime.get("alignment") or {})
    alignment_meta = {
        "option": runtime.get("option"),
        "value": runtime.get("default") if alignment else None,
        "recommended": bool(alignment),
        "applied": (
            runtime.get("current") == runtime.get("default")
            if runtime.get("current") is not None
            else False
        ),
        "actual": runtime.get("current"),
        "escalation": runtime.get("escalation_alignment") or {},
        "basis": runtime.get("policy"),
    }
    selectable = strength is not None and runtime["state"] in (
        "selectable",
        "not_applicable",
    )
    row["aa"] = {
        "state": (
            "measured"
            if strength is not None
            else str(intelligence.get("state") or "missing")
        ),
        "reason": str(intelligence.get("reason") or ""),
        "indices": {
            "intelligence": indices.get("intelligence_index"),
            "coding": indices.get("coding_index"),
            "agentic": indices.get("agentic_index"),
            "engineering": indices.get("engineering_index"),
        },
        "id": intelligence.get("id"),
        "slug": intelligence.get("slug"),
        "name": intelligence.get("name"),
        "release_date": intelligence.get("release_date"),
        # The feed's own raw inputs, distinct from the provider's listing.
        "cost_per_task": intelligence.get("cost_per_task"),
        "median_performance": intelligence.get("median_performance"),
        "token_prices": intelligence.get("token_prices") or {},
        "index_version": intelligence.get("index_version"),
        "fetched_at": intelligence.get("fetched_at"),
        "condition": {
            "measured_variant": measured_variant,
            "execution_default": runtime.get("default") or REASONING_DEFAULT,
            "execution_escalation": REASONING_ESCALATION,
            "execution_exception": bool(runtime.get("exception")),
            "execution_basis": str(runtime.get("basis") or ""),
            "native_variant": intelligence.get("native_variant") or "",
            "variant_match": intelligence.get("variant_match") or "",
            # True only when the native setting is the measured one, or when
            # the feed marks the record as the provider's default fallback.
            # An id without an effort option is not proof of either.
            "confirmed": bool(intelligence.get("condition_confirmed")),
            "unknown": bool(intelligence.get("condition_unknown")),
            "note": (
                "the benchmark condition is the feed's own label; a model "
                "that publishes no effort keeps that condition visible and "
                "is not assumed to run at it"
            ),
            "variants": intelligence.get("variants") or [],
            "checkpoint": intelligence.get("checkpoint") or "",
            "identity_match": intelligence.get("identity_match") or "",
        },
        "variants": intelligence.get("variants") or [],
        "reference": intelligence.get("reference"),
        "alternatives": intelligence.get("alternatives") or [],
        "value_missing": intelligence.get("value_missing") or [],
        "matched_by": intelligence.get("matched_by") or "",
        "variant_mismatch": variant_mismatch,
        "selectable": selectable,
        "alignment": alignment,
        "alignment_meta": alignment_meta,
        "runtime_policy": runtime,
        "execution": {
            "default": runtime.get("default") or REASONING_DEFAULT,
            "escalation": REASONING_ESCALATION,
            "exception": bool(runtime.get("exception")),
            "basis": str(runtime.get("basis") or ""),
            "state": runtime["state"],
            "reason": runtime.get("reason") or "",
            "is_benchmark_condition": False,
        },
        "text_only": bool(intelligence.get("text_only")),
        "reason": intelligence.get("reason") or "",
        "basis": "the verified Artificial Analysis record of the exact model",
    }
    # The public quality is the verified index, never a prior. A model with
    # no record carries no quality number at all.
    row["quality"] = (
        {
            "value": round(strength, 2),
            "source": "measured",
            "measured": True,
            "basis": "the verified Artificial Analysis intelligence index",
        }
        if strength is not None
        else {
            "value": None,
            "source": "unknown",
            "measured": False,
            "basis": "no verified record; the model awaits the feed",
        }
    )
    entry = None
    if catalog is not None:
        getter = getattr(catalog, "model_entry", None)
        if callable(getter):
            try:
                entry = getter(provider, model)
            except Exception:  # pragma: no cover - a catalog without the model
                entry = None
    provider_name = str(row.get("provider") or "")
    model_name = str(row.get("model") or "")
    row["_aa_3d"] = aa_3d.lookup(aa_3d_cache, provider_name, model_name)
    three_d = _three_d_state(row, entry)
    row["three_d"].update(three_d)
    row["aa_3d"] = row.pop("_aa_3d", {"state": "missing"})
    row["value_3d"] = _three_d_value(row)
    if three_d["state"] != "measured":
        # Without a measured AA-3D Elo the model is not a 3D candidate; the
        # pending state stays visible on the row.
        row["tiers"] = [tier for tier in row["tiers"] if tier != "3d"]
    elif "3d" not in row["tiers"]:
        # The measured Elo is the evidence; the ranking's 3D list is an
        # input, not the authority.
        row["tiers"].append("3d")
    indices = intelligence.get("indices") or {}

    def index(name: str) -> float | None:
        value = indices.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(0.0, min(1.0, float(value) / 100.0))
        return None

    cost_per_task = intelligence.get("cost_per_task")
    speed = intelligence.get("median_performance")
    released = None
    if isinstance(fact, Mapping):
        released = fact.get("released_at")
    if not isinstance(released, str):
        released = row.get("released_at")
    components: dict[str, float | None] = {
        "intelligence": (
            max(0.0, min(1.0, strength / 100.0)) if strength is not None else None
        ),
        "coding": index("coding_index"),
        "agentic": index("agentic_index"),
        "engineering": index("engineering_index"),
        # The raw cost per task, kept beside the efficiency: the transform
        # that turns the cost into the efficiency may need the cohort, and
        # the cohort is only known once every row is filled.
        "cost_per_task_raw": (
            float(cost_per_task)
            if isinstance(cost_per_task, (int, float))
            and not isinstance(cost_per_task, bool)
            and math.isfinite(float(cost_per_task))
            and float(cost_per_task) >= 0.0
            else None
        ),
        "cost_per_task": (
            1.0 / (1.0 + float(cost_per_task))
            if isinstance(cost_per_task, (int, float))
            and not isinstance(cost_per_task, bool)
            and math.isfinite(float(cost_per_task))
            and float(cost_per_task) >= 0.0
            else None
        ),
        "speed": (
            max(0.0, float(speed)) / (100.0 + max(0.0, float(speed)))
            if isinstance(speed, (int, float)) and not isinstance(speed, bool)
            else None
        ),
        "token_price": (
            1.0 / (1.0 + max(relative, PRICE_FLOOR)) if relative is not None else None
        ),
    }
    if not isinstance(released, str) or not released:
        if catalog is not None:
            getter = getattr(catalog, "release_date", None)
            if callable(getter):
                released = getter(provider, model)
            else:
                entry = catalog.model_entry(provider, model) if hasattr(catalog, "model_entry") else None
                if isinstance(entry, Mapping):
                    candidate = entry.get("release_date")
                    if isinstance(candidate, str):
                        released = candidate
    if isinstance(released, str) and released and now is not None:
        from datetime import datetime, timezone

        try:
            moment = datetime.fromisoformat(released[:10] + "T00:00:00+00:00")
            age_days = max(0.0, (now - moment.timestamp()) / 86400.0)
            components["recency"] = max(0.0, min(1.0, 1.0 - age_days / 365.0))
        except ValueError:
            components["recency"] = None
    component_sources = {
        name: ("measured" if value is not None else "unknown")
        for name, value in components.items()
    }
    row["_components"] = {
        name: {"value": components[name], "source": component_sources[name]}
        for name in components
    }
    row["access"] = _access_record(
        provider,
        model,
        free_set or set(),
        promo_set or set(),
        prices,
        native_mapped=bool((row.get("native") or {}).get("mapped")),
    )
    row["value"] = {
        "strength": None if strength is None else round(strength, 2),
        "strength_source": source,
        "strength_basis": {"measured": 1.0} if strength is not None else {},
        "confidence": (
            float(fact.get("confidence"))
            if isinstance(fact, Mapping) and isinstance(fact.get("confidence"), (int, float))
            else None
        ),
        # An attestation code, never the free text of a fact: the source of
        # the strength is a fact about the evidence, not a message.
        "basis": (
            "artificialanalysis_free"
            if source == "measured"
            else ("estimate" if source == "estimated" else "quality_prior")
        ),
        "relative_cost": None if relative is None else round(relative, 4),
        "formula": CALCULATION["value"]["formula"],
    }


# The capacity below which a reserved model is withheld from the work of
# the other tiers. The owner decided that a model that qualifies for the 3D
# tier is kept for CAD work while its provider has room.
RESERVE_CAPACITY_FLOOR = 0.50

# The tiers a reserve withholds a model from. The 3D tier is the tier the
# model is reserved for.
RESERVED_TIERS = ("bulk", "free")

# The width of the quality band of the free tier, in Artificial Analysis
# intelligence points. The eligible routes within this many points of the
# best eligible route form the band, and the band is used first.
FREE_BAND_POINTS = 5.0


def _apply_reserve(
    candidates: list[dict[str, Any]], provider_capacity: Mapping[str, Any]
) -> None:
    """Mark the models that are reserved for the 3D tier.

    A model that qualifies for the 3D tier - an explicit visual input and a
    measured AA-3D score - is reserved for CAD work. It ranks after every
    other winner of the other tiers, and it is not used for their work at
    all while its provider's remaining capacity is below the floor.

    The reserve changes the order and the eligibility. It never changes the
    value of a model.
    """
    for row in candidates:
        three_d = row.get("three_d") or {}
        reserved = str(three_d.get("state") or "") == "measured"
        account = str(row.get("account") or "")
        capacity = (provider_capacity.get(account) or {}).get("remaining_ratio")
        if not reserved:
            row["reserve"] = {
                "3d": False,
                "reason": "the model does not qualify for the 3D tier",
                "capacity": capacity,
            }
            continue
        withheld = (
            isinstance(capacity, (int, float))
            and not isinstance(capacity, bool)
            and float(capacity) < RESERVE_CAPACITY_FLOOR
        )
        if withheld:
            reason = (
                "the model is reserved for the 3D tier and its provider has "
                "less than half of its capacity left"
            )
        else:
            reason = (
                "the model is reserved for the 3D tier, so it ranks after "
                "every other winner of the other tiers"
            )
        row["reserve"] = {
            "3d": True,
            "reason": reason,
            "capacity": capacity,
            "withheld": bool(withheld),
            "tiers": list(RESERVED_TIERS),
            "floor": RESERVE_CAPACITY_FLOOR,
            "basis": (
                "the owner reserves the models that qualify for the 3D tier "
                "for CAD work; the reserve changes the order and the "
                "eligibility, never the value"
            ),
        }


def _winners(
    candidates: list[dict[str, Any]],
    tiers: dict[str, list[str]],
    aa_cache: Mapping[str, Any] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """One winner per provider and tier, ordered by the provider pacing.

    A model that holds no tier, that is not available, or that waits for its
    evaluation is never a winner. The next eligible model of the same
    provider takes its place at the next fresh snapshot.
    """
    by_key = {_key(row["provider"], row["model"]): row for row in candidates}
    winners: dict[str, list[dict[str, Any]]] = {}
    coverage: dict[str, Any] = {}
    # The Artificial Analysis evidence is the gate of every tier. When it is
    # missing, a tier has no winner for a reason that is not its own, and
    # the tier says so instead of looking empty.
    aa_evidence = "ok"
    aa_reason = ""
    if not isinstance(aa_cache, Mapping) or aa_cache.get("status") != "ok":
        aa_evidence = "pending_aa_evidence"
        aa_reason = (
            "no current Artificial Analysis evidence: the feed cache is "
            + str((aa_cache or {}).get("status") or "missing")
        )
    for tier in TIER_NAMES:
        members = tiers.get(tier) or []
        considered = 0
        providers: set[str] = set()
        chosen: dict[str, dict[str, Any]] = {}
        for key in members:
            row = by_key.get(key)
            if row is None:
                continue
            considered += 1
            providers.add(row["provider"])
            if not _holds_the_tier(row, tier):
                # A model that is not available, that waits for its
                # evaluation, or that is not permitted for the tier is never
                # its winner. The next permitted model of the same provider
                # takes its place.
                continue
            current = chosen.get(row["provider"])
            if current is None or _winner_key(row, tier) > _winner_key(current, tier):
                chosen[row["provider"]] = row
        # The quality band of the free tier: the routes within five
        # Artificial Analysis intelligence points of the best eligible free
        # route. The band comes first, ordered by the most remaining
        # headroom, with the least recently used route breaking ties. The
        # rest of the tier follows by intelligence, and a route without an
        # intelligence record comes last.
        best_strength = None
        if tier == "free":
            for key in members:
                row = by_key.get(key)
                if row is None:
                    continue
                if not _holds_the_tier(row, tier):
                    continue
                strength = _strength_of(row)
                if strength is None:
                    continue
                if best_strength is None or strength > best_strength:
                    best_strength = strength

        def _free_band(row: dict[str, Any]) -> bool:
            """True when a route is within the band of the best free route."""
            if tier != "free" or best_strength is None:
                return False
            strength = _strength_of(row)
            if strength is None:
                # A route without an intelligence record is the lower band.
                return False
            return (best_strength - strength) <= FREE_BAND_POINTS

        def _free_key(row: dict[str, Any]) -> tuple:
            """The order of the free tier.

            The band comes first, by the most remaining headroom, with the
            least recently used route breaking the ties. The routes outside
            the band follow by intelligence, and a route without an
            intelligence record comes last.
            """
            strength = _strength_of(row)
            if strength is None:
                # The lower band: a route with no Artificial Analysis match
                # is used only when no ranked route has headroom.
                return (2, 0.0, 0.0, 0.0, row["provider"], row["model"])
            if _free_band(row):
                headroom = _headroom_of(row)
                last_used = _last_used_of(row)
                return (
                    0,
                    # The most remaining headroom first. An unknown headroom
                    # is no headroom, and it never displaces a route that has
                    # one.
                    -(headroom if headroom is not None else 0.0),
                    # The least recently used route breaks the tie. A route
                    # the pool has no reading for is unknown, and it waits.
                    last_used if last_used is not None else float("inf"),
                    -strength,
                    row["provider"],
                    row["model"],
                )
            return (1, 0.0, 0.0, -strength, row["provider"], row["model"])

        # The best quality of every trust level of the tier, over every
        # route that holds it, free or paid. A free route leads while it is
        # within the margin of the best available model of its own trust
        # level: it costs nothing, so being close is enough, and among the
        # free routes that lead the published value decides.
        best_quality: dict[str, float] = {}
        if tier == "bulk":
            for key in members:
                row = by_key.get(key)
                if row is None or not _holds_the_tier(row, tier):
                    continue
                quality = _outcome_quality(row, tier)
                if quality is None:
                    continue
                level = _trust_level(row, tier)
                if level not in best_quality or quality > best_quality[level]:
                    best_quality[level] = quality

        def _free_leads(row: dict[str, Any]) -> int:
            """Zero when a free route leads its trust level, one otherwise."""
            if tier != "bulk" or not _is_free_route(row):
                return 1
            quality = _outcome_quality(row, tier)
            if quality is None:
                return 1
            best = best_quality.get(_trust_level(row, tier))
            if best is None:
                return 1
            return 0 if value_policy.free_route_leads(quality, best) else 1

        def _pace_key(row: dict[str, Any]) -> tuple:
            """The order of the pace: a known pace first, then the pace.

            A route with no window has no pace. It is not a pace of zero:
            an unknown pace waits behind every route that has one.
            """
            pace = _pace_of(row)
            if pace is None:
                return (1, 0.0)
            return (0, -pace)

        def _reserve_key(row: dict[str, Any]) -> int:
            """One for a model that is reserved for the 3D tier."""
            return 1 if (row.get("reserve") or {}).get("3d") else 0

        def _far_behind(row: dict[str, Any]) -> int:
            """One for a route more than twenty points behind its line.

            The owner's rule: a route whose binding window is far behind the
            pace goes to the back of the pool. It follows every route of its
            trust group that is not far behind, whatever the value of those
            routes; an untrusted route stays last, and a route that is
            merely behind keeps its place in the value order.
            """
            state = (row.get("capacity") or {}).get("pace_state")
            return 1 if state == "far_behind" else 0

        def _tier_key(row: dict[str, Any]) -> tuple:
            """The order of one tier.

            The trust of the route comes first: a trusted route leads, a
            backup route follows, and an untrusted route comes last with
            its reason. A route that is far behind the pace of its binding
            window follows every route of its trust group that is not, so
            the pool puts it at the back of the group. A model reserved for
            the 3D tier follows the other members of the tiers it is
            reserved away from. The bulk tier then reads the published
            value, and a free route that is close enough to the best route
            of its trust level leads it.
            """
            trust = value_policy.trust_rank(_trust_level(row, tier))
            # A route of a provider reserved for another workload is not a
            # worker of this tier: it joins the backup group and follows
            # every unreserved route of it. An untrusted route stays last.
            reserved = 1 if _reserved_for(row, tier) else 0
            if reserved and trust < value_policy.trust_rank("backup"):
                trust = value_policy.trust_rank("backup")
            if tier == "free":
                # The free tier keeps the order it had: the band, the
                # headroom and the last use.
                return (trust, _far_behind(row), reserved, _free_key(row))
            if tier == "bulk":
                published = _published_value_for(row, tier)
                return (
                    trust,
                    _far_behind(row),
                    reserved,
                    _reserve_key(row),
                    _free_leads(row),
                    -(published if published is not None else 0.0),
                    _pace_key(row),
                    row["provider"],
                    row["model"],
                )
            return (
                trust,
                _far_behind(row),
                reserved,
                _reserve_key(row),
                _pace_key(row),
                row["provider"],
                row["model"],
            )

        ordered = sorted(chosen.values(), key=_tier_key)
        winners[tier] = []
        for row in ordered:
            trust = _trust_record(row, tier)
            outcome = _outcome_record(row, tier)
            published = _published_value_for(row, tier)
            winner = {
                "provider": row["provider"],
                "model": row["model"],
                "key": _key(row["provider"], row["model"]),
                "tier": tier,
                # The published value: the outcome-weighted value under the
                # trust of the model. The Artificial Analysis value it was
                # built from is published beside it.
                "value": published,
                "value_aa": (row.get("value") or {}).get("value"),
                "strength": (row.get("value") or {}).get("strength"),
                "strength_source": (row.get("value") or {}).get("strength_source"),
                # The display score of the model, the same one every page
                # reads: one number per model, with the basis it was built
                # from and the global counts behind it.
                "quality_score": row.get("quality_score"),
                "quality_p0": row.get("quality_p0"),
                "quality_n": row.get("quality_n"),
                "quality_s": row.get("quality_s"),
                "quality_basis": row.get("quality_basis"),
                "relative_cost": (row.get("value") or {}).get("relative_cost"),
                "pace_delta": (row.get("capacity") or {}).get("pace_delta"),
                # The owner's name for the ordering measure: the Paced
                # Availability of the provider, in its most constraining
                # window. A higher number ranks first.
                "paced_availability": (row.get("capacity") or {}).get(
                    "paced_availability"
                ),
                "paced_availability_window": (row.get("capacity") or {}).get(
                    "paced_availability_window"
                ),
                # The band of that number: ahead, on_pace, behind,
                # far_behind, spent or unknown. The order of the tier reads
                # it, and so does the Providers page.
                "pace_state": (row.get("capacity") or {}).get("pace_state"),
                "quota_state": row.get("quota_state"),
                "native": row.get("native"),
                "role": row.get("role"),
                # The trust of the route, and the reason it holds, so a
                # reader sees why an untrusted route is where it is.
                "trust_level": str(trust.get("level") or "trusted"),
                "trust_reason": str(trust.get("reason") or ""),
                "trust_source": str(trust.get("source") or "default"),
                "trust_task_type": str(trust.get("task_type") or ""),
                # The workload the provider is reserved for, when this tier
                # is outside it: the route is shown, and it is not a worker.
                "reserved_for": _reserved_for(row, tier),
                # The outcome the published value was built from.
                "outcome": {
                    "p0": outcome.get("p0"),
                    "n": outcome.get("n"),
                    "s": outcome.get("s"),
                    "p": outcome.get("p"),
                },
                # The access of the winner, with the billing class. A
                # consumer that picks a route reads the same access record
                # the candidate row carries.
                "access": dict(row.get("access") or {}),
                "reason": (
                    "the best eligible model of this provider for this tier, "
                    "ordered by the trust of the route and then by the pace "
                    "of the account window"
                ),
            }
            if tier == "free":
                # The band of the free tier is published with its winner, so
                # a reader sees which routes are the band and which are the
                # rest. The other tiers are not banded.
                winner["band"] = "true" if _free_band(row) else "false"
            winners[tier].append(winner)
        coverage[tier] = {
            "candidates_considered": considered,
            "members": len(members),
            "providers": len(providers),
            "winners": len(ordered),
            "providers_without_a_winner": len(providers) - len(ordered),
            # The state of the tier itself: it is either held, it waits for
            # the Artificial Analysis evidence, or no model of it is
            # eligible. A tier with no winner never looks like a tier that
            # was never measured.
            "state": (
                "ok"
                if ordered
                else (aa_evidence if aa_evidence != "ok" else "no_eligible_model")
            ),
            "reason": (
                ""
                if ordered
                else (
                    aa_reason
                    if aa_evidence != "ok"
                    else "no model of this tier is eligible right now"
                )
            ),
        }
    return winners, coverage


# The owner's explicit selection exclusions. Astra and Fable remain in the
# usage and quota readings, and they are never a winner or a recommendation in
# any tier: the frontier workhorses are GPT-6.1 Sol and Claude Opus 5.5.
#
# These are the fallback, not the source: the runtime policy carries the
# owner's lists, and the policy is what is read. The fallback keeps the
# collector honest when the policy is absent.
SELECTION_EXCLUDED_MODELS = ("gpt-6-astra", "claude-fable-5", "claude-fable-5-1")
FRONTIER_WORKHORSES = ("gpt-6.1-sol", "claude-opus-5-5")

# The names of the runtime policy fields that carry the owner's lists.
POLICY_WORKHORSES = "frontierPrimeModels"
POLICY_EXCLUDED = "excludedModels"


def _normalised_model(model: str) -> str:
    return str(model or "").strip().lower().replace(".", "-")


# The owner's runtime reasoning policy. It is independent of the condition
# Artificial Analysis measured the model under: the AA record ranks the model,
# and this policy says how we run it.
REASONING_DEFAULT = "medium"
REASONING_ESCALATION = "high"
REASONING_LEVEL_OPTIONS = ("variant", "reasoningeffort", "effort")

# The owner-approved High default for the exact DeepSeek V4.1 Flash models.
# The id is compared exactly after the provider namespace is stripped; there
# is no substring, family or suffix rule, and no other model inherits it.
REASONING_HIGH_EXCEPTION_MODELS = (
    "deepseek-v4.1-flash",
    "deepseek-v4.1-flash:1017",
)


def _reasoning_default(model: str) -> tuple[str, str]:
    """The runtime reasoning default of a model and its published basis."""
    name = str(model or "").strip().lower().rsplit("/", 1)[-1]
    if name in REASONING_HIGH_EXCEPTION_MODELS:
        return (
            "high",
            "owner-approved High execution default for the exact DeepSeek "
            "V4.1 Flash model; the AA reference and its Max condition are "
            "unchanged",
        )
    return (
        REASONING_DEFAULT,
        "owner runtime policy: medium by default, high for escalations",
    )


def _runtime_reasoning(row: Mapping[str, Any]) -> dict[str, Any]:
    """The runtime reasoning policy of a model, from its stock options.

    The default is medium and the escalation is high. A model is selectable
    when its published option lists the default; if it lists other levels
    without medium, that is an explicit capability mismatch and nothing is
    substituted. A model with no published level option is not subject to the
    policy. The AA benchmark condition is reported beside this, never as the
    condition we run.
    """
    default, default_basis = _reasoning_default(str(row.get("model") or ""))
    options = (row.get("native") or {}).get("options") or []
    effort_options = [
        option
        for option in options
        if isinstance(option, Mapping)
        and str(option.get("id") or "").lower() in REASONING_LEVEL_OPTIONS
    ]
    policy = {
        "default": default,
        "escalation": REASONING_ESCALATION,
        "basis": default_basis,
        "exception": default != REASONING_DEFAULT,
        "not_from_aa": True,
    }
    if not effort_options:
        return {
            "state": "not_applicable",
            "reason": "the model publishes no reasoning level option",
            "policy": policy,
            "default": default,
            "exception": policy["exception"],
            "option": None,
            "supported": [],
            "default_supported": None,
            "escalation_supported": None,
            "alignment": {},
            "escalation_alignment": {},
        }
    option = effort_options[0]
    identifier = str(option.get("id"))
    values = [
        str(value).strip().lower()
        for value in (option.get("values") or [])
        if isinstance(value, (str, int, float))
    ]
    current = option.get("current_value")
    if not values and isinstance(current, str):
        values = [current.strip().lower()]
    default_supported = default in values
    escalation_supported = REASONING_ESCALATION in values
    state = "selectable" if default_supported else "capability_mismatch"
    reason = (
        f"the model lists {default} for {identifier}"
        if default_supported
        else (
            f"the model lists {', '.join(values) or 'no levels'} for {identifier} "
            f"and not {default}; no level is substituted"
        )
    )
    return {
        "state": state,
        "reason": reason,
        "policy": policy,
        "default": default,
        "exception": policy["exception"],
        "basis": default_basis,
        "option": identifier,
        "supported": values,
        "current": current if isinstance(current, str) else None,
        "default_supported": default_supported,
        "escalation_supported": escalation_supported,
        "alignment": {identifier: default} if default_supported else {},
        "escalation_alignment": {identifier: REASONING_ESCALATION}
        if escalation_supported
        else {},
    }


def _three_d_value(row: Mapping[str, Any]) -> dict[str, Any]:
    """The 3D value: 0.45 * intelligence + 0.25 * capability + 0.30 * efficiency.

    The capability input is the AA-3D Elo under the source's own explicit
    normalization, min-max over the complete AA-3D snapshot. The
    intelligence is beside it rather than replaced by it: the owner asked
    for the two together for CAD selection. The efficiency input is the
    AA-3D cost per task when the feed publishes it. When it does not, the
    owner explicitly approved the normal Artificial Analysis cost per task
    of the same model as a proxy: it is published with
    `cost_source=artificialanalysis_intelligence` and `proxy=true`, and it
    is never called a measured 3D cost. A missing input leaves the
    combined value unknown, while the raw Elo, its interval and the source
    stay visible.
    """
    three_d = row.get("three_d") or {}
    aa = row.get("aa") or {}
    elo = three_d.get("elo")
    normalized = three_d.get("normalized")
    aa_3d_cost = three_d.get("cost_per_task")
    language_cost = aa.get("cost_per_task")
    cost = aa_3d_cost if isinstance(aa_3d_cost, (int, float)) and not isinstance(aa_3d_cost, bool) else None
    cost_source = "aa3d" if cost is not None else None
    proxy = False
    if cost is None and isinstance(language_cost, (int, float)) and not isinstance(language_cost, bool):
        cost = float(language_cost)
        cost_source = "artificialanalysis_intelligence"
        proxy = True
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        if not math.isfinite(float(cost)) or float(cost) < 0.0:
            cost = None
            proxy = False
            cost_source = None
    efficiency, evidence = value_policy.cost_transform(cost, (), COST_TRANSFORM)
    intelligence = (aa.get("indices") or {}).get("intelligence")
    components = {
        "intelligence": (
            max(0.0, min(1.0, float(intelligence) / 100.0))
            if isinstance(intelligence, (int, float)) and not isinstance(intelligence, bool)
            else None
        ),
        "three_d": normalized if isinstance(normalized, (int, float)) else None,
        "cost_per_task": efficiency,
    }
    value, missing = value_policy.combine(components, VALUE_3D_WEIGHTS)
    return {
        "value": None if value is None else round(value, 6),
        "components": {
            name: None if component is None else round(float(component), 4)
            for name, component in components.items()
        },
        "weights": dict(VALUE_3D_WEIGHTS),
        "cost_transform": COST_TRANSFORM,
        "cost_transform_evidence": evidence,
        "cost_source": cost_source,
        "proxy": proxy,
        "cost_basis": (
            "the AA-3D cost per task"
            if cost_source == "aa3d"
            else (
                "the normal Artificial Analysis cost per task of the same "
                "model, an owner-approved proxy and not a measured 3D cost"
                if proxy
                else "no cost per task"
            )
        ),
        "raw": {
            "elo": elo,
            "elo_interval": three_d.get("elo_interval") or {},
            "cost_per_task": cost,
            "aa3d_cost_per_task": aa_3d_cost,
            "language_cost_per_task": language_cost,
            "normalized": normalized,
            "normalization": three_d.get("normalization"),
            "normalization_state": three_d.get("normalization_state"),
            "source": three_d.get("source"),
            "observed_at": three_d.get("observed_at"),
            "task_count": three_d.get("task_count"),
        },
        "missing": missing,
        "note": (
            "the AA-3D Elo under the source's published normalization; an Elo "
            "is not a 0..100 index and is never divided by 100"
        ),
    }


def _selection_excluded(model: str, excluded: Any = None) -> bool:
    """True when the owner's policy excludes a model from selection.

    The excluded list is the runtime policy's, and the constant is only the
    fallback for a collector that runs without one. An excluded model stays
    visible in the usage and the quota readings; it is never a winner and
    never a recommendation.
    """
    names = excluded if isinstance(excluded, (list, tuple)) else SELECTION_EXCLUDED_MODELS
    wanted = {_normalised_model(str(name)) for name in names}
    return _normalised_model(model) in wanted


def _frontier_workhorse(model: str, workhorses: Any = None) -> bool:
    """True when the owner's policy names a model a frontier workhorse.

    The list is the runtime policy's, and the constant is only the fallback
    for a collector that runs without one. There is one list, so a policy
    change cannot work in the producer and be ignored in the reader.
    """
    names = workhorses if isinstance(workhorses, (list, tuple)) else FRONTIER_WORKHORSES
    wanted = {str(name).strip().lower() for name in names}
    return str(model or "").strip().lower() in wanted


# -- the trust and the outcomes of a model --------------------------------


class _Trust:
    """The trust and the observed outcomes of the models, read once.

    The trust of a model and the rounds it was measured on are read once
    per identity and task type, not once per row: two routes of one
    identity are one model, and they are counted once.

    Everything is total. A missing file is an empty history, a model
    without a policy entry and without a fabrication is trusted, and a
    model without a round keeps the prior of its intelligence.
    """

    def __init__(self, outcomes: Mapping[str, Any] | None = None) -> None:
        source = outcomes if isinstance(outcomes, Mapping) else {}
        self.identities = source.get("identities")
        self.policy = source.get("policy")
        self.rounds = source.get("rounds")
        self.backfill = source.get("backfill")
        self._counts: dict[tuple[str, str], dict[str, Any]] | None = None
        self._levels: dict[tuple[str, str], dict[str, Any]] = {}
        self._identities: dict[tuple[str, str], str] = {}
        self.reservations: dict[str, str] = {}
        policy = self.policy if isinstance(self.policy, Mapping) else {}
        for entry in policy.get("provider_reservations") or ():
            if not isinstance(entry, Mapping):
                continue
            if str(entry.get("status") or "") not in RESERVATION_IN_FORCE:
                continue
            provider = RESERVATION_PROVIDERS.get(str(entry.get("provider") or ""))
            if provider:
                self.reservations[provider] = str(entry.get("workload") or "")

    def reserved_for(self, provider: str, tier: str) -> str:
        """The workload a provider is reserved for, outside that workload's tiers."""
        workload = self.reservations.get(str(provider or ""), "")
        if not workload or tier in RESERVATION_TIERS.get(workload, ()):
            return ""
        return workload

    def identity(self, provider: str, model: str) -> str:
        """The identity of a route: the model it serves."""
        key = (str(provider or ""), str(model or ""))
        if key not in self._identities:
            self._identities[key] = outcomes_module.identity_of(
                key[0], key[1], self.identities
            )
        return self._identities[key]

    def counts(self) -> dict[tuple[str, str], dict[str, Any]]:
        """The observed rounds of every model and task type."""
        if self._counts is None:
            self._counts = outcomes_module.outcome_counts(
                self.rounds, self.backfill, self.identities
            )
        return self._counts

    def observed(self, identity: str, task_type: str) -> tuple[int, int]:
        """The rounds and the accepted rounds of a model and task type."""
        entry = self.counts().get((identity, task_type)) or {}
        rounds = entry.get("n")
        accepted = entry.get("s")
        return (
            int(rounds) if isinstance(rounds, (int, float)) else 0,
            int(accepted) if isinstance(accepted, (int, float)) else 0,
        )

    def totals(self, identity: str) -> tuple[int, int]:
        """The rounds and the accepted rounds of a model, every task type.

        The display score of a model is one number, so it reads every round
        the model was measured on, not only the rounds of the task type of
        one tier. An identity with no round sums to zero.
        """
        rounds = 0
        accepted = 0
        for (name, _task_type), entry in self.counts().items():
            if name != identity:
                continue
            observed = entry.get("n")
            succeeded = entry.get("s")
            rounds += int(observed) if isinstance(observed, (int, float)) else 0
            accepted += int(succeeded) if isinstance(succeeded, (int, float)) else 0
        return rounds, accepted


    def trust(self, identity: str, task_type: str) -> dict[str, Any]:
        """The trust of a model for a task type, and the reason it holds."""
        key = (str(identity or ""), str(task_type or ""))
        if key not in self._levels:
            self._levels[key] = outcomes_module.trust_for(
                key[0],
                key[1],
                self.policy,
                self.rounds,
                self.backfill,
                self.identities,
            )
        return self._levels[key]


def _trust_record(row: Mapping[str, Any], tier: str) -> dict[str, Any]:
    """The trust of a row for a tier, as it is published."""
    record = (row.get("trust") or {}).get(tier)
    return dict(record) if isinstance(record, Mapping) else {}


def _trust_level(row: Mapping[str, Any], tier: str) -> str:
    """The trust level of a row for a tier.

    A row that holds no trust record is trusted: the policy grants no
    penalty to a route nobody has judged.
    """
    level = str(_trust_record(row, tier).get("level") or "").strip().lower()
    if level not in value_policy.TRUST_LEVELS:
        return "trusted"
    return level


def _outcome_record(row: Mapping[str, Any], tier: str) -> dict[str, Any]:
    """The outcome record of a row for a tier, as it is published."""
    record = (row.get("outcome") or {}).get(tier)
    return dict(record) if isinstance(record, Mapping) else {}


def _reserved_for(row: Mapping[str, Any], tier: str) -> str:
    """The workload the provider of a row is reserved for, in this tier."""
    return str((row.get("reservation") or {}).get(tier) or "")


def _published_value_for(row: Mapping[str, Any], tier: str) -> float | None:
    """The published value of a row for a tier: its value under its trust."""
    value = _outcome_record(row, tier).get("published")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _outcome_quality(row: Mapping[str, Any], tier: str) -> float | None:
    """The outcome quality p of a row for a tier, when it is known."""
    quality = _outcome_record(row, tier).get("p")
    if isinstance(quality, (int, float)) and not isinstance(quality, bool):
        return float(quality)
    return None


def _is_free_route(row: Mapping[str, Any]) -> bool:
    """True when a route costs nothing: its billing class says so."""
    access = row.get("access") or {}
    billing = str(access.get("billing") or "") if isinstance(access, Mapping) else ""
    return billing == BILLING_FREE


def _intelligence_of(row: Mapping[str, Any]) -> float | None:
    """The measured Artificial Analysis intelligence index of a row."""
    value = (row.get("value") or {}).get("strength")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _efficiency_of(row: Mapping[str, Any]) -> float | None:
    """The efficiency of the measured cost per task of a row."""
    components = (row.get("value") or {}).get("components") or {}
    cost = (components.get("cost_per_task") or {}).get("value")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        return float(cost)
    return None


def _quality_basis(intelligence: float | None, rounds: int) -> str:
    """The basis of a display score: the measurements that built it.

    The intelligence of the model and the rounds it was measured on are two
    evidences, and the basis names which of them were there. A model with
    neither keeps the neutral prior, and its basis says so.
    """
    if intelligence is not None:
        if rounds > 0:
            return value_policy.QUALITY_BASIS_AA_OUTCOMES
        return value_policy.QUALITY_BASIS_AA_ONLY
    if rounds > 0:
        return value_policy.QUALITY_BASIS_OUTCOMES_DEFAULT
    return value_policy.QUALITY_BASIS_DEFAULT



def _fill_trust(candidates: list[dict[str, Any]], trust: _Trust) -> None:
    """The trust and the outcome of every row, for every tier it holds.

    The trust of a model is the trust the owner's policy gives it, and the
    trust the ledger's own rule gives it: the worse of the two. The
    outcome of a model is its measured intelligence inside its tier, shrunk
    toward the rounds that were actually observed, combined with the
    measured efficiency, and scaled by the trust of the model.

    The display score of a model is added beside the per-tier outcome: one
    number per model, from the intelligence of every ranked candidate and
    the rounds of every task type. It never orders a tier, and the tier
    order is unchanged.
    """
    for row in candidates:
        row["trust"] = {}
        row["outcome"] = {}
        row["reservation"] = {
            tier: trust.reserved_for(str(row.get("provider") or ""), tier)
            for tier in TIER_NAMES
        }
    # The trust of every row, for every tier it is a member of. The trust
    # of a tier decides whether the row may hold it at all: an excluded
    # level never holds a tier.
    for row in candidates:
        provider = str(row.get("provider") or "")
        model = str(row.get("model") or "")
        identity = trust.identity(provider, model)
        for tier in row.get("tiers") or []:
            task_type = TIER_TASK_TYPES.get(str(tier), "implementation")
            entry = trust.trust(identity, task_type)
            level = str(entry.get("level") or "trusted").strip().lower()
            if level not in value_policy.TRUST_LEVELS:
                level = "trusted"
            row["trust"][tier] = {
                "level": level,
                "reason": str(entry.get("reason") or ""),
                "evidence": entry.get("evidence") or {},
                "source": str(entry.get("source") or "default"),
                "task_type": task_type,
            }
    # The outcome of every row, per tier. The range of the tier is the
    # range of the models that hold it: the prior places a model inside
    # the tier it competes in.
    for tier in TIER_NAMES:
        task_type = TIER_TASK_TYPES.get(tier, "implementation")
        holders = [
            row
            for row in candidates
            if tier in (row.get("tiers") or []) and _holds_the_tier(row, tier)
        ]
        strengths = [
            strength
            for strength in (_intelligence_of(row) for row in holders)
            if strength is not None
        ]
        i_min = min(strengths) if strengths else None
        i_max = max(strengths) if strengths else None
        for row in candidates:
            if tier not in (row.get("tiers") or []):
                continue
            identity = trust.identity(
                str(row.get("provider") or ""), str(row.get("model") or "")
            )
            level = _trust_level(row, tier)
            intelligence = _intelligence_of(row)
            p0 = value_policy.outcome_prior(intelligence, i_min, i_max)
            rounds, accepted = trust.observed(identity, task_type)
            try:
                quality = value_policy.outcome_quality(p0, rounds, accepted)
            except ValueError:
                # A count that cannot exist is not a quality: the value of
                # the row stays unknown rather than invented.
                quality = None
            efficiency = _efficiency_of(row)
            if tier == "3d":
                # The 3D tier is valued by its own measure: the intelligence,
                # the measured AA-3D capability and the cost. The outcome of
                # the model is published beside it, and its trust scales it.
                three_d = (row.get("value_3d") or {}).get("value")
                value = (
                    float(three_d)
                    if isinstance(three_d, (int, float)) and not isinstance(three_d, bool)
                    else None
                )
            else:
                value = (
                    value_policy.outcome_value(quality, efficiency)
                    if quality is not None
                    else None
                )
            published = value_policy.trust_adjusted_value(value, level)
            row["outcome"][tier] = {
                "identity": identity,
                "task_type": task_type,
                "intelligence": intelligence,
                "i_min": i_min,
                "i_max": i_max,
                "p0": p0,
                "k": value_policy.OUTCOME_PRIOR_STRENGTH,
                "n": rounds,
                "s": accepted,
                "p": quality,
                "value": value,
                # The published value: the outcome value under the trust of
                # the model. An untrusted route keeps half of it.
                "published": published,
            }

    # The display score of a model is one number, not one per tier. The
    # prior places the model inside the range of every ranked candidate,
    # across every tier, and the counts are every task type of the identity:
    # two routes of one model read the same score. It is published beside
    # the per-tier outcome and it does not order a tier.
    ranked = [
        row
        for row in candidates
        if any(
            tier in (row.get("tiers") or []) and _holds_the_tier(row, tier)
            for tier in TIER_NAMES
        )
    ]
    strengths = [
        strength
        for strength in (_intelligence_of(row) for row in ranked)
        if strength is not None
    ]
    i_min_all = min(strengths) if strengths else None
    i_max_all = max(strengths) if strengths else None
    for row in candidates:
        identity = trust.identity(
            str(row.get("provider") or ""), str(row.get("model") or "")
        )
        intelligence = _intelligence_of(row)
        p0 = value_policy.outcome_prior(intelligence, i_min_all, i_max_all)
        rounds, accepted = trust.totals(identity)
        try:
            score = value_policy.quality_score(p0, rounds, accepted)
        except ValueError:
            # A count that cannot exist is not a score: the display number
            # stays unknown rather than invented.
            score = None
        row["quality_score"] = score
        row["quality_p0"] = p0
        row["quality_n"] = rounds
        row["quality_s"] = accepted
        row["quality_basis"] = _quality_basis(intelligence, rounds)


def _eligible_for_tier(row: Mapping[str, Any], tier: str) -> bool:
    """True when a model may hold a rank in a tier.

    The frontier tier takes the prime models of the owner policy. The other
    tiers take the delegates, and a delegate may not be a model the owner
    policy does not permit.

    The free tier is an access tier: a dedicated free route may hold it
    even when the collector has no native instance for it, because the pool
    runs it as an inference job. A pool route needs a current admission; a
    native free route is a provider-native thread and needs none.
    """
    aa = row.get("aa") or {}
    if aa.get("state") != "measured":
        # No verified record: the model is unranked, waiting for the feed.
        # It is never promoted by an estimate.
        return False
    if aa.get("reference") is None:
        # The selection reference needs both measured inputs. Without it the
        # model is visible with its raw record and is not selected.
        return False
    if not aa.get("selectable", True):
        # The runtime reasoning policy is not satisfiable: the mismatch stays
        # visible and the model is not selected.
        return False
    selection = row.get("selection") or {}
    if selection.get("excluded"):
        # Astra and Fable are read, counted and shown; they are never picked.
        return False
    eligibility = row.get("eligibility") or {}
    if tier == "frontier":
        # The frontier is the owner's workhorses and nothing else.
        return bool((eligibility.get("frontier_prime") or {}).get("allowed")) and bool(
            selection.get("frontier_workhorse")
        )
    reserve = row.get("reserve") or {}
    if tier in RESERVED_TIERS and reserve.get("3d") and reserve.get("withheld"):
        # The model is reserved for the 3D tier, and its provider has too
        # little capacity left to spend it on the other work.
        return False
    if tier == "free":
        if (row.get("access") or {}).get("kind") != ACCESS_DEDICATED_FREE:
            return bool((eligibility.get("delegate") or {}).get("allowed"))
        if _is_pool_route(row):
            # A pool route runs as an inference job: it needs a current
            # admission before it may hold the tier.
            return _admitted_for_any(row)
        return True
    return bool((eligibility.get("delegate") or {}).get("allowed"))


def _winner_key(row: dict[str, Any], tier: str = "") -> tuple:
    """The order of the candidates of one provider: trust, then value.

    The trust of a route comes first: a trusted route of a provider is
    used before a backup one, and an untrusted one is used last. Inside
    one trust level the published value decides, and the published value
    is the outcome-weighted value under that trust.

    The 3D tier keeps its own value as the last tiebreak, so the measured
    AA-3D capability still separates two routes of one trust level and
    one published value.
    """
    level = _trust_level(row, tier)
    published = _published_value_for(row, tier)
    three_d = (row.get("value_3d") or {}).get("value") if tier == "3d" else None
    if published is None:
        # A route whose published value is unknown keeps the value it had:
        # the Artificial Analysis value, and the 3D value in the 3D tier.
        if tier == "3d" and isinstance(three_d, (int, float)) and not isinstance(three_d, bool):
            published = float(three_d)
        else:
            value = (row.get("value") or {}).get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                published = float(value)
    return (
        # The lowest trust rank is the best: the key is negated, because
        # the winner of a provider is the largest key.
        -value_policy.trust_rank(level),
        published if published is not None else 0.0,
        float(three_d) if isinstance(three_d, (int, float)) and not isinstance(three_d, bool) else 0.0,
        str(row.get("model") or ""),
    )


def _pace_of(row: dict[str, Any]) -> float | None:
    """The pace of the account of a model, when it is known."""
    delta = (row.get("capacity") or {}).get("pace_delta")
    if isinstance(delta, (int, float)) and not isinstance(delta, bool):
        return float(delta)
    return None


def _holds_the_tier(row: Mapping[str, Any], tier: str) -> bool:
    """True when a route may hold a rank in a tier.

    A route that is not available, that waits for its evaluation, or that
    the tier does not permit never holds a rank. A route the owner's policy
    excludes never holds one either: an excluded trust level holds no tier
    at all.
    """
    if (row.get("availability") or {}).get("state") != "available":
        return False
    if (row.get("admission") or {}).get("state") != "settled":
        return False
    if _trust_level(row, tier) == "excluded":
        return False
    return _eligible_for_tier(row, tier)


def _strength_of(row: Mapping[str, Any]) -> float | None:
    """The Artificial Analysis intelligence index of a route, when it is known."""
    strength = (row.get("value") or {}).get("strength")
    if isinstance(strength, (int, float)) and not isinstance(strength, bool):
        return float(strength)
    return None


def _headroom_of(row: Mapping[str, Any]) -> float | None:
    """The remaining headroom of a route, when it is known.

    The remaining share of the collector's own capacity reading: the lowest
    remaining share across the windows that apply to the route.
    """
    remaining = (row.get("capacity") or {}).get("remaining_ratio")
    if isinstance(remaining, (int, float)) and not isinstance(remaining, bool):
        return float(remaining)
    return None


def _last_used_of(row: Mapping[str, Any]) -> float | None:
    """When a route was last used, when the pool says so.

    The pool knows when it last sent a job to a route. A route it has no
    reading for has an unknown use, and it is never read as never used.
    """
    last_used = (row.get("free_pool") or {}).get("last_used")
    if isinstance(last_used, (int, float)) and not isinstance(last_used, bool):
        return float(last_used)
    return None


def build_snapshot(
    *,
    now: float,
    sources: Iterable[Mapping[str, Any]],
    ranked: Iterable[Any],
    native_models: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
    policy: Mapping[str, Any] | None = None,
    aa_cache: Mapping[str, Any] | None = None,
    measured_windows: Iterable[Mapping[str, Any]] | None = None,
    aa_3d_cache: Mapping[str, Any] | None = None,
    inventory: Iterable[Any] | None = None,
    catalog: Any = None,
    facts: Mapping[str, Any] | None = None,
    free_models: Iterable[Any] | None = None,
    promo_models: Iterable[Any] | None = None,
    pool_evidence: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
    inferred_windows: Iterable[Mapping[str, Any]] | None = None,
    outcomes: Mapping[str, Any] | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    routing_enabled: bool = False,
) -> dict[str, Any]:
    """Build the routing snapshot from the ranked models and the readings.

    The `outcomes` mapping carries the trust and the observed outcomes of
    the models: the `identities` of the models, the owner's `policy` of
    trust, the `rounds` of the ledger and the `backfill` of the rounds it
    does not carry. It is optional: without it every model is trusted and
    no round was observed.
    """
    facts_index = facts_module.index(facts or {})
    free_set: set[tuple[str, str]] = set()
    for record in free_models or ():
        if isinstance(record, tuple) and len(record) == 2:
            free_set.add((str(record[0]), str(record[1])))
    promo_set: set[tuple[str, str]] = set()
    for record in promo_models or ():
        if isinstance(record, tuple) and len(record) == 2:
            promo_set.add((str(record[0]), str(record[1])))
    native_models = native_models or {}
    policy = dict(policy or {})
    entries: dict[tuple[str, str], list[Any]] = {}
    for entry in ranked:
        entries.setdefault((entry.provider, entry.model), []).append(entry)

    facts_source = facts or {}
    # The version the feed published for the records it produced. A fact of
    # another version does not bind to it.
    feed_version = None
    if isinstance(aa_cache, Mapping) and aa_cache.get("status") == "ok":
        feed_version = str(aa_cache.get("index_version") or "") or None
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
        # The window keeps the scope the ranking gives it, so a window that
        # covers one model family is never published as a window of the
        # whole account. A reading of one model that names no family is
        # not a window of the account at all.
        scope = quota_module.measured_scope(measured)
        if scope is None:
            continue
        record = _window_record(measured, now)
        if scope:
            record["applies_to"] = [str(token) for token in scope]
        known = accounts.setdefault(account, [])
        if record not in known:
            known.append(record)
    # The windows the limit failures of the routes measured, beside the
    # readings the provider reported and never over one. They are published
    # once per account, and a refused route keeps its record even while the
    # ranking holds no row for it: the account's capacity is not a property
    # of the ranked rows.
    for inferred in inferred_windows or ():
        account = str(inferred.get("provider") or "")
        if not account:
            continue
        record = _inferred_window_record(
            inferred.get("window"), now, inferred.get("applies_to") or ()
        )
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
            free_set,
            promo_set,
            catalog,
            (pool_evidence or {}).get((provider, model)),
        )
        row["capacity"]["bindings_differ"] = _bindings_differ(row)
        variant = _row_variant(row)
        fact = facts_module.lookup_by_model(
            facts_source,
            provider,
            model,
            variant,
            now=now,
            version=feed_version,
        )
        _fill_value(row, catalog, fact, now, free_set, promo_set, aa_3d_cache)
        row["free_pool"] = _free_pool_record((pool_evidence or {}).get((provider, model)))
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
        if (
            row["rank"]
            or row["admission"]["state"] == "pending"
            or row["quota_state"] != "unknown"
            or row["aa"]["state"] != "measured"
            or not row["rank"]
        ):
            # An unranked model stays visible with its reason: the dashboard
            # shows it waiting for the feed, not silently dropped.
            candidates.append(row)
        else:
            omitted += 1
    provider_capacity: dict[str, Any] = {}
    for account, windows in accounts.items():
        # The provider's overall capacity is the account-level windows. A
        # model-scoped subordinate window constrains that model only.
        applicable = [
            window for window in windows if not window.get("applies_to")
        ]
        reported = [
            window
            for window in applicable
            # A provider-reported reading and a window the limit failures of
            # the account's routes learned are both evidence of the share
            # that is left; an inferred window is never counted as a number
            # it did not measure.
            if window.get("evidence") in ("provider_reported", "inferred")
            and isinstance(window.get("remaining_ratio"), (int, float))
            and not isinstance(window.get("remaining_ratio"), bool)
        ]
        unknown = [window for window in applicable if window not in reported]
        spent = [window for window in reported if float(window["remaining_ratio"]) <= 0.0]
        binding = None
        remaining: float | None = None
        if spent:
            # A spent window blocks the provider even when another window
            # still has room.
            binding = sorted(spent, key=lambda window: str(window.get("kind") or ""))[0]
            remaining = 0.0
        elif unknown:
            # An unknown window is not room: a positive reading from the
            # known windows is suppressed until the account is complete.
            remaining = None
        elif reported:
            binding = min(reported, key=lambda window: float(window["remaining_ratio"]))
            remaining = float(binding["remaining_ratio"])
        provider_capacity[account] = {
            "remaining_ratio": None if remaining is None else round(remaining, 4),
            "binding": None
            if binding is None
            else {
                "kind": binding.get("kind"),
                "quota": binding.get("quota"),
                "reset_at": binding.get("reset_at"),
            },
            "windows": len(applicable),
            "unknown_windows": len(unknown),
            "basis": (
                "the lowest applicable remaining share; any spent window "
                "blocks the provider, and an unknown window is not room"
            ),
        }
    _apply_reserve(candidates, provider_capacity)

    # The order of a tier: the published value decides, and a model
    # reserved for the 3D tier comes after every other member of the tiers
    # it is reserved away from. The 3D tier is ordered by the 3D value.
    reserve_of = {
        _key(row["provider"], row["model"]): 1
        if (row.get("reserve") or {}).get("3d")
        else 0
        for row in candidates
    }
    value_of: dict[str, Any] = {}
    for tier_name in TIER_NAMES:
        for row in candidates:
            key = _key(row["provider"], row["model"])
            value_of[(tier_name, key)] = (
                (row.get("value_3d") or {}).get("value")
                if tier_name == "3d"
                else (row.get("value") or {}).get("value")
            )
    for tier, members in tiers.items():
        order = {
            _key(entry.provider, entry.model): entry.rank
            for entry in ranked
            if entry.tier == tier
        }
        tiers[tier] = sorted(
            set(members),
            key=lambda key: (
                reserve_of.get(key, 0) if tier in RESERVED_TIERS else 0,
                -(
                    float(value_of.get((tier, key)))
                    if isinstance(value_of.get((tier, key)), (int, float))
                    and not isinstance(value_of.get((tier, key)), bool)
                    else 0.0
                ),
                order.get(key, 0),
                key,
            ),
        )
    _calibrate_values(candidates)
    # The trust of every model, and the outcome its published value is
    # built from. Both are read before the tiers are ordered, so a trusted
    # route leads a tier and an untrusted one comes last with its reason.
    _fill_trust(candidates, _Trust(outcomes))
    winners, tier_coverage = _winners(candidates, tiers, aa_cache=aa_cache)
    pending_identities = _pending_identities(candidates, facts_source, now)
    # The tiers are the operational list: one current winner per upstream
    # provider. The whole membership stays beside them for the comparison
    # view, and the counts say how much was considered.
    tier_members = {tier: list(members) for tier, members in tiers.items()}
    tiers = {
        tier: [winner["key"] for winner in rows] for tier, rows in winners.items()
    }

    candidate_keys = {(row["provider"], row["model"]) for row in candidates}
    inventory_keys = []
    for entry in inventory or ():
        if isinstance(entry, (tuple, list)) and len(entry) == 2:
            inventory_keys.append((str(entry[0]), str(entry[1])))
        elif isinstance(entry, Mapping):
            inventory_keys.append((str(entry.get("provider") or ""), str(entry.get("model") or "")))
    excluded = [list(pair) for pair in inventory_keys if pair not in candidate_keys]
    ranking_coverage = {
        "inventory": len(inventory_keys),
        "candidates": len(candidates),
        "excluded": len(excluded),
        "excluded_models": excluded[:500],
        "basis": (
            "every offered model is a candidate row; a model missing from the "
            "candidates is listed here, never silently dropped"
        ),
    }
    aa_coverage_rows = []
    for row in candidates:
        aa = row.get("aa") or {}
        condition = aa.get("condition") or {}
        aa_coverage_rows.append(
            {
                "provider": row["provider"],
                "model": row["model"],
                "state": aa.get("state"),
                "reason": aa.get("reason") or "",
                "aa_id": aa.get("id"),
                "aa_slug": aa.get("slug"),
                "aa_name": aa.get("name"),
                "release_date": aa.get("release_date"),
                "measured_variant": condition.get("measured_variant"),
                "native_variant": condition.get("native_variant"),
                "variant_match": condition.get("variant_match"),
                "checkpoint": condition.get("checkpoint"),
                "matched_by": aa.get("matched_by"),
                "selectable": aa.get("selectable"),
            }
        )
    aa_states: dict[str, int] = {}
    aa_reasons: dict[str, int] = {}
    for coverage_row in aa_coverage_rows:
        state = str(coverage_row["state"])
        aa_states[state] = aa_states.get(state, 0) + 1
        reason = str(coverage_row["reason"])
        if reason:
            aa_reasons[reason] = aa_reasons.get(reason, 0) + 1
    aa_coverage = {
        "source": "artificialanalysis",
        "index_version": (aa_cache or {}).get("index_version"),
        "fetched_at": (aa_cache or {}).get("fetched_at"),
        "basis": (
            "every candidate is bound to the exact measured record by id, "
            "slug, name or documented alias after removing routing, promotion "
            "and packaging wrappers; nothing is matched by substring"
        ),
        "total": len(aa_coverage_rows),
        "states": aa_states,
        "reasons": aa_reasons,
        "candidates": aa_coverage_rows,
        # The models the last pull found that the one before it did not
        # carry, and the models whose measurement changed. They are the
        # re-ranking trigger.
        "new_models": list((aa_cache or {}).get("new_models") or ()),
        "changed_models": list((aa_cache or {}).get("changed_models") or ()),
    }

    source_records = []
    for source in sources:
        record = dict(source)
        observed = record.get("observed_at_epoch")
        record["age_seconds"] = (
            None if observed is None else int(round(now - float(observed)))
        )
        source_records.append(record)
    failed = [
        record
        for record in source_records
        if record.get("status") not in ("ok", "partial")
    ]
    # A partial source means the snapshot does not hold the whole picture, so
    # it is partial too: a consumer must not read it as complete.
    incomplete = failed or [
        record for record in source_records if record.get("status") == "partial"
    ]

    # Whether a frontier prime is available right now. When it is not, the
    # consumer has to wait visibly: the reason and the reset time are here,
    # so a required frontier is never quietly replaced by a delegate.
    frontier_rows = [
        row
        for row in candidates
        if "frontier" in row["tiers"] and row["quota_state"] == "available"
    ]
    # The models the policy admits to the frontier, whether their quota
    # allows them right now or not. A spent frontier model stays a member,
    # with its state and its reset: it is not a phantom winner, and it is not
    # silently absent either.
    frontier_members = [
        row
        for row in candidates
        if (row.get("eligibility") or {}).get("frontier_prime", {}).get("allowed")
        and (row.get("admission") or {}).get("state") == "settled"
        and (row.get("native") or {}).get("mapped")
    ]
    frontier_eligible = []
    for row in frontier_members:
        capacity = row.get("capacity") or {}
        frontier_eligible.append(
            {
                "provider": row["provider"],
                "model": row["model"],
                "key": _key(row["provider"], row["model"]),
                "state": (
                    "available"
                    if (row.get("availability") or {}).get("state") == "available"
                    else "unavailable"
                ),
                "reason": (
                    ""
                    if (row.get("availability") or {}).get("state") == "available"
                    else "the quota of the frontier model is spent or unknown"
                ),
                "quota_state": row.get("quota_state"),
                "reset_at": (
                    (capacity.get("capacity_binding") or {}).get("reset_at")
                    if isinstance(capacity.get("capacity_binding"), Mapping)
                    else None
                ),
                "seconds_to_reset": capacity.get("expires_in_seconds"),
                "native": row.get("native"),
            }
        )
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
        "partial": bool(incomplete),
        # The owner's routing switch, published as it is. The collector never
        # acts on it: a consumer reads the switch and decides, and the switch
        # is off until the owner turns it on.
        "routing": {
            "enabled": bool(routing_enabled),
            "source": ROUTING_SOURCE,
        },
        "coverage": {
            "ranking": ranking_coverage,
            "sources_total": len(source_records),
            "sources_ok": sum(1 for r in source_records if r.get("status") == "ok"),
            "sources_partial": sum(
                1 for r in source_records if r.get("status") == "partial"
            ),
            "sources_failed": len(failed),
            "sources": source_records,
            "tiers": tier_coverage,
            "frontier": {
                "available": bool(frontier_rows),
                "models": frontier_models,
                "eligible": frontier_eligible,
                "reason": frontier_reason,
                "wait_for": "the frontier model becomes available again",
            },
        },
        "policy": {
            "frontier_prime_models": list(policy.get("frontierPrimeModels") or ()),
            "excluded_models": list(policy.get(POLICY_EXCLUDED) or ()),
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
        "tier_winners": winners,
        "tier_members": tier_members,
        "calculation": CALCULATION,
        "value_policy": value_policy.policy_document(COST_TRANSFORM),
        "quota": {
            "accounts": accounts,
            "provider_capacity": provider_capacity,
        },
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
                "a dedicated free route is preferred for the low complexity "
                "classes without further proof. For a high complexity class it "
                "is considered only with admission evidence of that route for "
                "that workload, and the private data and frontier review gates "
                "still apply. A provider's promotional zero-price model is a "
                "paid bulk route, not a dedicated free one"
            ),
            "complexity_rule": (
                "a high complexity class needs per workload admission evidence "
                "for the route, or a native route; neither a price nor a model "
                "name is evidence"
            ),
        },
        "recommendations": _recommendations(candidates, WORKLOAD_CLASSES),
        "candidates": candidates,
        "facts": {
            "count": len(facts_index),
            "version": facts_module.BENCHMARK_VERSION,
            "max_age_seconds": facts_module.FACT_MAX_AGE_SECONDS,
            # The facts are keyed by their identity (provider, model, and
            # reasoning variant), so two providers or two variants never
            # share a record.
            # Only a fact whose exact identity the live catalog proved is
            # published: a name from a file is not a model.
            "records": facts_module.public_facts(
                facts_source,
                {
                    facts_module.identity_key(
                        str(row.get("provider") or ""),
                        str(row.get("model") or ""),
                        _row_variant(row),
                    )
                    for row in candidates
                },
            ),
            # The identities a consumer may trigger a research for: every
            # model of a tier that has no usable fact yet. The list is
            # bounded to the models the tiers hold.
            "pending_identities": pending_identities,
        },
        "pending": pending,
        "value_policy": {
            **VALUE_POLICY,
            **value_policy.policy_document(COST_TRANSFORM),
        },
        "aa_coverage": aa_coverage,
        "counts": {
            "candidates": len(candidates),
            "ranked": sum(1 for row in candidates if row["rank"]),
            "pending": len(pending),
            "omitted": omitted,
        },
    }


def provider_capacity_samples(
    snapshot: Mapping[str, Any],
) -> list[tuple[str, dict[str, str], float]]:
    """The provider capacity, with its binding window, as gauges.

    A positive capacity is published only when it is known: an unknown window
    suppresses it, and a spent window publishes zero with its binding.
    """
    samples: list[tuple[str, dict[str, str], float]] = []
    quota = snapshot.get("quota") or {}
    for provider, capacity in sorted((quota.get("provider_capacity") or {}).items()):
        if not isinstance(capacity, Mapping):
            continue
        binding = capacity.get("binding") or {}
        kind = str(binding.get("kind") or "unknown") if isinstance(binding, Mapping) else "unknown"
        remaining = capacity.get("remaining_ratio")
        if isinstance(remaining, (int, float)) and not isinstance(remaining, bool):
            samples.append(
                (
                    "ghostship_ai_provider_capacity_remaining_ratio",
                    {"provider": str(provider), "binding": kind},
                    float(remaining),
                )
            )
        known = max(0, int(capacity.get("windows") or 0) - int(capacity.get("unknown_windows") or 0))
        unknown = int(capacity.get("unknown_windows") or 0)
        samples.append(
            (
                "ghostship_ai_provider_capacity_windows",
                {"provider": str(provider), "evidence": "known"},
                float(known),
            )
        )
        samples.append(
            (
                "ghostship_ai_provider_capacity_windows",
                {"provider": str(provider), "evidence": "unknown"},
                float(unknown),
            )
        )
    # The owner's ordering measure, per provider: the Paced Availability of
    # the provider in its most constraining window. It is the pace delta of
    # that window, and a higher number ranks first. The provider's own
    # measure is the smallest one over its models: the most constraining
    # window of the account.
    by_provider: dict[str, tuple[float, str]] = {}
    for row in snapshot.get("candidates") or []:
        if not isinstance(row, Mapping):
            continue
        capacity = row.get("capacity") or {}
        paced = capacity.get("paced_availability")
        if not isinstance(paced, (int, float)) or isinstance(paced, bool):
            continue
        provider = str(row.get("provider") or "")
        binding = str(capacity.get("paced_availability_window") or "")
        current = by_provider.get(provider)
        if current is None or float(paced) < current[0]:
            by_provider[provider] = (float(paced), binding)
    for provider, (paced, binding) in sorted(by_provider.items()):
        samples.append(
            (
                "ghostship_ai_provider_paced_availability",
                {"provider": provider, "binding": binding},
                paced,
            )
        )
    return samples


# The place a window row takes in the card of its account. The session
# window comes first, because it is the one that runs out first, and the
# monthly window comes after the weekly one. An inferred window comes
# after every window a provider reported, and a window of an unknown kind
# comes last.
ACCOUNT_WINDOW_ORDER = {
    "session": 1,
    "daily": 2,
    "weekly": 3,
    "monthly": 4,
    "quota": 5,
    "inferred": 8,
}
ACCOUNT_WINDOW_ORDER_OTHER = 9

# How many decimals the even-spend line of a window is published with. The
# line is a position in a bar, and a tenth of a percent is finer than a
# bar shows.
ACCOUNT_WINDOW_LINE_DECIMALS = 3

# The marks of an account that has no period to show. The inference files
# a route that was never refused under one of them, and the account is
# learning rather than holding a window.
NOT_A_WINDOW_QUOTA_IDS = frozenset({usage_inference.QUOTA_ID_NO_FAILURE})

# The length of a window as the inference names it: '5h', '1m', '12d'. The
# suffix of an inferred quota id is a window only when it is a length of
# time; a suffix that names a state of the inference, such as 'exhausted',
# is not a period, and the row of that window is named by its kind alone.
INFERRED_WINDOW_LENGTH = re.compile(r"^[0-9]+(s|m|h|d|w)$")


def _epoch_seconds(value: Any) -> float | None:
    """A moment in seconds, from the epoch or from the published form."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _finite(value)
    if isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.timestamp()
    return None


def _title_case(text: Any) -> str:
    """A name in title case: 'seven_day' reads 'Seven Day'."""
    return " ".join(
        word.capitalize()
        for word in re.split(r"[^0-9A-Za-z]+", str(text or ""))
        if word
    )


def _is_window(record: Mapping[str, Any]) -> bool:
    """True when a record is a window of an account.

    The mark of an account whose limit was never seen is not a window: the
    account has no period to show, and the card says it is learning.
    """
    return str(record.get("quota_id") or "") not in NOT_A_WINDOW_QUOTA_IDS


def _window_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    """The identity of a window: its kind, its quota and its scope.

    The quota id is the canonical one, so the two names of one window
    (the OpenCode Go status and the Go usage endpoint name the same three
    windows) are one window.
    """
    kind = str(record.get("kind") or "")
    quota_id = str(record.get("quota_id") or "")
    canonical = quota_module.QUOTA_ALIASES.get(quota_id, quota_id)
    applies = tuple(str(token) for token in (record.get("applies_to") or ()))
    return (kind, canonical, applies)


def _window_rank(record: Mapping[str, Any]) -> tuple[Any, ...]:
    """The order the readings of one window are read in.

    The reading that carries the length of the window wins, then the one
    that carries its reset, then the freshest one, then the one with the
    least left, and finally the one that resets first. A reading that
    knows nothing is never the one that wins.
    """
    duration = _finite(record.get("duration_seconds"))
    reset = _epoch_seconds(record.get("reset_at"))
    check = _epoch_seconds(record.get("check_at"))
    remaining = _finite(record.get("remaining_ratio"))
    return (
        0 if duration is not None and duration > 0 else 1,
        0 if reset is not None else 1,
        -check if check is not None else float("inf"),
        remaining if remaining is not None else float("inf"),
        reset if reset is not None else float("inf"),
    )


def _kept_windows(records: Iterable[Any]) -> list[dict[str, Any]]:
    """One record per window: the reading the row of the card is drawn from."""
    kept: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in records or ():
        if not isinstance(record, Mapping):
            continue
        if not _is_window(record):
            continue
        key = _window_key(record)
        current = kept.get(key)
        if current is None or _window_rank(record) < _window_rank(current):
            kept[key] = dict(record)
    return list(kept.values())


def _window_suffix(kind: str, quota_id: str, siblings: Iterable[str]) -> str:
    """The part of the label that names the window itself.

    An inferred window names the window it was inferred over, and a window
    whose quota id extends another window of the same kind says which one
    it is. An inferred window whose suffix names a state of the inference
    rather than a period names no window, and it says nothing more.
    """
    prefix = f"{kind}:"
    if quota_id.startswith(prefix):
        suffix = quota_id[len(prefix):]
        if quota_id.startswith(usage_inference.QUOTA_ID_PREFIX):
            # The suffix of an inferred quota id is the window it was
            # learned over, and a length of time is that window. A state
            # of the inference is not a period.
            if not INFERRED_WINDOW_LENGTH.match(suffix):
                return ""
        return _title_case(suffix)
    for other in sorted(siblings):
        if other == quota_id:
            continue
        for separator in ("_", "-"):
            if quota_id.startswith(other + separator):
                return _title_case(quota_id[len(other) + 1:])
    return ""


def _window_label(kind: str, quota_id: str, siblings: Iterable[str]) -> str:
    """The label of a row of a card.

    The label is the kind of the window, and a window that names a
    narrower period than its kind says which one after a dot: the weekly
    window of a model family reads 'Weekly · Fable'.
    """
    base = _title_case(kind)
    suffix = _window_suffix(kind, quota_id, siblings)
    return f"{base} · {suffix}" if suffix else base


def _scope_suffix(scope: Iterable[str], label: str) -> str:
    """The scope of a window, as the label of the row names it.

    A window that covers one model family says which one, and the label of
    the row names it: 'Session · Claude & GPT'. A label that names the
    scope already is not named twice: 'Weekly · Fable' stays that.
    """
    names = [
        quota_module.SCOPE_NAMES.get(str(token).lower(), _title_case(token))
        for token in scope or ()
    ]
    names = [name for name in names if name]
    if not names:
        return ""
    text = " & ".join(names)
    if str(label or "").lower().endswith(text.lower()):
        return ""
    return f" · {text}"


def _scoped_quota_id(window: Mapping[str, Any]) -> str:
    """The quota id a published window series carries.

    The card of an account keys its rows by the account, the kind and the
    quota id, so a provider that publishes one quota id for several model
    families would draw one row of the card for all of them. The scope of
    the window is named after the id when the id does not name it already,
    and every series of an account carries an id of its own.

    A window whose id names its scope keeps it: '3p-5h' names the Claude
    and the GPT models of the third-party group, and 'seven_day_fable'
    names the Fable models of the Claude account. A window without a scope
    is a window of the whole account, and it keeps its id. An inferred
    window keeps its id too: it names the window it was learned over, and
    the scope of the route is not part of that name.
    """
    quota_id = str(window.get("quota_id") or "")
    if str(window.get("evidence") or "") == "inferred":
        return quota_id
    scope = [
        str(token).strip().lower()
        for token in (window.get("applies_to") or ())
        if str(token).strip()
    ]
    if not scope or not quota_id:
        return quota_id
    named = quota_module.window_scope(quota_id)
    if named and set(named) == set(scope):
        return quota_id
    return f"{quota_id}@{'+'.join(scope)}"


def _published_quota_id(quota_id: str) -> ExactLabel:
    """The quota id of a published series, as the text file holds it.

    The writer's safe form of a label value replaces every character it
    does not know, and the id of a scoped window carries an '@' and a '+':
    the safe form of 'quotaInfo@gemini' is 'quotaInfo_gemini', and that is
    another id than the one the card keys its rows by. The id is a name
    the collector composed, so it is published as it is, and it keeps the
    bound every label value has.
    """
    return ExactLabel(str(quota_id)[:MAX_LABEL_LENGTH])


def account_window_samples(
    snapshot: Mapping[str, Any],
) -> list[tuple[str, dict[str, str], float]]:
    """The capacity windows of every account, one series per window.

    A row of a card is one window of one account: the label of the window,
    the share that is left, the even-spend line, the reset, the moment the
    window was checked, and the place the row takes in the card. The values
    are read from the routing snapshot, and the page never recomputes a
    window.

    Two readings of one window are one series. The reading that carries
    the length of the window wins, then the one that carries its reset,
    then the freshest one, then the one with the least left, and finally
    the one that resets first. The check time is the one of the reading
    that won, so the age of a card is the age of the reading it draws.

    Every series of an account carries a quota id of its own, so a
    provider that publishes one quota id for several model families draws
    one row of the card for each of them. The id is published the way the
    collector composed it, so the text file holds 'quotaInfo@gemini' and
    not another id.

    An account that publishes no window of its own is learning, and the
    collector says so instead of drawing a row.
    """
    quota = snapshot.get("quota") or {}
    accounts = {
        str(name): records for name, records in (quota.get("accounts") or {}).items()
    }
    capacity = {
        str(name): value for name, value in (quota.get("provider_capacity") or {}).items()
    }
    samples: list[tuple[str, dict[str, str], float]] = []
    for account in sorted(set(accounts) | set(capacity)):
        windows = _kept_windows(accounts.get(account) or [])
        if not windows:
            samples.append(
                (
                    "ghostship_ai_account_window_learning",
                    {"account": account},
                    1.0,
                )
            )
            continue
        published = [(window, _scoped_quota_id(window)) for window in windows]
        siblings: dict[str, list[str]] = {}
        for window, quota_id in published:
            kind = str(window.get("kind") or "")
            siblings.setdefault(kind, []).append(quota_id)
        for window, quota_id in sorted(
            published,
            key=lambda item: (
                ACCOUNT_WINDOW_ORDER.get(str(item[0].get("kind") or ""), ACCOUNT_WINDOW_ORDER_OTHER),
                str(item[0].get("kind") or ""),
                item[1],
            ),
        ):
            kind = str(window.get("kind") or "")
            # The scope of the window is named by the label of the row. An
            # inferred window names the window it was learned over, and
            # that name is the whole of it.
            scope = window.get("applies_to") or ()
            if str(window.get("evidence") or "") == "inferred":
                scope = ()
            label = _window_label(kind, quota_id, siblings.get(kind, []))
            labels = {
                "account": account,
                "kind": kind,
                # The quota id is a name the collector composed, and it is
                # published as it is: the card keys its rows by it.
                "quota_id": _published_quota_id(quota_id),
                # The label is a name for a reader, and it is published the
                # way it reads.
                "label": ExactLabel(label + _scope_suffix(scope, label)),
                "evidence": str(window.get("evidence") or "unknown"),
            }
            remaining = _finite(window.get("remaining_ratio"))
            if remaining is not None:
                samples.append(
                    ("ghostship_ai_account_window_remaining_ratio", dict(labels), remaining)
                )
            seconds = _finite(window.get("seconds_to_reset"))
            duration = _finite(window.get("duration_seconds"))
            line = None
            if seconds is not None and duration is not None and duration > 0:
                line = max(0.0, min(1.0, float(seconds) / float(duration)))
                samples.append(
                    (
                        "ghostship_ai_account_window_expected_remaining_ratio",
                        dict(labels),
                        round(line, ACCOUNT_WINDOW_LINE_DECIMALS),
                    )
                )
            # The band of the window's own line: ahead, on_pace, behind,
            # far_behind, spent or unknown. A window with no line to compare
            # with says unknown, so a card always has a state to colour and
            # never draws a band of its own.
            samples.append(
                (
                    "ghostship_ai_account_window_pace_state",
                    {**labels, "state": value_policy.pace_state(remaining, line)},
                    1.0,
                )
            )
            reset = _epoch_seconds(window.get("reset_at"))
            if reset is not None:
                samples.append(
                    (
                        "ghostship_ai_account_window_reset_timestamp_seconds",
                        dict(labels),
                        reset,
                    )
                )
            # The moment the provider reported the window. It is read from
            # the record the row is drawn from, so a card can be compared
            # with the provider's own site. A reading without a check time
            # publishes none, and the other series of the row stay as they
            # are.
            check = _epoch_seconds(window.get("check_at"))
            if check is not None:
                samples.append(
                    (
                        "ghostship_ai_account_window_check_timestamp_seconds",
                        dict(labels),
                        check,
                    )
                )
            # The mark of an inferred window that rolls: a window shorter
            # than five minutes with no reset. The page says 'rolling' for
            # it, and a reading that carries no mark publishes none.
            inference = window.get("inference")
            if isinstance(inference, Mapping) and inference.get("rolling") is True:
                samples.append(
                    (
                        "ghostship_ai_account_window_rolling",
                        dict(labels),
                        1.0,
                    )
                )
            samples.append(
                (
                    "ghostship_ai_account_window_order",
                    dict(labels),
                    float(
                        ACCOUNT_WINDOW_ORDER.get(kind, ACCOUNT_WINDOW_ORDER_OTHER)
                    ),
                )
            )
    return samples


def decision_samples(snapshot: Mapping[str, Any]) -> list[tuple[str, dict[str, str], float]]:
    """The metrics behind a decision, so the dashboard can show the inputs.

    Every value a winner was chosen on is published: the strength and where
    it came from, the relative price, the value, the benchmark indices, the
    cost per task, the provider's own token prices, the throughput, the state
    of the durable fact, and the position of a model among the candidates of
    its provider.
    """
    samples: list[tuple[str, dict[str, str], float]] = []
    for row in snapshot.get("candidates") or []:
        if not isinstance(row, Mapping):
            continue
        provider = str(row.get("provider") or "")
        model = str(row.get("model") or "")
        if not provider or not model:
            continue
        labels = {"provider": provider, "model": model}
        value = row.get("value") or {}
        for name, field in (
            # The strength is the verified intelligence index of the model,
            # kept for the existing panels. It is not a prior: a model without
            # a record has no strength and is unranked.
            ("ghostship_ai_model_strength", "strength"),
            ("ghostship_ai_model_relative_cost", "relative_cost"),
            ("ghostship_ai_model_value", "value"),
        ):
            number = value.get(field)
            if isinstance(number, (int, float)) and not isinstance(number, bool):
                samples.append(
                    (name, {**labels, "source": str(value.get("strength_source") or "prior")}, float(number))
                )
        intelligence = row.get("intelligence") or {}
        for index, number in (intelligence.get("indices") or {}).items():
            if isinstance(number, (int, float)) and not isinstance(number, bool):
                samples.append(
                    (
                        "ghostship_ai_model_intelligence_index",
                        {**labels, "index": str(index)},
                        float(number),
                    )
                )
        cost_per_task = intelligence.get("cost_per_task")
        if isinstance(cost_per_task, (int, float)) and not isinstance(cost_per_task, bool):
            samples.append(("ghostship_ai_model_cost_per_task", labels, float(cost_per_task)))
        throughput = intelligence.get("median_performance")
        if isinstance(throughput, (int, float)) and not isinstance(throughput, bool):
            samples.append(("ghostship_ai_model_throughput", labels, float(throughput)))
        price = row.get("price") or {}
        for kind in ("input", "output", "cache_read"):
            number = price.get(kind)
            if isinstance(number, (int, float)) and not isinstance(number, bool):
                samples.append(
                    ("ghostship_ai_model_token_price", {**labels, "kind": kind}, float(number))
                )
        pace_delta = (row.get("capacity") or {}).get("pace_delta")
        if isinstance(pace_delta, (int, float)) and not isinstance(pace_delta, bool):
            samples.append(
                ("ghostship_ai_model_pace_delta_ratio", labels, float(pace_delta))
            )
            # The owner's name for the same number: the Paced Availability of
            # the model. It is the pace delta of the model's most
            # constraining window.
            samples.append(
                ("ghostship_ai_model_paced_availability", labels, float(pace_delta))
            )
    facts = (snapshot.get("facts") or {}).get("records") or {}
    for fact in facts.values():
        if not isinstance(fact, Mapping):
            continue
        provider = str(fact.get("provider") or "")
        model = str(fact.get("model") or "")
        if not provider or not model:
            continue
        labels = {
            "provider": provider,
            "model": model,
            "status": str(fact.get("status") or "current"),
            "variant": str(fact.get("variant") or ""),
        }
        samples.append(("ghostship_ai_model_fact", labels, 1.0))
        fetched = fact.get("fetched_at_epoch")
        if isinstance(fetched, (int, float)) and not isinstance(fetched, bool):
            samples.append(
                ("ghostship_ai_model_fact_fetched_timestamp_seconds", labels, float(fetched))
            )
        samples.append(
            (
                "ghostship_ai_model_fact_confidence",
                labels,
                float(fact.get("confidence") or 0.0),
            )
        )
    calculation = snapshot.get("calculation") or {}
    for component, body in calculation.items():
        if not isinstance(body, Mapping):
            continue
        if isinstance(body.get("formula"), str):
            samples.append(
                (
                    "ghostship_ai_calculation_component",
                    {
                        "component": str(component),
                        "formula": str(body["formula"])[:120],
                        "scope": str(body.get("scope") or ""),
                    },
                    1.0,
                )
            )
        weights = body.get("weights")
        if isinstance(weights, Mapping):
            for name, weight in weights.items():
                if isinstance(weight, (int, float)) and not isinstance(weight, bool):
                    samples.append(
                        (
                            "ghostship_ai_calculation_weight",
                            {"component": str(component), "weight": str(name)},
                            float(weight),
                        )
                    )
        # The transform of a calculated input, and the one in force. A
        # reader can tell which transform built the value it sees.
        transform = body.get("cost_transform")
        if isinstance(transform, str) and transform:
            samples.append(
                (
                    "ghostship_ai_calculation_transform",
                    {
                        "component": str(component),
                        "transform": transform,
                        "in_force": transform,
                    },
                    1.0,
                )
            )
        rule = body.get("rule")
        if isinstance(rule, str):
            samples.append(
                (
                    "ghostship_ai_calculation_gate",
                    {"gate": str(component), "rule": rule[:120]},
                    1.0,
                )
            )
    for name, description in (snapshot.get("calculation") or {}).get(
        "cost_transforms", {}
    ).items():
        samples.append(
            (
                "ghostship_ai_calculation_transform",
                {
                    "component": "cost_per_task",
                    "transform": str(name),
                    "in_force": str(
                        (snapshot.get("calculation") or {}).get(
                            "cost_transform_in_force", ""
                        )
                    ),
                    "formula": str(description)[:120],
                },
                1.0,
            )
        )
    # The owner's lists, published so a reader can filter on them instead of
    # repeating them in a query.
    policy = snapshot.get("policy") or {}
    for model in policy.get("frontier_prime_models") or ():
        samples.append(
            ("ghostship_ai_policy_frontier_workhorse", {"model": str(model)}, 1.0)
        )
    for model in policy.get("excluded_models") or ():
        samples.append(
            ("ghostship_ai_policy_excluded_model", {"model": str(model)}, 1.0)
        )
    for tier, winners in (snapshot.get("tier_winners") or {}).items():
        for position, winner in enumerate(winners, start=1):
            if not isinstance(winner, Mapping):
                continue
            labels = {
                "tier": str(tier),
                "provider": str(winner.get("provider") or ""),
                "model": str(winner.get("model") or ""),
            }
            samples.append(("ghostship_ai_model_winner", labels, 1.0))
            position_labels = {
                "tier": str(tier),
                "provider": labels["provider"],
                "model": labels["model"],
            }
            if str(tier) == "free":
                # The free tier is ordered by its quality band, and the band
                # is published with the position, so a reader sees which
                # routes are the band and which are the rest.
                position_labels["band"] = str(winner.get("band") or "false")
            samples.append(
                (
                    "ghostship_ai_model_winner_position",
                    position_labels,
                    float(position),
                )
            )
    return samples


def _json_safe(value: Any) -> Any:
    """The snapshot with every number that cannot be written turned into null.

    JSON has no NaN and no infinity, and a single one of them would make
    the whole snapshot unwritable. A value that cannot be written is not a
    measurement: it is published as null, and the gap stays visible.
    """
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, int):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def write_snapshot(path: str | os.PathLike[str], snapshot: Mapping[str, Any]) -> int:
    """Write the snapshot atomically, and return the bytes written.

    A failure is raised, never swallowed: the snapshot is the canonical
    answer for a consumer, and a collection that cannot write it must fail
    visibly instead of leaving the previous file in place without a word.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".new")
    payload = json.dumps(
        _json_safe(snapshot), indent=1, sort_keys=False, default=str, allow_nan=False
    )
    temporary.write_text(payload + "\n", encoding="utf-8")
    os.chmod(temporary, 0o644)
    os.replace(temporary, target)
    return len(payload) + 1


def publish(
    snapshot: Mapping[str, Any], paths: Iterable[str | os.PathLike[str]]
) -> list[tuple[str, int]]:
    """Publish the same bytes to every presentation of the snapshot.

    The canonical file and the runtime projections carry the same bytes: one
    producer, no second scorer, no history. Every write is atomic, and the
    projections are credential free. A projection that cannot be written is
    an error: a consumer would read the previous file and believe it.
    """
    payload = json.dumps(
        _json_safe(snapshot), indent=1, sort_keys=False, default=str, allow_nan=False
    )
    written: list[tuple[str, int]] = []
    for path in paths:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".new")
        temporary.write_text(payload + "\n", encoding="utf-8")
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
        written.append((str(target), len(payload) + 1))
    return written


def snapshot_age(path: str | os.PathLike[str]) -> float | None:
    """The age of the snapshot on disk, or None when it is not there."""
    try:
        return max(0.0, time.time() - os.stat(path).st_mtime)
    except OSError:
        return None
