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
import limit_models
import model_quality
import outcomes as outcomes_module
import quota
import pools
import ranking
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


def apply_worker_builds(policy: dict[str, Any], preferences: Mapping[str, str]) -> None:
    """Host build choices augment, never erase or widen, runtime policy."""
    selection = policy.setdefault('model_selection', {})
    declared = selection.setdefault('worker_builds', {})
    if any(provider in declared and declared[provider] != model
           for provider, model in preferences.items()):
        raise ValueError('worker build preference conflicts with runtime policy')
    declared.update(preferences)


def policy_ready(evidence: Mapping[str, Any]) -> bool:
    policy = evidence.get('policy') or {}
    declared = {record.get('id') for record in evidence.get('identities') or []
                if isinstance(record, Mapping)}
    exclusions = {entry.get('model') for entry in (policy.get('model_trust') or {}).get('entries') or []
                  if entry.get('level') == 'excluded'}
    roles = (policy.get('model_selection') or {}).get('provider_roles', {})
    if not isinstance(roles, Mapping) or any(
            not isinstance(provider, str) or not provider or not isinstance(categories, list)
            or not categories or any(category not in CATEGORIES for category in categories)
            for provider, categories in roles.items()):
        return False
    excluded_pools = (policy.get('model_selection') or {}).get('excluded_pools', [])
    if (not isinstance(excluded_pools, list) or
            any(not isinstance(pool, str) or not pool for pool in excluded_pools)):
        return False
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


APPROVED_FREE_SCHEMA = "ghostship.approved-free-workers/v1"
SENSITIVITIES = ("public", "internal", "sensitive")


def load_approved_free_workers(path: str) -> list[dict[str, Any]]:
    """Load the owner's explicit free-worker approvals.

    The file is configuration, not a rule: every route is named by provider and
    model, and a malformed or unknown-schema file is an error rather than an
    empty approval set.
    """
    if not path:
        return []
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("approved free workers are unreadable") from None
    if not isinstance(document, dict) or document.get("schema") != APPROVED_FREE_SCHEMA:
        raise ValueError("approved free workers have an unsupported schema")
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise ValueError("approved free workers have no entries")
    approved = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("approved free worker is not an object")
        provider = str(entry.get("provider") or "").strip()
        model = str(entry.get("model") or "").strip()
        sensitivity = entry.get("sensitivity")
        if (not provider or not model or not isinstance(entry.get("allow_training"), bool)
                or not isinstance(sensitivity, list)
                or any(value not in SENSITIVITIES for value in sensitivity)):
            raise ValueError("approved free worker is invalid")
        key = (provider, model)
        if key in seen:
            continue
        seen.add(key)
        approved.append({
            "provider": provider,
            "model": model,
            "allow_training": bool(entry.get("allow_training")),
            "sensitivity": list(sensitivity),
            "approved_at": entry.get("approved_at"),
            "source": str(entry.get("source") or document.get("approval_source") or ""),
            "note": str(entry.get("note") or ""),
        })
    return approved


def apply_approved_free_workers(policy: dict[str, Any], entries: list[dict[str, Any]]) -> None:
    """Merge the explicit approvals into the runtime policy, never widening it."""
    selection = policy.setdefault("model_selection", {})
    declared = selection.setdefault("approved_free_workers", [])
    if not isinstance(declared, list):
        raise ValueError("runtime policy approved free workers are invalid")
    keys = {(entry.get("provider"), entry.get("model")) for entry in declared
            if isinstance(entry, dict)}
    for entry in entries:
        if (entry["provider"], entry["model"]) not in keys:
            declared.append(entry)
            keys.add((entry["provider"], entry["model"]))


def _approved_free(policy: Mapping[str, Any] | None, provider: str, model: str) -> dict[str, Any] | None:
    """The owner's approval for a free route, or None.

    The list lives in the runtime policy and is empty until the owner adds an
    entry. Nothing here invents an approval: a route not named by the owner
    never becomes a first-choice worker, whatever its quality.
    """
    entries = (policy or {}).get("approved_free_workers") if isinstance(policy, Mapping) else None
    if isinstance(entries, Mapping):
        entries = [entries]
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        if str(entry.get("provider") or "") != provider:
            continue
        wanted = str(entry.get("model") or "")
        if wanted not in ("*", model):
            continue
        sensitivity = entry.get("sensitivity")
        return {
            "source": str(entry.get("source") or entry.get("approval_source")
                          or "owner runtime policy: approved_free_workers"),
            "sensitivity": list(sensitivity) if isinstance(sensitivity, list) else ["public", "internal", "sensitive"],
            "allow_training": bool(entry.get("allow_training")),
            "approved_at": entry.get("approved_at"),
            "note": str(entry.get("note") or ""),
        }
    return None


def _data_policy(allowance_record: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The training/retention policy of an allowance-billed route.

    It is read from the provider's own dated table. A table that does not
    state the policy leaves ``sensitive_ok`` unknown, which never becomes a
    yes or a no.
    """
    if not isinstance(allowance_record, Mapping):
        return None
    sensitive = allowance_record.get("sensitive_ok")
    return {
        "training": allowance_record.get("training"),
        "retention": allowance_record.get("retention"),
        "retention_text": allowance_record.get("retention_text"),
        "sensitive_ok": sensitive if isinstance(sensitive, bool) else None,
        "basis": allowance_record.get("basis"),
        "source": allowance_record.get("source"),
        "checked_at": allowance_record.get("checked_at"),
        "stale": bool(allowance_record.get("stale")),
    }


def quality_value(row: Mapping[str, Any]) -> float | None:
    """Use canonical AA/observed quality; tolerate older snapshots in readers."""
    if 'quality_evidence' in row:
        measured = model_quality.choose(row, effort_options((row.get('native') or {}).get('options') or []))
        score = number((measured or {}).get('overall'))
        return None if score is None else score / 100
    prior = number(row.get('quality_p0'))
    if prior is not None:
        try:
            return value_policy.outcome_quality(prior, row.get('quality_n'), row.get('quality_s'))
        except (ValueError, TypeError):
            return None
    score = number(row.get('quality_score'))
    return None if score is None else score / 100


def _snapshot_epoch(snapshot: Mapping[str, Any]) -> float:
    try:
        return datetime.fromisoformat(str(snapshot.get("generated_at")).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def limiting_window(windows: list[Mapping[str, Any]], generated_at: str | None) -> dict[str, Any] | None:
    """Display the actual binding window, including short unpaced windows."""
    try:
        datetime.fromisoformat(str(generated_at).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
    eligible = []
    for window in windows:
        kind = str(window.get("kind") or "").lower()
        duration = number(window.get("duration_seconds"))
        if window.get('not_used'):
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
                         "pace_state": (value_policy.pace_state(remaining, expected) if quota.is_paced_window(window)
                                        else 'spent' if remaining <= 0 else 'on_pace'),
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
                and bool(row.get('approved_free'))
                and quality >= best.get(row['trust_level'], 1) - value_policy.FREE_ROUTE_MARGIN)
        # An allowance-billed route is ordered by its weighted quality and
        # affordable allowance; a route without an allowance keeps the quality
        # order. Both terms are on the same 0..1 scale, so they compare.
        combined = (row.get('pick_score') or {}).get('score')
        if combined is None:
            combined = quality
        # An owner-approved free route is a first-choice worker while it has
        # limit left; an overspent (far_behind) route moves behind every route
        # that is not, so the picker falls back to paid instead of spending a
        # limit that is already consumed faster than its window.
        approved_active = bool(row.get('approved_free')) and row['available'] and not row.get('overspent')
        # A free route the owner did not approve never takes a paid route's
        # place for internal work, whatever its score.
        unapproved_free = row['billing'] in ('free', 'promotion') and not row.get('approved_free')
        return (not row.get('selection_eligible', True), not row['available'], TRUST.get(row['trust_level'], 3),
                not approved_active, unapproved_free,
                row.get('ranking_pace_state', row['pace_state']) == 'far_behind', not free,
                -(combined if combined is not None else -1),
                -(quality if quality is not None else -1),
                -(row['pace_delta'] if row['pace_delta'] is not None else -2), row['key'])
    return sorted(rows, key=rank)


def worker_cost_allowed(source: Mapping[str, Any], candidates: list[Mapping[str, Any]]) -> bool:
    if (source.get('access') or {}).get('billing') in ('free','promotion'):
        return True
    reference = next((row for row in candidates if row.get('provider') == 'codex'
                      and row.get('model') == 'gpt-6.1-sol'), {})
    price, cap = source.get('price') or {}, reference.get('price') or {}
    fields = ['input','output'] + [field for field in ('cache_read','cache_write') if price.get(field) is not None]
    return all(number(price.get(field)) is not None and number(cap.get(field)) is not None
               and 0 <= price[field] <= cap[field] for field in fields)


def applicable_windows(snapshot: Mapping[str, Any], source: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Untiered native models still inherit their reported account/family caps."""
    windows = [window for window in source.get('windows') or [] if not window.get('not_used')]
    try:
        now = datetime.fromisoformat(str(snapshot.get('generated_at')).replace('Z','+00:00')).timestamp()
    except ValueError:
        return windows
    for window in ((snapshot.get('quota') or {}).get('accounts') or {}).get(source['provider']) or []:
        if window.get('not_used') or not ranking._window_applies(window,source['model']):
            continue
        try:
            checked = datetime.fromisoformat(str(window.get('check_at')).replace('Z','+00:00')).timestamp()
            reset = (datetime.fromisoformat(str(window['reset_at']).replace('Z','+00:00')).timestamp()
                     if window.get('reset_at') else None)
        except ValueError:
            continue
        timed_denial = (window.get('basis') == 'provider_limit_message'
                        and window.get('remaining_ratio') == 0 and reset is not None and reset > now)
        if ((timed_denial or now - quota.STALE_AFTER_SECONDS <= checked)
                and checked <= now + quota.FUTURE_TOLERANCE_SECONDS
                and (reset is None or reset > now) and window not in windows):
            windows.append(window)
    return windows


def worker_pool_guard(snapshot: Mapping[str, Any], provider: str,
                      policy: Mapping[str, Any]) -> dict[str, Any] | None:
    """A worker can spend only the shared headroom above the review reserve."""
    unknown = {'allowed': False, 'state': 'unknown',
               'reason': 'current shared weekly review headroom is unknown'}
    guards = policy.get('worker_pool_guards') or {}
    if not isinstance(guards, Mapping):
        return unknown
    rule = guards.get(provider)
    if rule is None:
        return unknown if provider == 'claude' else None
    if not isinstance(rule, Mapping):
        return unknown
    reserve = number(rule.get('minimum_remaining_ratio'))
    if (rule.get('kind') != 'weekly' or reserve is None or not 0 <= reserve <= 1
            or rule.get('require_pace_headroom') is not True):
        return unknown
    try:
        now = datetime.fromisoformat(str(snapshot.get('generated_at')).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return unknown
    readings = []
    for window in ((snapshot.get('quota') or {}).get('accounts') or {}).get(provider) or []:
        # This is the shared account window, never Fable's unused allowance,
        # a per-model sublimit, or the unpaced five-hour window.
        if (window.get('kind') != 'weekly' or window.get('not_used') or window.get('applies_to')):
            continue
        remaining, duration = number(window.get('remaining_ratio')), number(window.get('duration_seconds'))
        try:
            checked = datetime.fromisoformat(str(window.get('check_at')).replace('Z', '+00:00')).timestamp()
            reset = datetime.fromisoformat(str(window.get('reset_at')).replace('Z', '+00:00')).timestamp()
        except ValueError:
            continue
        if (remaining is None or not 0 <= remaining <= 1 or duration is None or duration <= 0
                or not now - quota.STALE_AFTER_SECONDS <= checked <= now + quota.FUTURE_TOLERANCE_SECONDS
                or reset <= now):
            continue
        expected = min(1.0, (reset - now) / duration)
        allowed = remaining >= reserve and remaining >= expected
        readings.append({'allowed': allowed, 'state': 'available' if allowed else 'reserved',
                         'remaining_ratio': remaining, 'expected_remaining_ratio': expected,
                         'minimum_remaining_ratio': reserve, 'check_at': window.get('check_at'),
                         'reset_at': window.get('reset_at'), 'source': window.get('source'),
                         'reason': ('shared weekly headroom covers pace and review reserve' if allowed else
                                    'shared weekly headroom is below its pace line or review reserve')})
    return min(readings, key=lambda row: (row['allowed'], row['remaining_ratio'] -
                                         max(reserve, row['expected_remaining_ratio']))) if readings else unknown


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
    free_selected: dict[str, str] = {}
    trust_cache = {}
    role_exclusions = list(snapshot.get("selection_exclusions") or [])
    excluded_pools = set((((evidence or {}).get("policy") or {}).get("model_selection") or {}).get("excluded_pools") or [])
    provider_roles = (((evidence or {}).get("policy") or {}).get("model_selection") or {}).get("provider_roles") or {}
    worker_builds = (((evidence or {}).get('policy') or {}).get('model_selection') or {}).get('worker_builds') or {}
    worker_policy = (((evidence or {}).get('policy') or {}).get('model_selection') or {})
    snapshot_now = _snapshot_epoch(snapshot)
    for source in snapshot.get("candidates") or []:
        native = source.get("native") or {}
        instance, model = native.get("provider_instance_id"), native.get("model_id")
        billing = (source.get('access') or {}).get('billing') or 'unknown'
        # Free inference choices are published independently of native T3
        # identities. They never become T3 favorites or a new-thread default.
        mapped = bool(native.get("mapped") and instance and model and billing not in ('free', 'promotion'))
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
        windows = applicable_windows(snapshot,source)
        reported = [value for window in windows if (value := number(window.get('remaining_ratio'))) is not None]
        if reported:
            remaining = min(reported + ([remaining] if remaining is not None else []))
        exhausted = source.get("quota_state") == "exhausted" or remaining == 0
        available = (bool(source.get("available")) and not exhausted and level != "excluded"
                     and (not mapped or native.get("available") is not False))
        reason = "quota_exhausted" if exhausted else str(
            (source.get("availability") or {}).get("reason") or "")
        quality = number(source.get("quality_score"))
        posterior = quality_value(source)
        measured = model_quality.choose(source, effort)
        if measured is not None:
            quality = measured['overall']
            posterior = None if quality is None else quality / 100
            if measured['effort_option']:
                effort_value = measured['effort']
                if measured['effort_option'] == 'thinking':
                    effort_value = effort_value == 'true'
                effort = [{'id':measured['effort_option'], 'value':effort_value}]
                options = [item for item in options if item['id'] != measured['effort_option']] + effort
        limit = limiting_window(windows, snapshot.get("generated_at"))
        allowance_record = source.get("allowance") if isinstance(source.get("allowance"), Mapping) else None
        data_policy = _data_policy(allowance_record)
        limit_model = source.get("limit_model") or limit_models.resolve(
            str(source.get('provider') or ''), str(source.get('model') or ''),
            now=snapshot_now, windows=windows, allowance=allowance_record,
            capacity=capacity, price=source.get('price'),
            page_limits=source.get('page_limits'))
        approval = _approved_free(worker_policy, str(source.get('provider') or ''),
                                  str(source.get('model') or ''))
        approved_free = bool(approval and billing in ('free', 'promotion'))
        overspent = remaining == 0 or (capacity.get('pace_state') or '') == 'far_behind'
        pick_score = limit_models.score(
            posterior if posterior is not None else (None if quality is None else quality / 100),
            limit_model, policy=worker_policy)
        required_build = worker_builds.get(str(source.get('provider') or ''))
        build_allowed = required_build is None or (mapped and model == required_build)
        cost_allowed = ('model_quality' not in snapshot or worker_cost_allowed(source, snapshot.get('candidates') or []))
        row = {
            "key": str(source.get("provider")) + ":" + str(source.get("model")),
            "provider": str(source.get("provider")), "model": str(source.get("model")),
            "display_name": str(source.get("display_name") or source.get("model")),
            "native": ({"instanceId": str(instance), "model": str(model),
                        **({"options": options} if options else {})} if mapped else None),
            "effort": effort[0] if effort else None,
            "picker_eligible": mapped,
            "selection_eligible": build_allowed and cost_allowed,
            "selection_reason": ('configured worker build: ' + required_build if not build_allowed else
                                 '' if cost_allowed else 'worker price exceeds reference or is unknown'),
            "billing": billing,
            "quality_basis": measured['basis'] if measured is not None else source.get("quality_basis"),
            "quality_binding_basis": (measured.get('aa_binding_basis') if measured is not None
                                      else source.get("quality_binding_basis")) or "",
            "quality_binding_evidence": (measured.get('aa_binding_evidence') if measured is not None
                                         else source.get("quality_binding_evidence")) or [],
            "quality_n": measured['n'] if measured is not None else source.get("quality_n"),
            "quality_s": measured['passed'] if measured is not None else source.get("quality_s"),
            "quality_evidence": measured,
            "available": available, "state": "excluded" if level == "excluded" else "exhausted" if exhausted else (
                "available" if available else "unavailable"),
            "reason": "model_excluded" if level == "excluded" else reason, "trust_level": level, "quality_score": quality,
            "quality_p": posterior,
            "remaining_ratio": remaining, "limiting_window": limit,
            "pace_delta": limit.get("pace_delta") if limit else None,
            "pace_state": limit.get("pace_state") if limit else "unknown",
            "ranking_pace_state": capacity.get('pace_state') or (limit.get('pace_state') if limit else 'unknown'),
            "pool": source.get("pool") or pools.record(str(source.get("provider") or ""),
                str(source.get("model") or ""), (source.get("access") or {}).get("billing") or ""),
        }
        if isinstance(source.get('command_code'), Mapping):
            # Published terms do not become a quota reading or a quality score.
            row['provider_terms'] = source['command_code']
        if allowance_record is not None:
            row["allowance"] = allowance_record
            row["data_policy"] = data_policy
        row["limit_model"] = limit_model
        row["pick_score"] = pick_score
        row["binding_window"] = (pick_score or {}).get("binding_window")
        row["approved_free"] = approval if approved_free else None
        row["free_worker"] = approved_free
        row["overspent"] = overspent
        if approved_free:
            # The owner named this route. It is a first-choice worker while it
            # has limit left; an approved training-allowed route may serve
            # internal work the generic data policy would otherwise exclude.
            row["selection_eligible"] = True
            row["selection_reason"] = "owner-approved free worker"
        if limit_model.get("basis") in ("discovered", "measured", "cost"):
            row["pick_reason"] = limit_models.reason(pick_score, limit_model)
        if approved_free:
            if not row.get("pick_reason"):
                row["pick_reason"] = "approved free worker"
            state = "approved free worker overspent; fall back to paid" if overspent else (
                "approved free worker")
            row["pick_reason"] = state + ("; " + row["pick_reason"] if row["pick_reason"] != state else "")
        if (data_policy and data_policy.get("sensitive_ok") is False
                and not (approved_free and (approval or {}).get("allow_training"))):
            # The owner's rule: a model whose prompts train the vendor or whose
            # data is not zero-retention stays out of internal and sensitive
            # work unless the owner explicitly approved this exact route.
            row["selection_eligible"] = False
            row["selection_reason"] = "data policy: training used or not ZDR"
        if row['pool']['id'] in excluded_pools:
            if mapped:
                role_exclusions.extend({'provider':row['provider'], 'native':row['native'],
                                        'category':category, 'reason':'pool_excluded'} for category in CATEGORIES)
            continue
        allowed = provider_roles.get(row['provider'], CATEGORIES)
        if "worker" in allowed:
            worker = dict(row)
            guard = worker_pool_guard(snapshot, row['provider'], worker_policy)
            if guard is not None:
                worker['worker_pool_guard'] = guard
                if not guard['allowed'] and worker['available']:
                    worker.update(available=False, state='reserved', reason=guard['reason'])
            categories["worker"].append(worker)
        elif mapped:
            role_exclusions.append({'provider':row['provider'], 'native':row['native'],
                                    'category':'worker', 'reason':'provider_role_policy'})
        if mapped and "orchestrator" in allowed and (instance, model) in orchestrator_ids:
            review_effort = effort_options(descriptors, preferred='medium')
            review_options = native_options(descriptors, preferred='medium')
            review_measured = model_quality.choose(source, review_effort)
            quality_fields = {}
            if review_measured is not None:
                if review_measured['effort_option']:
                    review_value = review_measured['effort']
                    if review_measured['effort_option'] == 'thinking':
                        review_value = review_value == 'true'
                    review_effort = [{'id':review_measured['effort_option'], 'value':review_value}]
                    review_options = [item for item in review_options if item['id'] != review_measured['effort_option']] + review_effort
                score = review_measured['overall']
                quality_fields = {'quality_score':score, 'quality_p':None if score is None else score / 100,
                    'quality_n':review_measured['n'], 'quality_s':review_measured['passed'],
                    'quality_basis':review_measured['basis'], 'quality_evidence':review_measured,
                    'quality_binding_basis': review_measured.get('aa_binding_basis') or '',
                    'quality_binding_evidence': review_measured.get('aa_binding_evidence') or []}
            review_native = {'instanceId': str(instance), 'model': str(model),
                             **({'options': review_options} if review_options else {})}
            orchestrator_row = {**row, 'native': review_native,
                                'effort': review_effort[0] if review_effort else None, **quality_fields}
            if (row.get('data_policy') or {}).get('sensitive_ok') is not False:
                # Review authority is independent of worker eligibility, but a
                # model the owner excluded from internal work stays out of
                # internal review too.
                orchestrator_row.update(selection_eligible=True, selection_reason='')
            categories["orchestrator"].append(orchestrator_row)
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
            if (category == 'worker' and row['available'] and row['selection_eligible']
                    and row['billing'] in ('free', 'promotion')):
                if row.get('approved_free') and not row.get('overspent'):
                    # The owner's approved free worker is the provider's free
                    # choice even when another free route has a higher score.
                    free_selected[row['provider']] = row['key']
                elif not row.get('overspent'):
                    free_selected.setdefault(row['provider'], row['key'])
            if row["available"] and row["selection_eligible"] and provider["selected"][category] is None:
                provider["selected"][category] = row["native"]
                if row.get("pick_reason"):
                    # The picker surfaces the provider choice's reason. The
                    # allowance and binding window are already published as
                    # their own fields; this carries them to the CLI too.
                    row["reason"] = "pick: " + str(row["pick_reason"])
    # Quality chooses the provider's model. Capacity orders those provider
    # choices across the lane; no provider name has a fixed position.
    for category, rows in categories.items():
        displayed_choices = {provider: group['selected'][category] or next(
            (item['native'] for item in rows if item['provider'] == provider
             and item['picker_eligible'] and item['selection_eligible']), None)
            for provider, group in providers.items()}
        def lane_key(row):
            displayed = displayed_choices[row['provider']]
            free_pick = (category != 'worker' or bool(row.get('approved_free')))
            picked = ((row['native'] is not None and row['native'] == displayed)
                      or (category == 'worker' and free_pick
                          and row['key'] == free_selected.get(row['provider'])))
            capacity = row['remaining_ratio']
            return (not picked, not row['available'], TRUST.get(row['trust_level'],3),
                    row.get('ranking_pace_state', row['pace_state']) == 'far_behind', -(capacity if capacity is not None else -1),
                    row['position'])
        rows.sort(key=lane_key)
        for index, row in enumerate(rows,1):
            row['position'] = index
    return {"schema": SCHEMA, "generated_at": snapshot.get("generated_at"),
            "partial": bool(snapshot.get("partial", False)),
            "max_age_seconds": snapshot.get("max_age_seconds", 900),
            "providers": providers, "worker_builds": dict(worker_builds),
            "free_selected": free_selected,
            "role_exclusions": role_exclusions, **categories,
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
            pick = row.get('pick_score') or {}
            policy = row.get('data_policy') or {}
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
                      'quality_basis': ExactLabel(str(row.get('quality_basis') or 'unknown')),
                      'quality_binding_basis': ExactLabel(str(row.get('quality_binding_basis') or '')),
                      'allowance_plan': str((row.get('allowance') or {}).get('plan') or ''),
                      'allowance_basis': ExactLabel(str((row.get('allowance') or {}).get('basis') or '')),
                      'binding_window': str(row.get('binding_window') or ''),
                      'pick_basis': ExactLabel(str(pick.get('basis') or '')),
                      'pick_reason': ExactLabel(str(row.get('pick_reason') or '')),
                      'data_policy': ExactLabel(str(policy.get('training') or '') + '/' + str(policy.get('retention') or '')),
                      'approved_free': 'true' if row.get('approved_free') else 'false',
                      'approval_source': ExactLabel(str((row.get('approved_free') or {}).get('source') or '')),
                      'overspent': 'true' if row.get('overspent') else 'false',
                      'sensitive_ok': ('' if policy.get('sensitive_ok') is None
                                       else 'true' if policy.get('sensitive_ok') else 'false')}
            numbers = {'info': 1.0, 'position': row['position'],
                       'selected': float((row['key'] == (selection.get('free_selected') or {}).get(row['provider'])
                                           if category == 'worker' and row.get('billing') in ('free', 'promotion') else
                                           row.get('native') is not None and row.get('native') == (
                           (((selection.get('providers') or {}).get(row['provider']) or {}).get('selected') or {}).get(category)
                           or next((item['native'] for item in selection.get(category) or []
                               if item['provider'] == row['provider'] and item['picker_eligible'] and item['selection_eligible']), None)))),
                       'provider_position': row.get('picker_provider_position', row.get('provider_position')),
                       'pool_position': row.get('picker_pool_position', row.get('pool_position')),
                       'quality': row.get('quality_score'),
                       'default': float(category == 'worker' and row.get('native') is not None
                                        and row.get('native') == selection.get('default_worker')),
                       'quality_rounds': row.get('quality_n'),
                       'quality_accepted': row.get('quality_s'),
                       'remaining_ratio': limit.get('remaining_ratio'),
                       'pace_delta': limit.get('pace_delta'),
                       'pick_score': pick.get('score'),
                       'approved_free': 1.0 if row.get('approved_free') else 0.0,
                       'overspent': 1.0 if row.get('overspent') else 0.0,
                       'quality_term': pick.get('quality_term'),
                       'capacity_term': pick.get('capacity_term'),
                       'affordable_requests': pick.get('affordable_requests'),
                       'allowance_requests_5h': (row.get('allowance') or {}).get('requests_5h'),
                       'allowance_requests_month': (row.get('allowance') or {}).get('requests_month')}
            guard = row.get('worker_pool_guard') or {}
            numbers['guard_remaining_ratio'] = guard.get('remaining_ratio')
            numbers['guard_expected_remaining_ratio'] = guard.get('expected_remaining_ratio')
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
