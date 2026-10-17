#!/usr/bin/env node
/**
 * T3 Code Activity Probe - v2 SQLite Adapter (statev2.sqlite)
 * T3 Code 2 records work in the orchestration_v2 projections; the legacy
 * projection tables in the same file stop at the migration.
 * Exit codes:
 *   0 = definitely idle
 *   1 = active
 *   2 = unknown / cannot determine (database missing, corrupt, locked, or inaccessible)
 */

const fs = require('node:fs');

// Matches the v1 adapter: user messages, then any turn-item progress (tools,
// streaming, subagents wrapping up), must both have gone quiet.
const USER_MESSAGE_MINUTES = 15;
const QUIET_MINUTES = 10;
// A run or subagent left non-terminal by a crash must not block maintenance
// indefinitely.
const OPEN_WORK_LOOKBACK_HOURS = 12;
// Unknown future states count as active.
const TERMINAL = "('completed', 'cancelled', 'failed', 'interrupted')";

const stateDb = process.env.T3CODE_STATE_DB;
if (!stateDb || !fs.existsSync(stateDb)) {
  process.exit(2);
}

try {
  const { DatabaseSync } = require('node:sqlite');
  const db = new DatabaseSync(stateDb, { readOnly: true });
  const since = (amount, unit) => `strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-${amount} ${unit}')`;

  const rows = db.prepare(
    `SELECT count(*) AS active FROM orchestration_v2_projection_runs AS run
     JOIN orchestration_v2_projection_threads AS thread USING (thread_id)
     WHERE thread.deleted_at IS NULL
       AND run.status NOT IN ${TERMINAL}
       AND run.requested_at > ${since(OPEN_WORK_LOOKBACK_HOURS, 'hours')}
     UNION ALL
     SELECT count(*) AS active FROM orchestration_v2_projection_subagents AS subagent
     JOIN orchestration_v2_projection_threads AS thread USING (thread_id)
     WHERE thread.deleted_at IS NULL
       AND subagent.status NOT IN ${TERMINAL}
       AND subagent.started_at > ${since(OPEN_WORK_LOOKBACK_HOURS, 'hours')}
     UNION ALL
     SELECT count(*) AS active FROM orchestration_v2_thread_launch_workflows
     WHERE status NOT IN ${TERMINAL}
       AND updated_at > ${since(OPEN_WORK_LOOKBACK_HOURS, 'hours')}
     UNION ALL
     SELECT count(*) AS active FROM orchestration_v2_projection_messages
     WHERE role = 'user' AND created_at > ${since(USER_MESSAGE_MINUTES, 'minutes')}
     UNION ALL
     SELECT count(*) AS active FROM orchestration_v2_projection_turn_items
     WHERE updated_at > ${since(QUIET_MINUTES, 'minutes')}`
  ).all();

  db.close();

  const isIdle = rows.every((entry) => Number(entry.active) === 0);
  process.exit(isIdle ? 0 : 1);
} catch (err) {
  process.stderr.write(`probe error: ${err.message}\n`);
  process.exit(2);
}
