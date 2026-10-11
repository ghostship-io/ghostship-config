#!/usr/bin/env node
/**
 * T3 Code Activity Probe - v1 SQLite Adapter
 * Exit codes:
 *   0 = definitely idle
 *   1 = active
 *   2 = unknown / cannot determine (database missing, corrupt, locked, or inaccessible)
 */

const fs = require('node:fs');
const path = require('node:path');

// Old pending-start placeholders can outlive the request that created them.
// Only protect a recent request from racing a maintenance restart.
const PENDING_ACTIVITY_GRACE_MINUTES = 10;
// Subagents, background commands, and turn wrap-up keep writing thread
// activity after the turn row settles. Require this long without any.
const QUIET_MINUTES = 10;
// Claude background tasks (shells, subagents, monitors) outlive their turn and
// always record a terminal event. Bound the lookback so one lost to a crash
// cannot block maintenance indefinitely.
const OPEN_TASK_LOOKBACK_HOURS = 12;

const stateDb = process.env.T3CODE_STATE_DB ||
  (process.env.T3CODE_HOME ? path.join(process.env.T3CODE_HOME, 'userdata/state.sqlite') : null) ||
  (process.env.HOME ? path.join(process.env.HOME, '.t3/userdata/state.sqlite') : null);

if (!stateDb) {
  process.exit(2);
}

if (!fs.existsSync(stateDb)) {
  process.exit(2);
}

try {
  const { DatabaseSync } = require('node:sqlite');
  const db = new DatabaseSync(stateDb, { readOnly: true });

  const rows = db.prepare(
    `SELECT count(*) AS active FROM projection_turns AS turn
     JOIN projection_threads AS thread USING (thread_id)
     WHERE thread.deleted_at IS NULL AND (
       -- Completion timestamps are authoritative when projections disagree.
       (turn.state = 'running' AND turn.completed_at IS NULL) OR (
         turn.state = 'pending'
         AND turn.completed_at IS NULL
         AND julianday(turn.requested_at) >
           julianday('now', '-' || ? || ' minutes')
         AND NOT EXISTS (
           SELECT 1 FROM projection_turns AS newer
           WHERE newer.thread_id = turn.thread_id
             AND newer.requested_at > turn.requested_at
             AND newer.turn_id IS NOT NULL
         )
       )
     )
     UNION ALL
     SELECT count(*) AS active FROM projection_threads
     WHERE deleted_at IS NULL
       AND julianday(latest_user_message_at) > julianday('now', '-15 minutes')
     UNION ALL
     -- A provider session that is starting or running is active work even when
     -- the turn row disagrees. T3 Code stamps completed_at on running turns
     -- when a mid-turn checkpoint diff completes, so completed_at alone cannot
     -- mark a turn finished; only the session leaving running settles it.
     SELECT count(*) AS active FROM projection_thread_sessions AS session
     JOIN projection_threads AS thread USING (thread_id)
     WHERE thread.deleted_at IS NULL
       AND session.status IN ('starting', 'running')
     UNION ALL
     SELECT count(*) AS active FROM projection_threads AS thread
     JOIN projection_thread_activities AS activity USING (thread_id)
     WHERE thread.deleted_at IS NULL
       AND activity.created_at >
         strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-' || ? || ' minutes')
     UNION ALL
     SELECT count(*) AS active FROM (
       SELECT kind, status, row_number() OVER (
         PARTITION BY task_id
         -- A task that starts and settles in the same millisecond is settled.
         ORDER BY created_at DESC, kind = 'task.started', sequence DESC
       ) AS rank
       FROM (
         SELECT activity.kind, activity.created_at, activity.sequence,
           json_extract(activity.payload_json, '$.taskId') AS task_id,
           json_extract(activity.payload_json, '$.taskType') AS task_type,
           json_extract(activity.payload_json, '$.status') AS status
         FROM projection_threads AS thread
         JOIN projection_thread_activities AS activity USING (thread_id)
         WHERE thread.deleted_at IS NULL
           AND activity.kind IN ('task.started', 'task.updated', 'task.completed')
           AND activity.created_at >
             strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-' || ? || ' hours')
       )
       -- Codex agents carry no task type and never settle; their work shows
       -- up as recent activity instead.
       WHERE task_id IS NOT NULL AND task_type IS NOT NULL
         AND (kind <> 'task.updated' OR status IS NOT NULL)
     )
     WHERE rank = 1
       AND (kind = 'task.started' OR (kind = 'task.updated' AND status = 'running'))`
  ).all(PENDING_ACTIVITY_GRACE_MINUTES, QUIET_MINUTES, OPEN_TASK_LOOKBACK_HOURS);

  db.close();

  const isIdle = rows.every((entry) => Number(entry.active) === 0);
  process.exit(isIdle ? 0 : 1);
} catch (err) {
  process.stderr.write(`probe error: ${err.message}\n`);
  process.exit(2);
}
