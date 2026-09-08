import assert from 'node:assert/strict';
import { createECDH, randomBytes } from 'node:crypto';
import { mkdtempSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import test from 'node:test';
const require = createRequire(import.meta.url);
const { createPushNotifications, validSubscription } = require('../bridge/push-notifications.cjs');
const webpush = require('web-push');
const ece = require('http_ece');
function subscription() {
  const receiver = createECDH('prime256v1');
  const keys = { p256dh: receiver.generateKeys().toString('base64url'), auth: randomBytes(16).toString('base64url') };
  return { receiver, value: { endpoint: 'https://fcm.googleapis.com/fcm/send/test', keys } };
}
test('push keys and subscriptions survive restart and payload decrypts with the device key', async () => {
  const root = mkdtempSync(path.join(tmpdir(), 'codex-push-'));
  try {
    const { receiver, value } = subscription();
    const first = createPushNotifications(root);
    first.subscribe('constructor', value);
    let received;
    const second = createPushNotifications(root, async (target, payload, options) => {
      const request = webpush.generateRequestDetails(target, payload, options);
      assert.equal(request.headers['Content-Encoding'], 'aes128gcm');
      received = JSON.parse(ece.decrypt(request.body, {
        version: 'aes128gcm', privateKey: receiver, authSecret: value.keys.auth,
      }).toString());
    });
    assert.equal(first.publicKey, second.publicKey);
    assert.equal(second.has('constructor'), true);
    assert.equal(statSync(path.join(root, 'push.json')).mode & 0o777, 0o600);
    await second.notify({ notificationId: 'completion', navigationPath: '/thread/shared', options: { title: 'Done', body: 'Shared task finished' } });
    assert.equal(received.notificationId, 'completion');
    assert.equal(received.navigationPath, '/thread/shared');
    assert.equal(received.options.body, 'Shared task finished');
    second.unsubscribe('constructor');
    assert.equal(createPushNotifications(root).has('constructor'), false);
  } finally { rmSync(root, { recursive: true }); }
});
test('push rejects internal endpoints and removes expired subscriptions without deleting renewals', async () => {
  const root = mkdtempSync(path.join(tmpdir(), 'codex-push-'));
  try {
    const { value } = subscription();
    for (const endpoint of ['http://fcm.googleapis.com/test', 'https://127.0.0.1/test', 'https://fcm.googleapis.com.attacker.test/a', 'https://fcm.googleapis.com:8443/a', 'https://user@fcm.googleapis.com/a']) {
      assert.equal(validSubscription({ ...value, endpoint }), false);
    }
    let release;
    const push = createPushNotifications(root, () => new Promise((resolve, reject) => { release = () => reject({ statusCode: 410 }); }));
    push.subscribe('device', value);
    const expired = push.notify({ notificationId: 'one', options: {} });
    release(); await expired;
    assert.equal(push.has('device'), false);
    push.subscribe('device', value);
    const renewed = push.notify({ notificationId: 'two', options: {} });
    push.subscribe('device', { ...value, endpoint: value.endpoint + '-renewed' });
    release(); await renewed;
    assert.equal(push.has('device'), true);
  } finally { rmSync(root, { recursive: true }); }
});
