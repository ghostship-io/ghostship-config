import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { createRequire } from "node:module";
import { WebSocket } from "ws";

const require = createRequire(import.meta.url);
const { createGateway } = require("../bridge/gateway.cjs");
const { decode, encode } = require("../bridge/codec.cjs");

function nextMessage(socket) {
  if (socket.messageQueue.length > 0) {
    return Promise.resolve(socket.messageQueue.shift());
  }
  return new Promise((resolve, reject) => {
    socket.messageWaiters.push({ reject, resolve });
  });
}

function openSocket(url, options) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(url, options);
    socket.messageQueue = [];
    socket.messageWaiters = [];
    socket.on("message", (payload) => {
      const message = decode(payload);
      const waiter = socket.messageWaiters.shift();
      if (waiter) waiter.resolve(message);
      else socket.messageQueue.push(message);
    });
    socket.on("error", (error) => {
      for (const waiter of socket.messageWaiters.splice(0)) waiter.reject(error);
    });
    socket.once("open", () => resolve(socket));
    socket.once("error", reject);
  });
}

test("gateway fans native events and dialogs out to multiple browser devices", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "codex-gateway-test-"));
  const webviewRoot = path.join(root, "webview");
  const sharedRoot = path.join(root, "workspace");
  await mkdir(webviewRoot);
  await mkdir(sharedRoot);
  await writeFile(
    path.join(webviewRoot, "index.html"),
    '<script type="module" src="/assets/index.js"></script>',
  );
  process.env.CODEX_WEB_FILE_ROOTS = sharedRoot;
  process.env.CODEX_WEB_UPLOAD_ROOT = path.join(root, "uploads");

  const gateway = await createGateway({
    appVersion: "test",
    host: "127.0.0.1",
    port: 0,
    relaySecret: "test-secret",
    webviewRoot,
  });
  const port = gateway.server.address().port;
  const relay = await openSocket(`ws://127.0.0.1:${port}/__bridge/relay`, {
    headers: {
      "x-codex-relay-primary": "1",
      "x-codex-relay-secret": "test-secret",
    },
  });
  relay.send(encode({ type: "relay-ready", bootstrap: {} }));

  const origin = `http://127.0.0.1:${port}`;
  const serviceWorker = await fetch(`${origin}/__bridge/sw.js`);
  assert.equal(serviceWorker.status, 200);
  assert.equal(serviceWorker.headers.get("service-worker-allowed"), "/");
  const manifestResponse = await fetch(`${origin}/manifest.webmanifest`);
  assert.equal(
    manifestResponse.headers.get("content-type"),
    "application/manifest+json; charset=utf-8",
  );
  const manifest = await manifestResponse.json();
  assert.equal(manifest.id, "/");
  assert.equal(manifest.start_url, "/");
  assert.equal(manifest.scope, "/");
  assert.equal(manifest.display, "standalone");
  assert.equal(manifest.prefer_related_applications, false);
  assert.deepEqual(
    manifest.icons.map(({ purpose, sizes }) => ({ purpose, sizes })),
    [
      { purpose: "any", sizes: "192x192" },
      { purpose: "any", sizes: "512x512" },
      { purpose: "maskable", sizes: "192x192" },
      { purpose: "maskable", sizes: "512x512" },
    ],
  );
  const first = await openSocket(`${origin}/__bridge/ipc?device=first`, {
    headers: { origin },
  });
  const second = await openSocket(`${origin}/__bridge/ipc?device=second`, {
    headers: { origin },
  });
  assert.equal((await nextMessage(first)).type, "hello");
  assert.equal((await nextMessage(second)).type, "hello");

  const relaySubscription = nextMessage(relay);
  first.send(encode({ type: "subscribe", channel: "shared-event" }));
  second.send(encode({ type: "subscribe", channel: "shared-event" }));
  assert.deepEqual(await relaySubscription, {
    type: "subscribe",
    channel: "shared-event",
  });

  const firstEvent = nextMessage(first);
  const secondEvent = nextMessage(second);
  relay.send(encode({ type: "event", channel: "shared-event", args: ["same"] }));
  assert.equal((await firstEvent).args[0], "same");
  assert.equal((await secondEvent).args[0], "same");

  const localSubscription = nextMessage(relay);
  first.send(encode({
    type: "subscribe",
    channel: "codex_desktop:message-for-view",
  }));
  second.send(encode({
    type: "subscribe",
    channel: "codex_desktop:message-for-view",
  }));
  assert.deepEqual(await localSubscription, {
    type: "subscribe",
    channel: "codex_desktop:message-for-view",
  });
  first.send(encode({
    type: "claim-device-local-command",
    commandId: "showKeyboardShortcuts",
  }));
  second.send(encode({
    type: "claim-device-local-command",
    commandId: "showKeyboardShortcuts",
  }));
  await new Promise((resolve) => setTimeout(resolve, 10));
  const firstCommand = nextMessage(first);
  relay.send(encode({
    type: "event",
    channel: "codex_desktop:message-for-view",
    args: [{ type: "run-command", id: "showKeyboardShortcuts" }],
  }));
  assert.deepEqual((await firstCommand).args, [
    { type: "run-command", id: "showKeyboardShortcuts" },
  ]);
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(
    second.messageQueue.some(
      (message) => message.args?.[0]?.type === "run-command",
    ),
    false,
  );
  const secondCommand = nextMessage(second);
  relay.send(encode({
    type: "event",
    channel: "codex_desktop:message-for-view",
    args: [{ type: "run-command", id: "showKeyboardShortcuts" }],
  }));
  assert.deepEqual((await secondCommand).args, [
    { type: "run-command", id: "showKeyboardShortcuts" },
  ]);
  relay.send(encode({
    type: "event",
    channel: "codex_desktop:message-for-view",
    args: [{ type: "run-command", id: "showKeyboardShortcuts" }],
  }));
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(
    [first, second].some((socket) =>
      socket.messageQueue.some(
        (message) => message.args?.[0]?.id === "showKeyboardShortcuts",
      )
    ),
    false,
  );
  const firstUnclaimedCommand = nextMessage(first);
  const secondUnclaimedCommand = nextMessage(second);
  relay.send(encode({
    type: "event",
    channel: "codex_desktop:message-for-view",
    args: [{ type: "run-command", id: "newChat" }],
  }));
  assert.deepEqual((await firstUnclaimedCommand).args, [
    { type: "run-command", id: "newChat" },
  ]);
  assert.deepEqual((await secondUnclaimedCommand).args, [
    { type: "run-command", id: "newChat" },
  ]);

  const firstBootstrapUpdate = nextMessage(first);
  const secondBootstrapUpdate = nextMessage(second);
  relay.send(encode({
    type: "bootstrap-update",
    bootstrap: {
      "codex_desktop:get-initial-sidebar-bootstrap": {
        globalStateEntries: [
          {
            key: "local-projects",
            value: {
              "project-id": { id: "project-id", name: "new-project" },
            },
          },
        ],
      },
    },
  }));
  assert.equal((await firstBootstrapUpdate).action, "update-bootstrap");
  assert.deepEqual(
    (await secondBootstrapUpdate).bootstrap[
      "codex_desktop:get-initial-sidebar-bootstrap"
    ].globalStateEntries[0].value["project-id"],
    { id: "project-id", name: "new-project" },
  );
  assert.equal((await nextMessage(first)).action, "project-state-changed");
  assert.equal((await nextMessage(second)).action, "project-state-changed");
  const refreshedIndex = await (await fetch(origin)).text();
  assert.match(refreshedIndex, /new-project/);

  const firstDialog = nextMessage(first);
  const secondDialog = nextMessage(second);
  const dialogResult = gateway.requestDialog("open", {
    properties: ["openDirectory"],
  });
  const dialog = await firstDialog;
  assert.equal(dialog.action, "show-dialog");
  assert.equal((await secondDialog).dialogId, dialog.dialogId);
  first.send(encode({
    type: "dialog-result",
    dialogId: dialog.dialogId,
    result: { canceled: false, filePaths: [sharedRoot] },
  }));
  assert.deepEqual(await dialogResult, {
    canceled: false,
    filePaths: [sharedRoot],
  });
  assert.equal((await nextMessage(first)).action, "dialog-complete");
  assert.equal((await nextMessage(second)).action, "dialog-complete");

  const firstMessageDialog = nextMessage(first);
  const secondMessageDialog = nextMessage(second);
  const messageDialogResult = gateway.requestDialog("message", {
    buttons: ["OK", "Cancel"],
    cancelId: 1,
    message: "Confirm",
  });
  const messageDialog = await firstMessageDialog;
  assert.equal(messageDialog.action, "show-dialog");
  assert.equal(messageDialog.dialogType, "message");
  assert.equal((await secondMessageDialog).dialogId, messageDialog.dialogId);
  first.send(encode({
    type: "dialog-result",
    dialogId: messageDialog.dialogId,
    result: { checkboxChecked: false, response: 0 },
  }));
  assert.deepEqual(await messageDialogResult, {
    checkboxChecked: false,
    response: 0,
  });
  assert.equal((await nextMessage(first)).action, "dialog-complete");
  assert.equal((await nextMessage(second)).action, "dialog-complete");

  let resolveNotificationEvent;
  const notificationEvent = new Promise((resolve) => {
    resolveNotificationEvent = resolve;
  });
  const firstNotification = nextMessage(first);
  const secondNotification = nextMessage(second);
  gateway.showNotification(
    "test-notification",
    { title: "Scheduled task complete", body: "Done" },
    (event) => {
      resolveNotificationEvent(event);
    },
  );
  assert.equal((await firstNotification).action, "show-notification");
  assert.equal((await secondNotification).notificationId, "test-notification");
  first.send(encode({
    type: "notification-action",
    notificationId: "test-notification",
    action: "click",
  }));
  assert.deepEqual(await notificationEvent, { type: "click", actionIndex: null });

  let resolveFullscreenState;
  const fullscreenState = new Promise((resolve) => {
    resolveFullscreenState = resolve;
  });
  gateway.setBrowserFullscreenStateHandler((enabled) => {
    resolveFullscreenState(enabled);
  });
  first.send(encode({ type: "browser-fullscreen-state", enabled: true }));
  assert.equal(await fullscreenState, true);

  const auxiliary = new EventEmitter();
  const auxiliaryContents = new EventEmitter();
  auxiliary.destroyed = false;
  auxiliary.visible = false;
  auxiliary.getContentBounds = () => ({ height: 240, width: 420, x: 0, y: 0 });
  auxiliary.getTitle = () => "About ChatGPT";
  auxiliary.isDestroyed = () => auxiliary.destroyed;
  auxiliary.isVisible = () => auxiliary.visible;
  auxiliary.webContents = auxiliaryContents;
  auxiliaryContents.capturePage = async () => ({
    getSize: () => ({ height: 240, width: 420 }),
    isEmpty: () => false,
    toPNG: () => Buffer.from("auxiliary-frame"),
  });
  auxiliaryContents.isDestroyed = () => false;
  auxiliaryContents.sendInputEvent = () => {};
  gateway.registerAuxiliaryWindow(auxiliary, { modal: true });
  const firstAuxiliaryState = nextMessage(first);
  const secondAuxiliaryState = nextMessage(second);
  auxiliary.visible = true;
  auxiliary.emit("show");
  assert.equal((await firstAuxiliaryState).action, "auxiliary-window-state");
  assert.equal((await secondAuxiliaryState).title, "About ChatGPT");
  assert.equal((await nextMessage(first)).action, "auxiliary-window-state");
  assert.equal((await nextMessage(first)).action, "auxiliary-window-frame");
  assert.equal((await nextMessage(second)).action, "auxiliary-window-state");
  assert.equal((await nextMessage(second)).action, "auxiliary-window-frame");
  const firstAuxiliaryClosed = nextMessage(first);
  const secondAuxiliaryClosed = nextMessage(second);
  auxiliary.destroyed = true;
  auxiliary.emit("closed");
  assert.equal((await firstAuxiliaryClosed).visible, false);
  assert.equal((await secondAuxiliaryClosed).visible, false);

  const guest = new EventEmitter();
  guest.currentUrl = "about:blank";
  guest.inputEvents = [];
  guest.capturePage = async () => ({
    getSize: () => ({ height: 720, width: 1280 }),
    isEmpty: () => false,
    toJPEG: () => Buffer.from("frame"),
  });
  guest.getTitle = () => guest.currentUrl;
  guest.getURL = () => guest.currentUrl;
  guest.isDestroyed = () => false;
  guest.isLoading = () => false;
  guest.loadURL = async (url) => {
    guest.currentUrl = url;
    guest.emit("did-navigate");
  };
  guest.navigationHistory = {
    canGoBack: () => false,
    canGoForward: () => false,
  };
  guest.sendInputEvent = (event) => guest.inputEvents.push(event);
  guest.stop = () => {};
  guest.reload = () => {};
  guest.focus = () => {};
  gateway.registerBrowserGuest(
    { browserTabId: "tab", conversationId: "conversation" },
    guest,
  );

  first.send(encode({
    type: "browser-surface-subscribe",
    browserTabId: "tab",
    conversationId: "conversation",
  }));
  second.send(encode({
    type: "browser-surface-subscribe",
    browserTabId: "tab",
    conversationId: "conversation",
  }));
  assert.equal((await nextMessage(first)).action, "browser-surface-state");
  assert.equal((await nextMessage(second)).action, "browser-surface-state");
  assert.equal((await nextMessage(first)).action, "browser-surface-frame");
  assert.equal((await nextMessage(second)).action, "browser-surface-frame");

  first.send(encode({
    type: "browser-surface-command",
    browserTabId: "tab",
    command: "navigate",
    conversationId: "conversation",
    url: "https://example.com/",
  }));
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(guest.currentUrl, "https://example.com/");

  first.send(encode({
    type: "browser-surface-command",
    browserTabId: "tab",
    command: "input",
    conversationId: "conversation",
    input: {
      button: "left",
      clickCount: 1,
      type: "mouseDown",
      xRatio: 0.25,
      yRatio: 0.5,
    },
  }));
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.deepEqual(guest.inputEvents.at(-1), {
    button: "left",
    clickCount: 1,
    type: "mouseDown",
    x: 320,
    y: 360,
  });

  first.close();
  second.close();
  relay.close();
  await new Promise((resolve) => setTimeout(resolve, 10));
  await gateway.close();
  delete process.env.CODEX_WEB_FILE_ROOTS;
  delete process.env.CODEX_WEB_UPLOAD_ROOT;
  await rm(root, { recursive: true, force: true });
});
