"""The public page refresh: validate, diff and keep the last good rows."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'modules/self-hosted/ai-usage/collector'))

import limit_pages

NOW = 1792810000.0
GO = {'provider': 'opencode-go', 'model': 'deepseek-v4.1-flash', 'window': 'session',
      'budget': 34670, 'unit': 'requests', 'estimate': False, 'source': limit_pages.PAGES['opencode-go']}


class ExtractionTests(unittest.TestCase):
    def test_a_fenced_json_answer_is_parsed(self):
        rows = limit_pages.parse('```json\n' + json.dumps({'rows': [GO]}) + '\n```')
        self.assertEqual(rows, [GO])

    def test_a_bare_list_is_accepted(self):
        self.assertEqual(limit_pages.parse(json.dumps([GO])), [GO])

    def test_garbage_is_empty_and_never_an_invented_row(self):
        self.assertEqual(limit_pages.parse('the page did not publish a table'), [])

    def test_validation_keeps_only_bounded_well_typed_rows(self):
        rows = limit_pages.validate([
            GO,
            {**GO, 'window': 'fortnight'},
            {**GO, 'unit': 'bananas'},
            {**GO, 'budget': -1},
            {**GO, 'budget': 'many'},
            {**GO, 'provider': 'other'},
            {**GO, 'model': ''},
        ], 'opencode-go', limit_pages.PAGES['opencode-go'])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['budget'], 34670.0)
        self.assertFalse(rows[0]['estimate'])


class RefreshTests(unittest.TestCase):
    def test_valid_rows_replace_the_page_and_garbage_keeps_the_last_good(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pages.json'

            def good(provider, url):
                if provider == 'opencode-go':
                    return json.dumps({'rows': [GO]})
                return 'not a table'

            first = limit_pages.refresh(NOW, path, good)
            self.assertEqual(len(first['rows']), 1)
            self.assertEqual(first['sources']['opencode-go']['status'], 'ok')
            self.assertEqual(first['sources']['commandCode']['status'], 'unavailable')
            self.assertEqual(first['changed']['added'], 1)

            def all_fail(provider, url):
                raise RuntimeError('the pool is unavailable')

            second = limit_pages.refresh(NOW + 100, path, all_fail)
            self.assertEqual(second['rows'], first['rows'])
            self.assertEqual(second['sources']['opencode-go']['status'], 'stale')
            self.assertTrue(second['stale'])

    def test_a_changed_value_is_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pages.json'
            limit_pages.refresh(NOW, path, lambda p, u: json.dumps({'rows': [GO]}))
            changed = dict(GO, budget=40000)
            state = limit_pages.refresh(NOW + 100, path, lambda p, u: json.dumps({'rows': [changed]}))
            self.assertEqual(state['changed']['changed'], 1)
            self.assertEqual(state['changed']['added'], 0)

    def test_the_reading_is_stale_after_twelve_hours(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pages.json'

            def every_page(provider, url):
                return json.dumps({'rows': [{**GO, 'provider': provider, 'source': url}]})

            limit_pages.refresh(NOW, path, every_page)
            self.assertFalse(limit_pages.read(NOW + 60, path)['stale'])
            self.assertTrue(limit_pages.read(NOW + limit_pages.MAX_AGE_SECONDS + 1, path)['stale'])

    def test_rows_match_the_exact_model_and_the_wildcard(self):
        state = {'rows': [GO, {**GO, 'model': '*', 'window': 'monthly'}]}
        self.assertEqual(len(limit_pages.rows_for(state, 'opencode-go', 'deepseek-v4.1-flash')), 2)
        self.assertEqual(len(limit_pages.rows_for(state, 'opencode-go', 'other')), 1)
        self.assertEqual(limit_pages.rows_for(state, 'codex', 'gpt-6.1-sol'), [])


if __name__ == '__main__':
    unittest.main()
