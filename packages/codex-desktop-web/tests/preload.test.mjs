import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { EventEmitter } from 'node:events';
import vm from 'node:vm';
import test from 'node:test';

test('native relay works with only the sandbox Electron API and rejects private channels', async () => {
  const ipc = new EventEmitter();
  const sent = [];
  ipc.sendSync = () => null;
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
  });
  assert.equal(sent[0][0], 'ghostship-native:relay-open');
  ipc.emit('ghostship-native:relay-state', {}, true);
  assert.equal(sent.at(-1)[1].type, 'relay-ready');
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
  ipc.emit('codex_desktop:message-for-view', {}, {
    marker: 'codex-host-chunked-message-v1', transferId: 'state', sequence: 2, kind: 'end',
  });
  assert.deepEqual(sent.slice(before).map(([, message]) => message.type), ['bootstrap-update', 'event']);
});
