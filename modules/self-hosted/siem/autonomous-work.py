#!/usr/bin/env python3
"""Bounded, read-only observations; no transcripts, prompts or orchestration writes.

Stock T3 v0.1.0 contracts: scheduledTasks.list / /api/orchestration/shell;
backing schemas in Migrations/OrchestrationV2/{ScheduledTasks,Subagents}.ts,
055_OrchestrationV2.ts and 057_ScheduledTaskWebhooks.ts. Read those projections
locally, selecting only allowlisted columns (including JSON scalar extraction).
Each poll is a snapshot, never an increment. Lists deduplicate in LogsQL; the
existing stores own retention. No cursor, orchestration DB or transcript archive.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import subprocess
import time

LIMIT = 200
QUERY_SECONDS = 1.0
HISTORY_SECONDS = 86400
STATES = {'pending', 'queued', 'running', 'starting', 'in_progress', 'waiting',
          'blocked', 'failed', 'error', 'denied', 'timeout', 'uncertain', 'partial',
          'upstream_blocked', 'unavailable', 'cancelled', 'interrupted', 'completed',
          'succeeded', 'success', 'done', 'ignored', 'accepted', 'disabled', 'enabled',
          'prepared', 'switch_uncertain', 'switch_accepted', 'message_uncertain', 'message_accepted', 'executing',
          'open', 'closed', 'merged', 'idle', 'never', 'unknown', 'retry', 'held', 'expired', 'conflict',
          'requested', 'native-running', 'terminal', 'reported', 'superseded', 'preparing', 'resolved',
          'dispatch_failed', 'duplicate', 'coalesced', 'rejected_signature', 'rate_limited', 'filtered',
          'unverified', 'checks_passed', 'verified_ci', 'pending_ci', 'archived'}
ACTIVE = {'pending', 'queued', 'running', 'starting', 'in_progress', 'waiting', 'requested', 'native-running', 'preparing', 'prepared', 'executing'}
ATTENTION = {'blocked', 'failed', 'error', 'denied', 'timeout', 'uncertain',
             'upstream_blocked', 'unavailable', 'partial', 'held', 'conflict',
             'dispatch_failed', 'rejected_signature', 'rate_limited', 'switch_uncertain', 'message_uncertain'}
PROVIDERS = {'codex', 'opencode', 'antigravity', 'claudeAgent', 'claude-code', 'claude',
             'gemini', 'grok', 'openai', 'anthropic', 'google', 'copilot'}
# Completion claims are not interchangeable. A model report, a CI receipt and a
# deployment receipt are different evidence. No source exposes objective proof
# today, so it stays an explicit gap instead of a reported zero.
EVIDENCE = {'model_report', 'ci', 'ci_proof', 'review', 'pr_closed', 'deployment'}
CI_EVENTS = {'workflow_run', 'check_run', 'check_suite'}
DEPLOYMENT_EVENTS = {'deployment_status'}
REVIEW_EVENTS = {'pull_request_review'}
# A receipt is not an outcome: the coordinator records that a review was
# submitted or that a pull request was closed, never the verdict, the merge
# result or the CI conclusion.
ACTIONS = {'opened', 'edited', 'closed', 'ready_for_review', 'submitted', 'created',
           'completed', 'reopened', 'synchronize', 'labeled', 'unlabeled'}
# The compact owner states of the coordinator. The raw note is never read.
OWNER_STATES = {'incomplete', 'uncertain', 'closed_unverified'}
# Kinds whose status is the provider's or the runtime's own report about work.
REPORTED_KINDS = {'review', 'run', 'subagent', 'thread', 'workflow', 'continuation'}
EVENTS = {'issues', 'issue_comment', 'pull_request', 'pull_request_review',
          'pull_request_review_comment', 'workflow_run', 'check_run', 'check_suite',
          'push', 'deployment_status'}
UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
# Native thread ids are opaque: ordinary threads are UUIDs and app-owned child
# threads look like 'thread:delegated-task:command%3Amcp%3A...'. Bound the shape
# instead of assuming a UUID, or every child link is silently dropped.
THREAD_ID = re.compile(
    r'^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    r'|mcp:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    r'|thread:[A-Za-z0-9:._%~-]{1,280})$')
BRANCH = re.compile(r'^[A-Za-z0-9._/-]{1,120}$')
MODEL = re.compile(r'^[A-Za-z0-9._:/-]{1,80}$')
WEB_URL = 'https://t3code.ghostship.io'
# The stock deep link of ghostship_t3.bridge.thread_url: a plain path join of
# the environment and the raw (already percent-encoded) thread id, and the app
# deep link when the environment is unknown.
ACTIVE_PAGE = 500
ACTIVE_PAGES = 4
ACTIVE_RUNS = ('running', 'pending', 'starting', 'waiting', 'queued', 'requested',
               'native-running', 'preparing', 'prepared', 'executing')
ACTIVE_SQL = '(' + ','.join(f"'{status}'" for status in ACTIVE_RUNS) + ')'
# The current run of a thread: an executing run first, then queued work, then
# the latest executed run by completion time, ties by ordinal. The projection
# stores no authoritative active-run binding, so execution authority is the
# highest ranked evidence: a newer queued model switch must never hide the run
# that is actually executing. A queued run stays visible as queued work, not as
# execution. A cancelled run that provably never started is not executed.
EXECUTING_SQL = ('(' + ','.join(f"'{status}'" for status in
                                ('running', 'starting', 'executing', 'preparing',
                                 'native-running', 'waiting')) + ')')
QUEUED_SQL = "('queued','pending','prepared','requested')"
CURRENT_RUN = f'''SELECT r2.run_id FROM orchestration_v2_projection_runs r2
        WHERE r2.thread_id=t.thread_id
          AND NOT (r2.status='cancelled' AND CASE WHEN json_valid(r2.payload_json)
            THEN coalesce(json_type(r2.payload_json,'$.startedAt')='null',0) ELSE 0 END)
        ORDER BY CASE WHEN r2.status IN {EXECUTING_SQL} THEN 0
                      WHEN r2.status IN {QUEUED_SQL} THEN 1 ELSE 2 END,
          coalesce(r2.completed_at,r2.requested_at) DESC, r2.ordinal DESC, r2.run_id LIMIT 1'''
AGENT_STATES = {'running': 'running', 'starting': 'running', 'executing': 'running',
                'preparing': 'running', 'pending': 'queued', 'queued': 'queued',
                'prepared': 'queued', 'requested': 'queued', 'waiting': 'waiting',
                'native-running': 'running'}
# Only fixed machine fields leave this process. Free text (even titles/errors)
# can contain secrets and is deliberately not exported.
FIELDS = {'source', 'kind', 'work_id', 'status', 'event_at', 'next_at', 'trigger',
          'thread_url', 'github_url', 'provider',
          'unit', 'coverage', 'reason', 'rows', 'limited', 'duration_seconds', 'fired_at', 'event', 'event_seconds', 'fired_seconds', 'project_id', 'thread_count', 'occupied', 'route_state', 'primary_quota', 'route_reason', 'fallback', 'switch_accepted', 'message_accepted', 'native_run_count', 'executing_count',
          'enabled', 'last_status', 'evidence', 'event_today', 'fired_today', 'action',
          'outcome', 'merged', 'required_checks', 'failed_checks', 'revision', 'owner_state',
          'model', 'branch', 'parent_url', 'total'}


def iso(value):
    if value is None or value == '':
        return ''
    if isinstance(value, (int, float)):
        if not math.isfinite(value) or value <= 0 or value > 32503680000:
            return ''
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError):
        return ''


def identity(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


def utc_day(value):
    return datetime.fromisoformat(value).astimezone(timezone.utc).date().isoformat()


def evidence_class(kind, event, action=''):
    if kind == 'ci_proof':
        return 'ci_proof'
    if event in CI_EVENTS:
        return 'ci'
    if event in DEPLOYMENT_EVENTS:
        return 'deployment'
    if event in REVIEW_EVENTS:
        return 'review'
    if event == 'pull_request' and action == 'closed':
        return 'pr_closed'
    if kind in REPORTED_KINDS:
        return 'model_report'
    return ''


def state(value):
    return value if value in STATES else 'unknown'


def provider(value):
    return value if value in PROVIDERS else 'unknown'


def provider_name(value):
    # Only canonical instance ids leave the collector; a private custom name is
    # never exported as a provider label or value.
    return value if value in PROVIDERS else 'unknown'


def environment_id(config):
    # The stock runtime writes stateDir/environment-id. Read that existing file
    # read-only and accept only a UUID; no hardcoded id, secret service or
    # network call. A missing or malformed file keeps the app deep link.
    path = config.get('environment_id_file')
    if not path:
        return ''
    try:
        raw = Path(path).read_text().strip()
    except (OSError, UnicodeError):
        return ''
    return raw if UUID.fullmatch(raw) else ''


def thread_url(thread, environment):
    if not THREAD_ID.fullmatch(str(thread)):
        return ''
    if UUID.fullmatch(str(environment)):
        return f'{WEB_URL}/{environment}/{thread}'
    # Stock fallback: the app deep link when the environment is unknown.
    return f't3-thread://v1/{thread}'


@contextmanager
def readonly(path):
    # Do not use immutable=1: it ignores a live WAL. No Store constructor,
    # migrations, mkdir, journal_mode changes, or fallback database creation.
    db = sqlite3.connect(Path(path).absolute().as_uri() + '?mode=ro', uri=True, timeout=0.2)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    deadline = time.monotonic() + QUERY_SECONDS
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    try:
        yield db
    finally:
        db.close()


def query(path, sql, args=()):
    with readonly(path) as db:
        rows = [dict(row) for row in db.execute(sql + ' LIMIT ?', (*args, LIMIT + 1))]
    return rows[:LIMIT], len(rows) > LIMIT


def schedule_rows(path, now):
    rows, limited = query(path, '''SELECT task_id AS id, enabled,
      json_extract(schedule_json,'$.type') AS trigger, next_run_at AS next_at,
      last_run_at AS event_at, last_run_status AS status, thread_id
      FROM scheduled_tasks ORDER BY enabled DESC, next_run_at, task_id''')
    result = []
    for row in rows:
        row['kind'] = 'schedule'
        enabled = 1 if row['enabled'] else 0
        last = state(row['status'])
        # The enable flag, the next run, the last run and the last result are
        # separate facts: a disabled schedule keeps its previous outcome.
        row['enabled'] = enabled
        row['last_status'] = last
        row['status'] = 'disabled' if not enabled else (last if last != 'unknown' else 'unknown')
        row['trigger'] = row['trigger'] if row['trigger'] in {'interval', 'fixed_time', 'cron', 'webhook'} else 'unknown'
        result.append(row)
    return result, limited


def project_rows(path, now):
    return query(path, """SELECT p.project_id AS id, p.project_id, p.updated_at AS event_at,
      'project' AS kind, 'available' AS coverage, count(t.thread_id) AS thread_count
      FROM projection_projects p LEFT JOIN orchestration_v2_projection_threads t
      ON t.project_id=p.project_id AND t.deleted_at IS NULL
      WHERE p.deleted_at IS NULL GROUP BY p.project_id
      ORDER BY p.updated_at DESC, p.project_id""")


def thread_rows(path, now):
    # Ordinary/manual threads across every project, with no broker ownership
    # predicate. Latest durable run state is an observation, never PID proof.
    return query(path, """SELECT t.thread_id AS id, t.thread_id, t.project_id,
      t.default_provider AS provider, t.updated_at AS event_at, 'thread' AS kind,
      coalesce(r.status,'idle') AS status,
      coalesce(json_extract(t.payload_json,'$.linkedPullRequest.url'),
               json_extract(t.payload_json,'$.pullRequests[0].url')) AS github_url
      FROM orchestration_v2_projection_threads t
      LEFT JOIN orchestration_v2_projection_runs r ON r.run_id=(SELECT r2.run_id
        FROM orchestration_v2_projection_runs r2
        WHERE r2.thread_id=t.thread_id
          AND NOT (r2.status='cancelled' AND CASE WHEN json_valid(r2.payload_json)
            THEN coalesce(json_type(r2.payload_json,'$.startedAt')='null',0) ELSE 0 END)
        ORDER BY (r2.status IN ('running','pending','starting','waiting','queued','requested',
                                'native-running','preparing','prepared','executing')) DESC,
          coalesce(r2.completed_at,r2.requested_at) DESC, r2.ordinal DESC, r2.run_id LIMIT 1)
      WHERE t.deleted_at IS NULL
      ORDER BY (r.status IN ('running','pending','starting','waiting','queued','requested',
                              'native-running','preparing','prepared','executing')) DESC,
        t.updated_at DESC, t.thread_id""")


def artifact_rows(path, now):
    return query(path, """SELECT t.thread_id || ':' || j.key AS id,
      t.thread_id, t.project_id, t.updated_at AS event_at, 'artifact' AS kind,
      lower(json_extract(j.value,'$.snapshot.state')) AS status,
      json_extract(j.value,'$.url') AS github_url
      FROM orchestration_v2_projection_threads t,
        json_each(t.payload_json,'$.pullRequests') j
      WHERE t.deleted_at IS NULL AND
        coalesce(json_extract(j.value,'$.source'),'manual') != 'stack-dismissed'
      ORDER BY (lower(json_extract(j.value,'$.snapshot.state'))='open') DESC,
        t.updated_at DESC, t.thread_id, j.key""")


def agent_rows(path, now):
    # One row per native thread, ordinary or app-owned child, across every
    # project. Branch and model come from the actual thread and run projections,
    # never from the title or the thread default. Active work is enumerated in
    # pages so the most-recent cap can never hide a running agent.
    rows, total = [], 0
    with readonly(path) as db:
        total = db.execute(f'''SELECT count(*) FROM orchestration_v2_projection_threads t
          WHERE t.deleted_at IS NULL AND ((SELECT r2.status FROM
            orchestration_v2_projection_runs r2 WHERE r2.thread_id=t.thread_id
            AND NOT (r2.status='cancelled' AND CASE WHEN json_valid(r2.payload_json)
              THEN coalesce(json_type(r2.payload_json,'$.startedAt')='null',0) ELSE 0 END)
            ORDER BY CASE WHEN r2.status IN {EXECUTING_SQL} THEN 0
                          WHEN r2.status IN {QUEUED_SQL} THEN 1 ELSE 2 END,
              coalesce(r2.completed_at,r2.requested_at) DESC, r2.ordinal DESC, r2.run_id
            LIMIT 1) IN {ACTIVE_SQL}
            OR EXISTS (SELECT 1 FROM orchestration_v2_projection_runtime_requests q
              WHERE q.thread_id=t.thread_id AND q.status='pending' AND q.resolved_at IS NULL))''').fetchone()[0]
        for page in range(ACTIVE_PAGES):
            chunk = [dict(row) for row in db.execute(f'''SELECT t.thread_id AS id, t.thread_id,
              t.project_id, t.updated_at AS event_at, 'agent' AS kind,
              coalesce(r.status,'idle') AS status,
              json_extract(t.payload_json,'$.branch') AS branch,
              json_extract(r.payload_json,'$.modelSelection.model') AS model,
              json_extract(r.payload_json,'$.modelSelection.instanceId') AS selection_provider,
              r.provider AS run_provider,
              (SELECT count(*) FROM orchestration_v2_projection_runtime_requests q
                WHERE q.thread_id=t.thread_id AND q.status='pending' AND q.resolved_at IS NULL)
                AS pending_requests,
              (SELECT s.thread_id FROM orchestration_v2_projection_subagents s
                WHERE s.child_thread_id=t.thread_id LIMIT 1) AS parent_thread
              FROM orchestration_v2_projection_threads t
              LEFT JOIN orchestration_v2_projection_runs r ON r.run_id = ({CURRENT_RUN})
              WHERE t.deleted_at IS NULL AND (r.status IN {ACTIVE_SQL}
                OR EXISTS (SELECT 1 FROM orchestration_v2_projection_runtime_requests q
                  WHERE q.thread_id=t.thread_id AND q.status='pending' AND q.resolved_at IS NULL))
              ORDER BY CASE WHEN r.status IN {EXECUTING_SQL} THEN 0
                            WHEN r.status IN {QUEUED_SQL} THEN 1 ELSE 2 END,
                t.updated_at DESC, t.thread_id
              LIMIT ? OFFSET ?''', (ACTIVE_PAGE, page*ACTIVE_PAGE))]
            rows.extend(chunk)
            if len(chunk) < ACTIVE_PAGE:
                break
    return rows, len(rows) < total, total


def agent_history_rows(path, now):
    # Windowed terminal history of the same threads, bounded like every other
    # source. Active work never appears here.
    return query(path, f'''SELECT t.thread_id AS id, t.thread_id, t.project_id,
      t.updated_at AS event_at, 'agent' AS kind, coalesce(r.status,'idle') AS status,
      json_extract(t.payload_json,'$.branch') AS branch,
      json_extract(r.payload_json,'$.modelSelection.model') AS model,
      json_extract(r.payload_json,'$.modelSelection.instanceId') AS selection_provider,
      r.provider AS run_provider,
      (SELECT s.thread_id FROM orchestration_v2_projection_subagents s
        WHERE s.child_thread_id=t.thread_id LIMIT 1) AS parent_thread
      FROM orchestration_v2_projection_threads t
      LEFT JOIN orchestration_v2_projection_runs r ON r.run_id = ({CURRENT_RUN})
      WHERE t.deleted_at IS NULL AND t.updated_at >= ?
        AND NOT coalesce(r.status IN {ACTIVE_SQL}, 0)
      ORDER BY t.updated_at DESC, t.thread_id''', (iso(now-HISTORY_SECONDS),))


def request_rows(path, now):
    return query(path, """SELECT runtime_request_id AS id, thread_id,
      created_at AS event_at, 'request' AS kind, 'blocked' AS status
      FROM orchestration_v2_projection_runtime_requests WHERE status='pending' AND resolved_at IS NULL
      ORDER BY created_at DESC, runtime_request_id""")


def launch_rows(path, now):
    return query(path, """SELECT command_id AS id, thread_id, project_id, status,
      updated_at AS event_at, 'workflow' AS kind
      FROM orchestration_v2_thread_launch_workflows
      WHERE updated_at >= ? OR status NOT IN ('completed','failed')
      ORDER BY updated_at DESC, command_id""", (iso(now-HISTORY_SECONDS),))


def run_rows(path, now):
    return query(path, '''SELECT run_id AS id, thread_id, provider, status,
      coalesce(completed_at,requested_at) AS event_at, 'run' AS kind
      FROM orchestration_v2_projection_runs
      WHERE completed_at IS NULL OR completed_at >= ?
      ORDER BY (completed_at IS NULL) DESC, coalesce(completed_at,requested_at) DESC, run_id''', (iso(now-HISTORY_SECONDS),))


def subagent_rows(path, now):
    return query(path, '''SELECT subagent_id AS id, coalesce(child_thread_id,thread_id) AS thread_id,
      provider, status, updated_at AS event_at, 'subagent' AS kind
      FROM orchestration_v2_projection_subagents
      WHERE completed_at IS NULL OR completed_at >= ?
      ORDER BY (completed_at IS NULL) DESC, updated_at DESC, subagent_id''', (iso(now-HISTORY_SECONDS),))


def webhook_rows(path, now):
    return query(path, '''SELECT delivery_id AS id, received_at AS event_at,
      outcome AS status, 'webhook' AS kind, 'webhook' AS trigger, received_at AS fired_at
      FROM scheduled_task_webhook_deliveries WHERE received_at >= ?
      ORDER BY received_at DESC, delivery_id''', (iso(now-HISTORY_SECONDS),))


def coordinator_rows(path, now):
    # JSON scalar selection: do not even load pointer bodies or note/error text.
    return query(path, '''SELECT key AS id, CASE WHEN note='over daily limit' THEN 'held' ELSE status END AS status, updated_at AS event_at,
      received_at AS fired_at, CASE WHEN coalesce(json_extract(pointer,'$.kind'),'github') IN ('github','cloudflare') THEN 'webhook' ELSE 'job' END AS kind, 'webhook' AS trigger,
      json_extract(pointer,'$.repository') AS repository,
      json_extract(pointer,'$.number') AS number,
      json_extract(pointer,'$.event') AS event,
      json_extract(pointer,'$.action') AS action,
      json_extract(pointer,'$.run_id') AS github_run_id,
      json_extract(pointer,'$.sha') AS head
      FROM events WHERE received_at >= ? OR status='pending'
      ORDER BY (status='pending') DESC, updated_at DESC, key''', (now-HISTORY_SECONDS,))


def ci_proof_rows(path, now):
    # Configured CI proof of the coordinator, bound to the exact head or merge
    # SHA. Scalars only: the outcome, the merge flag and the check counts. The
    # coordinator fails closed: a failing required check wins, and a stale
    # revision is invalidated before any evidence read.
    return query(path, '''SELECT repository || ':' || number AS id, repository, number,
      thread_id, revision, outcome, outcome AS status, updated_at AS event_at, 'ci_proof' AS kind,
      json_extract(evidence,'$.merged') AS merged,
      json_array_length(evidence,'$.required_checks') AS required_checks,
      (SELECT count(*) FROM json_each(evidence,'$.checks') c
        WHERE EXISTS (SELECT 1 FROM json_each(c.value) v
          WHERE v.value IN ('failure','error','cancelled','action_required','stale','timed_out')))
        AS failed_checks
      FROM pull_progress WHERE updated_at >= ? ORDER BY updated_at DESC, repository, number''',
      (now-HISTORY_SECONDS,))


def owner_rows(path, now):
    # The owner state column exists only in newer coordinator schemas. The raw
    # note is never read: only the compact state and the observation time.
    base = ('''SELECT repository || ':' || number AS id, repository, number, thread_id,
      claimed_at AS event_at, 'launch' AS kind, 'accepted' AS status''')
    try:
        rows, limited = query(path, base + ''', state, observed_at, run_id FROM owners
          WHERE claimed_at >= ? ORDER BY claimed_at DESC, repository, number''',
          (now-HISTORY_SECONDS,))
    except sqlite3.Error:
        rows, limited = query(path, base + ' FROM owners WHERE claimed_at >= ?'
                              ' ORDER BY claimed_at DESC, repository, number',
                              (now-HISTORY_SECONDS,))
    return rows, limited


def runtime_rows(path, now):
    return query(path, '''SELECT id, status, updated_at AS event_at, 'job' AS kind
      FROM jobs WHERE updated_at >= ? OR status IN ('queued','running')
      ORDER BY (status IN ('queued','running')) DESC, updated_at DESC, id''', (now-HISTORY_SECONDS,))


def mcp_runtime_rows(paths, now):
    # The relay and shared-backend layouts coexist across upgrades. Read only
    # these fixed configured stores, merge by durable job ID and keep the most
    # recent receipt. Never recurse through homes or create an absent store.
    combined, limited, found = {}, False, False
    for path in paths:
        if not Path(path).is_file():
            continue
        found = True
        rows, capped = runtime_rows(path, now)
        limited |= capped
        for row in rows:
            previous = combined.get(row['id'])
            if previous is None or row['event_at'] > previous['event_at']:
                combined[row['id']] = row
    if not found:
        raise LookupError('runtime_store_absent')
    rows = sorted(combined.values(), key=lambda r: (r['status'] in ACTIVE, r['event_at'], r['id']), reverse=True)
    return rows[:LIMIT], limited or len(rows)>LIMIT


def continuation_rows(path, now):
    rows, limited = query(path, """SELECT key AS id, 'continuation' AS kind,
      json_extract(value,'$.state') AS status,
      json_extract(value,'$.updated_at') AS event_at,
      json_extract(value,'$.thread_id') AS thread_id,
      json_extract(value,'$.project_id') AS project_id,
      json_extract(value,'$.selection.instanceId') AS provider,
      CASE WHEN json_type(value,'$.switch_accepted')='object' THEN 1 ELSE 0 END AS switch_accepted,
      CASE WHEN json_type(value,'$.message_accepted')='object' THEN 1 ELSE 0 END AS message_accepted,
      min(200,coalesce(json_array_length(value,'$.native_runs'),0)) AS native_run_count,
      min(200,coalesce(json_array_length(value,'$.executing'),0)) AS executing_count
      FROM meta WHERE key LIKE 'model-continuation:%' AND json_valid(value)
      ORDER BY json_extract(value,'$.updated_at') DESC, key""")
    if not rows:
        raise LookupError('optional_continuation_metadata_absent')
    return rows, limited


def review_rows(path, now):
    # Exact automatic_reviews contract. Reported means a model report only.
    return query(path, """SELECT request_id AS id, repository, number, thread_id, head,
      CASE WHEN number IS NULL THEN 'push' ELSE 'pull_request' END AS event,
      status, occupied, due_at AS next_at, updated_at AS event_at, 'review' AS kind
      FROM automatic_reviews
      WHERE updated_at >= ? OR occupied=1 OR status IN ('queued','requested','native-running','blocked')
      ORDER BY occupied DESC, updated_at DESC, request_id""", (now-HISTORY_SECONDS,))


def routing_rows(path, now):
    # Optional compact provenance in existing coordinator meta. Select known
    # scalar fields only; an absent/incompatible contract is an explicit gap.
    rows, limited = query(path, """SELECT key AS id, 'routing' AS kind,
      coalesce(json_extract(value,'$.selection.instanceId'),json_extract(value,'$.instanceId')) AS provider,
      CASE json_extract(value,'$.state') WHEN 'wait' THEN 'blocked'
        WHEN 'selected' THEN 'accepted' ELSE CASE WHEN json_extract(value,'$.until')>? THEN 'held' ELSE 'expired' END END AS status,
      json_extract(value,'$.at') AS event_at,
      json_extract(value,'$.project_id') AS project_id,
      json_extract(value,'$.state') AS route_state,
      json_extract(value,'$.candidates[0].quota') AS primary_quota,
      coalesce(json_extract(value,'$.candidates[0].reason'),json_extract(value,'$.class')) AS route_reason,
      CASE WHEN json_array_length(value,'$.candidates')>1 AND json_extract(value,'$.state')='selected'
        THEN 1 ELSE 0 END AS fallback,
      coalesce(json_extract(value,'$.failure.until'),json_extract(value,'$.until')) AS next_at
      FROM meta WHERE key LIKE 'model-route:%' AND json_valid(value) AND
        (json_extract(value,'$.at')>=? OR json_extract(value,'$.state')='wait' OR json_extract(value,'$.until')>?)
      ORDER BY json_extract(value,'$.at') DESC, key""", (now, now-HISTORY_SECONDS, now))
    if not rows:
        raise LookupError('optional_routing_metadata_absent')
    return rows, limited


def timer_rows(_path, now):
    proc = subprocess.run(['systemctl', 'list-timers', '--all', '--output=json', '--no-pager'],
                          check=True, capture_output=True, timeout=3)
    if len(proc.stdout) > 1024*1024:
        raise ValueError('timer_response_limit')
    timers = json.loads(proc.stdout)
    result = []
    for timer in timers[:LIMIT]:
        unit = timer.get('unit', '')
        if not re.fullmatch(r'[A-Za-z0-9@_.:-]{1,160}\.timer', unit):
            continue
        # systemd's JSON timestamps are microseconds since the epoch.
        next_at = timer.get('next')
        last_at = timer.get('last')
        result.append({'id': unit, 'unit': unit, 'kind': 'schedule', 'trigger': 'systemd',
                       'status': 'enabled' if next_at else 'unknown',
                       'enabled': 1 if next_at else 0,
                       'next_at': next_at/1e6 if isinstance(next_at, int) else None,
                       'event_at': last_at/1e6 if isinstance(last_at, int) else None})
    return result, len(timers) > LIMIT


def project(source, row, environment, now=None):
    kind = row.get('kind', 'workflow')
    if kind == 'agent':
        return agent_record(source, row, environment, now)
    result = {'source': source, 'kind': kind, 'work_id': identity(row['id']),
              'status': state(row.get('status')), 'event_at': iso(row.get('event_at'))}
    moment = datetime.fromtimestamp(now if now is not None else time.time(), timezone.utc)
    today = moment.date().isoformat()
    for key in ('next_at', 'fired_at'):
        if key in row:
            result[key] = iso(row[key])
    for key in ('event_at', 'fired_at'):
        if result.get(key):
            result[key.replace('_at', '_seconds')] = datetime.fromisoformat(result[key]).timestamp()
            # UTC-day marker computed at collection time: "today" needs no
            # dashboard macro and cannot drift with a stale clock.
            result[key.replace('_at', '_today')] = 1 if utc_day(result[key]) == today else 0
    event = row.get('event') if row.get('event') in EVENTS else ''
    if 'trigger' in row:
        result['trigger'] = row['trigger']
    if event:
        result['event'] = event
    action = row.get('action') if row.get('action') in ACTIONS else ''
    if action:
        result['action'] = action
    evidence = evidence_class(kind, event, action)
    if evidence:
        result['evidence'] = evidence
    if 'unit' in row:
        result['unit'] = row['unit']
    if UUID.fullmatch(str(row.get('project_id'))):
        result['project_id'] = row['project_id']
    if isinstance(row.get('thread_count'), int):
        result['thread_count'] = row['thread_count']
    if row.get('occupied') in (0, 1):
        result['occupied'] = row['occupied']
    if row.get('outcome') in {'unverified', 'failed', 'checks_passed', 'verified_ci', 'pending_ci'}:
        result['outcome'] = row['outcome']
    if row.get('merged') in (0, 1):
        result['merged'] = row['merged']
    for key in ('required_checks', 'failed_checks'):
        value = row.get(key)
        if isinstance(value, int) and 0 <= value <= 1000:
            result[key] = value
    if re.fullmatch(r'[0-9a-f]{40,64}', str(row.get('revision') or '')):
        result['revision'] = row['revision']
    if row.get('state') in OWNER_STATES:
        result['owner_state'] = row['state']
    if row.get('enabled') in (0, 1):
        result['enabled'] = row['enabled']
    if row.get('last_status') in STATES:
        result['last_status'] = row['last_status']
    if row.get('coverage') == 'available':
        result['coverage'] = 'available'
    if row.get('route_state') in {'selected', 'wait'}:
        result['route_state'] = row['route_state']
    if row.get('primary_quota') in {'unknown', 'available', 'exhausted'}:
        result['primary_quota'] = row['primary_quota']
    if row.get('route_reason') in {'not_in_catalog', 'provider_unavailable', 'project_disabled', 'provider_cooldown', 'usage_exhausted', 'invalid_model_or_options', 'eligible', 'usage_limit'}:
        result['route_reason'] = row['route_reason']
    if row.get('fallback') in (0, 1):
        result['fallback'] = row['fallback']
    for key in ('switch_accepted', 'message_accepted', 'native_run_count', 'executing_count'):
        if isinstance(row.get(key), int) and 0 <= row[key] <= 200:
            result[key] = row[key]
    if 'provider' in row:
        result['provider'] = provider(row['provider'])
    if link := thread_url(row.get('thread_id'), environment):
        result['thread_url'] = link
    if re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:issues|pull)/[0-9]+(?:#(?:issuecomment|pullrequestreview)-[0-9]+)?', str(row.get('github_url'))):
        result['github_url'] = row['github_url']
    repo, number = row.get('repository'), row.get('number')
    if isinstance(repo, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,80}/[A-Za-z0-9_.-]{1,100}', repo) and isinstance(number, int) and 0 < number < 100000000:
        result['github_url'] = f'https://github.com/{repo}/{"pull" if kind in ("review", "ci_proof") else "issues"}/{number}'
    if isinstance(repo, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,80}/[A-Za-z0-9_.-]{1,100}', repo):
        run_id = row.get('github_run_id')
        if isinstance(run_id, int) and 0 < run_id < 10**15:
            result['github_url'] = f'https://github.com/{repo}/actions/runs/{run_id}'
        if row.get('event') == 'push' and re.fullmatch(r'[0-9a-f]{40,64}', str(row.get('head'))):
            result['github_url'] = f'https://github.com/{repo}/commit/{row["head"]}'
    return result


def agent_record(source, row, environment, now):
    # A running agent is a recorded native state, never process liveness. The
    # model and provider are the ones the current run actually selected; the
    # thread default is deliberately not substituted after a reconfigure.
    pending = row.get('pending_requests') or 0
    raw = row.get('status')
    effective = 'waiting' if pending else AGENT_STATES.get(raw, state(raw))
    result = {'source': source, 'kind': 'agent', 'work_id': identity(row['id']),
              'status': effective, 'event_at': iso(row.get('event_at'))}
    moment = datetime.fromtimestamp(now if now is not None else time.time(), timezone.utc)
    if result['event_at']:
        result['event_seconds'] = datetime.fromisoformat(result['event_at']).timestamp()
        result['event_today'] = 1 if utc_day(result['event_at']) == moment.date().isoformat() else 0
    if row.get('branch') and BRANCH.fullmatch(str(row['branch'])):
        result['branch'] = row['branch']
    if row.get('model') and MODEL.fullmatch(str(row['model'])):
        result['model'] = row['model']
    provider = row.get('selection_provider') or row.get('run_provider')
    if provider:
        result['provider'] = provider_name(provider)
    if UUID.fullmatch(str(row.get('project_id'))):
        result['project_id'] = row['project_id']
    if link := thread_url(row.get('thread_id'), environment):
        result['thread_url'] = link
    parent = thread_url(row.get('parent_thread'), environment)
    if parent and parent != result.get('thread_url'):
        result['parent_url'] = parent
    return result


def collect(config, now=None, timers=timer_rows):
    now = now or time.time()
    started = time.monotonic()
    records, metrics = [], []
    environment = environment_id(config)

    def metric(name, value, **labels):
        label_text = ','.join(f'{k}={json.dumps(v)}' for k, v in sorted(labels.items()))
        metrics.append(f'ghostship_work_{name}{{{label_text}}} {value}')

    sources = [
        ('t3_projects', project_rows, config['t3_db']),
        ('t3_agents', agent_rows, config['t3_db']),
        ('t3_agent_history', agent_history_rows, config['t3_db']),
        ('t3_threads', thread_rows, config['t3_db']),
        ('t3_requests', request_rows, config['t3_db']),
        ('t3_artifacts', artifact_rows, config['t3_db']),
        ('t3_launches', launch_rows, config['t3_db']),
        ('t3_schedules', schedule_rows, config['t3_db']),
        ('t3_runs', run_rows, config['t3_db']),
        ('t3_subagents', subagent_rows, config['t3_db']),
        ('t3_webhooks', webhook_rows, config['t3_db']),
        ('github_receipts', coordinator_rows, config['coordinator_db']),
        ('github_launches', owner_rows, config['coordinator_db']),
        ('ci_proof', ci_proof_rows, config['coordinator_db']),
        ('runtime_jobs', runtime_rows, config['runtime_db']),
        ('runtime_mcp_jobs', mcp_runtime_rows, [config['mcp_runtime_db'], *config.get('mcp_runtime_alternates', [])]),
        ('systemd_timers', timers, None),
        ('review_metadata', review_rows, config['coordinator_db']),
        ('routing_metadata', routing_rows, config['coordinator_db']),
        ('model_continuations', continuation_rows, config['coordinator_db']),
    ]
    for source, read, path in sources:
        before = time.monotonic()
        reason, rows, limited = 'ok', [], False
        total = None
        try:
            result = read(path, now)
            raw, limited = result[0], result[1]
            if len(result) > 2:
                total = result[2]
            rows = [project(source, row, environment, now) for row in raw]
        except (OSError, sqlite3.Error, ValueError, TypeError, LookupError, subprocess.SubprocessError):
            # Do not log exception text: paths, SQL errors, raw data and command
            # output may contain credentials. Source identity suffices to triage.
            reason = 'unavailable_or_schema_changed'
        up = reason == 'ok'
        metric('source_up', int(up), source=source)
        metric('source_limited', int(limited), source=source)
        metric('source_duration_seconds', round(time.monotonic()-before, 6), source=source)
        if up:
            metric('source_last_success_seconds', now, source=source)
            metric('observations', len(rows), source=source)
            # Gauges refer only to this bounded snapshot, never cumulative counts.
            counts = Counter(row['status'] for row in rows)
            for status in sorted(STATES):
                metric('items', counts[status], source=source, status=status)
            metric('attention', sum(counts[s] for s in ATTENTION), source=source)
            metric('active', sum(counts[s] for s in ACTIVE), source=source)
            for evidence, count in Counter(r['evidence'] for r in rows if 'evidence' in r).items():
                metric('evidence_items', count, source=source, evidence=evidence)
            failures = sum(1 for r in rows if r.get('outcome') == 'failed')
            if failures:
                metric('ci_failures', failures, source=source)
        coverage = 'bounded' if limited else 'available' if up else 'gap' if source in {'review_metadata', 'routing_metadata', 'model_continuations', 'ci_proof'} else 'unknown'
        records.extend(rows)
        coverage_row = {'source': source, 'kind': 'coverage', 'work_id': source,
                        'coverage': coverage, 'reason': reason, 'rows': len(rows),
                        'limited': limited, 'duration_seconds': round(time.monotonic()-before, 6)}
        if isinstance(total, int) and 0 <= total <= 1000000:
            coverage_row['total'] = total
        records.append(coverage_row)
    records.append({'source': 'chatgpt_tasks', 'kind': 'coverage', 'work_id': 'chatgpt_tasks',
                    'coverage': 'gap', 'reason': 'no_local_inventory_prior_ui_observation_only'})
    metric('source_up', 0, source='chatgpt_tasks')
    records.append({'source': 'github_subscriptions', 'kind': 'coverage', 'work_id': 'github_subscriptions',
                    'coverage': 'gap', 'reason': 'no_local_subscription_inventory_receipts_only'})
    metric('source_up', 0, source='github_subscriptions')
    # Objective completion has no source: model reports, CI and deployment
    # receipts are not proof that an objective was met.
    records.append({'source': 'objective_completion', 'kind': 'coverage', 'work_id': 'objective_completion',
                    'coverage': 'gap', 'reason': 'no_source_exposes_objective_completion_proof'})
    metric('source_up', 0, source='objective_completion')
    # A receipt is not an outcome. No owner state records the CI conclusion,
    # the frontier approval or the deployed health of a change, so they are
    # published as gaps instead of a green count.
    for source, reason in (
            ('frontier_approval', 'unsupported_no_source_in_this_collector'),
            ('deployed_health', 'unsupported_no_source_in_this_collector')):
        records.append({'source': source, 'kind': 'coverage', 'work_id': source,
                        'coverage': 'gap', 'reason': reason})
        metric('source_up', 0, source=source)
    # AI provider usage, limits and model rankings are owned by the separate
    # ai-usage package and dashboard. This collector never reads them, so the
    # usage stays explicitly unknown here until that source is deployed.
    records.append({'source': 'ai_usage', 'kind': 'coverage', 'work_id': 'ai_usage',
                    'coverage': 'gap', 'reason': 'separate_owner_not_collected_here'})
    metric('source_up', 0, source='ai_usage')
    metric('snapshot_timestamp_seconds', now)
    metric('collector_duration_seconds', round(time.monotonic()-started, 6))
    for row in records:
        assert set(row) <= FIELDS
        row.update(timestamp=iso(now), snapshot_at=iso(now), host=config.get('host', 'chill-penguin'),
                   stream='autonomous-work', message='Autonomous work observation')
    return records, '\n'.join(metrics)+'\n'


def atomic(path, value):
    target = Path(path)
    temp = target.with_suffix(target.suffix+'.tmp')
    temp.write_text(value)
    temp.chmod(0o644)
    temp.replace(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    records, metrics = collect(config)
    # Replaced atomically, never appended: bounded current snapshots only.
    atomic(config['metrics'], metrics)
    atomic(config['snapshot'], ''.join(json.dumps(r, sort_keys=True)+'\n' for r in records))


if __name__ == '__main__':
    main()
