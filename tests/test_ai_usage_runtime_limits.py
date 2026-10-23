"""A completed Antigravity quota notice must never authorize another pick."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                       'modules/self-hosted/ai-usage/collector'))
import catalog
import main
import quota
import runtime_state
from metrics import SourceResult

NOW = 1_800_000_000.0
NOTICE = ('Usage Limit Reached\n\nYou have reached your current quota for this period. '
          'Your limit will reset in 6 days, 22 hours.')


def iso(moment):
    return datetime.fromtimestamp(moment, timezone.utc).isoformat()


class RuntimeLimitsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'state.sqlite'
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE orchestration_v2_projection_runs '
                       '(run_id TEXT, provider_instance_id TEXT, payload_json TEXT)')
            db.execute('CREATE TABLE orchestration_v2_projection_messages '
                       '(run_id TEXT, role TEXT, streaming INTEGER, created_at TEXT, payload_json TEXT)')

    def message(self, text=NOTICE, model='gemini-4-argon', at=NOW, role='assistant',
                instance='antigravity', streaming=0, selected=True):
        with sqlite3.connect(self.path) as db:
            key = str(db.execute('SELECT COUNT(*) FROM orchestration_v2_projection_runs').fetchone()[0])
            selection = {'instanceId': instance, 'model': model} if selected else {}
            db.execute('INSERT INTO orchestration_v2_projection_runs VALUES (?,?,?)',
                       (key, instance, json.dumps({'modelSelection': selection, 'status': 'completed'})))
            db.execute('INSERT INTO orchestration_v2_projection_messages VALUES (?,?,?,?,?)',
                       (key, role, streaming, iso(at), json.dumps({'text': text})))

    def test_completed_limit_notice_has_anchored_reset_and_exact_model(self):
        self.message()
        self.message(NOTICE.replace('6 days, 22 hours', '5 days, 6 hours'), model='gemini-3.8-flash')
        windows = runtime_state.read_limit_windows(self.path, NOW + 60)
        self.assertEqual(len(windows), 2)
        by_model = {w['model']: w for w in windows}
        argon = by_model['gemini-4-argon']
        self.assertEqual(argon['resetEpoch'], NOW + 6 * 86400 + 22 * 3600)
        self.assertEqual(argon['observedAtEpoch'], NOW)
        self.assertEqual(argon['appliesTo'], ['gemini-4-argon'])
        self.assertEqual(argon['usedRatio'], 1)
        self.assertEqual(argon['source'], 't3_runtime')
        self.assertNotEqual(argon['resetEpoch'], by_model['gemini-3.8-flash']['resetEpoch'])
        self.assertNotIn(NOTICE, json.dumps(windows))

    def test_notice_stays_spent_after_freshness_cutoff_but_expires_at_reset(self):
        self.message()
        window = runtime_state.read_limit_windows(self.path, NOW + 2 * 86400)[0]
        self.assertTrue(quota.current_reading(window, NOW + 2 * 86400))
        self.assertEqual(runtime_state.read_limit_windows(self.path, window['resetEpoch']), [])

    def test_prompt_quotes_other_providers_streaming_and_missing_identity_cannot_block(self):
        for kwargs in ({'role': 'user'}, {'instance': 'codex'}, {'streaming': 1},
                       {'selected': False}, {'at': NOW + 3600},
                       {'text': 'The test should handle: ' + NOTICE},
                       {'text': NOTICE + '\nExample quoted in an explanation.'},
                       {'text': NOTICE.replace('6 days, 22 hours', '99 days')},
                       {'text': NOTICE.replace('6 days, 22 hours', '0 seconds')}):
            self.message(**kwargs)
        self.assertEqual(runtime_state.read_limit_windows(self.path, NOW), [])

    def test_repeated_poll_does_not_slide_reset_and_other_model_success_cannot_release(self):
        self.message(at=NOW - 120)
        self.message(text='Task completed.', model='gemini-3.8-flash')
        first = runtime_state.read_limit_windows(self.path, NOW)
        later = runtime_state.read_limit_windows(self.path, NOW + 3600)
        self.assertEqual(first, later)

    def test_real_ranking_snapshot_and_selection_keep_notice_spent(self):
        self.message()
        moment = NOW + 2 * 86400
        context = {'offered_models': [('antigravity', 'gemini-4-argon'), ('codex', 'gpt-6.1-sol')],
                   'native_models': {('antigravity', 'gemini-4-argon'): {
                       'providerInstance': 'antigravity', 'modelId': 'gemini-4-argon',
                       'available': True}, ('codex', 'gpt-6.1-sol'): {
                           'providerInstance': 'codex', 'modelId': 'gpt-6.1-sol', 'available': True}}}
        price_catalog = catalog.Catalog({'openai': {'models': {'gpt-6.1-sol': {
            'cost': {'input': 1, 'output': 2}}}}})
        # The direct endpoint still claims a little headroom. A timed denial
        # cannot be erased by an optimistic reading from another surface.
        results = [SourceResult(source='antigravity', status='ok', windows=[{
            'provider': 'antigravity', 'account': 'default', 'model': 'gemini-4-argon',
            'kind': 'quota', 'quotaId': 'quotaInfo', 'usedRatio': .999,
            'resetEpoch': NOW + 7 * 86400, 'observedAtEpoch': moment}])]
        _, ranked = main.ranking_samples(results, price_catalog, context, moment,
                                        t3_home=self.folder.name, t3_state=str(self.path),
                                        state_path=str(Path(self.folder.name) / 'ranking.json'))
        measured = [w for result in results for w in result.windows]
        snapshot = main.build_snapshot(results, ranked, context, moment,
                                       measured_windows=measured, catalog=price_catalog)
        worker = next(r for r in snapshot['model_selection']['worker']
                      if r['model'] == 'gemini-4-argon')
        self.assertFalse(worker['available'])
        self.assertEqual(worker['state'], 'exhausted')
        self.assertEqual(worker['limiting_window']['remaining_ratio'], 0)
        self.assertEqual(worker['limiting_window']['source'], 't3_runtime')
        self.assertEqual(worker['limiting_window']['reset_at'],
                         '2027-01-22T06:00:00Z')
        self.assertEqual(snapshot['model_selection']['default_worker'],
                         {'instanceId': 'codex', 'model': 'gpt-6.1-sol'})
        self.assertIsNone(snapshot['model_selection']['providers']['antigravity']['selected']['worker'])


if __name__ == '__main__':
    unittest.main()
