"use strict";
const fs = require("node:fs");
const path = require("node:path");
const webpush = require("web-push");

function validSubscription(value) {
  try {
    const url = new URL(value.endpoint);
    const host = url.hostname;
    const vendor = host === "fcm.googleapis.com" || host === "web.push.apple.com" ||
      host.endsWith(".push.services.mozilla.com") || host.endsWith(".notify.windows.com");
    return vendor && url.protocol === "https:" && !url.port && !url.username && !url.password &&
      value.endpoint.length <= 4096 && /^[A-Za-z0-9_-]{87}$/.test(value.keys?.p256dh) &&
      /^[A-Za-z0-9_-]{22}$/.test(value.keys?.auth);
  } catch { return false; }
}

function createPushNotifications(directory, deliver = webpush.sendNotification.bind(webpush)) {
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  const filename = path.join(directory, "push.json");
  const state = fs.existsSync(filename)
    ? JSON.parse(fs.readFileSync(filename, "utf8"))
    : { keys: webpush.generateVAPIDKeys(), subscriptions: {} };
  state.subscriptions = Object.assign(Object.create(null), state.subscriptions);
  function save() {
    const temporary = `${filename}.tmp`;
    fs.writeFileSync(temporary, `${JSON.stringify(state)}\n`, { mode: 0o600 });
    fs.renameSync(temporary, filename);
  }
  save();
  return {
    publicKey: state.keys.publicKey,
    has(deviceId) { return Boolean(state.subscriptions[deviceId]); },
    subscribe(deviceId, subscription) {
      if (!/^[A-Za-z0-9-]{1,100}$/.test(deviceId) || !validSubscription(subscription)) {
        throw new Error("Invalid browser push subscription");
      }
      if (!state.subscriptions[deviceId] && Object.keys(state.subscriptions).length >= 100) {
        throw new Error("Browser subscription limit reached");
      }
      state.subscriptions[deviceId] = {
        endpoint: subscription.endpoint,
        keys: { p256dh: subscription.keys.p256dh, auth: subscription.keys.auth },
      };
      save();
    },
    unsubscribe(deviceId) { delete state.subscriptions[deviceId]; save(); },
    async notify(message) {
      const payload = JSON.stringify({
        notificationId: message.notificationId,
        navigationPath: message.navigationPath,
        notificationTag: message.notificationTag,
        options: {
          title: String(message.options.title || "Codex").slice(0, 120),
          body: String(message.options.body || "").slice(0, 500),
          silent: message.options.silent === true,
          // Approval callbacks cannot survive a restart; open the task for its current controls.
          actions: [],
        },
      });
      await Promise.all(Object.entries(state.subscriptions).map(async ([deviceId, subscription]) => {
        try {
          await deliver(subscription, payload, {
            vapidDetails: { subject: "https://codex.ghostship.io", ...state.keys },
            TTL: 86400, urgency: "normal", timeout: 10000,
          });
        } catch (error) {
          if (error.statusCode === 404 || error.statusCode === 410) {
            // Do not remove a subscription renewed while this delivery was in flight.
            if (state.subscriptions[deviceId] === subscription) {
              delete state.subscriptions[deviceId]; save();
            }
          } else {
            console.error("[codex-web] push delivery failed", error.statusCode || error.code || "network-error");
          }
        }
      }));
    },
  };
}
module.exports = { createPushNotifications, validSubscription };
