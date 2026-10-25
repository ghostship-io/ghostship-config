"""Bounded evidence for usage-limit resets announced by the primary author."""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone

POST_URL = re.compile(r"https://x\.com/thsottiaux/status/\d+$")
VERSION = 2


def timestamp(value):
    try:
        at = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return at if at.tzinfo is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def iso(at):
    return at.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def from_classification(post, classification, now, primary_author):
    """Build a bounded receipt from a code-validated model judgement."""
    if not isinstance(post, dict) or not isinstance(classification, dict):
        return None
    url = str(post.get('url', ''))
    author = str(post.get('author', '')).lstrip('@').lower()
    if (not POST_URL.fullmatch(url) or len(url) > 512 or author != primary_author.lower()
            or classification.get('source_url') != url
            or classification.get('is_reset_announcement') is not True):
        return None
    published = timestamp(post.get('published_at'))
    moment = float(now)
    if not published or not moment - 75 * 60 <= published.timestamp() <= moment + 60:
        return None
    quote = classification.get('evidence_quote')
    raw = str(post.get('text', ''))
    if not isinstance(quote, str) or not 0 < len(quote) <= 240 or quote not in raw:
        return None
    products, plans, windows = (classification.get(name) for name in ('products', 'plans', 'windows'))
    if (not isinstance(products, list) or not products or any(x not in ('codex', 'chatgpt') for x in products)
            or not isinstance(plans, list) or not plans or any(x not in ('all', 'paid', 'free', 'plus', 'pro', 'business', 'enterprise', 'edu') for x in plans)
            or not isinstance(windows, list) or not windows or any(x not in ('all', 'unknown', 'weekly', 'session', 'daily', 'monthly') for x in windows)):
        return None
    confidence = classification.get('confidence')
    if confidence not in ('low', 'high'):
        return None
    reset = classification.get('reset_at')
    parsed = timestamp(reset) if isinstance(reset, str) else None
    if reset is not None and (not parsed or not moment < parsed.timestamp() <= moment + 7 * 86400):
        return None
    if reset is None or 'unknown' in windows:
        confidence = 'low'
    products = list(dict.fromkeys(products))
    return {'event_version': VERSION, 'source_url': url, 'published_at': iso(published),
            'quote': quote, 'scope': ','.join(products), 'products': products,
            'plans': list(dict.fromkeys(plans)), 'windows': list(dict.fromkeys(windows)),
            'reset_at': iso(parsed) if parsed else None, 'confidence': confidence,
            'reason': 'free_model_classification'}

def valid(entry):
    return (isinstance(entry, dict) and entry.get('event_version') == VERSION
            and POST_URL.fullmatch(str(entry.get('source_url', '')))
            and timestamp(entry.get('published_at')) is not None
            and isinstance(entry.get('quote'), str) and 0 < len(entry['quote']) <= 240
            and entry.get('confidence') in ('low', 'high', 'confirmed')
            and isinstance(entry.get('products'), list) and bool(entry['products'])
            and all(p in ('codex', 'chatgpt') for p in entry['products'])
            and isinstance(entry.get('plans'), list) and bool(entry['plans'])
            and isinstance(entry.get('windows'), list) and bool(entry['windows'])
            and all(w in ('all', 'unknown', 'weekly', 'session', 'daily', 'monthly') for w in entry['windows'])
            and all(p in ('all', 'paid', 'free', 'plus', 'pro', 'business', 'enterprise', 'edu') for p in entry['plans'])
            and entry.get('scope') == ','.join(entry['products'])
            and (entry['confidence'] == 'low' or timestamp(entry.get('reset_at')) is not None))


def matches(entry, window):
    if not valid(entry) or entry['confidence'] not in ('high', 'confirmed') or window.get('provider') not in entry['products']:
        return False
    plans = entry['plans']
    plan = str(window.get('plan') or '').lower()
    if 'all' not in plans and plan not in plans and not (
            'paid' in plans and plan in ('plus', 'pro', 'business', 'enterprise', 'edu')):
        return False
    kind = str(window.get('kind') or '').lower()
    if kind == '5h':
        kind = 'session'
    if kind not in ('weekly', 'session', 'daily', 'monthly'):
        kind = {604800: 'weekly', 18000: 'session', 86400: 'daily'}.get(window.get('durationSeconds'), kind)
    return 'all' in entry['windows'] or kind in entry['windows']


def apply_completed(results, document, now):
    """An explicit reset supersedes only a measurement taken before that reset.

    Keep the provider reading separately and date the new allowance at the
    announced reset, never at discovery. Normal freshness checks still apply;
    a newer provider reading always wins and an old event grants no capacity.
    """
    for result in results:
        for window in result.windows:
            if window.get('resetSource') == 'custom':
                continue
            duration = window.get('durationSeconds')
            observed = window.get('observedAtEpoch')
            if (isinstance(duration, bool) or not isinstance(duration, (int, float))
                    or isinstance(observed, bool) or not isinstance(observed, (int, float))):
                continue
            try:
                duration, observed = float(duration), float(observed)
            except (OverflowError, ValueError):
                continue
            if not math.isfinite(duration) or duration <= 0 or not math.isfinite(observed):
                continue
            candidates = []
            for event in document.get('announcements', []):
                at = timestamp(event.get('reset_at'))
                if matches(event, window) and at and observed < at.timestamp() <= now < at.timestamp() + duration:
                    candidates.append((at.timestamp(), event))
            if not candidates:
                continue
            reset, event = max(candidates, key=lambda pair: pair[0])
            window.update(providerUsedRatio=window.get('usedRatio'), providerResetEpoch=window.get('resetEpoch'),
                          providerObservedAtEpoch=observed, usedRatio=0.0, resetEpoch=reset + duration,
                          observedAtEpoch=reset, resetSource='announced', resetLabel='announced reset',
                          basis='announced_reset', announcedResetEpoch=reset, announcementUrl=event['source_url'])
