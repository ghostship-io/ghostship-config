"""Load-bearing collector/privacy and provisioned dashboard contract tests."""
import importlib.util
import json
import os
import base64
import http.server
import shutil
import threading
import socket
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SIEM = ROOT / 'modules/self-hosted/siem'
spec = importlib.util.spec_from_file_location('work', SIEM / 'autonomous-work.py')
work = importlib.util.module_from_spec(spec)
spec.loader.exec_module(work)
NOW = 1792584000.0
THREAD = '11111111-1111-4111-8111-111111111111'
CHILD = 'thread:delegated-task:command%3Amcp%3Afixture-child'
ENV = '22222222-2222-4222-8222-222222222222'
SECRET = 'DO_NOT_EXPORT_SECRET_BODY_TOKEN'


class CollectorTests(unittest.TestCase):
    def test_operational_snapshot_is_not_world_readable(self):
        """Defect: private branch/model rows are published with public metric permissions."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'snapshot.jsonl'
            work.atomic(target, '{"branch":"synthetic"}\n', mode=0o640)
            self.assertEqual(target.stat().st_mode & 0o777, 0o640)
            public = Path(directory) / 'metrics.prom'
            work.atomic(public, 'synthetic_metric 1\n')
            self.assertEqual(public.stat().st_mode & 0o777, 0o644)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'stock.sqlite'
        self.config = {key: str(self.path) for key in
                       ['t3_db', 'coordinator_db', 'runtime_db', 'mcp_runtime_db']}
        env_file = Path(self.tmp.name) / 'environment-id'
        env_file.write_text(ENV)
        self.config.update(environment_id_file=str(env_file), host='fixture')
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.db.executescript('''
          CREATE TABLE projection_projects(project_id,updated_at,deleted_at);
          CREATE TABLE orchestration_v2_projection_threads(thread_id,project_id,default_provider,updated_at,deleted_at,payload_json);
          CREATE TABLE orchestration_v2_projection_runtime_requests(runtime_request_id,thread_id,created_at,resolved_at,status);
          CREATE TABLE orchestration_v2_thread_launch_workflows(command_id,thread_id,project_id,status,updated_at);
          CREATE TABLE meta(key,value);
          CREATE TABLE scheduled_tasks(task_id,title,prompt,enabled,schedule_json,
            next_run_at,last_run_at,last_run_status,thread_id);
          CREATE TABLE orchestration_v2_projection_runs(run_id,thread_id,provider,
            status,requested_at,completed_at,payload_json,ordinal);
          CREATE TABLE orchestration_v2_projection_subagents(subagent_id,thread_id,
            child_thread_id,provider,status,completed_at,updated_at,payload_json);
          CREATE TABLE scheduled_task_webhook_deliveries(delivery_id,received_at,
            outcome,body,headers_json,rendered_prompt);
          CREATE TABLE orchestration_v2_projection_provider_turns(provider_turn_id,
            thread_id,status,started_at,completed_at,payload_json,provider_thread_id);
          CREATE TABLE orchestration_v2_projection_provider_threads(provider_thread_id,provider);
          CREATE TABLE events(key,pointer,status,note,received_at,updated_at);
          CREATE TABLE owners(repository,number,thread_id,claimed_at);
          CREATE TABLE pull_progress(repository,number,thread_id,revision,outcome,evidence,updated_at);
          CREATE TABLE jobs(id,status,updated_at,progress,result,error);
          CREATE INDEX runs_thread_ordinal ON orchestration_v2_projection_runs(thread_id,ordinal);
          CREATE INDEX runs_thread_status ON orchestration_v2_projection_runs(thread_id,status);
          CREATE INDEX subagents_child ON orchestration_v2_projection_subagents(child_thread_id);
          CREATE INDEX threads_project_updated ON orchestration_v2_projection_threads(project_id,updated_at);
        ''')
        at = work.iso(NOW-10)
        self.db.execute('INSERT INTO scheduled_tasks VALUES(?,?,?,?,?,?,?,?,?)',
                        ('task', SECRET, SECRET, 1, '{"type":"webhook","secret":"'+SECRET+'"}', None, at, 'failed', THREAD))
        # An enabled schedule with a next run and a last result, and a disabled
        # one that keeps the outcome of its previous run.
        self.db.execute('INSERT INTO scheduled_tasks VALUES(?,?,?,?,?,?,?,?,?)',
                        ('task-enabled', SECRET, SECRET, 1, '{"type":"cron"}', NOW+600, NOW-120, 'succeeded', THREAD))
        self.db.execute('INSERT INTO scheduled_tasks VALUES(?,?,?,?,?,?,?,?,?)',
                        ('task-disabled', SECRET, SECRET, 0, '{"type":"interval"}', NOW+300, NOW-60, 'failed', THREAD))
        self.db.execute('INSERT INTO orchestration_v2_projection_runs VALUES(?,?,?,?,?,?,?,?)',
                        ('run', THREAD, 'codex', 'running', at, None,
                         json.dumps({'ordinal': 1, 'startedAt': NOW-9, 'transcript': SECRET}), 1))
        self.db.execute('INSERT INTO orchestration_v2_projection_subagents VALUES(?,?,?,?,?,?,?,?)',
                        ('child', THREAD, CHILD, 'codex', 'running', None, at,
                         json.dumps({'note': SECRET})))
        # The child is a real native thread with its own active run, model and
        # branch, so the agent table can link it to its parent.
        self.db.execute('INSERT INTO orchestration_v2_projection_threads VALUES(?,?,?,?,NULL,?)',
                        (CHILD, ENV, 'codex', at, json.dumps({'branch': 'feat/synthetic-child'})))
        self.db.execute('INSERT INTO orchestration_v2_projection_runs VALUES(?,?,?,?,?,?,?,?)',
                        ('run:child', CHILD, 'opencode', 'running', NOW-8, None,
                         json.dumps({'startedAt': NOW-7,
                                     'modelSelection': {'instanceId': 'opencode',
                                                        'model': 'synthetic-model-child'}}), 1))
        self.db.execute('INSERT INTO scheduled_task_webhook_deliveries VALUES(?,?,?,?,?,?)',
                        ('delivery', at, 'accepted', SECRET, SECRET, SECRET))
        for name, payload in [('turn', {'turnTokenUsage': {'usageStatus':'complete','inputTokens':25,'outputTokens':10}, 'transcript':SECRET}),
                              ('context', {'tokenUsage': {'usedTokens':999999,'inputTokens':999999}})]:
            self.db.execute('INSERT INTO orchestration_v2_projection_provider_turns VALUES(?,?,?,?,?,?,?)',
                            (name, THREAD, 'completed', at, at, json.dumps(payload), 'provider-thread'))
        self.db.execute('INSERT INTO orchestration_v2_projection_provider_threads VALUES(?,?)', ('provider-thread','codex'))
        self.db.execute('INSERT INTO projection_projects VALUES(?,?,NULL)', (ENV,at))
        self.db.execute('INSERT INTO orchestration_v2_projection_threads VALUES(?,?,?,?,NULL,?)', (THREAD,ENV,'codex',at,json.dumps({'linkedPullRequest':{'url':'https://github.com/ghostship-io/ghostship-config/pull/42'},'prompt':SECRET,'pullRequests':[{'url':'https://github.com/ghostship-io/ghostship-config/pull/42','snapshot':{'state':'OPEN'}},{'url':'https://github.com/ghostship-io/ghostship-config/pull/43','snapshot':{'state':'OPEN'}}]})))
        self.db.execute('INSERT INTO orchestration_v2_projection_runtime_requests VALUES(?,?,?,NULL,?)', ('approval',THREAD,at,'pending'))
        # An active agent with its own branch, model and provider, plus a
        # terminal one for the windowed history.
        self.db.execute('INSERT INTO orchestration_v2_projection_threads VALUES(?,?,?,?,NULL,?)',
                        ('eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', ENV, 'codex', at,
                         json.dumps({'branch': 'feat/synthetic-active'})))
        self.db.execute('INSERT INTO orchestration_v2_projection_runs VALUES(?,?,?,?,?,?,?,?)',
                        ('run:active', 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', 'claudeAgent',
                         'running', NOW-12, None,
                         json.dumps({'startedAt': NOW-11,
                                     'modelSelection': {'instanceId': 'claudeAgent',
                                                        'model': 'synthetic-model-active'}}), 1))
        self.db.execute('INSERT INTO orchestration_v2_projection_threads VALUES(?,?,?,?,NULL,?)',
                        ('dddddddd-dddd-4ddd-8ddd-dddddddddddd', ENV, 'codex', at,
                         json.dumps({'branch': 'feat/synthetic-done'})))
        self.db.execute('INSERT INTO orchestration_v2_projection_runs VALUES(?,?,?,?,?,?,?,?)',
                        ('run:done', 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', 'codex', 'completed',
                         NOW-30, at, json.dumps({'startedAt': NOW-40,
                                                  'modelSelection': {'instanceId': 'codex',
                                                                     'model': 'synthetic-model'}}), 1))
        pointer = json.dumps({'repository':'ghostship-io/ghostship-config','number':123,'event':'issues','body':SECRET})
        self.db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',
                        ('receipt', pointer, 'done', 'over daily limit', NOW-20, NOW-10))
        for key, event, action in [('ci', 'workflow_run', 'completed'),
                                   ('deploy', 'deployment_status', 'created'),
                                   ('review', 'pull_request_review', 'submitted'),
                                   ('closed', 'pull_request', 'closed')]:
            self.db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',
                            (key, json.dumps({'repository': 'ghostship-io/ghostship-config', 'event': event,
                                              'action': action, 'number': 42}),
                             'done', '', NOW-30, NOW-30))
        self.db.execute('INSERT INTO owners VALUES(?,?,?,?)', ('ghostship-io/ghostship-config',123,THREAD,NOW-10))
        # The coordinator CI proof: exact revision, outcome, merge flag and the
        # configured check conclusions.
        for number, outcome, merged, checks in ((42, 'verified_ci', 1, {'build': ['success']}),
                                                (43, 'failed', 0, {'build': ['failure']}),
                                                (44, 'pending_ci', 0, {'build': ['pending']}),
                                                (45, 'unverified', 0, {})):
            evidence = json.dumps({'required_checks': sorted(checks), 'merged': bool(merged),
                                   'checks': checks})
            self.db.execute('INSERT INTO pull_progress VALUES(?,?,?,?,?,?,?)',
                            ('ghostship-io/ghostship-config', number, THREAD, 'a'*40, outcome, evidence, NOW-15))
        self.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)', ('job','queued',NOW-10,SECRET,SECRET,SECRET))
        self.db.commit()

    def collect(self):
        return work.collect(self.config, NOW, timers=lambda *_: ([], False))

    def test_repeat_poll_is_snapshot_not_increment_and_does_not_export_bodies(self):
        before = self.path.read_bytes()
        rows, metrics = self.collect()
        rows2, metrics2 = self.collect()
        stable = lambda m: [line for line in m.splitlines() if 'duration_seconds' not in line]
        self.assertEqual(stable(metrics), stable(metrics2))
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual([r['work_id'] for r in rows], [r['work_id'] for r in rows2])
        self.assertNotIn(SECRET, json.dumps(rows)+metrics)
        self.assertNotIn('999999', json.dumps(rows)+metrics)
        # AI provider usage belongs to the separate ai-usage package: this
        # collector exports no token usage at all.
        self.assertNotIn('input_tokens', json.dumps(rows)+metrics)
        self.assertNotIn('output_tokens', json.dumps(rows)+metrics)
        self.assertNotIn('ghostship_work_input_tokens', metrics)
        self.assertEqual(sum(r['kind']=='usage' for r in rows), 0)
        self.assertTrue(any(r.get('thread_url') == f'https://t3code.ghostship.io/{ENV}/{THREAD}' for r in rows))
        self.assertTrue(any(r.get('github_url') == 'https://github.com/ghostship-io/ghostship-config/issues/123' for r in rows))
        receipt = next(r for r in rows if r['source']=='github_receipts' and r['kind']=='webhook')
        self.assertEqual(receipt['status'], 'held')
        self.assertEqual(receipt['fired_at'], work.iso(NOW-20))
        self.assertNotIn('_total', metrics)

    def test_missing_source_is_unknown_not_zero_and_never_creates_database(self):
        missing = Path(self.tmp.name)/'missing.sqlite'
        self.config['t3_db'] = str(missing)
        rows, metrics = self.collect()
        self.assertFalse(missing.exists())
        self.assertIn('ghostship_work_source_up{source="t3_runs"} 0', metrics)
        self.assertNotIn('ghostship_work_active{source="t3_runs"}', metrics)
        self.assertNotIn('ghostship_work_source_last_success_seconds{source="t3_runs"}', metrics)
        self.assertTrue(any(r.get('coverage')=='unknown' and r['source']=='t3_runs' for r in rows))
        self.assertTrue(any(r.get('coverage')=='gap' and r['source']=='chatgpt_tasks' for r in rows))
        # Independent sources survive.
        self.assertIn('ghostship_work_source_up{source="github_receipts"} 1', metrics)

    def test_row_limit_prioritizes_open_work_and_marks_coverage_bounded(self):
        self.db.executemany('INSERT INTO jobs VALUES(?,?,?,?,?,?)',
                            [(f'finished-{n}','success',NOW-n,'','','') for n in range(work.LIMIT+5)])
        self.db.commit()
        rows, metrics = self.collect()
        jobs = [r for r in rows if r['source']=='runtime_jobs' and r['kind']=='job']
        self.assertEqual(len(jobs), work.LIMIT)
        self.assertTrue(any(r['status']=='queued' for r in jobs))
        self.assertIn('ghostship_work_source_limited{source="runtime_jobs"} 1', metrics)
        self.assertTrue(any(r.get('coverage')=='bounded' and r['source']=='runtime_jobs' for r in rows))

    def test_ro_live_wal_and_query_deadline(self):
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)', ('wal','running',NOW,'','',''))
        self.db.commit()
        rows, _ = work.runtime_rows(str(self.path), NOW)
        self.assertTrue(any(r['id']=='wal' for r in rows))
        with work.readonly(self.path) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute('DELETE FROM jobs')
        started = time.monotonic()
        with patch.object(work, 'QUERY_SECONDS', 0.01):
            with self.assertRaises(sqlite3.OperationalError):
                work.query(self.path, '''WITH RECURSIVE n(x) AS
                  (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<100000000)
                  SELECT sum(x) FROM n''')
        self.assertLess(time.monotonic()-started, 0.5)

    def test_all_native_projects_manual_threads_pending_requests_and_actual_reviews(self):
        rows, _ = self.collect()
        self.assertTrue(any(r['source']=='review_metadata' and r.get('coverage')=='gap' for r in rows))
        # A second project/thread has no broker event, issue, PR or native run.
        self.db.execute('INSERT INTO projection_projects VALUES(?,?,NULL)', (THREAD,work.iso(NOW)))
        self.db.execute('INSERT INTO orchestration_v2_projection_threads VALUES(?,?,?,?,NULL,?)',
                        (ENV,THREAD,'codex',work.iso(NOW),'{}'))
        self.db.execute('CREATE TABLE automatic_reviews(request_id,repository,number,thread_id,status,occupied,due_at,updated_at,note,tasks,receipt,head)')
        self.db.execute('INSERT INTO automatic_reviews VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                        ('review','ghostship-io/ghostship-config',42,THREAD,'reported',0,NOW,NOW,SECRET,SECRET,SECRET,'a'*40))
        self.db.commit()
        rows, _ = self.collect()
        self.assertEqual(len([r for r in rows if r['kind']=='project']), 2)
        self.assertEqual(len([r for r in rows if r['kind']=='artifact']), 2)
        manual = next(r for r in rows if r['kind']=='thread' and r['work_id']==work.identity(ENV))
        self.assertEqual(manual['status'], 'idle')
        self.assertTrue(any(r['kind']=='request' and r['status']=='blocked' for r in rows))
        review = next(r for r in rows if r['kind']=='review')
        self.assertEqual(review['status'], 'reported')
        self.assertEqual(review['github_url'], 'https://github.com/ghostship-io/ghostship-config/pull/42')
        self.assertTrue(any(r['kind']=='thread' and r.get('github_url')==review['github_url'] for r in rows))
        self.assertNotIn(SECRET, json.dumps(rows))
        self.db.execute('UPDATE automatic_reviews SET number=NULL')
        self.db.commit()
        rows,_=self.collect()
        self.assertEqual(next(r['github_url'] for r in rows if r['kind']=='review'),
                         'https://github.com/ghostship-io/ghostship-config/commit/'+'a'*40)

    def test_optional_actual_router_provenance_is_allowlisted(self):
        record = {'at':NOW, 'project_id':ENV, 'state':'selected',
                  'selection':{'instanceId':'codex','model':SECRET,'options':SECRET},
                  'candidates':[{'instanceId':'claude-code','quota':'exhausted','reason':'usage_exhausted'},
                                {'instanceId':'codex','quota':'unknown','reason':'eligible'}],
                  'prompt':SECRET}
        self.db.execute('INSERT INTO meta VALUES(?,?)', ('model-route:choice:'+SECRET,json.dumps(record)))
        self.db.commit()
        rows, _ = self.collect()
        route = next(r for r in rows if r['kind']=='routing')
        self.assertEqual(route['provider'], 'codex')
        self.assertEqual(route['primary_quota'], 'exhausted')
        self.assertEqual(route['route_reason'], 'usage_exhausted')
        self.assertEqual(route['fallback'], 1)
        self.assertEqual(route['route_state'], 'selected')
        self.assertNotIn(SECRET, json.dumps(rows))

    def test_continuation_metadata_excludes_frozen_commands_and_reports_receipt_state(self):
        record={'thread_id':THREAD,'project_id':ENV,'state':'message_uncertain',
                'updated_at':NOW,'selection':{'instanceId':'codex','model':SECRET},
                'switch_accepted':{'sequence':1},'native_runs':[{'id':SECRET},{'id':SECRET}],
                'executing':[SECRET],'text':SECRET,'note':SECRET,'message_command':{'text':SECRET}}
        self.db.execute('INSERT INTO meta VALUES(?,?)',('model-continuation:'+SECRET,json.dumps(record)))
        self.db.commit()
        rows, _=self.collect()
        row=next(r for r in rows if r['kind']=='continuation')
        self.assertEqual(row['status'],'message_uncertain')
        self.assertEqual(row['switch_accepted'],1)
        self.assertEqual(row['message_accepted'],0)
        self.assertEqual(row['native_run_count'],2)
        self.assertEqual(row['executing_count'],1)
        self.assertNotIn(SECRET,json.dumps(rows))

    def test_mcp_store_layouts_merge_latest_durable_receipt_without_creating_missing_paths(self):
        other=self.path.with_name('backend.sqlite')
        shutil.copyfile(self.path,other)
        db=sqlite3.connect(other)
        try:
            db.execute("UPDATE jobs SET status='failed',updated_at=? WHERE id='job'",(NOW,))
            db.commit()
        finally:
            db.close()
        missing=self.path.with_name('absent.sqlite')
        self.config['mcp_runtime_alternates']=[str(other),str(missing)]
        rows,_=self.collect()
        jobs=[r for r in rows if r['source']=='runtime_mcp_jobs' and r['kind']=='job']
        self.assertEqual(len(jobs),1)
        self.assertEqual(jobs[0]['status'],'failed')
        self.assertFalse(missing.exists())

    def test_schedule_state_keeps_enabled_next_last_and_result_apart(self):
        rows, metrics = self.collect()
        schedules = {r['work_id']: r for r in rows if r['kind'] == 'schedule'}
        enabled = schedules[work.identity('task-enabled')]
        self.assertEqual(enabled['enabled'], 1)
        self.assertEqual(enabled['status'], 'succeeded')
        self.assertEqual(enabled['last_status'], 'succeeded')
        self.assertEqual(enabled['next_at'], work.iso(NOW+600))
        self.assertEqual(enabled['event_at'], work.iso(NOW-120))
        self.assertEqual(enabled['trigger'], 'cron')
        disabled = schedules[work.identity('task-disabled')]
        self.assertEqual(disabled['enabled'], 0)
        self.assertEqual(disabled['status'], 'disabled')
        # A disabled schedule keeps the outcome of its previous run.
        self.assertEqual(disabled['last_status'], 'failed')
        # The UTC-day marker is computed at collection time, not by a query macro.
        self.assertEqual(enabled['event_today'], 1)
        self.assertEqual(disabled['event_today'], 1)

    def test_evidence_classes_separate_receipts_from_outcomes(self):
        rows, metrics = self.collect()
        classes = {(r['source'], r.get('evidence')) for r in rows if r.get('evidence')}
        self.assertIn(('github_receipts', 'ci'), classes)
        self.assertIn(('github_receipts', 'deployment'), classes)
        self.assertIn(('github_receipts', 'review'), classes)
        self.assertIn(('github_receipts', 'pr_closed'), classes)
        self.assertIn(('t3_runs', 'model_report'), classes)
        self.assertIn(('t3_subagents', 'model_report'), classes)
        # A receipt is not an outcome: no class claims a conclusion, a verdict,
        # a merge result or a deployed health.
        self.assertNotIn('objective', {r.get('evidence') for r in rows})
        self.assertNotIn('approved', {r.get('status') for r in rows})
        self.assertNotIn('merged', {r.get('status') for r in rows})
        self.assertIn('ghostship_work_evidence_items{evidence="ci",source="github_receipts"} 1', metrics)
        self.assertIn('ghostship_work_evidence_items{evidence="deployment",source="github_receipts"} 1', metrics)
        self.assertIn('ghostship_work_evidence_items{evidence="review",source="github_receipts"} 1', metrics)
        self.assertIn('ghostship_work_evidence_items{evidence="pr_closed",source="github_receipts"} 1', metrics)
        # The action of a receipt is recorded, the outcome is not.
        receipt = next(r for r in rows if r.get('evidence') == 'review')
        self.assertEqual(receipt['action'], 'submitted')
        # Every dimension without an owner state stays an explicit gap.
        for source in ('objective_completion', 'frontier_approval',
                       'deployed_health', 'ai_usage'):
            gap = next(r for r in rows if r['source'] == source)
            self.assertEqual(gap['coverage'], 'gap')
            self.assertIn(f'ghostship_work_source_up{{source="{source}"}} 0', metrics)

    def test_receipt_actions_are_allowlisted(self):
        rows, _ = self.collect()
        actions = {r.get('action') for r in rows if 'action' in r}
        self.assertTrue(actions <= work.ACTIONS)
        self.assertIn('completed', actions)
        self.assertIn('submitted', actions)
        self.assertIn('closed', actions)

    def test_thread_state_uses_the_current_run_not_the_highest_ordinal(self):
        # A later executed run with a lower ordinal must win: the highest
        # ordinal can mask a run that started and failed afterwards.
        self.db.execute('DELETE FROM orchestration_v2_projection_runs')
        started = json.dumps({'ordinal': 2, 'startedAt': NOW-110, 'transcript': SECRET})
        self.db.execute('INSERT INTO orchestration_v2_projection_runs VALUES(?,?,?,?,?,?,?,?)',
                        ('run-old', THREAD, 'codex', 'completed', NOW-100, NOW-90, started, 2))
        self.db.execute('INSERT INTO orchestration_v2_projection_runs VALUES(?,?,?,?,?,?,?,?)',
                        ('run-new', THREAD, 'codex', 'failed', NOW-50, NOW-40,
                         json.dumps({'ordinal': 1, 'startedAt': NOW-60, 'transcript': SECRET}), 1))
        self.db.commit()
        rows, _ = self.collect()
        thread = next(r for r in rows if r['kind'] == 'thread')
        self.assertEqual(thread['status'], 'failed')
        # A queued run is active work and must be visible as such.
        self.db.execute('DELETE FROM orchestration_v2_projection_runs')
        self.db.execute('INSERT INTO orchestration_v2_projection_runs VALUES(?,?,?,?,?,?,?,?)',
                        ('run-queued', THREAD, 'codex', 'queued', NOW-5, None,
                         json.dumps({'ordinal': 1}), 1))
        self.db.commit()
        rows, metrics = self.collect()
        thread = next(r for r in rows if r['kind'] == 'thread')
        self.assertEqual(thread['status'], 'queued')
        self.assertEqual(thread['status'] in work.ACTIVE, True)

    def test_cancelled_run_that_never_started_does_not_mask_the_completed_run(self):
        self.db.execute('DELETE FROM orchestration_v2_projection_runs')
        self.db.execute('INSERT INTO orchestration_v2_projection_runs VALUES(?,?,?,?,?,?,?,?)',
                        ('completed', THREAD, 'codex', 'completed', NOW-600, NOW-550,
                         json.dumps({'ordinal': 1, 'startedAt': NOW-590}), 1))
        # Requested later and cancelled before it ever started.
        self.db.execute('INSERT INTO orchestration_v2_projection_runs VALUES(?,?,?,?,?,?,?,?)',
                        ('cancelled', THREAD, 'codex', 'cancelled', NOW-240, NOW-200,
                         json.dumps({'ordinal': 2, 'startedAt': None}), 2))
        self.db.commit()
        rows, _ = self.collect()
        thread = next(r for r in rows if r['kind'] == 'thread')
        self.assertEqual(thread['status'], 'completed')
        # A cancelled run that did start is still the latest executed state.
        self.db.execute("UPDATE orchestration_v2_projection_runs SET payload_json=? WHERE run_id='cancelled'",
                        (json.dumps({'ordinal': 2, 'startedAt': NOW-230}),))
        self.db.commit()
        rows, _ = self.collect()
        self.assertEqual(next(r for r in rows if r['kind'] == 'thread')['status'], 'cancelled')
        # Malformed or absent payload JSON is not proof that a run never
        # started, so it still counts as executed.
        self.db.execute("UPDATE orchestration_v2_projection_runs SET payload_json='not-json' WHERE run_id='cancelled'")
        self.db.commit()
        rows, _ = self.collect()
        self.assertEqual(next(r for r in rows if r['kind'] == 'thread')['status'], 'cancelled')
        self.assertNotIn('not-json', json.dumps(rows))

    def test_equal_completion_time_breaks_the_tie_by_ordinal(self):
        self.db.execute('DELETE FROM orchestration_v2_projection_runs')
        for run_id, ordinal in (('low', 1), ('high', 3)):
            self.db.execute('INSERT INTO orchestration_v2_projection_runs VALUES(?,?,?,?,?,?,?,?)',
                            (run_id, THREAD, 'codex', 'completed', NOW-90, NOW-60,
                             json.dumps({'ordinal': ordinal, 'startedAt': NOW-89}), ordinal))
        self.db.commit()
        rows, _ = self.collect()
        thread = next(r for r in rows if r['kind'] == 'thread')
        self.assertEqual(thread['status'], 'completed')

    def test_canonical_native_instance_ids_are_known_and_custom_names_are_not(self):
        self.assertEqual(work.provider('claudeAgent'), 'claudeAgent')
        for provider in ('codex', 'opencode', 'antigravity', 'grok'):
            self.assertEqual(work.provider(provider), provider)
        self.assertEqual(work.provider('my-private-agent'), 'unknown')
        self.assertEqual(work.provider('/home/t3code/custom'), 'unknown')

    def test_coordinator_ci_proof_is_read_as_scalars_on_the_exact_revision(self):
        rows, metrics = self.collect()
        proofs = {r['status']: r for r in rows if r['kind'] == 'ci_proof'}
        self.assertEqual(len(proofs), 4)
        verified = proofs['verified_ci']
        self.assertEqual(verified['outcome'], 'verified_ci')
        self.assertEqual(verified['merged'], 1)
        self.assertEqual(verified['required_checks'], 1)
        self.assertEqual(verified['failed_checks'], 0)
        self.assertEqual(verified['revision'], 'a'*40)
        self.assertEqual(verified['evidence'], 'ci_proof')
        self.assertEqual(verified['github_url'], 'https://github.com/ghostship-io/ghostship-config/pull/42')
        failed = proofs['failed']
        self.assertEqual(failed['failed_checks'], 1)
        self.assertEqual(failed['merged'], 0)
        # A failing required check is visible as a failure, without inventing
        # an objective or deployed proof.
        self.assertIn('ghostship_work_ci_failures{source="ci_proof"} 1', metrics)
        self.assertNotIn(SECRET, json.dumps(rows)+metrics)
        self.assertNotIn('conclusion', json.dumps(rows))

    def test_missing_ci_proof_table_is_an_explicit_gap(self):
        self.db.execute('DROP TABLE pull_progress')
        self.db.commit()
        rows, metrics = self.collect()
        gap = next(r for r in rows if r['source'] == 'ci_proof')
        self.assertEqual(gap['coverage'], 'gap')
        self.assertIn('ghostship_work_source_up{source="ci_proof"} 0', metrics)
        self.assertNotIn('ghostship_work_evidence_items{evidence="ci_proof"', metrics)

    def test_owner_state_is_compact_and_never_raw(self):
        self.db.execute('ALTER TABLE owners ADD COLUMN state TEXT')
        self.db.execute('ALTER TABLE owners ADD COLUMN observed_at REAL')
        self.db.execute('ALTER TABLE owners ADD COLUMN run_id TEXT')
        self.db.execute('ALTER TABLE owners ADD COLUMN note TEXT')
        self.db.execute('UPDATE owners SET state=?, observed_at=?, run_id=?, note=?',
                        ('closed_unverified', NOW-5, 'run-1', SECRET))
        self.db.commit()
        rows, metrics = self.collect()
        owner = next(r for r in rows if r['source'] == 'github_launches')
        self.assertEqual(owner['owner_state'], 'closed_unverified')
        self.assertNotIn(SECRET, json.dumps(rows)+metrics)
        self.assertNotIn('note', json.dumps(rows))

    def test_ai_usage_stays_with_its_own_package_and_dashboard(self):
        rows, metrics = self.collect()
        gap = next(r for r in rows if r['source']=='ai_usage')
        self.assertEqual(gap['coverage'], 'gap')
        self.assertIn('ghostship_work_source_up{source="ai_usage"} 0', metrics)
        self.assertFalse(any(r['kind']=='usage' for r in rows))
        self.assertNotIn('input_tokens', json.dumps(rows))
        self.assertNotIn('output_tokens', json.dumps(rows))
        self.assertNotIn('usage_samples', metrics)

    def test_gap_reasons_claim_no_stale_or_deployment_state(self):
        rows, _ = self.collect()
        reasons = {r['source']: r.get('reason') for r in rows if r['kind'] == 'coverage'}
        self.assertEqual(reasons['ai_usage'], 'separate_owner_not_collected_here')
        self.assertNotIn('10', reasons['chatgpt_tasks'])
        self.assertNotIn('not_deployed', reasons['ai_usage'])
        self.assertEqual(reasons['frontier_approval'], 'unsupported_no_source_in_this_collector')
        self.assertEqual(reasons['deployed_health'], 'unsupported_no_source_in_this_collector')
        self.assertNotIn('ci_conclusion', reasons)

    def add_agent(self, thread_id, project, branch, model, provider, status='running',
                  default_provider='codex', updated=None, requests=0):
        stamp = updated if updated is not None else NOW-20
        self.db.execute('INSERT INTO orchestration_v2_projection_threads VALUES(?,?,?,?,NULL,?)',
                        (thread_id, project, default_provider, work.iso(stamp),
                         json.dumps({'branch': branch, 'providerInstanceId': default_provider})))
        self.db.execute('INSERT INTO orchestration_v2_projection_runs VALUES(?,?,?,?,?,?,?,?)',
                        (identity_run := f'run:{thread_id}', thread_id, provider, status,
                         stamp-5, stamp-1 if status in ('completed','failed','cancelled') else None,
                         json.dumps({'modelSelection': {'instanceId': provider, 'model': model},
                                     'startedAt': stamp-5}), 1))
        if requests:
            self.db.execute('INSERT INTO orchestration_v2_projection_runtime_requests VALUES(?,?,?,NULL,?)',
                            (f'req:{thread_id}', thread_id, stamp, 'pending'))

    def test_agents_show_every_active_thread_beyond_the_recent_cap(self):
        self.db.execute('DELETE FROM orchestration_v2_projection_runs')
        self.db.execute('DELETE FROM orchestration_v2_projection_threads')
        projects = [f'3333333{n}-3333-4333-8333-333333333333' for n in range(1, 4)]
        for n in range(250):
            thread = (f'44444444-4444-4444-8444-{n:012d}' if n % 2 == 0
                      else f'thread:delegated-task:command%3Amcp%3A{n:08d}')
            self.add_agent(thread, projects[n % 3], f'feat/synthetic-{n}', f'synthetic-model-{n % 4}',
                           'claudeAgent' if n % 2 else 'codex')
        self.db.commit()
        rows, metrics = self.collect()
        agents = [r for r in rows if r['kind'] == 'agent' and r['source'] == 't3_agents']
        self.assertEqual(len(agents), 250)
        self.assertEqual(len({r['project_id'] for r in agents}), 3)
        self.assertTrue(any(str(r['work_id']) for r in agents))
        coverage = next(r for r in rows if r['source'] == 't3_agents' and r['kind'] == 'coverage')
        self.assertEqual(coverage['coverage'], 'available')
        self.assertEqual(coverage['rows'], 250)
        self.assertEqual(coverage['total'], 250)
        self.assertEqual(coverage['limited'], False)
        self.assertIn('ghostship_work_active{source="t3_agents"} 250', metrics)
        # Branch and model are private values, never metric labels.
        self.assertNotIn('synthetic-model', metrics)
        self.assertNotIn('feat/synthetic', metrics)

    def test_active_enumeration_reports_incomplete_when_the_page_cap_is_hit(self):
        self.db.execute('DELETE FROM orchestration_v2_projection_runs')
        self.db.execute('DELETE FROM orchestration_v2_projection_threads')
        cap = work.ACTIVE_PAGE * work.ACTIVE_PAGES
        self.db.executemany('INSERT INTO orchestration_v2_projection_threads VALUES(?,?,?,?,NULL,?)',
                            [(f'55555555-5555-4555-8555-{n:012d}', ENV, 'codex', work.iso(NOW-10),
                              json.dumps({'branch': f'feat/synthetic-{n}'})) for n in range(cap+1)])
        self.db.executemany('INSERT INTO orchestration_v2_projection_runs VALUES(?,?,?,?,?,?,?,?)',
                            [(f'run:{n}', f'55555555-5555-4555-8555-{n:012d}', 'codex', 'running',
                              NOW-10, None, json.dumps({'startedAt': NOW-9,
                                                        'modelSelection': {'instanceId': 'codex',
                                                                           'model': 'synthetic-model'}}), 1)
                             for n in range(cap+1)])
        self.db.commit()
        rows, _ = self.collect()
        agents = [r for r in rows if r['kind'] == 'agent' and r['source'] == 't3_agents']
        self.assertEqual(len(agents), cap)
        coverage = next(r for r in rows if r['source'] == 't3_agents' and r['kind'] == 'coverage')
        self.assertEqual(coverage['coverage'], 'bounded')
        self.assertEqual(coverage['limited'], True)
        self.assertEqual(coverage['total'], cap+1)
        self.assertEqual(coverage['rows'], cap)

    def test_agent_rows_carry_branch_model_provider_and_parent(self):
        child = 'thread:delegated-task:command%3Amcp%3A019f3733%3Adelegate-task%3Asynthetic'
        self.add_agent(child, ENV, 'feat/synthetic-child-links', 'synthetic-model-links', 'claudeAgent')
        self.db.execute('INSERT INTO orchestration_v2_projection_subagents VALUES(?,?,?,?,?,?,?,?)',
                        ('child', THREAD, child, 'claudeAgent', 'running', None, work.iso(NOW-10),
                         json.dumps({})))
        self.db.commit()
        rows, _ = self.collect()
        agent = next(r for r in rows if r['kind'] == 'agent'
                     and r.get('branch') == 'feat/synthetic-child-links')
        self.assertEqual(agent['provider'], 'claudeAgent')
        self.assertEqual(agent['model'], 'synthetic-model-links')
        self.assertEqual(agent['status'], 'running')
        # The stock deep link keeps the opaque id verbatim.
        self.assertEqual(agent['thread_url'],
                         f'https://t3code.ghostship.io/{ENV}/{child}')
        self.assertEqual(agent['parent_url'],
                         f'https://t3code.ghostship.io/{ENV}/{THREAD}')
        # An ordinary thread has no parent link.
        ordinary = next(r for r in rows if r['kind'] == 'agent' and r.get('thread_url')
                        and r['work_id'] == work.identity(THREAD))
        self.assertNotIn('parent_url', ordinary)

    def test_agent_model_follows_the_current_run_not_the_thread_default(self):
        thread = '66666666-6666-4666-8666-666666666666'
        self.add_agent(thread, ENV, 'feat/synthetic-switch', 'synthetic-model-a', 'claudeAgent',
                       default_provider='codex')
        self.db.commit()
        rows, _ = self.collect()
        agent = next(r for r in rows if r['kind'] == 'agent' and r['work_id'] == work.identity(thread))
        self.assertEqual(agent['provider'], 'claudeAgent')
        self.assertEqual(agent['model'], 'synthetic-model-a')
        # A newer active run on another provider and model wins after a switch.
        self.db.execute('INSERT INTO orchestration_v2_projection_runs VALUES(?,?,?,?,?,?,?,?)',
                        ('run:switch', thread, 'opencode', 'running', NOW-5, None,
                         json.dumps({'startedAt': NOW-4, 'ordinal': 2,
                                     'modelSelection': {'instanceId': 'opencode',
                                                        'model': 'synthetic-model-b'}}), 2))
        self.db.commit()
        rows, _ = self.collect()
        agent = next(r for r in rows if r['kind'] == 'agent' and r['work_id'] == work.identity(thread))
        self.assertEqual(agent['provider'], 'opencode')
        self.assertEqual(agent['model'], 'synthetic-model-b')

    def test_executing_run_outranks_a_newer_queued_model_switch(self):
        thread = 'eeee1111-1111-4111-8111-111111111111'
        self.add_agent(thread, ENV, 'feat/synthetic-exec', 'synthetic-model-running', 'claudeAgent',
                       status='running')
        # A newer queued run asks for another provider/model but is not executing.
        self.db.execute('INSERT INTO orchestration_v2_projection_runs VALUES(?,?,?,?,?,?,?,?)',
                        ('run:queued-switch', thread, 'opencode', 'queued', NOW-2, None,
                         json.dumps({'startedAt': None, 'ordinal': 2,
                                     'modelSelection': {'instanceId': 'opencode',
                                                        'model': 'synthetic-model-queued'}}), 2))
        self.db.commit()
        rows, _ = self.collect()
        agent = next(r for r in rows if r['kind'] == 'agent' and r['work_id'] == work.identity(thread))
        self.assertEqual(agent['status'], 'running')
        self.assertEqual(agent['provider'], 'claudeAgent')
        self.assertEqual(agent['model'], 'synthetic-model-running')
        # The queued switch is still visible as queued work, not as execution.
        queued = [r for r in rows if r['kind'] == 'run' and r['status'] == 'queued']
        self.assertTrue(queued)

    def test_agent_total_matches_the_row_predicate(self):
        thread = 'eeee2222-2222-4222-8222-222222222222'
        self.db.execute('INSERT INTO orchestration_v2_projection_threads VALUES(?,?,?,?,NULL,?)',
                        (thread, ENV, 'codex', work.iso(NOW-10),
                         json.dumps({'branch': 'feat/synthetic-done-waiting'})))
        self.db.execute('INSERT INTO orchestration_v2_projection_runs VALUES(?,?,?,?,?,?,?,?)',
                        ('run:terminal', thread, 'codex', 'completed', NOW-40, NOW-30,
                         json.dumps({'startedAt': NOW-50,
                                     'modelSelection': {'instanceId': 'codex',
                                                        'model': 'synthetic-model'}}), 1))
        self.db.execute('INSERT INTO orchestration_v2_projection_runtime_requests VALUES(?,?,?,NULL,?)',
                        ('req:waiting', thread, NOW-20, 'pending'))
        self.db.commit()
        rows, _ = self.collect()
        agent = next(r for r in rows if r['kind'] == 'agent' and r['work_id'] == work.identity(thread))
        self.assertEqual(agent['status'], 'waiting')
        coverage = next(r for r in rows if r['source'] == 't3_agents' and r['kind'] == 'coverage')
        active = [r for r in rows if r['source'] == 't3_agents' and r['kind'] == 'agent']
        self.assertEqual(coverage['rows'], len(active))
        self.assertEqual(coverage['total'], len(active))
        self.assertEqual(coverage['limited'], False)

    def test_environment_id_comes_from_the_stock_runtime_file(self):
        rows, _ = self.collect()
        link = next(r['thread_url'] for r in rows if r['kind'] == 'agent' and r.get('thread_url'))
        self.assertTrue(link.startswith(f'https://t3code.ghostship.io/{ENV}/'))
        # Missing or malformed runtime files fall back to the app deep link.
        Path(self.config['environment_id_file']).unlink()
        rows, _ = self.collect()
        link = next(r['thread_url'] for r in rows if r['kind'] == 'agent' and r.get('thread_url'))
        self.assertTrue(link.startswith('t3-thread://v1/'))
        Path(self.config['environment_id_file']).write_text('not-a-uuid')
        rows, _ = self.collect()
        link = next(r['thread_url'] for r in rows if r['kind'] == 'agent' and r.get('thread_url'))
        self.assertTrue(link.startswith('t3-thread://v1/'))
        # The module never bakes the live id into configuration.
        module = (SIEM/'autonomous-work.nix').read_text()
        self.assertNotIn('environment_id =', module)
        self.assertIn('environment_id_file', module)
        self.assertNotIn(ENV, module)

    def test_agent_missing_fields_stay_unknown(self):
        thread = '77777777-7777-4777-8777-777777777777'
        self.db.execute('INSERT INTO orchestration_v2_projection_threads VALUES(?,?,?,?,NULL,?)',
                        (thread, ENV, 'opencode', work.iso(NOW-10), json.dumps({})))
        self.db.execute('INSERT INTO orchestration_v2_projection_runs VALUES(?,?,?,?,?,?,?,?)',
                        ('run:bare', thread, 'codex', 'running', NOW-10, None,
                         json.dumps({'startedAt': NOW-9}), 1))
        self.db.commit()
        rows, _ = self.collect()
        agent = next(r for r in rows if r['kind'] == 'agent' and r['work_id'] == work.identity(thread))
        self.assertNotIn('branch', agent)
        self.assertNotIn('model', agent)
        self.assertEqual(agent['status'], 'running')
        # The provider is the run's own, never the thread default.
        self.assertEqual(agent['provider'], 'codex')

    def test_agent_waiting_queued_and_held_are_explicit_and_not_pid_proof(self):
        waiting = '88888888-8888-4888-8888-888888888888'
        queued = '99999999-9999-4999-8999-999999999999'
        held = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        self.add_agent(waiting, ENV, 'feat/synthetic-wait', 'synthetic-model', 'codex', status='waiting')
        self.add_agent(queued, ENV, 'feat/synthetic-queue', 'synthetic-model', 'codex', status='queued')
        self.add_agent(held, ENV, 'feat/synthetic-held', 'synthetic-model', 'codex', status='waiting',
                       requests=1)
        self.db.commit()
        rows, _ = self.collect()
        states = {r['work_id']: r['status'] for r in rows if r['kind'] == 'agent'}
        self.assertEqual(states[work.identity(waiting)], 'waiting')
        self.assertEqual(states[work.identity(queued)], 'queued')
        # A pending native request is waiting work, not a running process.
        self.assertEqual(states[work.identity(held)], 'waiting')
        self.assertFalse(any('pid' in key for r in rows for key in r))

    def test_agent_links_fail_closed_for_unverified_ids(self):
        self.assertEqual(work.thread_url('thread:delegated-task:command%3Amcp%3Aabc', ENV),
                         f'https://t3code.ghostship.io/{ENV}/thread:delegated-task:command%3Amcp%3Aabc')
        self.assertEqual(work.thread_url(THREAD, ''), f't3-thread://v1/{THREAD}')
        for value in ('DO_NOT_EXPORT_SECRET_BODY_TOKEN', 'thread:' + 'a'*300, '', None,
                      'thread:delegated-task:../../etc/passwd', 'http://evil.example/thread'):
            self.assertEqual(work.thread_url(value, ENV), '', value)

    def test_agent_history_is_windowed_and_excludes_active(self):
        recent = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
        old = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
        self.add_agent(recent, ENV, 'feat/synthetic-terminal', 'synthetic-model', 'codex',
                       status='completed', updated=NOW-600)
        self.add_agent(old, ENV, 'feat/synthetic-old', 'synthetic-model', 'codex',
                       status='completed', updated=NOW-2*86400)
        self.db.commit()
        rows, _ = self.collect()
        history = [r for r in rows if r['source'] == 't3_agent_history']
        ids = {r['work_id'] for r in history}
        self.assertIn(work.identity(recent), ids)
        self.assertNotIn(work.identity(old), ids)
        # Active work is enumerated in the active source, never in history.
        active_ids = {r['work_id'] for r in rows if r['source'] == 't3_agents'}
        self.assertFalse(ids & active_ids)

    def test_timer_metadata_only_and_subprocess_failure(self):
        payload = [{'unit':'newsletter.timer','next':int((NOW+60)*1e6),'last':int((NOW-60)*1e6),'activates':SECRET},
                   {'unit':'unsafe / '+SECRET,'next':int(NOW*1e6)}]
        with patch.object(work.subprocess, 'run', return_value=type('P', (), {'stdout':json.dumps(payload).encode()})()):
            timers, limited = work.timer_rows(None, NOW)
        self.assertFalse(limited)
        self.assertEqual(len(timers), 1)
        row = work.project('systemd_timers', timers[0], ENV)
        self.assertEqual(row['next_at'], work.iso(NOW+60))
        self.assertNotIn(SECRET, json.dumps(row))
        with patch.object(work.subprocess, 'run', side_effect=work.subprocess.TimeoutExpired('systemctl',3)):
            _, metrics = work.collect(self.config, NOW)
        self.assertIn('ghostship_work_source_up{source="systemd_timers"} 0', metrics)

    def test_new_status_and_invalid_link_values_fail_closed(self):
        row = work.project('t3_runs', {'id':SECRET,'kind':'run','status':SECRET,
            'provider':SECRET,'thread_id':SECRET,'repository':SECRET,'number':1,
            'event_at':SECRET,'input_tokens':float('nan')}, ENV)
        self.assertEqual(row['status'], 'unknown')
        self.assertEqual(row['provider'], 'unknown')
        self.assertNotIn('thread_url', row)
        self.assertNotIn('input_tokens', row)
        self.assertNotIn(SECRET, json.dumps(row))


class DashboardContractTests(unittest.TestCase):
    def test_candidate_columns_name_the_quantity_the_query_returns(self):
        page = json.loads((SIEM/'dashboards/ai-usage.json').read_text())
        panel = next(p for p in page['panels'] if p['id'] == 29)
        names = next(t['options']['renameByName'] for t in panel['transformations']
                     if t['id'] == 'rename')
        quantities = {names['Value #' + t['refId']]: t['expr'] for t in panel['targets']}
        self.assertIn('ghostship_ai_model_cost_per_task', quantities['Cost per task'])
        self.assertIn('ghostship_ai_model_available', quantities['Available'])
        self.assertNotIn('Capacity', quantities, 'A task price is not quota capacity')

    def test_ai_usage_panel_rectangles_do_not_overlap(self):
        page = json.loads((SIEM/'dashboards/ai-usage.json').read_text())
        for i, left in enumerate(page['panels']):
            a = left['gridPos']
            for right in page['panels'][i+1:]:
                b = right['gridPos']
                overlap = (a['x'] < b['x']+b['w'] and b['x'] < a['x']+a['w']
                           and a['y'] < b['y']+b['h'] and b['y'] < a['y']+a['h'])
                self.assertFalse(overlap, (left['title'], right['title']))

    def test_actual_json_queries_use_provisioned_datasources_and_bounded_deduplicated_lists(self):
        dashboard = json.loads((SIEM/'dashboards/autonomous-work.json').read_text())
        self.assertFalse(dashboard['editable'])
        self.assertEqual(dashboard['uid'], 'ghostship-autonomous-work')
        ui = (SIEM/'ui.nix').read_text()
        self.assertIn('GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH = "/etc/grafana/provisioning/dashboards-json/autonomous-work.json"', ui)
        self.assertIn('cp ${./dashboards}/*.json', ui)
        self.assertIn('GF_USERS_HOME_PAGE = "/d/ghostship-autonomous-work"', ui)
        self.assertIn('secureJsonData.basicAuthPassword = "$GRAFANA_VMAUTH_PASSWORD"', ui)
        self.assertIn('environmentFiles = [ "${root}/vmauth.env" ]', ui)
        for panel in dashboard['panels']:
            for target in panel.get('targets', []):
                uid = target['datasource']['uid']
                self.assertIn(uid, ('victorialogs','victoriametrics'))
                self.assertEqual(panel['datasource'], target['datasource'])
                self.assertIn(f'"{uid}"', ui)
                if uid == 'victorialogs':
                    self.assertIn('last 1 by (_time) partition by (source,kind,work_id', target['expr'])
                    if target['queryType'] == 'instant':
                        limit = int(work.re.search(r'limit (\d+)', target['expr']).group(1))
                        self.assertIn(limit, (200, 1000))
                    else:
                        self.assertEqual(target['queryType'], 'stats')
        uids = {json.loads(p.read_text())['uid'] for p in (SIEM/'dashboards').glob('*.json')}
        # The AI usage dashboard is owned and provisioned by the separate
        # ai-usage package; this page only links to it.
        external = {'ghostship-ai-usage'}
        for link in dashboard['links']:
            self.assertIn(link['url'].removeprefix('/d/'), uids | external)
        self.assertIn('/d/ghostship-ai-usage', [link['url'] for link in dashboard['links']])

    def test_navigation_has_exactly_one_link_per_page(self):
        # Rebuilding a dashboard must never append a second copy of a link: the
        # bar is five pages, each exactly once, with the same order everywhere.
        expected = ['ghostship-autonomous-work', 'ghostship-host', 'ghostship-security',
                    'ghostship-siem-pipeline', 'ghostship-ai-usage']
        for path in (SIEM/'dashboards').glob('*.json'):
            page = json.loads(path.read_text())
            urls = [link['url'] for link in page['links']]
            with self.subTest(dashboard=page['uid']):
                self.assertEqual([url.removeprefix('/d/') for url in urls], expected)
                self.assertEqual(len(urls), len(set(urls)))
                self.assertEqual(len(urls), 5)
                for link in page['links']:
                    self.assertTrue(link['keepTime'], 'navigation must keep the selected time range')
                    self.assertTrue(link['includeVars'], 'navigation must keep the selected filters')
            for panel in page['panels']:
                if panel.get('type') == 'text':
                    content = panel['options']['content']
                    # Native dashboard links above own navigation; compact
                    # text panels need not repeat the entire navigation bar.
                    self.assertLessEqual(content.count('ghostship-ai-usage'), 1)
                    self.assertLessEqual(content.count('/d/ghostship-'), 5)

    def test_all_five_pages_have_consistent_direct_navigation_and_source_shapes(self):
        dashboards=[json.loads(p.read_text()) for p in (SIEM/'dashboards').glob('*.json')]
        self.assertEqual({d["uid"] for d in dashboards}, {"ghostship-autonomous-work", "ghostship-host", "ghostship-security", "ghostship-siem-pipeline", "ghostship-ai-usage"})
        nav=dashboards[0]['links']
        for d in dashboards:
            self.assertEqual(d['links'],nav)
            self.assertEqual(d['timezone'],'utc')
            self.assertFalse(d['editable'])
            self.assertEqual(len({p['id'] for p in d['panels']}),len(d['panels']))
            for p in d['panels']:
                for t in p.get('targets',[]):
                    self.assertIn(t['datasource']['uid'],('victorialogs','victoriametrics'))
                    if p['type']=='logs':
                        self.assertIn('_msg',t['expr'])
                        self.assertIn('limit 200',t['expr'])
                    if p['type']=='table' and t['datasource']['uid']=='victoriametrics':
                        self.assertTrue(t['instant'])
                        self.assertEqual(t['format'],'table')

    def test_dashboard_uses_no_unsupported_macros_and_never_reports_missing_telemetry_as_zero(self):
        dashboard = json.loads((SIEM/'dashboards/autonomous-work.json').read_text())
        for panel in dashboard['panels']:
            for target in panel.get('targets', []):
                expr = target['expr']
                # Grafana has no __from/__to/__range macro the logs datasource
                # would expand here; the collector computes the UTC day instead.
                # $__range is expanded by the VictoriaLogs datasource itself
                # (its applyTemplateVariables passes __range to the template
                # service), so a selected-range LogsQL filter may use it; the
                # unsupported date/format macros stay banned.
                for macro in ('${__from', '${__to', '$__from', '$__to'):
                    self.assertNotIn(macro, expr)
                if target['datasource']['uid'] != 'victoriametrics':
                    continue
                if 'source_last_success_seconds' in expr:
                    continue
                # Every metric is gated on a fresh snapshot.
                self.assertIn('ghostship_work_snapshot_timestamp_seconds', expr)
                # Per-source counts are gated on that source being readable, so
                # a missing source shows as unknown instead of zero.
                for metric in ('ghostship_work_attention', 'ghostship_work_active',
                               'ghostship_work_observations', 'ghostship_work_evidence_items',
                               'ghostship_work_usage_samples'):
                    if metric in expr:
                        self.assertIn('ghostship_work_source_up == 1', expr)
                if 'vector(0)' in expr:
                    self.assertIn('ghostship_work_snapshot_timestamp_seconds', expr)

    def test_host_dashboard_shows_cpu_total_per_core_and_memory_split(self):
        page = json.loads((SIEM/'dashboards/host.json').read_text())
        self.assertEqual(page['uid'], 'ghostship-host')
        self.assertFalse(page['editable'])
        titles = {panel['title']: panel for panel in page['panels']}
        for title in ('CPU total  (all cores)', 'CPU per core  /  5-minute busy average', 'Memory used',
                      'Memory total', 'Memory available', 'Host writers', 'CPUs reporting'):
            self.assertIn(title, titles)
        units = {title: titles[title]['fieldConfig']['defaults'].get('unit')
                 for title in ('CPU total  (all cores)', 'Memory used', 'Memory total',
                               'Memory available', 'Memory used %')}
        self.assertEqual(units['CPU total  (all cores)'], 'percent')
        self.assertEqual(units['Memory used %'], 'percent')
        for title in ('Memory used', 'Memory total', 'Memory available'):
            self.assertEqual(units[title], 'bytes')
        # Total CPU averages every core once; per-core is a native state timeline
        # with one row per core in numeric order and restrained busy thresholds.
        self.assertIn('avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))',
                      titles['CPU total  (all cores)']['targets'][0]['expr'])
        per_core = titles['CPU per core  /  5-minute busy average']
        self.assertEqual(per_core['type'], 'state-timeline')
        self.assertIn('avg by (cpu)', per_core['targets'][0]['expr'])
        self.assertIn('sort_by_label_numeric(', per_core['targets'][0]['expr'])
        self.assertEqual(per_core['fieldConfig']['defaults']['unit'], 'percent')
        self.assertEqual([s['value'] for s in per_core['fieldConfig']['defaults']['thresholds']['steps']],
                         [None, 70, 90])
        self.assertFalse(per_core['options']['mergeValues'])
        self.assertEqual(
            [t['expr'] for t in titles['Memory  (total, used, available)']['targets']],
            ['node_memory_MemTotal_bytes', 'node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes',
             'node_memory_MemAvailable_bytes'])
        # The link bar stays the five reviewed pages.
        self.assertEqual(len(page['links']), 5)
        self.assertEqual(len({link['url'] for link in page['links']}), 5)

    def test_agent_table_shows_branch_model_provider_state_and_links(self):
        dashboard = json.loads((SIEM/'dashboards/autonomous-work.json').read_text())
        agents = next(p for p in dashboard['panels'] if p.get('title','').startswith('Agents now'))
        expr = agents['targets'][0]['expr']
        for field in ('status', 'provider', 'model', 'branch', 'thread_url', 'parent_url'):
            self.assertIn(field, expr.split('| fields ')[1])
        self.assertEqual(agents['targets'][0]['datasource']['uid'], 'victorialogs')
        renamed = agents['transformations'][1]['options']['renameByName']
        for column in ('State', 'Provider', 'Model', 'Branch', 'T3 thread', 'Parent'):
            self.assertIn(column, renamed.values())
        # Branch and model are private values: never a metric label.
        for panel in dashboard['panels']:
            for target in panel.get('targets', []):
                if target['datasource']['uid'] == 'victoriametrics':
                    self.assertNotIn('model', target['expr'].replace('model_report', ''))
                    self.assertNotIn('branch', target['expr'])

    def test_dashboard_distinguishes_receipts_from_outcomes(self):
        dashboard = json.loads((SIEM/'dashboards/autonomous-work.json').read_text())
        titles = {panel['title']: panel for panel in dashboard['panels']}
        for title in ('Model reports', 'CI proofs', 'CI failures', 'Review receipts',
                      'PRs closed'):
            self.assertIn(title, list(titles))
            expr = titles[title]['targets'][0]['expr']
            self.assertTrue('evidence_items' in expr or 'ci_failures' in expr)
            self.assertIn('ghostship_work_source_up == 1', expr)
        # Nothing on the page may present a conclusion that no owner records.
        for panel in dashboard['panels']:
            for target in panel.get('targets', []):
                for forbidden in ('approved', 'conclusion', 'frontier_approved'):
                    self.assertNotIn(forbidden, target['expr'])
        header = next(p for p in dashboard['panels'] if p['type'] == 'text')
        self.assertIn('receipt is never a green outcome', header['options']['content'].lower())
        # No panel may claim a complete enumeration of a capped source.
        for panel in dashboard['panels']:
            self.assertNotIn('All projects', panel['title'])
            self.assertNotIn('All threads', panel['title'])

    def test_read_only_auth_network_and_provisioning_invariants(self):
        ui = (SIEM/'ui.nix').read_text()
        for invariant in ['access = "proxy"', 'url = "http://vmauth:8427"', 'editable = false',
                          'allowUiUpdates = false', 'GF_USERS_AUTO_ASSIGN_ORG_ROLE = "Viewer"',
                          'GF_AUTH_PROXY_WHITELIST = cloudflaredAddress', 'iifname "${bridge}" drop',
                          'GF_PLUGINS_PREINSTALL_DISABLED = "true"']:
            self.assertIn(invariant, ui)
        allowlist = ui.split('src_paths =')[1:3]
        self.assertIn('/select/logsql/.+', allowlist[0])
        self.assertIn('/api/v1/(query|query_range|series|labels|label/', allowlist[1])
        self.assertNotIn('/insert', ''.join(allowlist))
        module = (SIEM/'autonomous-work.nix').read_text()
        self.assertIn('PrivateNetwork = true', module)
        self.assertIn('ProtectSystem = "strict"', module)
        self.assertNotIn('t3-token', module)
        fields = module.split('fields = [',1)[1].split('];',1)[0]
        self.assertEqual(set(work.re.findall(r'"([^"]+)"', fields)), work.FIELDS | {'host'})
        self.assertIn('transforms.redacted.inputs = [ "autonomous_work_shape" ]', module)


@unittest.skipUnless(os.environ.get('GHOSTSHIP_TEST_VLOGS') and os.environ.get('GHOSTSHIP_TEST_VMETRICS'),
                     'Set GHOSTSHIP_TEST_VLOGS and GHOSTSHIP_TEST_VMETRICS for disposable native-store checks')
class NativeStoreTests(unittest.TestCase):
    def test_allowance_cards_keep_identity_pacing_marker_and_parent_gate(self):
        # Execute the actual repeated-card expressions with Grafana-style regex
        # escaping. A slash in the composite identity previously made every
        # card query invalid, while direct un-interpolated probes looked green.
        import re
        now = int(time.time())
        stamp = now * 1000
        rows = [f'ghostship_ai_collection_duration_seconds 1 {stamp-120000}',
                f'ghostship_ai_collection_duration_seconds 1 {stamp}',
                f'ghostship_ai_provider_coverage{{provider="claude",source="t3"}} 1 {stamp}',
                f'ghostship_ai_provider_coverage{{provider="cursor",source="t3"}} 1 {stamp}',
                f'ghostship_ai_provider_capacity_remaining_ratio{{provider="claude"}} 0 {stamp}']
        for quota, used in [('seven_day', 1.0), ('seven_day_fable', .05)]:
            # The cards read the canonical entitlement family: one reading per
            # entitlement, with the entitlement id beside the reading.
            labels = (f'provider="claude",account="account.test",model="_",window="weekly",'
                      f'quota="{quota}",source="t3",entitlement="claude:account.test:_:weekly:{quota}"')
            for metric, value in [('used_ratio', used), ('expected_used_ratio', 2/7),
                                  ('pace_delta_ratio', 2/7-used)]:
                rows.append(f'ghostship_ai_entitlement_{metric}{{{labels}}} {value} {stamp}')
        rows += [f'ghostship_ai_model_winner_position{{tier="bulk",provider="ollama",model="current"}} 1 {stamp}',
                 f'ghostship_ai_model_capacity_remaining{{provider="ollama",model="current"}} .8 {stamp}',
                 f'ghostship_ai_model_winner_position{{tier="bulk",provider="ollama",model="unknown"}} 2 {stamp}',
                 f'ghostship_ai_model_winner_position{{tier="bulk",provider="ollama",model="obsolete"}} 1 {stamp-120000}',
                 f'ghostship_ai_model_capacity_remaining{{provider="ollama",model="obsolete"}} .9 {stamp-120000}']
        rows += [f'ghostship_ai_model_rank{{tier="bulk",provider="ollama",model="current"}} 1 {stamp}',
                 f'ghostship_ai_model_rank{{tier="bulk",provider="claude",model="other-provider"}} 1 {stamp}',
                 f'ghostship_ai_model_rank{{tier="bulk",provider="ollama",model="obsolete"}} 1 {stamp-120000}']
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        vm = self.server(os.environ['GHOSTSHIP_TEST_VMETRICS'], tmp.name + '/metrics')
        urllib.request.urlopen(urllib.request.Request(vm + '/api/v1/import/prometheus',
            data='\n'.join(rows).encode()), timeout=3).close()
        urllib.request.urlopen(vm + '/internal/force_flush', timeout=3).close()
        page = json.loads((SIEM/'dashboards/ai-usage.json').read_text())
        by_id = {panel['id']: panel for panel in page['panels']}
        identity = 'claude / account.test / _ / weekly / seven_day_fable / t3'
        escaped = re.sub(r'([.*/])', r'\\\1', identity)

        def query(target):
            expr = target['expr'].replace('$provider', '.*').replace('${allowance:regex}', escaped)
            with urllib.request.urlopen(vm + '/api/v1/query?' + urllib.parse.urlencode({'query': expr}), timeout=3) as response:
                result = json.load(response)['data']['result']
            self.assertEqual(len(result), 1, 'Select exactly the full entitlement identity')
            return float(result[0]['value'][1])

        self.assertAlmostEqual(query(by_id[47]['targets'][0]), .95)
        segments = [query(target) for target in by_id[48]['targets']]
        self.assertAlmostEqual(sum(segments), 1.0)
        self.assertAlmostEqual(sum(segments[:2]) + segments[2]/2, 5/7)
        self.assertAlmostEqual(query(by_id[49]['targets'][1]), 100*(2/7-.05))
        self.assertEqual(query(by_id[49]['targets'][2]), 0,
                         'The shared exhausted weekly blocks the 95%-remaining sublimit')
        expr = by_id[44]['targets'][0]['expr'].replace('$provider', '.*')
        with urllib.request.urlopen(vm + '/api/v1/query?' + urllib.parse.urlencode({'query': expr}), timeout=3) as response:
            providers = json.load(response)['data']['result']
        self.assertEqual({row['metric']['provider']: float(row['value'][1]) for row in providers},
                         {'claude': 0, 'cursor': -1},
                         'Exhausted and unknown providers must remain distinct')
        for target, expected in zip(by_id[41]['targets'],
                                    [{'current': 1, 'unknown': 2}, {'current': .8, 'unknown': -1}]):
            expr = target['expr'].replace('$provider', '.*')
            with urllib.request.urlopen(vm + '/api/v1/query?' + urllib.parse.urlencode({'query': expr}), timeout=3) as response:
                result = json.load(response)['data']['result']
            self.assertEqual({r['metric']['model']: float(r['value'][1]) for r in result}, expected,
                             'Old series inside the lookback must not become current recommendations')
        expr = by_id[10]['targets'][0]['expr'].replace('$provider', 'ollama')
        for selected_time, expected in [(now, {'current'}), (now-60, {'obsolete'})]:
            with urllib.request.urlopen(vm + '/api/v1/query?' + urllib.parse.urlencode(
                    {'query': expr, 'time': selected_time}), timeout=3) as response:
                result = json.load(response)['data']['result']
            self.assertEqual({r['metric']['model'] for r in result}, expected,
                             'Details respect both the Provider filter and the selected end time')

    def test_one_allowance_card_per_entitlement_when_one_window_has_two_readings(self):
        # The T3 status names the OpenCode Go windows go_monthly/go_rolling/go_weekly
        # and the provider's own endpoint names monthly/rolling/weekly: one
        # entitlement, read twice. The allowance list must show it once, while
        # the quota table keeps every raw reading.
        import re
        now = int(time.time())
        stamp = now * 1000
        rows = [f'ghostship_ai_collection_duration_seconds 1 {stamp}']
        for quota in ('go_weekly', 'weekly'):
            rows.append(
                f'ghostship_ai_quota_used_ratio{{provider="opencode-go",account="default",model="*",'
                f'window="weekly",quota="{quota}",source="t3"}} 0.4 {stamp}'
            )
        labels = ('provider="opencode-go",account="default",model="*",window="weekly",'
                  'quota="weekly",source="t3",'
                  'entitlement="opencode-go:default:*:weekly:weekly"')
        rows.append(f'ghostship_ai_entitlement_info{{{labels}}} 1 {stamp}')
        rows.append(f'ghostship_ai_entitlement_used_ratio{{{labels}}} 0.4 {stamp}')
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        vm = self.server(os.environ['GHOSTSHIP_TEST_VMETRICS'], tmp.name + '/metrics')
        urllib.request.urlopen(urllib.request.Request(vm + '/api/v1/import/prometheus',
            data='\n'.join(rows).encode()), timeout=3).close()
        urllib.request.urlopen(vm + '/internal/force_flush', timeout=3).close()
        page = json.loads((SIEM/'dashboards/ai-usage.json').read_text())
        by_id = {panel['id']: panel for panel in page['panels']}
        allowance = page['templating']['list'][1]

        def query(expr):
            with urllib.request.urlopen(vm + '/api/v1/query?' + urllib.parse.urlencode({'query': expr}),
                                       timeout=5) as response:
                return json.load(response)['data']['result']

        # The allowance list is built from the canonical entitlement family.
        self.assertIn('ghostship_ai_entitlement_info', allowance['query'])
        self.assertNotIn('ghostship_ai_quota_used_ratio', allowance['query'])
        for panel_id in (47, 48, 49):
            for target in by_id[panel_id]['targets']:
                for raw in ('ghostship_ai_quota_used_ratio', 'ghostship_ai_quota_expected_used_ratio',
                            'ghostship_ai_quota_pace_delta_ratio', 'ghostship_ai_quota_reset_timestamp_seconds'):
                    self.assertNotIn(raw, target['expr'],
                                     f'panel {panel_id} must read the canonical entitlement, not the raw reading')
        # Grafana strips the query_result() wrapper before it asks the store.
        inner = re.match(r'^query_result\((.*)\)$', allowance['query'], re.S).group(1)
        listed = query(inner.replace('$provider', '.*'))
        self.assertEqual(len(listed), 1, 'One entitlement is one allowance, not one per alias reading')
        self.assertEqual(listed[0]['metric']['allowance'],
                         'opencode-go / default / * / weekly / weekly / t3')
        # Both raw readings stay visible in the quota table.
        self.assertEqual(len(query('ghostship_ai_quota_used_ratio')), 2)
        identity = 'opencode-go / default / * / weekly / weekly / t3'
        escaped = re.sub(r'([.*/])', r'\\\1', identity)
        expr = (by_id[47]['targets'][0]['expr'].replace('$provider', '.*')
                .replace('${allowance:regex}', escaped))
        cards = query(expr)
        self.assertEqual(len(cards), 1, 'The card selects exactly the one entitlement')
        self.assertAlmostEqual(float(cards[0]['value'][1]), .6)

    def server(self, binary, directory):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        extra = ['-search.latencyOffset=0'] if Path(binary).name=='victoria-metrics' else []
        proc = subprocess.Popen([binary, f'-storageDataPath={directory}',
                                 f'-httpListenAddr=127.0.0.1:{port}', '-loggerLevel=ERROR', *extra],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def stop():
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        self.addCleanup(stop)
        url = f'http://127.0.0.1:{port}'
        for _ in range(100):
            try:
                urllib.request.urlopen(url+'/health', timeout=0.1).close()
                return url
            except OSError:
                time.sleep(0.05)
        self.fail('Disposable test store did not become ready')

    def test_host_cpu_and_memory_panels_report_all_cores_and_the_memory_split(self):
        # A real VictoriaMetrics fixture with two cores (one idle, one busy) and
        # a total/available split proves the panel queries, their machine filter
        # and their non-duplication, not just that the API returned success.
        now = int(time.time())
        older = (now - 120) * 1000
        newer = (now - 60) * 1000
        fixture = '\n'.join([
            f'node_cpu_seconds_total{{cpu="0",mode="idle"}} 0 {older}',
            f'node_cpu_seconds_total{{cpu="0",mode="idle"}} 60 {newer}',
            f'node_cpu_seconds_total{{cpu="1",mode="idle"}} 0 {older}',
            f'node_cpu_seconds_total{{cpu="1",mode="idle"}} 0 {newer}',
            f'node_memory_MemTotal_bytes 1000 {newer}',
            f'node_memory_MemAvailable_bytes 400 {newer}',
            f'node_uname_info{{nodename="fixture"}} 1 {newer}',
        ]).encode()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        vm = self.server(os.environ['GHOSTSHIP_TEST_VMETRICS'], tmp.name + '/metrics')
        urllib.request.urlopen(urllib.request.Request(vm + '/api/v1/import/prometheus', data=fixture,
                                                     headers={'Content-Type': 'text/plain'}), timeout=3).close()
        urllib.request.urlopen(vm + '/internal/force_flush', timeout=3).close()

        def query(expr):
            url = vm + '/api/v1/query?' + urllib.parse.urlencode({'query': expr})
            with urllib.request.urlopen(url, timeout=5) as response:
                return json.load(response)['data']['result']

        page = json.loads((SIEM/'dashboards/host.json').read_text())
        by_id = {panel['id']: panel for panel in page['panels']}
        # Select by panel id: a retitled panel must not break this load-bearing test.
        total = query(by_id[1001]['targets'][0]['expr'])
        self.assertEqual(len(total), 1)
        self.assertAlmostEqual(float(total[0]['value'][1]), 50.0, places=3)
        cores = query(by_id[8]['targets'][0]['expr'])
        self.assertEqual(len(cores), 2, 'One series per cpu, no duplicated core')
        self.assertEqual(sorted(float(c['value'][1]) for c in cores), [0.0, 100.0])
        self.assertEqual(float(query(by_id[1002]['targets'][0]['expr'])[0]['value'][1]), 600.0)
        self.assertEqual(float(query(by_id[1003]['targets'][0]['expr'])[0]['value'][1]), 1000.0)
        self.assertEqual(float(query(by_id[1004]['targets'][0]['expr'])[0]['value'][1]), 400.0)
        self.assertAlmostEqual(float(query(by_id[1007]['targets'][0]['expr'])[0]['value'][1]), 60.0, places=3)
        self.assertEqual(float(query(by_id[1008]['targets'][0]['expr'])[0]['value'][1]), 1.0)
        self.assertEqual(float(query(by_id[1009]['targets'][0]['expr'])[0]['value'][1]), 2.0)
        memory = {m['metric'].get('__name__') for m in query(by_id[2]['targets'][0]['expr'])}
        self.assertEqual(len(memory), 1, 'A single memory total series from one writer')
        self.assertAlmostEqual(float(query(by_id[1006]['targets'][0]['expr'])[0]['value'][1]), 60.0, delta=70)

    def test_ai_usage_exception_table_reports_only_unhealthy_sources(self):
        # The exception panel must never list a healthy provider: every target is
        # restricted to the exception set, and the ages only cover those sources.
        now = int(time.time())
        samples = [
            ('healthy', 'ok', 1, now - 60),
            ('partial', 'partial', 1, now - 60),
            ('stale', 'ok', 1, now - 3600),
            ('failed', 'ok', 0, now - 60),
        ]
        lines = []
        for source, status, success, last in samples:
            lines.append(f'ghostship_ai_provider_coverage{{provider="{source}",source="{source}"}} 1 {now*1000}')
            lines.append(f'ghostship_ai_source_status{{provider="{source}",source="{source}",status="{status}"}} 1 {now*1000}')
            lines.append(f'ghostship_ai_source_success{{provider="{source}",source="{source}"}} {success} {now*1000}')
            lines.append(f'ghostship_ai_source_last_success_timestamp_seconds{{provider="{source}",source="{source}"}} {last} {now*1000}')
            lines.append(f'ghostship_ai_source_observed_timestamp_seconds{{provider="{source}",source="{source}"}} {now-30} {now*1000}')
        # A provider whose coverage exists but whose source never reported.
        lines.append(f'ghostship_ai_provider_coverage{{provider="missing",source="missing"}} 1 {now*1000}')
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        vm = self.server(os.environ['GHOSTSHIP_TEST_VMETRICS'], tmp.name + '/metrics')
        urllib.request.urlopen(urllib.request.Request(
            vm + '/api/v1/import/prometheus', data=('\n'.join(lines)).encode(),
            headers={'Content-Type': 'text/plain'}), timeout=3).close()
        urllib.request.urlopen(vm + '/internal/force_flush', timeout=3).close()

        page = json.loads((SIEM/'dashboards/ai-usage.json').read_text())
        panel = next(p for p in page['panels'] if p['title'] == 'Providers with no fresh reading')

        def query(expr):
            # The Provider filter at All substitutes its allValue.
            expr = expr.replace('$provider', '.*')
            url = vm + '/api/v1/query?' + urllib.parse.urlencode({'query': expr})
            with urllib.request.urlopen(url, timeout=5) as response:
                return json.load(response)['data']['result']

        exceptions = {item['metric'].get('provider') for item in query(panel['targets'][0]['expr'])}
        self.assertNotIn('healthy', exceptions)
        self.assertEqual(exceptions, {'partial', 'stale', 'failed', 'missing'})
        status = {item['metric']['provider']: item['metric'].get('status')
                  for item in query(panel['targets'][1]['expr'])}
        self.assertEqual(status.get('partial'), 'partial', 'A partial source stays visible')
        self.assertNotIn('healthy', status)
        self.assertNotIn('missing', status, 'A source with no reading has no status, not a healthy one')
        ages = {item['metric'].get('provider') for item in query(panel['targets'][2]['expr'])}
        self.assertEqual(ages, {'partial', 'stale', 'failed'})

    def test_ai_usage_decision_hierarchy_units_and_variables(self):
        page = json.loads((SIEM/'dashboards/ai-usage.json').read_text())
        by_id = {panel['id']: panel for panel in page['panels']}
        titles = {panel['title']: panel for panel in page['panels']}
        winners = titles['Winners by tier']
        detail = titles['Winner detail  /  source, quality, expiry']
        units = {}
        for override in winners['fieldConfig']['overrides'] + detail['fieldConfig']['overrides']:
            for prop in override['properties']:
                if prop['id'] == 'unit':
                    units[override['matcher']['options']] = prop['value']
        self.assertEqual(units['Capacity'], 'percentunit')
        self.assertEqual(units['Expires in'], 'dtdurations')
        # The core table carries only the decision fields; the evidence is a
        # drilldown panel with the value's source, so a prior estimate never
        # reads as measured.
        core_fields = list(winners['transformations'][2]['options']['indexByName'])
        self.assertEqual(core_fields, ['tier', 'provider', 'model', 'Value', 'Capacity'])
        self.assertNotIn('Expires in', core_fields)
        self.assertIn('group_left(source)', detail['targets'][0]['expr'])
        renamed = detail['transformations'][1]['options']['renameByName']
        self.assertIn('Source', renamed.values())
        # Core columns are narrow enough to read at phone width.
        widths = {}
        for override in winners['fieldConfig']['overrides']:
            for prop in override['properties']:
                if prop['id'] == 'custom.width':
                    widths[override['matcher']['options']] = prop['value']
        self.assertLessEqual(sum(widths.values()), 460)
        # Rows are grouped by tier, never interleaved by position.
        self.assertEqual(winners['options']['sortBy'][0]['displayName'], 'tier')
        self.assertEqual([v['name'] for v in page['templating']['list']], ['provider', 'allowance'])
        allowance = page['templating']['list'][1]
        self.assertEqual(allowance['hide'], 2)
        # Repeated cards must select one complete entitlement, including
        # sources and model scopes which may share a quota/window name.
        for label in ('provider', 'account', 'model', 'window', 'quota', 'source'):
            self.assertIn('"' + label + '"', allowance['query'])
        self.assertEqual(by_id[46]['repeat'], 'allowance')
        candidates = titles['Candidates considered']
        self.assertTrue(all('$provider' in t['expr'] for t in candidates['targets']))
        self.assertLessEqual(len(candidates['targets']), 8)
        self.assertFalse(any('calculation_gate' in t['expr']
                             for p in page['panels'] for t in p.get('targets', [])))
        self.assertIn('Routing off or disabled providers', titles)
        exception = titles['Providers with no fresh reading']
        self.assertTrue(all('unless on(source)' in t['expr'] for t in exception['targets']))
        self.assertLess(titles['Frontier tier']['gridPos']['y'], titles['Winners by tier']['gridPos']['y'])
        self.assertLess(titles['Winners by tier']['gridPos']['y'], titles['Candidates considered']['gridPos']['y'])
        self.assertLess(titles['Providers with no fresh reading']['gridPos']['y'],
                        titles['Quota windows']['gridPos']['y'])

    def test_host_grid_reports_twenty_cores_in_numeric_order_with_a_hot_core(self):
        now = int(time.time())
        older, newer = (now - 120) * 1000, (now - 60) * 1000
        lines = []
        for cpu in range(20):
            # core 7 is saturated; every other core is idle.
            idle = 0 if cpu == 7 else 60
            lines.append(f'node_cpu_seconds_total{{cpu="{cpu}",mode="idle"}} 0 {older}')
            lines.append(f'node_cpu_seconds_total{{cpu="{cpu}",mode="idle"}} {idle} {newer}')
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        vm = self.server(os.environ['GHOSTSHIP_TEST_VMETRICS'], tmp.name + '/metrics')
        urllib.request.urlopen(urllib.request.Request(vm + '/api/v1/import/prometheus',
                                                     data=('\n'.join(lines)).encode(),
                                                     headers={'Content-Type': 'text/plain'}), timeout=3).close()
        urllib.request.urlopen(vm + '/internal/force_flush', timeout=3).close()
        page = json.loads((SIEM/'dashboards/host.json').read_text())
        grid = next(panel for panel in page['panels'] if panel['id'] == 8)
        url = vm + '/api/v1/query?' + urllib.parse.urlencode({'query': grid['targets'][0]['expr']})
        with urllib.request.urlopen(url, timeout=5) as response:
            result = json.load(response)['data']['result']
        self.assertEqual(len(result), 20, 'Every core must be present')
        order = [int(item['metric']['cpu']) for item in result]
        self.assertEqual(order, sorted(order), 'sort_by_label_numeric keeps 2 before 10')
        hot = {int(item['metric']['cpu']): float(item['value'][1]) for item in result}
        self.assertAlmostEqual(hot[7], 100.0, places=3)
        # A core with no samples at all is absent (a true gap), which the grid shows
        # as no row; a skipped scrape inside a 5m rate is interpolated and must not
        # be asserted as a gap.
        lines.append(f'node_cpu_seconds_total{{cpu="99",mode="idle"}} 0 {older}')
        urllib.request.urlopen(urllib.request.Request(vm + '/api/v1/import/prometheus',
                                                     data=(lines[-1] + '\n').encode(),
                                                     headers={'Content-Type': 'text/plain'}), timeout=3).close()
        urllib.request.urlopen(vm + '/internal/force_flush', timeout=3).close()
        with urllib.request.urlopen(url, timeout=5) as response:
            single = json.load(response)['data']['result']
        self.assertNotIn(99, [int(item['metric']['cpu']) for item in single],
                         'One sample cannot form a rate, so the core has no row')

    def test_actual_dashboard_queries_against_native_stores_and_repoll_dedup(self):
        fixture = CollectorTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        now = time.time()
        rows, metrics = fixture.collect()
        for row in rows:
            row['timestamp'] = work.iso(now)
            if 'event_seconds' in row:
                row['event_seconds'] = now-10
                row['event_at'] = work.iso(now-10)
            if 'fired_seconds' in row:
                row['fired_seconds'] = now-20
                row['fired_at'] = work.iso(now-20)
            for key in ('event_at', 'fired_at'):
                if key in row and row[key]:
                    row[key.replace('_at', '_today')] = int(
                        work.utc_day(row[key]) == work.utc_day(work.iso(now)))
        metrics = metrics.replace(str(NOW), str(now))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        logs = self.server(os.environ['GHOSTSHIP_TEST_VLOGS'], tmp.name+'/logs')
        vm = self.server(os.environ['GHOSTSHIP_TEST_VMETRICS'], tmp.name+'/metrics')
        payload = ''.join(json.dumps(row)+'\n' for row in rows).encode()
        def insert():
            request = urllib.request.Request(logs+'/insert/jsonline?_stream_fields=host,source,stream&_msg_field=message&_time_field=timestamp', data=payload, headers={'Content-Type':'application/stream+json'})
            urllib.request.urlopen(request, timeout=3).close()
        insert()
        urllib.request.urlopen(urllib.request.Request(vm+'/api/v1/import/prometheus', data=metrics.encode(), headers={'Content-Type':'text/plain'}), timeout=3).close()
        # Native VM intentionally buffers writes; flush only this disposable
        # local test instance before asserting actual sample visibility.
        urllib.request.urlopen(vm+'/internal/force_flush', timeout=3).close()
        dashboards = [json.loads(p.read_text()) for p in (SIEM/'dashboards').glob('*.json')]
        def log_query(expr):
            expr = expr.replace('${__from:date:seconds}', str(int(now)-3600)).replace('${__to:date:seconds}', str(int(now)+60))
            query = urllib.parse.urlencode({'query':expr})
            with urllib.request.urlopen(logs+'/select/logsql/query?'+query, timeout=5) as response:
                return [json.loads(line) for line in response.read().splitlines()]
        for _ in range(100):
            if log_query('stream:=autonomous-work _time:3m | limit 1'):
                break
            time.sleep(0.1)
        def stats_query(expr):
            params={'query':expr,'start':now-3600,'end':now,'step':'300s'}
            with urllib.request.urlopen(logs+'/select/logsql/stats_query?'+urllib.parse.urlencode(params),timeout=5) as response:
                result=json.load(response)
            self.assertEqual(result['status'],'success')
            return result['data']['result']
        before = []
        counts = []
        for dashboard in dashboards:
            for panel in dashboard['panels']:
                for target in panel.get('targets', []):
                    with self.subTest(panel=panel['title']):
                        if target['datasource']['uid']=='victorialogs':
                            if target['queryType']=='instant':
                                rows_found=log_query(target['expr'])
                                before.append((target['expr'],rows_found))
                                if dashboard['uid']=='ghostship-autonomous-work':
                                    self.assertTrue(rows_found,
                                                    'Every autonomous-work list panel must show fixture rows: '
                                                    + panel['title'] + ' :: ' + target['expr'])
                            elif target['queryType']=='stats':
                                found=stats_query(target['expr'])
                                counts.append((target['expr'],found))
                                if dashboard['uid']=='ghostship-autonomous-work':
                                    self.assertTrue(found,
                                                    'Every autonomous-work count panel must count fixture rows')
                            else:
                                endpoint='stats_query_range' if target['queryType']=='statsRange' else 'stats_query'
                                params={'query':target['expr'],'start':now-3600,'end':now,'step':'300s'}
                                with urllib.request.urlopen(logs+'/select/logsql/'+endpoint+'?'+urllib.parse.urlencode(params),timeout=5) as response: result=json.load(response)
                                self.assertEqual(result['status'],'success')
                        else:
                            url = vm+'/api/v1/query?'+urllib.parse.urlencode({'query':target['expr']})
                            with urllib.request.urlopen(url, timeout=5) as response:
                                result = json.load(response)
                            self.assertEqual(result['status'], 'success')
                            if target['expr']=='time() - ghostship_work_snapshot_timestamp_seconds':
                                self.assertTrue(result['data']['result'], 'Fixture metric must reach the native query path')
                            if dashboard['uid']=='ghostship-autonomous-work' and 'ghostship_work_evidence_items' in target['expr']:
                                self.assertTrue(result['data']['result'],
                                                'Fixture evidence metrics must reach the native query path')
        self.assertTrue(any(result for _,result in before), 'Fixture must produce visible dashboard rows')
        insert()
        time.sleep(1)
        for expr, result in before:
            self.assertEqual(len(log_query(expr)), len(result), 'Polling must not multiply list entries')
        for expr, result in counts:
            self.assertEqual(stats_query(expr), result, 'Polling must not multiply counted entries')
        # A real state transition must remain in history alongside its prior
        # observation; deduplicating only by work ID would lose that history.
        changed = dict(next(r for r in rows if r['kind']=='run'))
        changed.update(status='completed', event_at=work.iso(now-5), event_seconds=now-5)
        payload = (json.dumps(changed)+'\n').encode()
        insert()
        time.sleep(1)
        timeline_expr, timeline_before = next((expr,result) for expr,result in before if 'partition by (source,kind,work_id,event_at,status)' in expr)
        expected=len(timeline_before)+1
        for _ in range(50):
            result=log_query(timeline_expr)
            if len(result)==expected:break
            time.sleep(0.1)
        self.assertEqual(len(result),expected)


@unittest.skipUnless(os.environ.get('GHOSTSHIP_TEST_GRAFANA') and os.environ.get('GHOSTSHIP_TEST_PROVISIONING'),
                     'Set GHOSTSHIP_TEST_GRAFANA and GHOSTSHIP_TEST_PROVISIONING for native provisioning/auth checks')
class GrafanaProvisioningTests(unittest.TestCase):
    def test_actual_provisioning_home_five_dashboards_and_datasource_auth(self):
        # Fresh Grafana migrations fsync hundreds of transactions. Use private
        # tmpfs for this disposable DB so the loop measures provisioning, not
        # the host filesystem's fsync latency.
        tmp = tempfile.TemporaryDirectory(dir='/dev/shm' if Path('/dev/shm').is_dir() else None)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        provisioning = root/'provisioning'
        shutil.copytree(os.environ['GHOSTSHIP_TEST_PROVISIONING'], provisioning)
        # Nix outputs are read-only; the test changes only this private copy's
        # target URLs/paths to use disposable loopback services and fixture auth.
        for path in provisioning.rglob('*'):
            path.chmod(0o755 if path.is_dir() else 0o644)
        provisioning.chmod(0o755)
        password = 'disposable-test-password'
        expected = 'Basic '+base64.b64encode(('grafana:'+password).encode()).decode()
        authenticated = []
        class Backend(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                ok = self.headers.get('Authorization')==expected
                authenticated.append(ok)
                self.send_response(200 if ok else 401)
                self.send_header('Content-Type','application/json')
                self.end_headers()
                self.wfile.write(b'{"status":"success","data":{"resultType":"vector","result":[]}}')
            def log_message(self, *_args):
                pass
        backend = http.server.ThreadingHTTPServer(('127.0.0.1',0),Backend)
        threading.Thread(target=backend.serve_forever,daemon=True).start()
        self.addCleanup(backend.server_close)
        self.addCleanup(backend.shutdown)
        ds_path = provisioning/'datasources/siem.yaml'
        datasources = json.loads(ds_path.read_text())
        for ds in datasources['datasources']:
            ds['url'] = f'http://127.0.0.1:{backend.server_port}'
        ds_path.write_text(json.dumps(datasources))
        provider_path = provisioning/'dashboards/siem.yaml'
        providers = json.loads(provider_path.read_text())
        providers['providers'][0]['options']['path'] = str(provisioning/'dashboards-json')
        provider_path.write_text(json.dumps(providers))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        package = Path(os.environ['GHOSTSHIP_TEST_GRAFANA'])
        env = {'PATH':os.environ['PATH'],'HOME':str(root),'TMPDIR':str(root),'GRAFANA_VMAUTH_PASSWORD':password,
               'GF_PATHS_DATA':str(root/'data'),'GF_PATHS_LOGS':str(root/'logs'),
               'GF_PATHS_PLUGINS':str(root/'plugins'),'GF_PATHS_PROVISIONING':str(provisioning),
               'GF_SERVER_HTTP_ADDR':'127.0.0.1','GF_SERVER_HTTP_PORT':str(port),
               'GF_AUTH_ANONYMOUS_ENABLED':'true','GF_AUTH_ANONYMOUS_ORG_ROLE':'Viewer',
               'GF_LOG_LEVEL':'info','GF_ANALYTICS_REPORTING_ENABLED':'false',
               'GF_ANALYTICS_CHECK_FOR_UPDATES':'false','GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES':'false',
               'GF_PLUGINS_PREINSTALL_DISABLED':'true','GF_PLUGINS_PUBLIC_KEY_RETRIEVAL_DISABLED':'true',
               'GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH':str(provisioning/'dashboards-json/autonomous-work.json'),
               'GF_USERS_HOME_PAGE':'/d/ghostship-autonomous-work'}
        logfile=root/'grafana.log'
        output=logfile.open('w')
        self.addCleanup(output.close)
        proc = subprocess.Popen([str(package/'bin/grafana'),'server','--homepath',str(package/'share/grafana')],
                                env=env,stdout=output,stderr=output)
        def stop():
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
        self.addCleanup(stop)
        url = f'http://127.0.0.1:{port}'
        for _ in range(300):
            try:
                urllib.request.urlopen(url+'/api/health',timeout=0.1).close();break
            except OSError:
                if proc.poll() is not None:self.fail('Disposable Grafana exited before readiness')
                time.sleep(0.1)
        else:self.fail('Disposable Grafana did not become ready: '+logfile.read_text()[-3500:].replace(password,'<fixture>'))
        with urllib.request.urlopen(url+'/api/search?type=dash-db',timeout=5) as response:
            dashboards=json.load(response)
        self.assertEqual({d['uid'] for d in dashboards},
                         {'ghostship-autonomous-work','ghostship-host','ghostship-security',
                          'ghostship-siem-pipeline','ghostship-ai-usage'})
        with urllib.request.urlopen(url+'/api/dashboards/home',timeout=5) as response:home=json.load(response)
        self.assertTrue(home.get('redirectUri','').startswith('/d/ghostship-autonomous-work') or
                        home.get('dashboard',{}).get('uid')=='ghostship-autonomous-work',
                        'Home must open the provisioned overview instead of generic Welcome')
        with urllib.request.urlopen(url+'/api/datasources/proxy/uid/victoriametrics/api/v1/query?query=up',timeout=5) as response:
            self.assertEqual(response.status,200)
        self.assertTrue(authenticated and all(authenticated), 'Provisioned datasource auth must resolve the restricted environment credential')


if __name__ == '__main__':
    unittest.main()
