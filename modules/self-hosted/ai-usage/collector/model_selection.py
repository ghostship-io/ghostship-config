"""The model picker and dashboards share these two selection categories.

Native catalog membership is required for picker models. Quota availability is
read from the collector; no model-family reservation or CAD category applies.
"""
from __future__ import annotations

import math
from datetime import datetime

import value_policy
import outcomes as outcomes_module
from metrics import ExactLabel
from typing import Any, Mapping

CATEGORIES = ("orchestrator", "worker")
SCHEMA = "ghostship.model-selection/v1"
TRUST = {"trusted": 0, "backup": 1, "untrusted": 2, "excluded": 3}


def policy_ready(evidence: Mapping[str, Any]) -> bool:
    policy = evidence.get('policy') or {}
    declared = {record.get('id') for record in evidence.get('identities') or []
                if isinstance(record, Mapping)}
    exclusions = {entry.get('model') for entry in (policy.get('model_trust') or {}).get('entries') or []
                  if entry.get('level') == 'excluded'}
    return (bool(declared) and exclusions <= declared
            and (policy.get('model_selection') or {}).get('categories') == list(CATEGORIES)
            and bool((policy.get('roles') or {}).get('orchestrator')))


def number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _trust(row: Mapping[str, Any]) -> str:
    records = row.get("trust") or {}
    levels = [str(record.get("level") or "trusted") for record in records.values()
              if isinstance(record, Mapping)]
    return max(levels or ["trusted"], key=lambda level: TRUST.get(level, 3))


def limiting_window(windows: list[Mapping[str, Any]], generated_at: str | None) -> dict[str, Any] | None:
    """Display a long or quota limit; short windows only gate availability."""
    try:
        datetime.fromisoformat(str(generated_at).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
    eligible = []
    for window in windows:
        kind = str(window.get("kind") or "").lower()
        duration = number(window.get("duration_seconds"))
        short = (any(token in kind for token in ("session", "hour", "daily", "minute"))
                 or (kind == "inferred" and duration is not None and duration < 7 * 86400))
        long = (any(token in kind for token in ("week", "month", "quota", "credit"))
                or (duration is not None and duration >= 7 * 86400))
        if short or not long:
            continue
        remaining = number(window.get("remaining_ratio"))
        if remaining is None:
            continue
        seconds = number(window.get("seconds_to_reset"))
        expected = None
        if duration is not None and duration >= 7 * 86400 and seconds is not None:
            expected = min(1.0, max(0.0, seconds / duration))
        delta = None if expected is None else round(100 * (remaining - expected), 6)
        eligible.append({"kind": kind, "quota_id": window.get("quota_id"),
                         "remaining_ratio": remaining, "reset_at": window.get("reset_at"),
                         "seconds_to_reset": seconds, "expected_remaining_ratio": expected,
                         "pace_delta": delta,
                         "pace_state": value_policy.pace_state(remaining, expected),
                         "source": window.get("source"), "evidence": window.get("evidence")})
        eligible[-1].update({name: window.get(name) for name in
                            ('reset_source', 'reset_label', 'provider_reset_at')})
    return min(eligible, key=lambda window: (window["remaining_ratio"],
                                            str(window.get("quota_id") or ""))) if eligible else None



def effort_options(descriptors: list[Mapping[str, Any]], preferred: str = "high") -> list[dict[str, Any]]:
    """Use the role default when offered, otherwise a published native level."""
    levels = {'none': 0, 'minimal': 1, 'low': 2, 'medium': 3, 'thinking': 3,
              'high': 4, 'xhigh': 5, 'max': 6, 'ultra': 7}
    for option in descriptors:
        name = str(option.get('id') or '')
        if name.lower() not in ('reasoningeffort', 'effort', 'variant', 'thinking'):
            continue
        if name.lower() == 'thinking' and option.get('type') == 'boolean':
            return [{'id': name, 'value': True}]
        choices = option.get('values') or []
        usable = [value for value in choices if isinstance(value, str) and value.lower() in levels]
        if usable:
            wanted = levels[preferred]
            higher = [value for value in usable if levels[value.lower()] >= wanted]
            chosen = min(higher, key=lambda value: levels[value.lower()]) if higher else max(
                usable, key=lambda value: levels[value.lower()])
            return [{'id': name, 'value': chosen}]
    return []


def native_options(descriptors: list[Mapping[str, Any]], preferred: str = 'high') -> list[dict[str, Any]]:
    options = effort_options(descriptors, preferred)
    for descriptor in descriptors:
        if descriptor.get('id') == 'fastMode' and descriptor.get('type') == 'boolean':
            options.append({'id': 'fastMode', 'value': False})
        if descriptor.get('id') == 'serviceTier' and 'standard' in (descriptor.get('values') or []):
            options.append({'id': 'serviceTier', 'value': 'standard'})
    return options

def build(snapshot: Mapping[str, Any], orchestrator: list[Mapping[str, Any]],
          *, evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Publish eligible sets and each provider's best available model.

    Every available member of the sets is a managed favorite. The owner picks
    a model per thread; the first available worker is only the new-thread
    default. Non-native inference routes remain outside the T3 picker.
    """
    orchestrator_ids = {(entry.get("instance_id"), entry.get("model")) for entry in orchestrator}
    categories: dict[str, list[dict[str, Any]]] = {name: [] for name in CATEGORIES}
    providers: dict[str, dict[str, Any]] = {}
    trust_cache = {}
    for source in snapshot.get("candidates") or []:
        native = source.get("native") or {}
        instance, model = native.get("provider_instance_id"), native.get("model_id")
        mapped = bool(native.get("mapped") and instance and model)
        descriptors = native.get("options") or []
        effort = effort_options(descriptors) if mapped else []
        options = native_options(descriptors) if mapped else []
        level = _trust(source)
        if evidence is not None:
            identity = outcomes_module.identity_of(str(source.get('provider') or ''),
                                                   str(source.get('model') or ''), evidence.get('identities'))
            if identity not in trust_cache:
                trust_cache[identity] = outcomes_module.trust_for(
                    identity, 'implementation', evidence.get('policy'), evidence.get('rounds'),
                    evidence.get('backfill'), evidence.get('identities'))
            level = trust_cache[identity]['level']
        capacity = source.get("capacity") or {}
        remaining = number(capacity.get("remaining_ratio"))
        exhausted = source.get("quota_state") == "exhausted" or remaining == 0
        available = (bool(source.get("available")) and not exhausted and level != "excluded"
                     and (not mapped or native.get("available") is not False))
        reason = "quota_exhausted" if exhausted else str(
            (source.get("availability") or {}).get("reason") or "")
        quality = number(source.get("quality_score"))
        limit = limiting_window(source.get("windows") or [], snapshot.get("generated_at"))
        row = {
            "key": str(source.get("provider")) + ":" + str(source.get("model")),
            "provider": str(source.get("provider")), "model": str(source.get("model")),
            "display_name": str(source.get("display_name") or source.get("model")),
            "native": ({"instanceId": str(instance), "model": str(model),
                        **({"options": options} if options else {})} if mapped else None),
            "effort": effort[0] if effort else None,
            "picker_eligible": mapped,
            "billing": (source.get("access") or {}).get("billing") or "unknown",
            "quality_basis": source.get("quality_basis"),
            "quality_n": source.get("quality_n"), "quality_s": source.get("quality_s"),
            "available": available, "state": "excluded" if level == "excluded" else "exhausted" if exhausted else (
                "available" if available else "unavailable"),
            "reason": "model_excluded" if level == "excluded" else reason, "trust_level": level, "quality_score": quality,
            "remaining_ratio": remaining, "limiting_window": limit,
            "pace_delta": limit.get("pace_delta") if limit else None,
            "pace_state": limit.get("pace_state") if limit else "unknown",
            "pool": source.get("pool"),
        }
        # Orchestrator models can also be workers; the categories describe use,
        # not reservations. No review subscription is withheld from the owner.
        categories["worker"].append(row)
        if mapped and (instance, model) in orchestrator_ids:
            review_effort = effort_options(descriptors, preferred='medium')
            review_options = native_options(descriptors, preferred='medium')
            review_native = {'instanceId': str(instance), 'model': str(model),
                             **({'options': review_options} if review_options else {})}
            categories["orchestrator"].append({**row, 'native': review_native,
                                               'effort': review_effort[0] if review_effort else None})
    def order(row: Mapping[str, Any]) -> tuple:
        return (not row["available"], TRUST.get(row["trust_level"], 3),
                row["pace_state"] == "far_behind",
                -(row["quality_score"] if row["quality_score"] is not None else -1),
                -(row["pace_delta"] if row["pace_delta"] is not None else -2), row["key"])
    for category, rows in categories.items():
        # Free routes close to the best quality lead within their trust group.
        best = {}
        for row in rows:
            if row["available"] and row["quality_score"] is not None:
                best[row["trust_level"]] = max(best.get(row["trust_level"], 0), row["quality_score"])
        def rank(row):
            baseline = order(row)
            free = (row["billing"] in ("free", "promotion") and row["quality_score"] is not None
                    and row["quality_score"] >= best.get(row["trust_level"], 100) - 10)
            return (*baseline[:3], not free, *baseline[3:])
        rows.sort(key=rank)
        for index, row in enumerate(rows, 1):
            row["position"] = index
            provider = providers.setdefault(row["provider"], {
                "orchestrator": [], "worker": [], "selected": {"orchestrator": None, "worker": None}})
            provider[category].append(row)
            if row["available"] and provider["selected"][category] is None:
                provider["selected"][category] = row["native"]
    return {"schema": SCHEMA, "generated_at": snapshot.get("generated_at"),
            "partial": bool(snapshot.get("partial", False)),
            "max_age_seconds": snapshot.get("max_age_seconds", 900),
            "providers": providers, **categories,
            "default_worker": next((row["native"] for row in categories["worker"]
                                    if row["available"] and row["picker_eligible"]), None)}


def samples(selection: Mapping[str, Any]) -> list[tuple[str, dict[str, str], float]]:
    values = []
    for category in CATEGORIES:
        for row in selection.get(category) or []:
            labels = {"category": category, "provider": row["provider"], "model": row["model"],
                      "display_name": ExactLabel(row["display_name"]), "state": row["state"],
                      "picker_eligible": "true" if row["picker_eligible"] else "false",
                      "trust": row["trust_level"]}
            values.append(("ghostship_ai_picker_model_info", labels, 1.0))
            values.append(("ghostship_ai_picker_model_position", labels, float(row["position"])))
            if row.get("quality_score") is not None:
                values.append(("ghostship_ai_picker_model_quality", labels, row["quality_score"]))
    return values
