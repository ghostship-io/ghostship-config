"""Bounded evidence for usage-limit resets announced by the primary author."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

POST_URL = re.compile(r"https://x\.com/thsottiaux/status/\d+$")
VERSION = 2
CLOCK = re.compile(r'\b([01]?\d|2[0-3])(?::([0-5]\d))?\s*(am|pm)?\s*(PT|PDT|PST|UTC)\b', re.I)


def timestamp(value):
    try:
        at = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return at if at.tzinfo is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def iso(at):
    return at.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def parse(post):
    """Ignore reset features/chatter; retain only an announced usage-limit reset."""
    url = str(post.get('url', ''))
    raw = str(post.get('text', ''))[:8000]
    # Scope comes from the announcement clause, not unrelated launch prose.
    clauses = [part for part in re.split(r'(?<=[.!?;])\s+|\n\n', raw)
               if re.search(r'\b(?:codex|chatgpt)\b', part, re.I)
               and re.search(r'\breset(?:ting|s)?\b', part, re.I)
               and re.search(r'\b(?:limits?|quotas?|usage|weekly|daily|monthly|5h|5[ -]hours?|five[ -]hours?)\b', part, re.I)]
    if not clauses:
        return None
    text = ' '.join(clauses)
    published = timestamp(post.get('published_at'))
    products = [p for p in ('codex', 'chatgpt') if re.search(r'\b' + p + r'\b', text, re.I)]
    if (len(url) > 512 or not POST_URL.fullmatch(url) or not published or not products
            or not re.search(r'\b(?:limits?|quotas?|usage|weekly|daily|monthly|5h|5[ -]hours?|five[ -]hours?)\b', text, re.I)
            or not re.search(r'\breset(?:ting|s)?\b', text, re.I)):
        return None
    # A reset button, recurring schedule, question or troubleshooting mention
    # does not announce that a provider is resetting usage limits.
    if (re.search(r'\b(?:banked|manual|button|restart|reboot|dashboard|display|graph|chart|preferences|settings|cache|context)\b', text, re.I)
            or re.search(r'\b(?:every|each)\s+(?:day|week|month|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', text, re.I)
            or '?' in text
            or re.search(r'\b(?:not|never|no)\s+(?:\w+\s+){0,3}reset', text, re.I)):
        return None
    claim = re.search(r"\b(?:we(?:'re|'ve| are| will| have| just|’re|’ve)?\s+(?:\w+\s+){0,4}reset(?:ting)?"
                      r"|resetting\b|(?:codex|chatgpt)\b[^.!?]{0,40}\b(?:weekly|daily|monthly|5h)\s+reset\b|(?:limits?|quotas?|usage)\s+(?:(?:will|have|has|are|were|be|been|just)\s+)*reset(?:s)?\b)", text, re.I)
    occasion = re.search(r'\b(?:today|tomorrow|now|just|soon|later|\d{4}-\d{2}-\d{2})\b', text, re.I)
    clock = CLOCK.search(text)
    has_clock = clock is not None and (clock[2] is not None or clock[3] is not None)
    if not claim or not (occasion or has_clock or re.search(r'\b(?:have|has)\s+reset\b|\b\d{4}-\d{2}-\d{2}T', text, re.I)):
        return None
    windows = []
    for kind, pattern in (('weekly', r'\b(?:weekly|7[ -]?days?)\b'),
                          ('session', r'\b(?:5\s*(?:h|hours?)|five[ -]hours?|5[ -]hour)\b'),
                          ('daily', r'\b(?:daily|24[ -]?hours?)\b'),
                          ('monthly', r'\bmonthly\b')):
        if re.search(pattern, text, re.I):
            windows.append(kind)
    if not windows:
        windows = ['all'] if re.search(r'\ball\b[^.!?]{0,60}\b(?:limits|quotas)\b', text, re.I) else ['unknown']
    plans = [p for p in ('free', 'plus', 'pro', 'business', 'enterprise', 'edu')
             if re.search(r'\b(?:codex|chatgpt|for|on)\s+(?:all\s+)?' + p + r'\b|' +
                          r'\b' + p + r'\s+(?:plans?|users|accounts|subscribers|codex|chatgpt)\b', text, re.I)]
    if not plans:
        plans = ['paid'] if re.search(r'\bpaid\b', text, re.I) else ['all']
    event = {'event_version': VERSION, 'source_url': url, 'published_at': iso(published),
             'quote': re.sub(r'\s+', ' ', text).strip()[:240],
             'scope': ','.join(products), 'products': products, 'plans': plans, 'windows': windows,
             'reset_at': None, 'confidence': 'low', 'reason': 'ambiguous_reset_announcement'}
    if len(clauses) > 1 or (len(products) > 1 and len(windows) > 1) or re.search(r'\b(?:maybe|might|could|hope|plan|before|by|except|excluding)\b', text, re.I):
        return event
    at = None
    absolute = re.search(r'\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})\b', text)
    if absolute:
        at = timestamp(absolute[0])
    if has_clock and at is None:
        zone = timezone.utc if clock[4].upper() == 'UTC' else ZoneInfo('America/Los_Angeles')
        day = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', text)
        try:
            date = datetime.strptime(day[1], '%Y-%m-%d').date() if day else published.astimezone(zone).date()
            if not day and re.search(r'\btomorrow\b', text, re.I):
                date += timedelta(days=1)
            hour = int(clock[1])
            if clock[3]:
                if not 1 <= hour <= 12:
                    return event
                hour = hour % 12 + (12 if clock[3].lower() == 'pm' else 0)
            candidate = datetime.combine(date, datetime.min.time(), zone).replace(hour=hour, minute=int(clock[2] or 0))
            if (clock[4].upper() in ('PT', 'UTC') or clock[4].upper() == candidate.tzname()) and (
                    candidate.replace(fold=1).utcoffset() == candidate.utcoffset()):
                at = candidate
        except ValueError:
            pass
    if at is None and re.search(r'\b(?:now|just|have\s+reset|has\s+reset)\b', text, re.I):
        at = published
    if at is not None:
        event['reset_at'] = iso(at)
        if windows != ['unknown']:
            event.update(confidence='confirmed', reason='primary_explicit_reset')
        else:
            event['reason'] = 'ambiguous_reset_scope'
    return event


def valid(entry):
    return (isinstance(entry, dict) and entry.get('event_version') == VERSION
            and POST_URL.fullmatch(str(entry.get('source_url', '')))
            and timestamp(entry.get('published_at')) is not None
            and isinstance(entry.get('quote'), str) and 0 < len(entry['quote']) <= 240
            and entry.get('confidence') in ('low', 'confirmed')
            and isinstance(entry.get('products'), list) and bool(entry['products'])
            and all(p in ('codex', 'chatgpt') for p in entry['products'])
            and isinstance(entry.get('plans'), list) and bool(entry['plans'])
            and isinstance(entry.get('windows'), list) and bool(entry['windows'])
            and all(w in ('all', 'unknown', 'weekly', 'session', 'daily', 'monthly') for w in entry['windows'])
            and all(p in ('all', 'paid', 'free', 'plus', 'pro', 'business', 'enterprise', 'edu') for p in entry['plans'])
            and entry.get('scope') == ','.join(entry['products'])
            and (entry['confidence'] == 'low' or timestamp(entry.get('reset_at')) is not None))


def matches(entry, window):
    if not valid(entry) or entry['confidence'] != 'confirmed' or window.get('provider') not in entry['products']:
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
            if not isinstance(duration, (int, float)) or duration <= 0 or not isinstance(observed, (int, float)):
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
