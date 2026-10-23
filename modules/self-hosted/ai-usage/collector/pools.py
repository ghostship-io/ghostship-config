"""Quota pool identities from the provider limits audit.

Pool membership labels evidence; each candidate's applicable windows still gate
availability. A nested pool drains its parent as well as its own allowance.
"""
from __future__ import annotations
from typing import Any, Mapping

LABELS = {
    'antigravity:3p': 'Claude & GPT', 'antigravity:gemini': 'Gemini',
    'claude:all': 'All models', 'claude:fable': 'Fable (within all models)',
    'codex:all': 'All models', 'ollama:included': 'Included allowance',
    'ollama:credits': 'Usage credits', 'opencode-go:paid': 'Paid models',
    'opencode-go:free': 'Free models', 'grok:credits': 'Credits',
    'openrouter:free': 'Free models', 'openrouter:credits': 'Credits',
}
PER_MODEL = frozenset(('google', 'groq'))


def pool_of_route(provider: str, model: str, billing: str = '') -> str:
    text = model.lower().rsplit('/', 1)[-1]
    if provider in PER_MODEL:
        return f'{provider}:{model}'
    if provider == 'antigravity':
        if text.startswith(('claude-', 'gpt-oss-')):
            return 'antigravity:3p'
        if text.startswith('gemini-'):
            return 'antigravity:gemini'
        return 'antigravity:unknown'
    if provider == 'claude':
        return 'claude:fable' if text.startswith('claude-fable-') else 'claude:all'
    if provider == 'codex': return 'codex:all'
    if provider == 'ollama': return 'ollama:included'
    if provider == 'grok': return 'grok:credits'
    if provider == 'opencode-go':
        return 'opencode-go:free' if billing in ('free', 'promotion') else 'opencode-go:paid'
    if provider == 'openrouter':
        return 'openrouter:free' if billing in ('free', 'promotion') else 'openrouter:credits'
    return f'{provider}:default'


def pool_parent(pool: str) -> str | None:
    return 'claude:all' if pool == 'claude:fable' else None


def pool_label(pool: str) -> str:
    return LABELS.get(pool, pool.split(':', 1)[-1])


def pool_of_window(provider: str, window: Mapping[str, Any]) -> str:
    model = str(window.get('model') or '')
    identifier = str(window.get('quota_id') or window.get('quotaId') or '')
    scope = ' '.join(str(part) for part in window.get('applies_to') or ())
    text = (identifier + ' ' + scope + ' ' + model).lower()
    if provider == 'antigravity':
        if any(token in text for token in ('3p', 'claude', 'gpt')): return 'antigravity:3p'
        if 'gemini' in text: return 'antigravity:gemini'
        return 'antigravity:unknown'
    if provider == 'claude':
        return 'claude:fable' if 'fable' in text else 'claude:all'
    if provider in PER_MODEL:
        return f'{provider}:{model}' if model and model != '*' else f'{provider}:unknown'
    if provider == 'opencode-go':
        return 'opencode-go:free' if 'free' in text else 'opencode-go:paid'
    if provider == 'openrouter':
        return 'openrouter:free' if any(x in text for x in ('free', 'daily', 'minute')) else 'openrouter:credits'
    if provider == 'ollama' and 'purchased' in text: return 'ollama:credits'
    return pool_of_route(provider, model)


def record(provider: str, model: str, billing: str = '') -> dict[str, Any]:
    pool = pool_of_route(provider, model, billing)
    return {'id': pool, 'label': pool_label(pool), 'parent': pool_parent(pool),
            'basis': 'per_model' if provider in PER_MODEL else ('audit' if pool in LABELS else 'default')}
