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
ENV = '22222222-2222-4222-8222-222222222222'
SECRET = 'DO_NOT_EXPORT_SECRET_BODY_TOKEN'


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'stock.sqlite'
        self.config = {key: str(self.path) for key in
                       ['t3_db', 'coordinator_db', 'runtime_db', 'mcp_runtime_db']}
        self.config.update(environment_id=ENV, host='fixture')
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
                        ('child', THREAD, THREAD, 'codex', 'running', None, at,
                         json.dumps({'note': SECRET})))
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
                        self.assertIn('limit 200', target['expr'])
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
            for panel in page['panels']:
                if panel.get('type') == 'text':
                    content = panel['options']['content']
                    self.assertEqual(content.count('ghostship-ai-usage'), 1)
                    self.assertLessEqual(content.count('/d/ghostship-'), 5)

    def test_all_four_pages_have_consistent_direct_navigation_and_source_shapes(self):
        dashboards=[json.loads(p.read_text()) for p in (SIEM/'dashboards').glob('*.json')]
        self.assertEqual(len(dashboards),4)
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
                for macro in ('${__from', '${__to', '$__range', '$__from', '$__to'):
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

    def test_dashboard_distinguishes_receipts_from_outcomes(self):
        dashboard = json.loads((SIEM/'dashboards/autonomous-work.json').read_text())
        titles = {panel['title']: panel for panel in dashboard['panels']}
        for title in ('Model reports', 'CI proofs', 'CI failures', 'Review receipts',
                      'Pull requests closed'):
            self.assertIn(title, titles)
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
    def test_actual_provisioning_home_four_dashboards_and_datasource_auth(self):
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
                         {'ghostship-autonomous-work','ghostship-host','ghostship-security','ghostship-siem-pipeline'})
        with urllib.request.urlopen(url+'/api/dashboards/home',timeout=5) as response:home=json.load(response)
        self.assertTrue(home.get('redirectUri','').startswith('/d/ghostship-autonomous-work') or
                        home.get('dashboard',{}).get('uid')=='ghostship-autonomous-work',
                        'Home must open the provisioned overview instead of generic Welcome')
        with urllib.request.urlopen(url+'/api/datasources/proxy/uid/victoriametrics/api/v1/query?query=up',timeout=5) as response:
            self.assertEqual(response.status,200)
        self.assertTrue(authenticated and all(authenticated), 'Provisioned datasource auth must resolve the restricted environment credential')


if __name__ == '__main__':
    unittest.main()
