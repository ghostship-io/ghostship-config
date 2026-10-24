"""Published Command Code GOAT terms, separate from measured quota and build identity."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

# The picker calls the subscription route commandCode, whatever T3 Code
# instance serves it. T3 Code reaches it through its OpenCode instance now.
INSTANCE = 'commandCode'
T3_INSTANCE = 'opencode'
MODEL_PREFIXES = ('command-code', 'command-code-anthropic')
MODEL = 'deepseek/deepseek-v4.1-flash'
IDENTITY = INSTANCE + '/' + MODEL
PROVIDER_ID = 'command-code'
KEY_ENV = 'COMMAND_CODE_API_KEY'
BASE_URL = 'https://api.commandcode.ai/provider/v1'
CONFIG_NAMES = ('.config/opencode/opencode.jsonc', '.config/opencode/opencode.json')
SOURCE = 'https://commandcode.ai/docs/plans/goat'
MODEL_SOURCE = 'https://commandcode.ai/models/deepseek-v4-1-flash'
PEAK_INTERVALS = ((1, 4), (6, 10))
RATES = {'peak': {'input': .30, 'output': 1.20, 'cache_read': .006},
         'off_peak': {'input': .15, 'output': .60, 'cache_read': .003}}


def is_worker_route(provider: str, model: str) -> bool:
    return provider == INSTANCE and model == MODEL


def is_model(model_id: str) -> bool:
    """True when an OpenCode slug is served by a Command Code provider."""
    return str(model_id).partition('/')[0] in MODEL_PREFIXES


def _read(path: str) -> str:
    if not path:
        return ''
    try:
        return Path(path).read_text(encoding='utf-8')
    except OSError:
        return ''


def _config(home: str) -> dict[str, Any] | None:
    for relative in CONFIG_NAMES:
        text = _read(str(Path(home) / relative))
        if not text:
            continue
        try:
            config = json.loads(text)
        except ValueError:
            return None
        return config if isinstance(config, dict) else None
    return None


def configured(home: str, secrets_env: str = '') -> bool:
    """Verify the live OpenCode route for picker admission, never visibility.

    The provider must carry the vendor's zero-retention header by name, read
    the key from the projected environment instead of the file, stay enabled,
    and the projection must actually carry the key. A paid worker route is
    admitted only on that evidence; model visibility never depends on it.
    """
    if not home:
        return False
    config = _config(home)
    if config is None:
        return False
    providers = config.get('providers')
    entry = providers.get(PROVIDER_ID) if isinstance(providers, Mapping) else None
    if not isinstance(entry, Mapping):
        return False
    settings = entry.get('settings')
    settings = settings if isinstance(settings, Mapping) else {}
    headers = entry.get('headers')
    headers = headers if isinstance(headers, Mapping) else {}
    disabled = config.get('disabled_providers')
    disabled = disabled if isinstance(disabled, list) else []
    enabled = config.get('enabled_providers')
    if PROVIDER_ID in disabled or (isinstance(enabled, list) and PROVIDER_ID not in enabled):
        return False
    projected = _read(secrets_env)
    has_key = False
    for line in projected.splitlines():
        line = line.strip()
        if line.startswith('export '):
            line = line[7:].lstrip()
        if not line or line.startswith('#'):
            continue
        name, separator, value = line.partition('=')
        if separator and name.strip() == KEY_ENV and value.strip():
            has_key = True
            break
    return (
        settings.get('baseURL') == BASE_URL
        and settings.get('apiKey') == '{env:' + KEY_ENV + '}'
        and str(headers.get('x-cmd-zdr')) == '1'
        and has_key
    )


def peak(now: float) -> bool:
    moment = datetime.fromtimestamp(now, tz=timezone.utc)
    return moment.weekday() < 5 and any(start <= moment.hour < end for start, end in PEAK_INTERVALS)


def rates(now: float) -> dict[str, float]:
    return dict(RATES['peak' if peak(now) else 'off_peak'])


def enrich(row: dict[str, Any], now: float, native: Mapping[str, Any] | None) -> None:
    if row.get('provider') != INSTANCE:
        return
    # The route is verified once, from the live OpenCode config and the
    # projected key: every model on it is a paid ZDR route, not only the
    # reviewed worker model. An unverified route is not dispatched at all.
    verified = bool((native or {}).get('commandCodePolicyVerified'))
    row['native']['available'] = row['native'].get('available', False) and verified
    row['available'] = row['available'] and row['native']['available']
    if not verified:
        row['availability'].update(state='unavailable', reason='managed paid-ZDR Command Code route is not verified')
    row['tiers'] = [tier for tier in row['tiers'] if tier != 'free']
    row['rank'].pop('free', None)
    row['score'].pop('free', None)
    row['access'].update(kind='provider_paid', billing='subscription',
                         basis='Command Code GOAT subscription; paid models and x-cmd-zdr required',
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
        'usage_source': 'OpenCode request records in T3 and the Command Code usage page; no inferred balance',
        'paid_only': True, 'zdr_required': True, 'zdr_configuration_verified': verified,
        'harness_quality': 'not evaluated; controlled harness pilot pending',
    }
