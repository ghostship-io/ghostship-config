"""Audited pools preserve independent and nested allowances."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'modules/self-hosted/ai-usage/collector'))
import pools


class PoolTests(unittest.TestCase):
    def test_antigravity_families_share_only_their_own_allowance(self):
        for model in ('claude-sonnet-5-5-high', 'claude-opus-5-5-low', 'gpt-oss-120b-medium', 'gpt-6.1-sol'):
            self.assertEqual(pools.pool_of_route('antigravity', model), 'antigravity:3p')
        self.assertEqual(pools.pool_of_route('antigravity', 'gemini-3.8-flash'), 'antigravity:gemini')
        self.assertEqual(pools.pool_of_route('antigravity', 'unknown-model'), 'antigravity:unknown')

    def test_claude_nested_cap_retains_parent(self):
        fable = pools.record('claude', 'claude-fable-5-1')
        self.assertEqual((fable['id'], fable['parent']), ('claude:fable', 'claude:all'))
        self.assertEqual(pools.record('claude', 'claude-opus-5-5')['id'], fable['parent'])

    def test_paid_and_free_routes_do_not_share_an_allowance(self):
        for provider in ('opencode-go', 'openrouter'):
            for billing in ('free', 'promotion'):
                self.assertEqual(pools.record(provider, 'model', billing)['id'], provider + ':free')
            self.assertNotEqual(pools.record(provider, 'model', 'subscription')['id'], provider + ':free')

    def test_google_and_groq_preserve_exact_model_scope(self):
        for provider in ('google', 'groq'):
            a, b = (pools.record(provider, model) for model in ('family/model-a', 'family/model-b'))
            self.assertNotEqual(a['id'], b['id'])
            self.assertEqual(a['basis'], 'per_model')
            self.assertEqual(pools.pool_of_window(provider, {'model': 'family/model-a'}), a['id'])
            self.assertEqual(pools.pool_of_window(provider, {'model': '*'}), provider + ':unknown')

    def test_shared_and_overflow_windows_are_distinct(self):
        for provider, expected in (('codex', 'codex:all'), ('ollama', 'ollama:included'),
                                   ('grok', 'grok:credits')):
            self.assertEqual(pools.record(provider, 'any-model')['id'], expected)
        self.assertEqual(pools.pool_of_window('ollama', {'quota_id': 'purchased'}), 'ollama:credits')

    def test_window_scope_and_unknown_are_not_account_wide_guesses(self):
        self.assertEqual(pools.pool_of_window('antigravity', {'applies_to': ['claude', 'gpt']}), 'antigravity:3p')
        self.assertEqual(pools.pool_of_window('antigravity', {'quota_id': 'gemini-5h'}), 'antigravity:gemini')
        self.assertEqual(pools.pool_of_window('antigravity', {}), 'antigravity:unknown')
        self.assertEqual(pools.record('new-provider', 'model')['basis'], 'default')
