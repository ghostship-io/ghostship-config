const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { DatabaseSync } = require('node:sqlite');

const probePath = path.join(__dirname, 'probe-v1-sqlite.cjs');

function runProbe({
  turns = [], sessions = [], activities = [], latestUserMessageAt = null,
  v2Schema = null, selectedSchema = null, adapter = null,
} = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 't3-activity-probe-'));
  const databasePath = path.join(directory, 'state.sqlite');
  const db = new DatabaseSync(databasePath);
  db.exec(`
    CREATE TABLE projection_threads (
      thread_id TEXT PRIMARY KEY,
      deleted_at TEXT,
      latest_user_message_at TEXT
    );
    CREATE TABLE projection_turns (
      row_id INTEGER PRIMARY KEY,
      thread_id TEXT NOT NULL,
      turn_id TEXT,
      state TEXT NOT NULL,
      requested_at TEXT NOT NULL,
      started_at TEXT,
      completed_at TEXT
    );
    CREATE TABLE projection_thread_sessions (
      thread_id TEXT PRIMARY KEY,
      status TEXT NOT NULL,
      active_turn_id TEXT
    );
    CREATE TABLE projection_thread_activities (
      activity_id TEXT PRIMARY KEY,
      thread_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      payload_json TEXT NOT NULL,
      created_at TEXT NOT NULL,
      sequence INTEGER
    );
  `);
  const threadIds = new Set([
    'thread-1',
    ...turns.map((turn) => turn.threadId ?? 'thread-1'),
    ...sessions.map((session) => session.threadId ?? 'thread-1'),
    ...activities.map((activity) => activity.threadId ?? 'thread-1'),
  ]);
  const insertThread = db.prepare(
    'INSERT INTO projection_threads (thread_id, deleted_at, latest_user_message_at) VALUES (?, NULL, ?)',
  );
  for (const threadId of threadIds) {
    insertThread.run(threadId, threadId === 'thread-1' ? latestUserMessageAt : null);
  }
  for (const session of sessions) {
    db.prepare(
      'INSERT INTO projection_thread_sessions (thread_id, status, active_turn_id) VALUES (?, ?, ?)',
    ).run(session.threadId ?? 'thread-1', session.status, session.activeTurnId ?? null);
  }
  for (const [index, activity] of activities.entries()) {
    db.prepare(
      'INSERT INTO projection_thread_activities (activity_id, thread_id, kind, payload_json, created_at, sequence) VALUES (?, ?, ?, ?, ?, ?)',
    ).run(
      `activity-${index}`,
      activity.threadId ?? 'thread-1',
      activity.kind,
      JSON.stringify(activity.payload ?? {}),
      activity.createdAt,
      index,
    );
  }
  for (const [index, turn] of turns.entries()) {
    db.prepare(
      'INSERT INTO projection_turns (row_id, thread_id, turn_id, state, requested_at, started_at, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
    ).run(
      index + 1,
      turn.threadId ?? 'thread-1',
      turn.turnId ?? null,
      turn.state,
      turn.requestedAt,
      turn.startedAt ?? null,
      turn.completedAt ?? null,
    );
  }
  if (selectedSchema !== null) db.exec(selectedSchema);
  db.close();

  try {
    if (v2Schema !== null) {
      const v2 = new DatabaseSync(path.join(directory, 'statev2.sqlite'));
      v2.exec(v2Schema);
      v2.close();
    }
    return spawnSync(adapter ? 'bash' : process.execPath, [
      adapter ? path.join(__dirname, 't3code-activity-probe.sh') : probePath,
    ], {
      encoding: 'utf8',
      env: {
        ...process.env,
        T3CODE_STATE_DB: databasePath,
        ...(adapter ? { T3CODE_ACTIVITY_PROBE_ADAPTER: adapter, T3CODE_API_URL: '' } : {}),
      },
    });
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
}

const now = () => new Date().toISOString();
const minutesAgo = (minutes) => new Date(Date.now() - minutes * 60_000).toISOString();

test('ignores stale completed running rows and old durable pending rows', () => {
  const result = runProbe({
    turns: [
      { state: 'running', requestedAt: minutesAgo(20), completedAt: now() },
      { state: 'pending', requestedAt: minutesAgo(20) },
      { state: 'pending', requestedAt: now(), completedAt: now(), threadId: 'thread-2' },
    ],
  });
  assert.equal(result.status, 0, result.stderr);
});

test('keeps a running turn active while its provider session is running', () => {
  // T3 Code stamps completed_at on a running turn when a mid-turn checkpoint
  // diff completes; only the session leaving running settles the turn.
  const result = runProbe({
    turns: [{ state: 'running', requestedAt: minutesAgo(60), completedAt: minutesAgo(59) }],
    sessions: [{ status: 'running', activeTurnId: 'turn-1' }],
  });
  assert.equal(result.status, 1, result.stderr);
});

test('treats a starting or running session as active without a turn row', () => {
  const starting = runProbe({ sessions: [{ status: 'starting' }] });
  assert.equal(starting.status, 1, starting.stderr);

  const running = runProbe({ sessions: [{ status: 'running' }] });
  assert.equal(running.status, 1, running.stderr);
});

test('does not treat a ready or stopped session as active', () => {
  const ready = runProbe({ sessions: [{ status: 'ready' }] });
  assert.equal(ready.status, 0, ready.stderr);

  const stopped = runProbe({ sessions: [{ status: 'stopped' }] });
  assert.equal(stopped.status, 0, stopped.stderr);
});

test('protects a newly submitted pending turn during the dispatch grace period', () => {
  const result = runProbe({ turns: [{ state: 'pending', requestedAt: minutesAgo(5) }] });
  assert.equal(result.status, 1, result.stderr);
});

test('protects an unfinished running turn', () => {
  const result = runProbe({
    turns: [{ state: 'running', requestedAt: minutesAgo(20), startedAt: minutesAgo(20) }],
  });
  assert.equal(result.status, 1, result.stderr);
});

test('protects recent user activity even when no turn row is present', () => {
  const result = runProbe({ latestUserMessageAt: now() });
  assert.equal(result.status, 1, result.stderr);
});

test('protects user activity within the 15-minute grace window', () => {
  const activeResult = runProbe({ latestUserMessageAt: minutesAgo(12) });
  assert.equal(activeResult.status, 1, activeResult.stderr);

  const idleResult = runProbe({ latestUserMessageAt: minutesAgo(16) });
  assert.equal(idleResult.status, 0, idleResult.stderr);
});


const bash = (taskId, extra = {}) => ({ taskId, taskType: 'local_bash', ...extra });

test('protects thread activity within the quiet window', () => {
  const recent = runProbe({ activities: [{ kind: 'tool.completed', createdAt: minutesAgo(8) }] });
  assert.equal(recent.status, 1, recent.stderr);

  const quiet = runProbe({ activities: [{ kind: 'tool.completed', createdAt: minutesAgo(11) }] });
  assert.equal(quiet.status, 0, quiet.stderr);
});

test('protects a background task that outlives its turn', () => {
  const result = runProbe({
    turns: [{ state: 'completed', requestedAt: minutesAgo(60), completedAt: minutesAgo(59) }],
    activities: [{ kind: 'task.started', payload: bash('b1'), createdAt: minutesAgo(45) }],
  });
  assert.equal(result.status, 1, result.stderr);
});

test('protects a backgrounded task whose latest update has no status', () => {
  const result = runProbe({
    activities: [
      { kind: 'task.started', payload: bash('b1'), createdAt: minutesAgo(45) },
      { kind: 'task.updated', payload: bash('b1', { isBackgrounded: true }), createdAt: minutesAgo(30) },
    ],
  });
  assert.equal(result.status, 1, result.stderr);
});

test('settles a background task by its terminal event', () => {
  for (const [kind, status] of [
    ['task.completed', 'completed'],
    ['task.completed', 'stopped'],
    ['task.updated', 'cancelled'],
  ]) {
    const result = runProbe({
      activities: [
        { kind: 'task.started', payload: bash('b1'), createdAt: minutesAgo(45) },
        { kind, payload: bash('b1', { status }), createdAt: minutesAgo(30) },
      ],
    });
    assert.equal(result.status, 0, `${kind} ${status}: ${result.stderr}`);
  }
});

test('settles a task that starts and completes in the same instant', () => {
  const at = minutesAgo(30);
  const result = runProbe({
    activities: [
      { kind: 'task.completed', payload: bash('b1', { status: 'completed' }), createdAt: at },
      { kind: 'task.started', payload: bash('b1'), createdAt: at },
    ],
  });
  assert.equal(result.status, 0, result.stderr);
});

test('ignores untyped agent tasks and tasks beyond the lookback', () => {
  const result = runProbe({
    activities: [
      { kind: 'task.updated', payload: { taskId: 'codex-1', status: 'running' }, createdAt: minutesAgo(60) },
      { kind: 'task.started', payload: bash('b1'), createdAt: minutesAgo(13 * 60) },
    ],
  });
  assert.equal(result.status, 0, result.stderr);
});

test('reports unknown when the database is missing', () => {
  const result = spawnSync(process.execPath, [probePath], {
    encoding: 'utf8',
    env: { ...process.env, T3CODE_STATE_DB: path.join(os.tmpdir(), 'missing-t3-state.sqlite') },
  });
  assert.equal(result.status, 2);
});

test('never treats stale idle V1 state as idle while a V2 turn is running', () => {
  const result = runProbe({ v2Schema: `
    CREATE TABLE orchestration_v2_projection_provider_turns (
      provider_turn_id TEXT, status TEXT, completed_at TEXT
    );
    INSERT INTO orchestration_v2_projection_provider_turns VALUES ('turn-1', 'running', NULL);
  ` });
  assert.equal(result.status, 2, result.stderr);
  assert.match(result.stderr, /V2 activity adapter unavailable/);
});

test('blocks a V2 background task after the V1 turn has settled', () => {
  const result = runProbe({
    turns: [{ state: 'completed', requestedAt: minutesAgo(60), completedAt: minutesAgo(59) }],
    v2Schema: `
      CREATE TABLE orchestration_v2_projection_subagents (subagent_id TEXT, status TEXT);
      INSERT INTO orchestration_v2_projection_subagents VALUES ('agent-1', 'running');
    `,
  });
  assert.equal(result.status, 2, result.stderr);
});

test('blocks an unknown V2 schema instead of consulting idle V1 state', () => {
  const result = runProbe({ v2Schema: 'CREATE TABLE future_activity (state TEXT);' });
  assert.equal(result.status, 2, result.stderr);
});

test('blocks V2 tables even when an explicit database has a different filename', () => {
  const result = runProbe({
    selectedSchema: 'CREATE TABLE orchestration_v2_projection_runs (status TEXT);',
  });
  assert.equal(result.status, 2, result.stderr);
});

test('reports unknown for an incompatible V1 schema', () => {
  const result = runProbe({ selectedSchema: 'DROP TABLE projection_turns;' });
  assert.equal(result.status, 2, result.stderr);
});

test('unsupported V2 API adapter cannot fall back to idle V1 state without a URL', () => {
  const result = runProbe({ adapter: 'v2-api' });
  assert.equal(result.status, 2, result.stderr);
});
