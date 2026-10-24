"""The dated OpenCode Go table, its allowance pick and the assume-latest binder."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'modules/self-hosted/ai-usage/collector'))

import aa_bind
import main
import model_selection
import opencode_go

NOW = 1792810000.0

PAGE = """<!doctype html><html><body>
<link rel="modulepreload" href="/_build/assets/index-TESTHASH.js">
<div data-slot="faq-model-table"><table><tbody>
<tr><td>DeepSeek V4.1 Flash</td><td>Not used</td><td>0 days</td></tr>
<tr><td>MiMo-V2.6-Pro</td><td>Not used</td><td>0 days</td></tr>
<tr><td>Gemini 4 Argon Contributor</td><td>Used</td><td>Not ZDR</td></tr>
<tr><td>Muse Spark 1.3 Contributor</td><td>Used</td><td>Not ZDR</td></tr>
<tr><td>LongCat 2.5 Preview Free</td><td>Not used</td><td>0 days</td></tr>
</tbody></table></div></body></html>"""

CHUNK = """const goModels = [{
  id: "deepseek-flash", name: "DeepSeek V4.1 Flash", requests: 34670, allowance: 80, featured: true
}, {
  id: "mimo-v2.6-pro", name: "MiMo-V2.6-Pro", requests: 3250, allowance: 15
}, {
  id: "gemini-4-argon-contributor", name: "Gemini 4 Argon Contributor", requests: 440, allowance: 60, bonus: 2
}, {
  id: "muse-spark-1.3-contributor", name: "Muse Spark 1.3 Contributor", requests: 45300, allowance: 60
}, {
  id: "longcat-2.5-preview-free", name: "LongCat 2.5 Preview Free", requests: Infinity, allowance: Infinity, limitedTime: true
}];
const plusLimits = {
  "deepseek-flash": [69330, 160],
  "mimo-v2.6-pro": [13e3, 60],
  "gemini-4-argon-contributor": [1760, 240],
  "muse-spark-1.3-contributor": [90600, 120],
  "longcat-2.5-preview-free": [Infinity, Infinity]
};"""


def http_ok(url):
    body = PAGE if url == opencode_go.PAGE_URL else CHUNK
    from util import HttpResult
    return HttpResult(200, body.encode())


def http_fail(url):
    from util import HttpResult
    return HttpResult(503, b"")


def read_once(path, now=NOW, http=http_ok):
    opencode_go.refresh(now, path, http=http)
    return opencode_go.read(now, path)


def candidate(state, model, quality, mapped=True):
    entry = opencode_go.lookup(state, model)
    return {
        'provider': 'opencode-go', 'model': model, 'display_name': model,
        'available': True, 'quota_state': 'available', 'capacity': {'remaining_ratio': 1},
        'quality_score': quality, 'quality_p': quality / 100, 'quality_basis': 'AA only',
        'access': {'billing': 'subscription'},
        'native': ({'mapped': True, 'provider_instance_id': 'opencode', 'model_id': model,
                    'available': True, 'options': [{'id': 'effort', 'values': ['low', 'high']}]}
                   if mapped else {'mapped': False}),
        'allowance': opencode_go.allowance_record(entry),
    }


class ParserTests(unittest.TestCase):
    def test_the_whole_table_and_the_retention_policy_are_read(self):
        models = opencode_go.parse_models(CHUNK)
        retention = opencode_go.parse_retention(PAGE)
        self.assertEqual(len(models), 5)
        deepseek = models['deepseek-flash']
        self.assertEqual((deepseek['go_requests_5h'], deepseek['go_allowance_usd']), (34670.0, 80.0))
        self.assertEqual((deepseek['plus_requests_5h'], deepseek['plus_allowance_usd']), (69330.0, 160.0))
        # The monthly figure is the published five-hour figure divided by 20%.
        self.assertEqual(deepseek['go_requests_month'], 173350.0)
        self.assertEqual(models['mimo-v2.6-pro']['go_requests_5h'], 3250.0)
        self.assertTrue(models['longcat-2.5-preview-free']['unlimited'])
        self.assertIsNone(models['longcat-2.5-preview-free']['go_requests_5h'])
        self.assertEqual(retention['Gemini 4 Argon Contributor']['training'], 'used')
        self.assertEqual(retention['Gemini 4 Argon Contributor']['retention'], 'not_zdr')
        self.assertEqual(retention['DeepSeek V4.1 Flash']['retention'], 0)

    def test_the_hash_is_resolved_and_never_hardcoded(self):
        self.assertEqual(opencode_go.chunk_url(PAGE),
                         'https://opencode.ai/_build/assets/index-TESTHASH.js')
        self.assertEqual(opencode_go.chunk_url('<html></html>'), '')

    def test_a_route_is_matched_by_id_or_display_name_only(self):
        models = opencode_go.parse_models(CHUNK)
        state = {'models': models, 'source': opencode_go.PAGE_URL}
        self.assertEqual(opencode_go.lookup(state, 'deepseek-v4.1-flash')['id'], 'deepseek-flash')
        self.assertEqual(opencode_go.lookup(state, 'mimo-v2.6-pro')['id'], 'mimo-v2.6-pro')
        self.assertIsNone(opencode_go.lookup(state, 'deepseek-v4.1-pro'))
        self.assertIsNone(opencode_go.lookup(state, 'flash'))


class CacheTests(unittest.TestCase):
    def test_a_failed_refresh_keeps_the_last_dates_and_marks_them_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'go.json'
            fresh = read_once(path)
            self.assertFalse(fresh['stale'])
            self.assertEqual(fresh['checked_at'], '2026-10-24T02:46:40Z')
            checked = fresh['checked_at']
            stale = read_once(path, now=NOW + opencode_go.MAX_AGE_SECONDS + 1, http=http_fail)
            self.assertTrue(stale['stale'])
            self.assertEqual(stale['checked_at'], checked)
            self.assertEqual(len(stale['models']), 5)
            # A failure is not retried on every five-minute collection.
            retried = read_once(path, now=NOW + opencode_go.MAX_AGE_SECONDS + 2,
                                http=lambda url: self.fail('the page was fetched again'))
            self.assertTrue(retried['stale'])
            self.assertEqual(retried['checked_at'], checked)

    def test_a_fresh_reading_is_not_fetched_again(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'go.json'
            read_once(path)
            again = read_once(path, now=NOW + 60,
                              http=lambda url: self.fail('a fresh reading must not fetch'))
            self.assertFalse(again['stale'])


class AssumedLatestTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {'id': 'deepseek-v4-1-flash-0929', 'slug': 'deepseek-v4-1-flash-0929',
             'model': 'DeepSeek V4.1 Flash 0929', 'release_date': '2026-09-29',
             'indices': {'intelligence_index': 44.0}, 'cost_per_task': 1.0},
            {'id': 'deepseek-v4-1-flash-1017', 'slug': 'deepseek-v4-1-flash-1017',
             'model': 'DeepSeek V4.1 Flash 1017', 'release_date': '2026-10-17',
             'indices': {'intelligence_index': 45.1}, 'cost_per_task': 1.0},
        ]

    def test_an_undated_id_binds_to_the_newest_dated_record(self):
        binding = aa_bind.resolve(self.records, 'opencode-go', 'deepseek-v4.1-flash',
                                  mode='reference', latest=True,
                                  evidence=[{'source': 'vendor', 'build': '1017'}])
        self.assertEqual(binding['state'], 'measured')
        self.assertEqual(binding['id'], 'deepseek-v4-1-flash-1017')
        self.assertTrue(binding['assumed_latest'])
        self.assertEqual(binding['assumption_basis'], 'assumed latest (owner rule)')
        self.assertEqual(binding['evidence'], [{'source': 'vendor', 'build': '1017'}])

    def test_a_dated_id_stays_exact(self):
        older = aa_bind.resolve(self.records, 'opencode-go', 'deepseek-v4.1-flash-0929',
                                mode='reference', latest=True)
        self.assertEqual(older['id'], 'deepseek-v4-1-flash-0929')
        self.assertFalse(older.get('assumed_latest', False))
        newer = aa_bind.resolve(self.records, 'opencode-go', 'deepseek-v4.1-flash-1017',
                                mode='reference', latest=True)
        self.assertEqual(newer['id'], 'deepseek-v4-1-flash-1017')

    def test_an_alias_binds_through_the_same_family(self):
        binding = aa_bind.resolve(self.records, 'opencode-go', 'deepseek-v4-1-flash',
                                  mode='reference', latest=True)
        self.assertEqual(binding['id'], 'deepseek-v4-1-flash-1017')


class AllowancePickTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.state = read_once(Path(directory.name) / 'go.json')

    def build(self, models):
        candidates = [candidate(self.state, model, quality) for model, quality in models]
        return model_selection.build(
            {'generated_at': '2026-10-24T02:46:40Z', 'candidates': candidates}, [])

    def test_quality_is_weighed_against_the_affordable_allowance(self):
        result = self.build([('deepseek-v4.1-flash', 45.1), ('mimo-v2.6-pro', 46.3)])
        rows = {row['model']: row for row in result['worker']}
        deepseek, mimo = rows['deepseek-v4.1-flash'], rows['mimo-v2.6-pro']
        self.assertGreater(deepseek['pick_score']['score'], mimo['pick_score']['score'])
        self.assertEqual(deepseek['binding_window'], 'session')
        self.assertIn('binding session', deepseek['pick_reason'])
        self.assertIn('34,670', deepseek['pick_reason'])
        self.assertEqual(result['default_worker']['model'], 'deepseek-v4.1-flash')
        self.assertEqual(result['providers']['opencode-go']['selected']['worker']['model'],
                         'deepseek-v4.1-flash')
        self.assertTrue(deepseek['reason'].startswith('pick: '))
        self.assertIn('binding session', deepseek['reason'])

    def test_a_measured_window_becomes_the_binding_capacity(self):
        result = self.build([('deepseek-v4.1-flash', 45.1), ('mimo-v2.6-pro', 46.3)])
        windows = [{'kind': 'monthly', 'quota_id': 'monthly', 'remaining_ratio': 0.1,
                    'check_at': '2026-10-24T02:40:00Z', 'reset_at': '2026-11-01T00:00:00Z',
                    'source': 'opencode-go'}]
        # The monthly window leaves a tenth of its budget (17,335 requests);
        # the session window is still fully available (34,670), so the
        # monthly share binds before the next reset.
        deepseek = next(row for row in result['worker'] if row['model'] == 'deepseek-v4.1-flash')
        picked = model_selection.allowance.affordable(deepseek['allowance'], windows)
        self.assertEqual(picked['binding_window'], 'monthly')
        self.assertAlmostEqual(picked['affordable_requests'], 17335.0)
        mimo = next(row for row in result['worker'] if row['model'] == 'mimo-v2.6-pro')
        self.assertAlmostEqual(
            model_selection.allowance.affordable(mimo['allowance'], windows)['affordable_requests'],
            1625.0)

    def test_models_trained_on_prompts_stay_out_of_internal_work(self):
        result = self.build([('deepseek-v4.1-flash', 45.1),
                             ('gemini-4-argon-contributor', 60),
                             ('muse-spark-1.3-contributor', 50)])
        rows = {row['model']: row for row in result['worker']}
        self.assertFalse(rows['gemini-4-argon-contributor']['selection_eligible'])
        self.assertFalse(rows['muse-spark-1.3-contributor']['selection_eligible'])
        self.assertEqual(rows['gemini-4-argon-contributor']['selection_reason'],
                         'data policy: training used or not ZDR')
        self.assertFalse(rows['gemini-4-argon-contributor']['data_policy']['sensitive_ok'])
        self.assertIs(rows['deepseek-v4.1-flash']['data_policy']['sensitive_ok'], True)

    def test_a_route_without_a_published_number_has_no_allowance(self):
        result = self.build([('deepseek-v4.1-flash', 45.1)])
        row = result['worker'][0]
        self.assertEqual(row['allowance']['requests_5h'], 34670.0)
        entry = opencode_go.lookup(self.state, 'deepseek-v4.1-flash')
        self.assertIsNone(entry.get('unknown_number', None))
        self.assertIsNone(opencode_go.lookup(self.state, 'not-in-the-table'))


class SnapshotAttachmentTests(unittest.TestCase):
    def test_the_snapshot_publishes_allowance_health_and_the_route_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            state = read_once(Path(directory) / 'go.json')
        snapshot = {'candidates': [
            {'provider': 'opencode-go', 'model': 'deepseek-v4.1-flash', 'quality_p': 0.451},
            {'provider': 'codex', 'model': 'gpt-6.1-sol'},
        ]}
        main._attach_opencode_go(snapshot, state)
        health = snapshot['opencode_go']
        self.assertFalse(health['stale'])
        self.assertEqual(health['models'], 5)
        deepseek = snapshot['candidates'][0]
        self.assertEqual(deepseek['allowance']['requests_5h'], 34670.0)
        self.assertEqual(deepseek['aa_evidence'][0]['build'], '1017')
        self.assertNotIn('allowance', snapshot['candidates'][1])


if __name__ == '__main__':
    unittest.main()
