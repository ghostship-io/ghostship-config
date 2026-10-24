"""The private Command Code usage page: dated windows, no account identifier."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'modules/self-hosted/ai-usage/collector'))

import catalog
import command_code_usage as usage
import limit_models
import main
from metrics import SourceResult

NOW = 1792810000.0
FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'ai-usage'


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


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


class BrowserCheckTests(unittest.TestCase):
    def document(self, now=NOW):
        return usage.document_from_usage(
            fixture('command-code-credits.json'),
            fixture('command-code-subscription.json'),
            fixture('command-code-by-model.json'),
            now=now,
        )

    def test_the_captured_page_responses_yield_the_three_windows(self):
        document = self.document()
        self.assertEqual(document['schema'], usage.SCHEMA)
        self.assertEqual(document['status'], 'ok')
        self.assertEqual([window['kind'] for window in document['windows']],
                         ['session', 'weekly', 'monthly'])
        by_kind = {window['kind']: window for window in document['windows']}
        self.assertAlmostEqual(by_kind['session']['remaining_ratio'], 1 - 0.8274443007 / 14)
        self.assertAlmostEqual(by_kind['weekly']['remaining_ratio'], 1 - 11.7003025875 / 35)
        self.assertAlmostEqual(by_kind['monthly']['remaining_ratio'], 58.2996974125 / 70)
        self.assertEqual(by_kind['weekly']['reset_at'], '2026-10-31T01:14:09Z')
        self.assertEqual(by_kind['monthly']['reset_at'], '2026-11-23T23:36:32.000Z')
        self.assertEqual(document['source'], usage.SOURCE)

    def test_the_document_carries_no_account_or_workspace_identifier(self):
        document = self.document()
        text = json.dumps(document)
        self.assertNotIn('sub_captured', text)
        self.assertNotIn('individual-goat', text)
        self.assertNotIn('workspace', text)
        self.assertNotIn('userId', text)

    def test_only_model_rows_survive_the_tool_rows(self):
        models = {row['model'] for row in self.document()['models']}
        self.assertEqual(models, {'deepseek/deepseek-v4.1-flash', 'claude-sonnet-5-5'})

    def test_a_written_document_becomes_a_measured_window_with_a_reset(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'command-code-usage.json'
        usage.write(path, self.document())
        state = usage.read(NOW, path)
        self.assertFalse(state['stale'])
        rows = usage.windows(state)
        self.assertEqual({row['kind'] for row in rows}, {'session', 'weekly', 'monthly'})
        weekly = next(row for row in rows if row['kind'] == 'weekly')
        self.assertIsNotNone(weekly['resetEpoch'])
        self.assertEqual(weekly['durationSeconds'], 7 * 86400.0)
        self.assertEqual(weekly['observedAtEpoch'], NOW)
        self.assertEqual(weekly['source'], 'command_code_usage')

    def test_a_failed_check_keeps_the_last_good_state(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'command-code-usage.json'
        usage.write(path, self.document())
        before = path.read_text()
        with self.assertRaises(usage.UsageError):
            usage.refresh(NOW + 60, path, lambda: {'credits': {}, 'subscription': {}})
        self.assertEqual(path.read_text(), before)

    def test_the_launcher_envelope_is_decoded_once(self):
        payload = {'credits': {'windowLimits': {}}, 'subscription': {}, 'by_model': None}
        for result in (json.dumps(payload), json.dumps(json.dumps(payload))):
            envelope = json.dumps({'ok': True, 'result': result})
            self.assertEqual(usage.parse_check_output(envelope)['credits'], {'windowLimits': {}})
        note = '\nnote: the script returned a STRING containing JSON'
        envelope = json.dumps({'ok': True, 'result': json.dumps(json.dumps(payload))})
        self.assertEqual(usage.parse_check_output(envelope + note)['credits'], {'windowLimits': {}})
        with self.assertRaises(usage.UsageError):
            usage.parse_check_output('{"ok": false}')

    def test_the_snapshot_reports_the_command_code_candidate_usage(self):
        document = self.document()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'command-code-usage.json'
        usage.write(path, document)
        source = usage.windows(usage.read(NOW, path))
        context = {
            'offered_models': [('commandCode', 'deepseek/deepseek-v4.1-flash')],
            'native_models': {
                ('commandCode', 'deepseek/deepseek-v4.1-flash'): {
                    'providerInstance': 'opencode',
                    'modelId': 'command-code/deepseek/deepseek-v4.1-flash',
                    'available': True,
                }
            },
        }
        results = [SourceResult(source='command_code_usage', status='ok', reason='ok',
                                observed_at=NOW, windows=source)]
        _, ranked = main.ranking_samples(
            results,
            catalog.Catalog({}),
            context,
            NOW,
            t3_home=directory.name,
            t3_state=str(Path(directory.name) / 'state.sqlite'),
            state_path=str(Path(directory.name) / 'ranking.json'),
        )
        snapshot = main.build_snapshot(
            results,
            ranked,
            context,
            NOW,
            measured_windows=source,
            catalog=catalog.Catalog({}),
        )
        candidate = next(row for row in snapshot['candidates']
                         if row['model'] == 'deepseek/deepseek-v4.1-flash')
        self.assertEqual(candidate['quota_state'], 'available')
        self.assertAlmostEqual(candidate['capacity']['remaining_ratio'],
                               1 - 11.7003025875 / 35, places=3)
        self.assertEqual(candidate['capacity']['capacity_binding']['kind'], 'weekly')
        self.assertTrue(candidate['capacity']['capacity_binding']['reset_at'])


if __name__ == '__main__':
    unittest.main()
