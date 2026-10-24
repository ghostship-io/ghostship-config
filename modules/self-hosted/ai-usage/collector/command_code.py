"""Published Command Code GOAT terms, separate from measured quota and build identity."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

INSTANCE = 'commandCode'
MODEL = 'deepseek/deepseek-v4.1-flash'
IDENTITY = INSTANCE + '/' + MODEL
SOURCE = 'https://commandcode.ai/docs/plans/goat'
MODEL_SOURCE = 'https://commandcode.ai/models/deepseek-v4-1-flash'
PEAK_INTERVALS = ((1, 4), (6, 10))
RATES = {'peak': {'input': .30, 'output': 1.20, 'cache_read': .006},
         'off_peak': {'input': .15, 'output': .60, 'cache_read': .003}}


def is_worker_route(provider: str, model: str) -> bool:
    return provider == INSTANCE and model == MODEL


def configured(instance: Mapping[str, Any], model: str) -> bool:
    """Only the reviewed launcher enforces paid selection as well as ZDR."""
    if not isinstance(instance, Mapping):
        return False
    config = instance.get('config') or {}
    environment = instance.get('environment') or []
    if not isinstance(config, Mapping) or not isinstance(environment, list):
        return False
    zdr = [entry.get('value') for entry in environment
           if isinstance(entry, Mapping) and entry.get('name') == 'CMD_ZDR']
    return (model == MODEL and instance.get('driver') == 'acpRegistry'
            and instance.get('enabled') is True and zdr == ['1']
            and config.get('source') == 'local'
            and config.get('commandPath') == '/home/t3code/.local/bin/cmd'
            and config.get('commandArgs') == ['acp'])


def peak(now: float) -> bool:
    moment = datetime.fromtimestamp(now, tz=timezone.utc)
    return moment.weekday() < 5 and any(start <= moment.hour < end for start, end in PEAK_INTERVALS)


def rates(now: float) -> dict[str, float]:
    return dict(RATES['peak' if peak(now) else 'off_peak'])


def enrich(row: dict[str, Any], now: float, native: Mapping[str, Any] | None) -> None:
    if row.get('provider') != INSTANCE:
        return
    valid = bool((native or {}).get('commandCodePolicyVerified')) and row['model'] == MODEL
    row['native']['available'] = row['native'].get('available', False) and valid
    row['available'] = row['available'] and row['native']['available']
    if not valid:
        row['availability'].update(state='unavailable', reason='managed paid-ZDR Command Code route is not verified')
    row['tiers'] = [tier for tier in row['tiers'] if tier != 'free']
    row['rank'].pop('free', None)
    row['score'].pop('free', None)
    row['access'].update(kind='provider_paid', billing='subscription',
                         basis='Command Code GOAT subscription; paid models and CMD_ZDR=1 required',
                         paid_only=True, zdr_required=True)
    if row['model'] != MODEL:
        return
    row['price'].update(source=MODEL_SOURCE, unit='USD per million tokens',
                        period='peak' if peak(now) else 'off_peak',
                        zdr_pricing_note='published model rates; actual ZDR routing can differ',
                        schedule={'timezone': 'UTC', 'weekdays': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
                                  'peak_hours': [list(interval) for interval in PEAK_INTERVALS],
                                  'weekends': 'off_peak', 'peak': dict(RATES['peak']),
                                  'off_peak': dict(RATES['off_peak'])})
    row['command_code'] = {
        'plan': 'GOAT', 'alias': '(latest)', 'alias_can_move': True, 'route_identity': IDENTITY,
        'resolved_build': None, 'build_source': 'not exposed by the native model catalog',
        'vendor_build_evidence': {
            'build': '1017', 'published_at': '2026-10-19T16:13:13Z',
            'source': 'https://x.com/CommandCodeAI/status/2112215504064819443',
            'basis': 'dated vendor announcement, separate from per-run build resolution'},
        'estimated_allowances': [
            {'kind': kind, 'requests': requests, 'unit': 'requests', 'estimated': True,
             'basis': 'vendor example request mix; not a measured limit or remaining balance',
             'source': SOURCE}
            for kind, requests in (('five_hour', 41000), ('weekly', 103000), ('monthly', 205000))],
        'usage_state': 'reported' if row['capacity']['measured'] else 'unknown',
        'usage_source': 'native Command Code reporting through T3; no inferred balance',
        'paid_only': True, 'zdr_required': True, 'zdr_configuration_verified': valid,
        'harness_quality': 'not evaluated; controlled harness pilot pending',
    }
