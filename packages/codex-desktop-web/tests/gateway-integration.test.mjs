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
