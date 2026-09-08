import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { createRequire } from 'node:module';
import test from 'node:test';
const { trackNotificationPort, takeNotificationMetadata, validNavigationPath } = createRequire(import.meta.url)('../bridge/notification-context.cjs');
test('notification metadata survives RPC async context loss and handles ambiguous titles safely', async () => {
  const port = new EventEmitter();
  trackNotificationPort(port);
  const show = (id, title, body, navigationPath) => port.emit('message', {
    data: ['push', ['pipeline', -5, ['show'], [{ id, title, body, conversationId: id, navigationPath }]]],
  });
  show('one', 'Task', 'First result', '/local/one');
  show('two', 'Other task', 'Second result', '/local/two');
  await Promise.resolve();
  assert.equal(takeNotificationMetadata({ title: 'Other task', body: 'Second result' }).id, 'two');
  assert.equal(takeNotificationMetadata({ title: 'Task', body: 'First result' }).navigationPath, '/local/one');
  show('markdown', 'Unique title', '**Done**', '/local/markdown');
  assert.equal(takeNotificationMetadata({ title: 'Unique title', body: 'Done' }).navigationPath, '/local/markdown');
  show('a', 'Same title', '**Done**', '/local/a');
  show('b', 'Same title', 'Done', '/local/b');
  assert.equal(takeNotificationMetadata({ title: 'Same title', body: 'Done' }).navigationPath, '/');
  assert.equal(takeNotificationMetadata({ title: 'Same title', body: 'Done' }).navigationPath, '/');
  assert.equal(takeNotificationMetadata({ title: 'Unknown' }), undefined);
  for (const path of ['https://attacker.test', '//attacker.test', '/\\attacker.test', '/\ninvalid']) assert.equal(validNavigationPath(path), false);
});
