const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { DatabaseSync } = require('node:sqlite');

const probePath = path.join(__dirname, 'probe-v2-sqlite.cjs');

function runProbe({ runs = [], subagents = [], launches = [], messages = [], items = [], deleted = false } = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 't3-activity-probe-v2-'));
  const databasePath = path.join(directory, 'statev2.sqlite');
  const db = new DatabaseSync(databasePath);
  db.exec(`
    CREATE TABLE orchestration_v2_projection_threads (thread_id TEXT PRIMARY KEY, deleted_at TEXT);
    CREATE TABLE orchestration_v2_projection_runs (run_id TEXT PRIMARY KEY, thread_id TEXT, status TEXT, requested_at TEXT);
    CREATE TABLE orchestration_v2_projection_subagents (subagent_id TEXT PRIMARY KEY, thread_id TEXT, status TEXT, started_at TEXT);
    CREATE TABLE orchestration_v2_thread_launch_workflows (command_id TEXT PRIMARY KEY, status TEXT, updated_at TEXT);
    CREATE TABLE orchestration_v2_projection_messages (message_id TEXT PRIMARY KEY, role TEXT, created_at TEXT);
    CREATE TABLE orchestration_v2_projection_turn_items (turn_item_id TEXT PRIMARY KEY, updated_at TEXT);
  `);
  db.prepare('INSERT INTO orchestration_v2_projection_threads VALUES (?, ?)').run('thread-1', deleted ? now() : null);
  runs.forEach((run, index) => db.prepare('INSERT INTO orchestration_v2_projection_runs VALUES (?, ?, ?, ?)')
    .run(`run-${index}`, 'thread-1', run.status, run.requestedAt));
  subagents.forEach((subagent, index) => db.prepare('INSERT INTO orchestration_v2_projection_subagents VALUES (?, ?, ?, ?)')
    .run(`subagent-${index}`, 'thread-1', subagent.status, subagent.startedAt));
  launches.forEach((launch, index) => db.prepare('INSERT INTO orchestration_v2_thread_launch_workflows VALUES (?, ?, ?)')
    .run(`launch-${index}`, launch.status, launch.updatedAt));
  messages.forEach((message, index) => db.prepare('INSERT INTO orchestration_v2_projection_messages VALUES (?, ?, ?)')
    .run(`message-${index}`, message.role, message.createdAt));
  items.forEach((item, index) => db.prepare('INSERT INTO orchestration_v2_projection_turn_items VALUES (?, ?)')
    .run(`item-${index}`, item.updatedAt));
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

test('reports idle when every run, subagent and launch settled and work went quiet', () => {
  const result = runProbe({
    runs: [{ status: 'completed', requestedAt: minutesAgo(30) }, { status: 'cancelled', requestedAt: minutesAgo(40) }],
    subagents: [{ status: 'completed', startedAt: minutesAgo(30) }],
    launches: [{ status: 'completed', updatedAt: minutesAgo(30) }],
    messages: [{ role: 'user', createdAt: minutesAgo(16) }, { role: 'assistant', createdAt: minutesAgo(2) }],
    items: [{ updatedAt: minutesAgo(11) }],
  });
  assert.equal(result.status, 0, result.stderr);
});

test('protects a running run and treats unknown states as active', () => {
  for (const status of ['running', 'queued']) {
    const result = runProbe({ runs: [{ status, requestedAt: minutesAgo(90) }] });
    assert.equal(result.status, 1, `${status}: ${result.stderr}`);
  }
});

test('ignores open runs beyond the lookback and runs of deleted threads', () => {
  const stale = runProbe({ runs: [{ status: 'running', requestedAt: minutesAgo(13 * 60) }] });
  assert.equal(stale.status, 0, stale.stderr);

  const deleted = runProbe({ runs: [{ status: 'running', requestedAt: now() }], deleted: true });
  assert.equal(deleted.status, 0, deleted.stderr);
});

test('protects a running subagent and an open thread launch', () => {
  const subagent = runProbe({ subagents: [{ status: 'running', startedAt: minutesAgo(60) }] });
  assert.equal(subagent.status, 1, subagent.stderr);

  const launch = runProbe({ launches: [{ status: 'preparing', updatedAt: minutesAgo(5) }] });
  assert.equal(launch.status, 1, launch.stderr);
});

test('protects user messages within 15 minutes and turn items within the quiet window', () => {
  assert.equal(runProbe({ messages: [{ role: 'user', createdAt: minutesAgo(12) }] }).status, 1);
  assert.equal(runProbe({ items: [{ updatedAt: minutesAgo(8) }] }).status, 1);
});

test('reports unknown when the database is missing or not a v2 database', () => {
  const missing = spawnSync(process.execPath, [probePath], {
    encoding: 'utf8',
    env: { ...process.env, T3CODE_STATE_DB: path.join(os.tmpdir(), 'missing-t3-statev2.sqlite') },
  });
  assert.equal(missing.status, 2);

  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 't3-activity-probe-v1-'));
  const legacy = path.join(directory, 'statev2.sqlite');
  new DatabaseSync(legacy).close();
  const result = spawnSync(process.execPath, [probePath], {
    encoding: 'utf8',
    env: { ...process.env, T3CODE_STATE_DB: legacy },
  });
  fs.rmSync(directory, { recursive: true, force: true });
  assert.equal(result.status, 2);
});
