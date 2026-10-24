"""One limit model per provider, resolved discovered -> measured -> cost -> unknown."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'modules/self-hosted/ai-usage/collector'))

import limit_models

NOW = 1792810000.0
WINDOW = {'kind': 'weekly', 'remaining_ratio': 0.5, 'reset_at': '2026-10-30T00:00:00Z',
          'seconds_to_reset': 4 * 86400, 'source': 't3'}


class DiscoveredTests(unittest.TestCase):
    def test_the_go_allowance_is_the_binding_discovered_limit(self):
        allowance = {'budgets': [
            {'kind': 'session', 'requests': 34670.0, 'unit': 'requests', 'source': 'opencode.ai/go'},
            {'kind': 'weekly', 'requests': 86675.0, 'unit': 'requests', 'source': 'opencode.ai/go'},
            {'kind': 'monthly', 'requests': 173350.0, 'unit': 'requests', 'source': 'opencode.ai/go'},
        ], 'source': 'opencode.ai/go', 'stale': False}
        model = limit_models.resolve('opencode-go', 'deepseek-v4.1-flash', now=NOW,
                                     allowance=allowance, windows=[])
        self.assertEqual(model['basis'], 'discovered')
        self.assertEqual(model['affordable']['binding_window'], 'session')
        self.assertAlmostEqual(model['affordable']['tasks'], 34670.0)
        self.assertGreater(model['capacity_term'], 0.9)

    def test_a_measured_monthly_share_narrows_the_go_binding(self):
        allowance = {'budgets': [
            {'kind': 'session', 'requests': 34670.0, 'unit': 'requests'},
            {'kind': 'weekly', 'requests': 86675.0, 'unit': 'requests'},
            {'kind': 'monthly', 'requests': 173350.0, 'unit': 'requests'},
        ]}
        monthly = dict(WINDOW, kind='monthly', remaining_ratio=0.1)
        model = limit_models.resolve('opencode-go', 'deepseek-v4.1-flash', now=NOW,
                                     allowance=allowance, windows=[monthly, WINDOW])
        self.assertEqual(model['basis'], 'discovered')
        self.assertEqual(model['affordable']['binding_window'], 'monthly')
        self.assertAlmostEqual(model['affordable']['tasks'], 17335.0)

    def test_command_code_exposes_estimate_windows_and_pricing(self):
        model = limit_models.resolve('commandCode', 'deepseek/deepseek-v4.1-flash', now=NOW)
        self.assertEqual(model['basis'], 'discovered')
        self.assertTrue(model['estimate'])
        budgets = {row['kind']: row['budget'] for row in model['windows']}
        self.assertEqual(budgets, {'session': 41000.0, 'weekly': 103000.0, 'monthly': 205000.0})
        self.assertEqual(model['affordable']['binding_window'], 'session')
        self.assertEqual(model['affordable']['tasks'], 41000.0)
        self.assertIn('input', model['pricing'])


class MeasuredTests(unittest.TestCase):
    def test_measured_windows_are_used_when_no_limit_is_published(self):
        model = limit_models.resolve('codex', 'gpt-6.1-sol', now=NOW,
                                     windows=[dict(WINDOW, kind='session', remaining_ratio=0.9), WINDOW])
        self.assertEqual(model['basis'], 'measured')
        self.assertIsNone(model['affordable']['tasks'])
        self.assertEqual(model['affordable']['binding_window'], 'weekly')
        self.assertAlmostEqual(model['capacity_term'], 0.5)
        self.assertFalse(model['estimate'])

    def test_ollama_reads_a_session_and_a_weekly_window(self):
        model = limit_models.resolve(
            'ollama', 'deepseek-v4.1-flash:1017', now=NOW,
            windows=[dict(WINDOW, kind='session', remaining_ratio=0.8), WINDOW])
        self.assertEqual([row['kind'] for row in model['windows']], ['session', 'weekly'])
        self.assertEqual(model['affordable']['binding_window'], 'weekly')

    def test_claude_is_one_shared_weekly_pool_with_a_fable_sub_cap(self):
        model = limit_models.resolve('claude', 'claude-fable-5', now=NOW,
                                     windows=[dict(WINDOW, kind='weekly', remaining_ratio=0.4)])
        kinds = [row['kind'] for row in model['windows']]
        self.assertEqual(kinds, ['weekly'])
        self.assertEqual(model['sub_cap']['kind'], 'weekly')
        self.assertIn('sub-cap', model['sub_cap']['basis'])

    def test_antigravity_names_its_per_model_runtime_limit(self):
        model = limit_models.resolve('antigravity', 'gemini-4-argon', now=NOW,
                                     windows=[dict(WINDOW, kind='session', remaining_ratio=0.7), WINDOW])
        weekly = next(row for row in model['windows'] if row['kind'] == 'weekly')
        self.assertEqual(weekly['per_model'], 'runtime-limit:<model>')
        self.assertEqual(model['affordable']['binding_window'], 'weekly')

    def test_grok_reads_one_weekly_window(self):
        model = limit_models.resolve('grok', 'grok-4.7', now=NOW,
                                     windows=[dict(WINDOW, remaining_ratio=0.6)])
        self.assertEqual([row['kind'] for row in model['windows']], ['weekly'])
        self.assertEqual(model['affordable']['binding_window'], 'weekly')

    def test_the_free_pool_publishes_minute_daily_and_token_windows(self):
        model = limit_models.resolve('free_pool', 'qwen3.8-max', now=NOW,
                                     windows=[dict(WINDOW, kind='daily', remaining_ratio=0.25)])
        units = [(row['kind'], row['unit']) for row in model['free_pool']]
        self.assertIn(('minute', 'requests'), units)
        self.assertIn(('daily', 'tokens'), units)
        self.assertEqual(model['affordable']['binding_window'], 'daily')


class CostAndUnknownTests(unittest.TestCase):
    def test_cost_is_a_rough_guide_when_no_window_or_inference_exists(self):
        model = limit_models.resolve('grok', 'grok-4.7', now=NOW,
                                     price={'input': 1.0, 'output': 5.0})
        self.assertEqual(model['basis'], 'cost')
        self.assertIsNotNone(model['affordable']['cost_index'])
        self.assertGreater(model['capacity_term'], 0)
        self.assertLess(model['capacity_term'], 1)

    def test_an_unknown_provider_stays_unknown_and_is_never_zero(self):
        model = limit_models.resolve('mystery', 'model', now=NOW)
        self.assertEqual(model['basis'], 'unknown')
        self.assertIsNone(model['capacity_term'])
        self.assertIsNone(model['affordable']['tasks'])
        self.assertFalse(model['estimate'])

    def test_the_score_uses_the_explicit_weights_and_an_override(self):
        model = limit_models.resolve('codex', 'gpt-6.1-sol', now=NOW, windows=[WINDOW])
        breakdown = limit_models.score(0.8, model)
        self.assertEqual(breakdown['weights'], {'quality': 0.6, 'capacity': 0.4})
        self.assertAlmostEqual(breakdown['score'], 0.6 * 0.8 + 0.4 * 0.5)
        override = limit_models.score(0.8, model, policy={
            'model_selection': {'ranking_weights': {'quality': 0.5, 'capacity': 0.5}}})
        self.assertEqual(override['weights'], {'quality': 0.5, 'capacity': 0.5})
        self.assertAlmostEqual(override['score'], 0.65)
        bad = limit_models.score(0.8, model, policy={
            'model_selection': {'ranking_weights': {'quality': -1, 'capacity': 2}}})
        self.assertEqual(bad['weights'], {'quality': 0.6, 'capacity': 0.4})

    def test_quality_only_when_capacity_is_unknown(self):
        model = limit_models.resolve('mystery', 'model', now=NOW)
        breakdown = limit_models.score(0.7, model)
        self.assertEqual(breakdown['score'], 0.7)
        self.assertIn('capacity unknown', breakdown['basis'])
        self.assertIsNone(limit_models.score(None, model))


if __name__ == '__main__':
    unittest.main()
