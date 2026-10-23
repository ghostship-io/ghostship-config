"""Owner-set reset times, separate from the provider's measurement."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def load(path: str) -> list[dict[str, Any]]:
    try:
        document = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return []
    if not isinstance(document, dict) or document.get('schema') != 1:
        raise ValueError('invalid custom reset document')
    entries = document.get('windows')
    if not isinstance(entries, list) or len(entries) > 100:
        raise ValueError('invalid custom reset windows')
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or not all(isinstance(entry.get(key), str) and entry[key]
                                                 for key in ('provider', 'quota_id', 'reset_at')):
            raise ValueError('custom reset needs provider, quota_id and reset_at')
        key = (entry['provider'], entry.get('model', '*'), entry['quota_id'])
        if key in seen:
            raise ValueError('duplicate custom reset window')
        seen.add(key)
        at = datetime.fromisoformat(entry['reset_at'].replace('Z', '+00:00'))
        if at.tzinfo is None:
            raise ValueError('custom reset needs an explicit time zone')
    return entries


def apply(results, overrides: list[dict[str, Any]], now: float) -> None:
    """Change only effective reset, never usage, freshness, or provider truth."""
    for result in results:
        for window in result.windows:
            for override in overrides:
                if (window.get('provider') != override['provider']
                        or window.get('quotaId') != override['quota_id']
                        or str(window.get('model') or '*') != override.get('model', '*')):
                    continue
                reset = datetime.fromisoformat(override['reset_at'].replace('Z', '+00:00')).timestamp()
                if reset <= now:
                    continue
                window['providerResetEpoch'] = window.get('resetEpoch')
                window['resetEpoch'] = reset
                window['resetSource'] = 'custom'
                window['resetLabel'] = 'custom reset'
