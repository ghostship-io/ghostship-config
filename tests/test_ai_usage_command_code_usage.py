"""The private Command Code usage page: dated windows, no account identifier."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'modules/self-hosted/ai-usage/collector'))

import command_code_usage as usage
import limit_models

NOW = 1792810000.0
DOCUMENT = {
    'schema': usage.SCHEMA,
    'status': 'ok',
    'checked_at': '2026-10-24T02:40:00Z',
    'checked_at_epoch': NOW - 60,
    'source': 'the owner signed-in usage page',
    'workspace': 'must-not-leak',
    'windows': [
        {'kind': 'five_hour', 'remaining_ratio': 0.99, 'reset_at': '2026-10-24T07:00:00Z'},
        {'kind': 'weekly', 'remaining_ratio': 0.99, 'reset_at': '2026-10-30T00:00:00Z'},
        {'kind': 'monthly', 'remaining_ratio': 1.0, 'reset_at': '2026-11-01T00:00:00Z'},
    ],
    'models': [
        {'model': 'deepseek/deepseek-v4.1-flash', 'requests': 12, 'tokens': 9000, 'cost_usd': 0.12},
    ],
}


class UsagePageTests(unittest.TestCase):
    def write(self, document):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'usage.json'
        path.write_text(json.dumps(document))
        return path

    def test_the_three_windows_and_the_model_rows_are_read(self):
        state = usage.read(NOW, self.write(DOCUMENT))
        self.assertEqual(state['status'], 'ok')
        self.assertFalse(state['stale'])
        self.assertEqual({row['kind'] for row in state['windows']}, {'session', 'weekly', 'monthly'})
        self.assertEqual(state['models'][0]['requests'], 12.0)
        self.assertEqual(state['models'][0]['cost_usd'], 0.12)

    def test_no_workspace_or_account_identifier_leaves_the_reader(self):
        state = usage.read(NOW, self.write(DOCUMENT))
        self.assertNotIn('workspace', state)
        self.assertNotIn('must-not-leak', json.dumps(state))

    def test_a_missing_file_is_not_a_zero(self):
        state = usage.read(NOW, '/nonexistent/command-code-usage.json')
        self.assertTrue(state['stale'])
        self.assertEqual(state['windows'], [])
        self.assertEqual(usage.windows(state), [])

    def test_a_stale_reading_does_not_become_a_measured_window(self):
        state = usage.read(NOW + usage.MAX_AGE_SECONDS + 1, self.write(DOCUMENT))
        self.assertTrue(state['stale'])
        self.assertEqual(usage.windows(state), [])

    def test_measured_windows_beat_the_published_estimate(self):
        state = usage.read(NOW, self.write(DOCUMENT))
        windows = usage.windows(state)
        model = limit_models.resolve('commandCode', 'deepseek/deepseek-v4.1-flash', now=NOW,
                                     windows=windows)
        self.assertEqual(model['basis'], 'discovered')
        self.assertEqual(model['affordable']['binding_window'], 'session')
        self.assertAlmostEqual(model['affordable']['tasks'], 41000.0 * 0.99)


if __name__ == '__main__':
    unittest.main()
