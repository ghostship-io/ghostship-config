"""A completed Antigravity quota notice must never authorize another pick."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

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
# The 5-hour window, as the same notice names it when the short window is spent.
SHORT_NOTICE = ('Usage Limit Reached\n\nYou have reached your current quota for this period. '
                'Your limit will reset in 3 hours, 45 minutes.')
# The captured notices: the fields the reader reads, with the thread, run and
# message identifiers removed. They are the live shapes of the two windows.
CAPTURED = Path(__file__).resolve().parent / 'fixtures' / 'ai-usage' / 'antigravity-notices.json'


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

    def test_a_short_notice_carries_the_five_hour_reset_and_the_long_one_the_weekly_reset(self):
        self.message(text=SHORT_NOTICE)
        self.message(text=NOTICE)
        windows = {w['quotaId']: w for w in runtime_state.read_limit_windows(self.path, NOW + 60)}
        short = windows['runtime-limit-5h:gemini-4-argon']
        weekly = windows['runtime-limit:gemini-4-argon']
        self.assertEqual(short['kind'], 'session')
        self.assertEqual(short['durationSeconds'], 5 * 3600)
        self.assertEqual(short['resetEpoch'], NOW + 3 * 3600 + 45 * 60)
        self.assertEqual(weekly['kind'], 'weekly')
        self.assertEqual(weekly['durationSeconds'], 7 * 86400)
        self.assertEqual(weekly['resetEpoch'], NOW + 6 * 86400 + 22 * 3600)

    def test_the_weekly_notice_has_a_pace_and_the_short_one_has_none(self):
        self.message(text=SHORT_NOTICE)
        self.message(text=NOTICE)
        windows = {w['quotaId']: w for w in runtime_state.read_limit_windows(self.path, NOW + 60)}
        self.assertIsNone(quota.window_pace(windows['runtime-limit-5h:gemini-4-argon'], NOW + 60))
        pace = quota.window_pace(windows['runtime-limit:gemini-4-argon'], NOW + 60)
        self.assertIsNotNone(pace)
        self.assertEqual(pace['duration_seconds'], 7 * 86400)

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


class RuntimeSourceObservationTests(unittest.TestCase):
    """The runtime source is dated by the state read, not by an old notice.

    A provider notice stays in force for its whole window, but the state it
    was read from keeps moving. The source's observation is the newest run
    the read found, and every window keeps the notice's own observation.
    """

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'state.sqlite'
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE orchestration_v2_projection_runs '
                       '(run_id TEXT, thread_id TEXT, provider TEXT, '
                       'provider_instance_id TEXT, status TEXT, requested_at TEXT, '
                       'completed_at TEXT, payload_json TEXT)')
            db.execute('CREATE TABLE orchestration_v2_projection_messages '
                       '(run_id TEXT, role TEXT, streaming INTEGER, created_at TEXT, payload_json TEXT)')
            db.execute('CREATE TABLE orchestration_v2_projection_run_attempts '
                       '(thread_id TEXT, run_id TEXT, provider TEXT, '
                       'provider_instance_id TEXT, status TEXT, payload_json TEXT)')
            db.execute('CREATE TABLE projection_thread_sessions '
                       '(thread_id TEXT, last_error TEXT)')
            db.execute('CREATE TABLE provider_session_runtime '
                       '(thread_id TEXT, runtime_payload_json TEXT)')

    def notice(self, at):
        with sqlite3.connect(self.path) as db:
            db.execute(
                'INSERT INTO orchestration_v2_projection_runs VALUES (?,?,?,?,?,?,?,?)',
                ('run-notice', 'thread-notice', 'antigravity', 'antigravity',
                 'completed', iso(at), iso(at),
                 json.dumps({'modelSelection': {'instanceId': 'antigravity',
                                                'model': 'gemini-4-argon'}})),
            )
            db.execute(
                'INSERT INTO orchestration_v2_projection_messages VALUES (?,?,?,?,?)',
                ('run-notice', 'assistant', 0, iso(at), json.dumps({'text': NOTICE})),
            )

    def recent_run(self, run_id, at, instance='codex', model='gpt-6.1-sol'):
        with sqlite3.connect(self.path) as db:
            db.execute(
                'INSERT INTO orchestration_v2_projection_runs VALUES (?,?,?,?,?,?,?,?)',
                (run_id, 'thread-' + run_id, instance, instance, 'completed',
                 iso(at), iso(at),
                 json.dumps({'modelSelection': {'instanceId': instance, 'model': model}})),
            )

    def rank(self):
        results = []
        catalog_module = catalog.Catalog({})
        context = {'offered_models': [('antigravity', 'gemini-4-argon')],
                   'native_models': {}}
        samples, ranked = main.ranking_samples(
            results, catalog_module, context, NOW,
            t3_home=self.folder.name, t3_state=str(self.path),
            state_path=str(Path(self.folder.name) / 'ranking.json'),
        )
        runtime = next(result for result in results if result.source == 't3_runtime')
        measured = [window for result in results for window in result.windows]
        snapshot = main.build_snapshot(results, ranked, context, NOW,
                                       measured_windows=measured,
                                       catalog=catalog_module)
        return runtime, snapshot

    def test_the_state_connection_keeps_its_sort_in_memory(self):
        connection = runtime_state._connect(self.path)
        self.addCleanup(connection.close)
        # A temporary file would land on the read-only service sandbox.
        self.assertEqual(connection.execute("PRAGMA temp_store").fetchone()[0], 2)
        self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)

    def test_a_current_run_dates_the_source_while_the_notice_keeps_its_own_time(self):
        notice_at = NOW - 200_000
        run_at = NOW - 45
        self.notice(notice_at)
        self.recent_run('run-current', run_at)
        runtime, snapshot = self.rank()
        self.assertEqual(runtime.status, 'ok')
        self.assertEqual(runtime.observed_at, run_at)
        self.assertLessEqual(NOW - runtime.observed_at, 900)
        # The window is still spent from the notice, and its time never moves.
        self.assertEqual(runtime.windows[0]['observedAtEpoch'], notice_at)
        coverage = next(source for source in snapshot['coverage']['sources']
                        if source['id'] == 't3_runtime')
        self.assertEqual(coverage['status'], 'ok')
        self.assertLessEqual(coverage['age_seconds'], 900)

    def test_without_a_current_run_the_source_keeps_the_notices_real_age(self):
        notice_at = NOW - 200_000
        self.notice(notice_at)
        runtime, snapshot = self.rank()
        self.assertEqual(runtime.status, 'ok')
        # No clock is assigned to the old notice: its own time is the reading,
        # and the age that follows is the real age.
        self.assertEqual(runtime.observed_at, notice_at)
        self.assertGreater(NOW - runtime.observed_at, 900)
        coverage = next(source for source in snapshot['coverage']['sources']
                        if source['id'] == 't3_runtime')
        self.assertEqual(coverage['age_seconds'], NOW - notice_at)

    def test_a_run_dated_ahead_of_the_collection_is_not_the_source_time(self):
        self.recent_run('run-past', NOW - 120)
        self.recent_run('run-future', NOW + 45)
        observations = runtime_state.read_observations(self.path, NOW)
        self.assertEqual(observations['status'], 'ok')
        self.assertEqual(observations['observed_at'], NOW - 120)

    def test_a_missing_state_is_reported_and_never_stamped_fresh(self):
        absent = str(Path(self.folder.name) / 'absent.sqlite')
        results = []
        main.ranking_samples(results, catalog.Catalog({}), {}, NOW,
                             t3_home=self.folder.name, t3_state=absent,
                             state_path=str(Path(self.folder.name) / 'ranking.json'))
        runtime = next(result for result in results if result.source == 't3_runtime')
        self.assertEqual(runtime.status, 'unreadable')
        self.assertEqual(runtime.reason, 'database_missing')
    def test_a_transient_wal_io_error_is_retried_and_the_source_is_current(self):
        notice_at = NOW - 200_000
        run_at = NOW - 45
        self.notice(notice_at)
        self.recent_run('run-current', run_at)
        real = runtime_state._connect
        state = {'failed': False}

        class Flaky:
            def __init__(self, connection):
                self.connection = connection

            def execute(self, *args, **kwargs):
                if not state['failed']:
                    state['failed'] = True
                    raise sqlite3.OperationalError('disk I/O error')
                return self.connection.execute(*args, **kwargs)

            def close(self):
                self.connection.close()

        calls = []

        def connect(path):
            calls.append(path)
            return Flaky(real(path))

        with patch.object(runtime_state, '_connect', side_effect=connect):
            observations = runtime_state.read_observations(self.path, NOW)
        self.assertTrue(state['failed'])
        self.assertEqual(len(calls), 2)
        self.assertEqual(observations['status'], 'ok')
        self.assertEqual(observations['observed_at'], run_at)

    def test_a_persistent_wal_io_error_names_its_cause(self):
        self.notice(NOW - 200_000)

        class Broken:
            def execute(self, *args, **kwargs):
                raise sqlite3.OperationalError('disk I/O error')

            def close(self):
                pass

        with patch.object(runtime_state, '_connect', return_value=Broken()):
            observations = runtime_state.read_observations(self.path, NOW)
        self.assertEqual(observations['status'], 'unreadable')
        self.assertEqual(observations['reason'], 'database_io_error')
        self.assertIsNone(observations['observed_at'])

    def test_a_failed_state_read_is_not_masked_by_an_old_notice(self):
        notice_at = NOW - 200_000
        self.notice(notice_at)
        unreadable = runtime_state._unreadable(
            self.path, reason='database_io_error'
        )
        with patch.object(runtime_state, 'read_observations',
                          return_value=unreadable):
            runtime, _snapshot = self.rank()
        # The window is still there, but it is not evidence that the state
        # was read. No observation is invented from it.
        self.assertEqual(runtime.status, 'unreadable')
        self.assertEqual(runtime.reason, 'database_io_error')
        self.assertIsNone(runtime.observed_at)
        self.assertEqual(runtime.windows[0]['observedAtEpoch'], notice_at)


class CapturedNoticeTests(unittest.TestCase):
    """The notices the live state held, in their captured shapes.

    Both windows are kept: the short one carries its five-hour reset, and the
    weekly one its seven-day reset.
    """

    def build(self, rows):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'state.sqlite'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE orchestration_v2_projection_runs '
                       '(run_id TEXT, provider_instance_id TEXT, payload_json TEXT)')
            db.execute('CREATE TABLE orchestration_v2_projection_messages '
                       '(run_id TEXT, role TEXT, streaming INTEGER, created_at TEXT, payload_json TEXT)')
            for index, row in enumerate(rows):
                db.execute('INSERT INTO orchestration_v2_projection_runs VALUES (?,?,?)', (
                    str(index), row['instance'],
                    json.dumps({'modelSelection': {'instanceId': row['instance'], 'model': row['model']}}),
                ))
                db.execute('INSERT INTO orchestration_v2_projection_messages VALUES (?,?,?,?,?)', (
                    str(index), 'assistant', 0, row['created_at'], json.dumps({'text': row['text']}),
                ))
        return path

    def test_the_captured_notices_publish_both_windows_with_their_resets(self):
        rows = json.loads(CAPTURED.read_text(encoding='utf-8'))['rows']
        moment = runtime_state._iso_epoch('2026-10-23T21:16:30Z')
        windows = {
            window['quotaId']: window
            for window in runtime_state.read_limit_windows(self.build(rows), moment)
        }
        short = windows['runtime-limit-5h:gemini-3.8-flash']
        self.assertEqual(short['kind'], 'session')
        self.assertEqual(short['durationSeconds'], 5 * 3600)
        self.assertEqual(short['resetEpoch'], runtime_state._iso_epoch('2026-10-24T00:48:42.609Z'))
        weekly = windows['runtime-limit:gemini-3.8-flash']
        self.assertEqual(weekly['kind'], 'weekly')
        self.assertEqual(weekly['durationSeconds'], 7 * 86400)
        self.assertEqual(weekly['resetEpoch'], runtime_state._iso_epoch('2026-10-29T03:03:55.536Z'))
        self.assertGreater(short['resetEpoch'], moment)
        self.assertGreater(weekly['resetEpoch'], short['resetEpoch'])
        argon = windows['runtime-limit:gemini-4-argon']
        self.assertEqual(argon['kind'], 'weekly')
        self.assertEqual(argon['resetEpoch'], runtime_state._iso_epoch('2026-10-30T19:15:59.947Z'))
        self.assertGreater(argon['resetEpoch'], moment)


if __name__ == '__main__':
    unittest.main()
