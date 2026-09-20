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
       turn.state = 'running' OR (
         turn.state = 'pending' AND NOT EXISTS (
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
       AND julianday(latest_user_message_at) > julianday('now', '-1 minute')`
  ).all();

  db.close();

  const isIdle = rows.every((entry) => Number(entry.active) === 0);
  process.exit(isIdle ? 0 : 1);
} catch (err) {
  process.stderr.write(`probe error: ${err.message}\n`);
  process.exit(2);
}
