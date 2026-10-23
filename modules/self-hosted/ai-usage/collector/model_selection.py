"""The model picker and dashboards share these two selection categories.

Native catalog membership is required for picker models. Quota availability is
read from the collector; no model-family reservation or CAD category applies.
"""
from __future__ import annotations

import math
import json
from pathlib import Path
from datetime import datetime

import value_policy
import outcomes as outcomes_module
import quota
import pools
from metrics import ExactLabel
from typing import Any, Mapping

CATEGORIES = ("orchestrator", "worker")
SCHEMA = "ghostship.model-selection/v1"
TRUST = {"trusted": 0, "backup": 1, "untrusted": 2, "excluded": 3}


def load_worker_builds(path: str) -> dict[str, str]:
    """Exact native build constraints are configuration, never identity aliases."""
    if not path:
        return {}
    try:
        document = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        raise ValueError('model selection preferences are unreadable') from None
    if not isinstance(document, dict) or document.get('schema') != 'ghostship.model-selection-preferences/v1':
        raise ValueError('model selection preferences have an unsupported schema')
    builds = document.get('worker_builds')
    if not isinstance(builds, dict) or any(
            not isinstance(provider, str) or not provider.strip() or not isinstance(model, str)
            or not model.strip() for provider, model in builds.items()):
        raise ValueError('model selection worker builds are invalid')
    return builds


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


def quality_value(row: Mapping[str, Any]) -> float | None:
    """Order by the posterior; the integer Quality score is display only."""
    prior = number(row.get('quality_p0'))
    if prior is not None:
        try:
            return value_policy.outcome_quality(prior, row.get('quality_n'), row.get('quality_s'))
        except (ValueError, TypeError):
            return None
    score = number(row.get('quality_score'))
    return None if score is None else score / 100


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
                 or (duration is not None and duration < 7 * 86400
                     and not any(token in kind for token in ("week", "month"))))
        long = (any(token in kind for token in ("week", "month", "quota", "credit"))
                or (duration is not None and duration >= 7 * 86400))
        if short or not long:
            continue
        remaining = number(window.get("remaining_ratio"))
        if remaining is None:
            continue
        seconds = number(window.get("seconds_to_reset"))
        expected = None
        if quota.is_paced_window(window) and duration is not None and duration > 0 and seconds is not None:
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

def ordered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The preference used by picker defaults, pools and dashboard ranks."""
    best = {}
    for row in rows:
        if row['available'] and row.get('selection_eligible', True) and row['quality_p'] is not None:
            level = row['trust_level']
            best[level] = max(best.get(level, 0), row['quality_p'])

    def rank(row):
        quality = row['quality_p']
        free = (row['billing'] in ('free', 'promotion') and quality is not None
                and quality >= best.get(row['trust_level'], 1) - value_policy.FREE_ROUTE_MARGIN)
        return (not row.get('selection_eligible', True), not row['available'], TRUST.get(row['trust_level'], 3),
                row['pace_state'] == 'far_behind', not free,
                -(quality if quality is not None else -1),
                -(row['pace_delta'] if row['pace_delta'] is not None else -2), row['key'])
    return sorted(rows, key=rank)


def build(snapshot: Mapping[str, Any], orchestrator: list[Mapping[str, Any]],
          *, evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Publish eligible sets and each provider's best available model.

    Each provider's selected available models are managed favorites. The owner picks
    a model per thread; the first available worker is only the new-thread
    default. Non-native inference routes remain outside the T3 picker.
    """
    orchestrator_ids = {(entry.get("instance_id"), entry.get("model")) for entry in orchestrator}
    categories: dict[str, list[dict[str, Any]]] = {name: [] for name in CATEGORIES}
    providers: dict[str, dict[str, Any]] = {}
    trust_cache = {}
    worker_builds = (((evidence or {}).get('policy') or {}).get('model_selection') or {}).get('worker_builds') or {}
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
        posterior = quality_value(source)
        limit = limiting_window(source.get("windows") or [], snapshot.get("generated_at"))
        required_build = worker_builds.get(str(source.get('provider') or ''))
        build_allowed = required_build is None or (mapped and model == required_build)
        row = {
            "key": str(source.get("provider")) + ":" + str(source.get("model")),
            "provider": str(source.get("provider")), "model": str(source.get("model")),
            "display_name": str(source.get("display_name") or source.get("model")),
            "native": ({"instanceId": str(instance), "model": str(model),
                        **({"options": options} if options else {})} if mapped else None),
            "effort": effort[0] if effort else None,
            "picker_eligible": mapped,
            "selection_eligible": build_allowed,
            "selection_reason": '' if build_allowed else 'configured worker build: ' + required_build,
            "billing": (source.get("access") or {}).get("billing") or "unknown",
            "quality_basis": source.get("quality_basis"),
            "quality_n": source.get("quality_n"), "quality_s": source.get("quality_s"),
            "available": available, "state": "excluded" if level == "excluded" else "exhausted" if exhausted else (
                "available" if available else "unavailable"),
            "reason": "model_excluded" if level == "excluded" else reason, "trust_level": level, "quality_score": quality,
            "quality_p": posterior,
            "remaining_ratio": remaining, "limiting_window": limit,
            "pace_delta": limit.get("pace_delta") if limit else None,
            "pace_state": limit.get("pace_state") if limit else "unknown",
            "pool": source.get("pool") or pools.record(str(source.get("provider") or ""),
                str(source.get("model") or ""), (source.get("access") or {}).get("billing") or ""),
        }
        # Orchestrator models can also be workers; the categories describe use,
        # not reservations. No review subscription is withheld from the owner.
        categories["worker"].append(row)
        if mapped and (instance, model) in orchestrator_ids:
            review_effort = effort_options(descriptors, preferred='medium')
            review_options = native_options(descriptors, preferred='medium')
            review_native = {'instanceId': str(instance), 'model': str(model),
                             **({'options': review_options} if review_options else {})}
            categories["orchestrator"].append({**row, 'selection_eligible': True, 'selection_reason': '', 'native': review_native,
                                               'effort': review_effort[0] if review_effort else None})
    for category, rows in categories.items():
        rows[:] = ordered(rows)
        native_providers, native_pools = {}, {}
        for index, row in enumerate(rows, 1):
            row["position"] = index
            provider = providers.setdefault(row["provider"], {
                "orchestrator": [], "worker": [], "selected": {"orchestrator": None, "worker": None}, 'pools': {}})
            provider[category].append(row)
            row['provider_position'] = len(provider[category])
            pool = row.get('pool') or {}
            pool_id = str(pool.get('id') or row['provider'] + ':unknown')
            group = provider['pools'].setdefault(pool_id, {'id': pool_id, 'label': pool.get('label'),
                'parent': pool.get('parent'), 'basis': pool.get('basis') or 'unknown',
                'orchestrator': [], 'worker': [], 'selected': {'orchestrator': None, 'worker': None}})
            group[category].append(row)
            row['pool_position'] = len(group[category])
            if row['picker_eligible']:
                native_providers[row['provider']] = native_providers.get(row['provider'], 0) + 1
                native_pools[pool_id] = native_pools.get(pool_id, 0) + 1
                row['picker_provider_position'] = native_providers[row['provider']]
                row['picker_pool_position'] = native_pools[pool_id]
            if row['available'] and row['selection_eligible'] and group['selected'][category] is None:
                group['selected'][category] = row['native']
            if row["available"] and row["selection_eligible"] and provider["selected"][category] is None:
                provider["selected"][category] = row["native"]
    return {"schema": SCHEMA, "generated_at": snapshot.get("generated_at"),
            "partial": bool(snapshot.get("partial", False)),
            "max_age_seconds": snapshot.get("max_age_seconds", 900),
            "providers": providers, "worker_builds": dict(worker_builds), **categories,
            "default_worker": next((row["native"] for row in categories["worker"]
                                    if row["available"] and row["picker_eligible"] and row["selection_eligible"]), None)}


def samples(selection: Mapping[str, Any]) -> list[tuple[str, dict[str, str], float]]:
    """Project canonical choices without re-ranking or inventing readings."""
    values = []
    for category in CATEGORIES:
        for row in selection.get(category) or []:
            pool = row.get('pool') or {}
            limit = row.get('limiting_window') or {}
            effort = row.get('effort') or {}
            labels = {'category': category, 'provider': row['provider'], 'model': ExactLabel(row['model']),
                      'display_name': ExactLabel(row['display_name']), 'state': row['state'],
                      'picker_eligible': 'true' if row['picker_eligible'] else 'false',
                      'trust': row['trust_level'], 'pool': ExactLabel(str(pool.get('id') or '')),
                      'pool_label': ExactLabel(str(pool.get('label') or 'Unknown pool')),
                      'billing': row.get('billing') or 'unknown',
                      'reason': ExactLabel(str(row.get('reason') or '')),
                      'window': str(limit.get('kind') or ''),
                      'quota_id': str(limit.get('quota_id') or ''),
                      'pace_state': str(limit.get('pace_state') or 'unknown'),
                      'reset_source': str(limit.get('reset_source') or 'provider'),
                      'effort': str(effort.get('value') or ''),
                      'quality_basis': ExactLabel(str(row.get('quality_basis') or 'unknown'))}
            numbers = {'info': 1.0, 'position': row['position'],
                       'provider_position': row.get('picker_provider_position', row.get('provider_position')),
                       'pool_position': row.get('picker_pool_position', row.get('pool_position')),
                       'quality': row.get('quality_score'),
                       'default': float(category == 'worker' and row.get('native') is not None
                                        and row.get('native') == selection.get('default_worker')),
                       'quality_rounds': row.get('quality_n'),
                       'quality_accepted': row.get('quality_s'),
                       'remaining_ratio': limit.get('remaining_ratio'),
                       'pace_delta': limit.get('pace_delta')}
            if limit.get('reset_at'):
                try:
                    numbers['reset_timestamp_seconds'] = datetime.fromisoformat(
                        str(limit['reset_at']).replace('Z', '+00:00')).timestamp()
                except (ValueError, OverflowError):
                    pass
            for field, value in numbers.items():
                finite = number(value)
                if finite is not None:
                    values.append(('ghostship_ai_picker_model_' + field, dict(labels), finite))
    return values
