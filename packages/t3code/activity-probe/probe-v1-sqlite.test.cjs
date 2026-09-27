const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { DatabaseSync } = require('node:sqlite');

const probePath = path.join(__dirname, 'probe-v1-sqlite.cjs');

function runProbe({ turns = [], latestUserMessageAt = null } = {}) {
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
  `);
  const threadIds = new Set(['thread-1', ...turns.map((turn) => turn.threadId ?? 'thread-1')]);
  const insertThread = db.prepare(
    'INSERT INTO projection_threads (thread_id, deleted_at, latest_user_message_at) VALUES (?, NULL, ?)',
  );
  for (const threadId of threadIds) {
    insertThread.run(threadId, threadId === 'thread-1' ? latestUserMessageAt : null);
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
  db.close();

  try {
    return spawnSync(process.execPath, [probePath], {
      encoding: 'utf8',
      env: { ...process.env, T3CODE_STATE_DB: databasePath },
    });
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
}

const now = () => new Date().toISOString();
const minutesAgo = (minutes) => new Date(Date.now() - minutes * 60_000).toISOString();

test('ignores completed running rows and old durable pending rows', () => {
  const result = runProbe({
    turns: [
      { state: 'running', requestedAt: minutesAgo(20), completedAt: now() },
      { state: 'pending', requestedAt: minutesAgo(20) },
      { state: 'pending', requestedAt: now(), completedAt: now(), threadId: 'thread-2' },
    ],
  });
  assert.equal(result.status, 0, result.stderr);
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


test('reports unknown when the database is missing', () => {
  const result = spawnSync(process.execPath, [probePath], {
    encoding: 'utf8',
    env: { ...process.env, T3CODE_STATE_DB: path.join(os.tmpdir(), 'missing-t3-state.sqlite') },
  });
  assert.equal(result.status, 2);
});
