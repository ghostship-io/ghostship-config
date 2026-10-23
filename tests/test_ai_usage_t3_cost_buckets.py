"""Provider history uses T3's cost and token arithmetic, never catalog estimates."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                       'modules/self-hosted/ai-usage/collector'))
import t3source


class T3CostBucketsTests(unittest.TestCase):
    def test_actual_t3_costs_survive_and_reasoning_tokens_are_not_counted_twice(self):
        rows = [{'day': '2026-01-01', 'provider': 'opencode',
                 'model': 'ollama-cloud/model:1017', 'sourcePath': '/private/history',
                 'costUsd': 1.2345, 'costSource': 'providerReported',
                 'totals': {'uncachedInputTokens': 100, 'cachedInputTokens': 20,
                            'cacheCreationTokens': 10, 'outputTokens': 40, 'reasoningTokens': 30}},
                {'day': '2026-01-01', 'provider': 'opencode',
                 'model': 'ollama-cloud/model:1017', 'costUsd': .25, 'costSource': 'modelPriced',
                 'totals': {'outputTokens': 5}},
                {'day': '2026-01-02', 'provider': 'codex', 'model': 'unpriced',
                 'costUsd': None, 'costSource': 'unpriced', 'unpricedRecords': 2,
                 'totals': {'outputTokens': 5}}]
        samples = t3source.usage_bucket_samples(rows, 'UTC')
        tokens = [(labels, n) for name, labels, n in samples if name.endswith('_tokens')]
        total = next(n for labels, n in tokens if labels['provider'] == 'ollama' and labels['kind'] == 'total')
        self.assertEqual(total, 175)
        costs = [(labels, n) for name, labels, n in samples if name.endswith('_cost_usd')]
        self.assertAlmostEqual(sum(n for _, n in costs), 1.4845)
        self.assertFalse(any(labels['model'] == 'unpriced' for labels, _ in costs))
        self.assertEqual({labels['basis'] for labels, _ in costs}, {'provider_reported', 'api_equivalent'})
        self.assertNotIn('/private/history', str(samples))
        self.assertTrue(all(labels['day'] in ('2026-01-01', '2026-01-02') for _, labels, _ in samples))

    def test_invalid_dates_and_nonfinite_or_negative_money_never_become_usage(self):
        for day, cost in (('not-a-day', 2), ('2026-01-01', float('nan')),
                          ('2026-01-01', -1), ('2026-01-01', True)):
            samples = t3source.usage_bucket_samples([{'day': day, 'provider': 'codex', 'model': 'example',
                'costSource': 'providerReported', 'costUsd': cost, 'totals': {}}], 'UTC')
            self.assertFalse(any(name.endswith('_cost_usd') for name, _, _ in samples))
