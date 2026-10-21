"""The durable facts of a model.

A fact is an objective statement about one exact model, with the evidence
that produced it. The facts are kept in the state the producer already owns,
so a model is researched once and the result is reused: the research is redone
only when the identity or the reasoning variant changes, when the benchmark
version or the evidence changes, or when an input goes stale.

Every fact says what kind of statement it is:

* `measured` - the value came from a source that measured it. The source, the
  version, the time of the read, and a fingerprint of the evidence are kept.
* `estimated` - the value is a bounded estimate, for a model that no public
  feed lists. An estimate never claims to be a measurement, and it names the
  basis it came from.

The facts are keyed by the exact model and its reasoning variant, because a
model and its reasoning variant are not the same model.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Iterable, Mapping

# How long a fact stays valid. The benchmark indices move slowly, and a fact
# that is a month old is rechecked rather than researched again.
FACT_MAX_AGE_SECONDS = 30 * 24 * 3600.0

# The benchmark version this producer understands. A feed of another version
# invalidates the facts that came from it.
BENCHMARK_VERSION = "4.3"

# The confidence of an estimate, and the ceiling of its use. An estimate is
# only a tie breaker, never the reason a model wins on its own. The confidence
# is a share (0..1) and the strength is on the same scale as a measured index
# (0..100): the two are not the same number and are never mixed.
ESTIMATE_CONFIDENCE = 0.4
ESTIMATE_CEILING = 0.7
STRENGTH_MIN = 0.0
STRENGTH_MAX = 100.0

FACT_FIELDS = (
    "model",
    "variant",
    "canonical_identity",
    "aliases",
    "provider",
    "native_bindings",
    "benchmark_id",
    "brief_url",
    "benchmark_version",
    "fetched_at",
    "evidence_fingerprint",
    "indices",
    "cost_per_task",
    "token_prices",
    "throughput",
    "released_at",
    "capabilities",
    "complexity_eligibility",
    "source",
    "confidence",
    "basis",
    "pending_reason",
    "next_check_at",
    "status",
)


def fingerprint(document: Any) -> str:
    """A stable fingerprint of the evidence a fact came from."""
    payload = json.dumps(document, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def identity_key(provider: str, model: str, variant: str = "") -> str:
    """The key of a fact: the exact model and its reasoning variant."""
    return f"{provider}:{model}" + (f"#{variant}" if variant else "")


def make_fact(
    *,
    provider: str,
    model: str,
    variant: str = "",
    canonical_identity: str = "",
    aliases: Iterable[str] = (),
    native_bindings: Mapping[str, Any] | None = None,
    benchmark_id: str = "",
    brief_url: str = "",
    benchmark_version: str = BENCHMARK_VERSION,
    indices: Mapping[str, Any] | None = None,
    cost_per_task: float | None = None,
    token_prices: Mapping[str, Any] | None = None,
    throughput: Mapping[str, Any] | None = None,
    released_at: str = "",
    capabilities: Mapping[str, Any] | None = None,
    complexity_eligibility: str = "low",
    source: str = "measured",
    confidence: float = 1.0,
    basis: str = "",
    now: float | None = None,
) -> dict[str, Any]:
    """Build one fact, with its evidence fingerprint."""
    moment = time.time() if now is None else now
    evidence = {
        "benchmark_id": benchmark_id,
        "brief_url": brief_url,
        "benchmark_version": benchmark_version,
        "indices": dict(indices or {}),
        "cost_per_task": cost_per_task,
        "token_prices": dict(token_prices or {}),
        "throughput": dict(throughput or {}),
        "released_at": released_at,
    }
    return {
        "model": model,
        "variant": variant,
        "canonical_identity": canonical_identity or model,
        "aliases": sorted({str(alias) for alias in aliases if alias}),
        "provider": provider,
        "native_bindings": dict(native_bindings or {}),
        "benchmark_id": benchmark_id,
        "brief_url": brief_url,
        "benchmark_version": benchmark_version,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(moment)),
        "fetched_at_epoch": moment,
        "evidence_fingerprint": fingerprint(evidence),
        "indices": dict(indices or {}),
        "cost_per_task": cost_per_task,
        "token_prices": dict(token_prices or {}),
        "throughput": dict(throughput or {}),
        "released_at": released_at,
        "capabilities": dict(capabilities or {}),
        "complexity_eligibility": complexity_eligibility,
        "source": source,
        "confidence": round(float(confidence), 3),
        "basis": basis,
        "pending_reason": "",
        "next_check_at": None,
        "status": "current",
    }


def estimated_fact(
    *,
    provider: str,
    model: str,
    variant: str = "",
    strength: float,
    basis: str,
    confidence: float = ESTIMATE_CONFIDENCE,
    now: float | None = None,
) -> dict[str, Any]:
    """A bounded estimate for a model no public feed lists.

    A model that is not listed may still be used, but only with a clearly
    estimated strength, and the estimate never claims to be a measurement.
    The strength is on the 0..100 scale of a measured index, the confidence is
    a 0..1 share, and a value outside its range is rejected instead of being
    clamped into a quality claim.
    """
    number = _finite(strength)
    if number is None or not (STRENGTH_MIN <= number <= STRENGTH_MAX):
        raise ValueError("an estimate needs a finite strength between 0 and 100")
    share = _finite(confidence)
    if share is None or not (0.0 < share <= ESTIMATE_CEILING):
        raise ValueError(
            "an estimate needs a finite confidence above 0 and at most the ceiling"
        )
    fact = make_fact(
        provider=provider,
        model=model,
        variant=variant,
        indices={"intelligence_index": number},
        source="estimated",
        confidence=share,
        basis=basis,
        complexity_eligibility="low",
        now=now,
    )
    fact["status"] = "estimated"
    fact["estimate_ceiling"] = ESTIMATE_CEILING
    fact["strength_scale"] = {"min": STRENGTH_MIN, "max": STRENGTH_MAX}
    return fact


def pending_fact(
    *,
    provider: str,
    model: str,
    variant: str = "",
    reason: str,
    next_check_at: float | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """A model whose research is expected but not available yet."""
    fact = make_fact(
        provider=provider,
        model=model,
        variant=variant,
        source="pending",
        confidence=0.0,
        basis="the research is expected and not available yet",
        now=now,
    )
    fact["status"] = "pending"
    fact["pending_reason"] = reason
    fact["next_check_at"] = next_check_at
    return fact


def _finite(value: Any) -> float | None:
    """A finite float, or None. A NaN or an infinity is not a number here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def evidence_age(fact: Mapping[str, Any], now: float) -> float | None:
    """The age of the evidence of a fact, or None when it cannot be aged.

    The age must be finite and not negative: a reading from the future is not
    an old reading, it is a reading that cannot be believed.
    """
    fetched = _finite(fact.get("fetched_at_epoch"))
    moment = _finite(now)
    if fetched is None or moment is None:
        return None
    age = moment - fetched
    if age < 0:
        return None
    return age


def is_current(fact: Mapping[str, Any], now: float) -> bool:
    """True when a fact may be reused without another research."""
    if not isinstance(fact, Mapping):
        return False
    if fact.get("status") not in ("current", "estimated"):
        return False
    if str(fact.get("benchmark_version") or "") != BENCHMARK_VERSION:
        return False
    age = evidence_age(fact, now)
    if age is None:
        return False
    return age <= FACT_MAX_AGE_SECONDS


def needs_research(
    fact: Mapping[str, Any] | None, identity: str, now: float
) -> tuple[bool, str]:
    """Whether a model has to be researched again, and why.

    A pending fact waits for the moment it says it is checked again: the
    research is not repeated before it, so a model whose brief is expected is
    not researched again and again.
    """
    if not isinstance(fact, Mapping) or not fact:
        return True, "no fact yet"
    fact_key = identity_key(
        str(fact.get("provider") or ""),
        str(fact.get("model") or ""),
        str(fact.get("variant") or ""),
    )
    if fact_key != identity:
        return True, "the canonical identity changed"
    if str(fact.get("benchmark_version") or "") != BENCHMARK_VERSION:
        return True, "the benchmark version changed"
    if fact.get("status") == "pending":
        next_check = _finite(fact.get("next_check_at"))
        if next_check is not None and now < next_check:
            return False, "the pending fact is checked again later"
        return True, str(fact.get("pending_reason") or "the research is pending")
    if not is_current(fact, now):
        return True, "the fact went stale"
    return False, ""


def merge(state: Mapping[str, Any], facts: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Merge facts into the state, keeping the newest per identity."""
    merged = dict(state.get("facts") or {})
    for fact in facts:
        if not isinstance(fact, Mapping):
            continue
        key = identity_key(
            str(fact.get("provider") or ""),
            str(fact.get("model") or ""),
            str(fact.get("variant") or ""),
        )
        current = merged.get(key)
        if not isinstance(current, Mapping):
            merged[key] = dict(fact)
            continue
        current_fingerprint = str(current.get("evidence_fingerprint") or "")
        new_fingerprint = str(fact.get("evidence_fingerprint") or "")
        current_time = _finite(current.get("fetched_at_epoch"))
        new_time = _finite(fact.get("fetched_at_epoch"))
        newer = (
            current_time is None
            or (new_time is not None and new_time >= current_time)
        )
        changed = new_fingerprint and new_fingerprint != current_fingerprint
        # A fresh measurement of the same evidence still refreshes the read
        # time of a record that went stale.
        if changed or newer:
            merged[key] = dict(fact)
    return merged


def index(facts: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The facts by their identity: provider, model, and reasoning variant.

    The model name alone is not an identity: two providers can serve the same
    name, and a model and its reasoning variant are different models.
    """
    result: dict[str, dict[str, Any]] = {}
    for key, fact in (facts or {}).items():
        if not isinstance(fact, Mapping):
            continue
        identity = identity_key(
            str(fact.get("provider") or ""),
            str(fact.get("model") or ""),
            str(fact.get("variant") or ""),
        )
        result[identity or str(key)] = dict(fact)
    return result


def lookup_by_model(
    facts: Mapping[str, Any], provider: str, model: str, variant: str = ""
) -> dict[str, Any] | None:
    """The fact of one exact model, or None when there is none."""
    for key, fact in (facts or {}).items():
        if not isinstance(fact, Mapping):
            continue
        if (
            str(fact.get("provider") or "") == str(provider)
            and str(fact.get("model") or "") == str(model)
            and str(fact.get("variant") or "") == str(variant)
        ):
            return dict(fact)
        if str(key) == identity_key(provider, model, variant):
            return dict(fact)
    return None
