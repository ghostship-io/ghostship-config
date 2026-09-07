import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { EventEmitter } from 'node:events';
import vm from 'node:vm';
import test from 'node:test';

test('native relay works with only the sandbox Electron API and rejects private channels', async () => {
  const ipc = new EventEmitter();
  const sent = [];
  let heartbeat;
  const syncChannels = [];
  ipc.sendSync = (channel) => {
    syncChannels.push(channel);
    return channel === 'codex_desktop:get-shared-object-snapshot' ? {} : null;
  };
  ipc.send = (...args) => sent.push(args);
  ipc.invoke = async (channel) => ({ result: channel });
  const source = await readFile(new URL('../bridge/combined-preload.cjs', import.meta.url), 'utf8');
  vm.runInNewContext(source, {
    require: (name) => {
      assert.equal(name, 'electron', 'sandbox cannot load Node modules');
      return { ipcRenderer: ipc };
    },
    process: { platform: 'linux', arch: 'arm64', versions: { electron: '42.3.0' } },
    console,
    setInterval: (callback) => { heartbeat = callback; },
  });
  assert.equal(sent[0][0], 'ghostship-native:relay-open');
  ipc.emit('ghostship-native:relay-state', {}, true);
  assert.ok(sent.some(([, message]) => message?.type === 'relay-ready'));
  heartbeat();
  assert.equal(sent.at(-1)[1].type, 'relay-heartbeat');
  ipc.emit('ghostship-native:relay-message', {}, {
    type: 'invoke', channel: 'codex_desktop:test', args: [], clientId: 'client', requestId: 'request',
  });
  await new Promise(setImmediate);
  assert.equal(sent.at(-1)[1].result.result, 'codex_desktop:test');
  ipc.emit('ghostship-native:relay-message', {}, { type: 'send', channel: 'ghostship-native:relay-open', args: [] });
  await new Promise(setImmediate);
  assert.equal(sent.at(-1)[1].type, 'relay-error');
  assert.equal(sent.filter(([channel]) => channel === 'ghostship-native:relay-open').length, 1);
  ipc.emit('ghostship-native:relay-message', {}, {
    type: 'subscribe', channel: 'codex_desktop:message-for-view',
  });
  const before = sent.length;
  const chunk = (sequence, kind, tokens) => ipc.emit('codex_desktop:message-for-view', {}, {
    marker: 'codex-host-chunked-message-v1', transferId: 'state', sequence, kind, tokens,
  });
  chunk(0, 'start');
  chunk(1, 'chunk', [
    { type: 'object-start' }, { type: 'key', value: 'type' },
    { type: 'value', value: 'global-state-updated' },
    { type: 'key', value: 'keys' }, { type: 'array-start' },
    { type: 'value', value: 'local-projects' }, { type: 'container-end' },
    { type: 'key', value: '__proto__' }, { type: 'value', value: 'safe' },
    { type: 'key', value: 'text' }, { type: 'string-start', target: 'value' },
    { type: 'string-chunk', value: 'split ' },
  ]);
  assert.equal(sent.length, before, 'partial transfers must not reach browser sessions');
  chunk(2, 'chunk', [{ type: 'string-chunk', value: 'string' },
    { type: 'string-end' }, { type: 'container-end' }]);
  syncChannels.length = 0;
  chunk(3, 'end');
  assert.deepEqual(sent.slice(before).map(([, message]) => message.type), ['bootstrap-update', 'event']);
  assert.deepEqual(syncChannels, ['codex_desktop:get-initial-sidebar-bootstrap']);
  assert.deepEqual(JSON.parse(JSON.stringify(sent.at(-1)[1].args[0])), {
    type: 'global-state-updated', keys: ['local-projects'], ['__proto__']: 'safe', text: 'split string',
  });
  const complete = sent.length;
  chunk(8, 'end');
  assert.equal(sent.length, complete, 'joining mid-transfer must not emit an incomplete message');
  ipc.emit('ghostship-native:relay-message', {}, {
    type: 'send', channel: 'codex_desktop:chunked-message-ack', args: ['state', 3],
  });
  await new Promise(setImmediate);
  assert.equal(sent.length, complete, 'the native renderer owns acknowledgements');
  chunk(0, 'start');
  chunk(1, 'chunk', [{ type: 'object-start' }]);
  ipc.emit('codex_desktop:message-for-view', {}, {
    marker: 'codex-host-chunked-message-v1', transferId: 'replacement', sequence: 0, kind: 'start',
  });
  chunk(2, 'end');
  assert.equal(sent.length, complete, 'superseded transfers must be discarded');
  ipc.emit('ghostship-native:relay-message', {}, {
    type: 'unsubscribe', channel: 'codex_desktop:message-for-view',
  });
  ipc.emit('ghostship-native:relay-state', {}, false);
  ipc.emit('codex_desktop:message-for-view', {}, {
    type: 'shared-object-updated', key: 'updated-while-disconnected', value: true,
  });
  ipc.emit('ghostship-native:relay-state', {}, true);
  const resumed = sent.findLast(([, message]) => message?.type === 'relay-ready')[1];
  assert.equal(resumed.bootstrap['codex_desktop:get-shared-object-snapshot']['updated-while-disconnected'], true);
});
