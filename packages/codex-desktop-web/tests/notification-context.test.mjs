import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { createRequire } from 'node:module';
import test from 'node:test';
const { trackNotificationPort, currentNotificationPath, validNavigationPath } = createRequire(import.meta.url)('../bridge/notification-context.cjs');
test('notification RPC retains each task route through asynchronous handling', async () => {
  const port = new EventEmitter();
  trackNotificationPort(port);
  const seen = [];
  const pending = [];
  port.on('message', () => pending.push(Promise.resolve().then(() => seen.push(currentNotificationPath()))));
  for (const navigationPath of ['/thread/one', '/thread/two', 'https://attacker.test']) {
    port.emit('message', { data: ['push', ['pipeline', -5, ['show'], [{ conversationId: 'thread', navigationPath }]]] });
  }
  assert.equal(currentNotificationPath(), undefined);
  await Promise.all(pending);
  assert.deepEqual(seen, ['/thread/one', '/thread/two', undefined]);
  for (const path of ['//attacker.test', '/\\attacker.test', '/\ninvalid']) assert.equal(validNavigationPath(path), false);
});
