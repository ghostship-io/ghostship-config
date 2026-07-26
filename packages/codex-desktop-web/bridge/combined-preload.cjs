"use strict";

const path = require("node:path");
const { ipcRenderer } = require("electron");
const WebSocket = require("ws");
const { decode, encode } = require("./codec.cjs");

require(path.join(__dirname, "..", ".vite", "build", "preload.js"));

const relaySecret = process.env.CODEX_WEB_RELAY_SECRET;
const relayPort = process.env.CODEX_WEB_PORT || "8214";
const relayUrl = `ws://127.0.0.1:${relayPort}/__bridge/relay`;
const channelListeners = new Map();
const messagePorts = new Map();
let socket;
let reconnectTimer;

function readBootstrap() {
  const channels = [
    "codex_desktop:get-sentry-init-options",
    "codex_desktop:get-build-flavor",
    "codex_desktop:get-uses-owl-app-shell",
    "codex_desktop:get-shared-object-snapshot",
    "codex_desktop:get-system-theme-variant",
    "codex_desktop:get-initial-sidebar-bootstrap",
  ];
  return {
    ...Object.fromEntries(
    channels.map((channel) => {
      try {
        return [channel, ipcRenderer.sendSync(channel)];
      } catch (error) {
        console.error("[codex-web] bootstrap channel failed", channel, error);
        return [channel, undefined];
      }
    }),
    ),
    __codexWebPlatform: {
      arch: process.arch,
      electron: process.versions.electron,
      platform: process.platform,
    },
  };
}

const bootstrap = readBootstrap();

function send(message) {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(encode(message));
  }
}

function subscribe(channel) {
  if (channelListeners.has(channel)) {
    return;
  }
  const listener = (_event, ...args) => {
    send({ type: "event", channel, args });
  };
  channelListeners.set(channel, listener);
  ipcRenderer.on(channel, listener);
}

function unsubscribe(channel) {
  const listener = channelListeners.get(channel);
  if (!listener) {
    return;
  }
  ipcRenderer.removeListener(channel, listener);
  channelListeners.delete(channel);
}

function createTransferredPort(message) {
  const channel = new MessageChannel();
  channel.port1.onmessage = (event) => {
    send({
      type: "port-message",
      portId: message.portId,
      data: event.data,
    });
  };
  channel.port1.start();
  messagePorts.set(message.portId, channel.port1);
  ipcRenderer.postMessage(message.channel, message.message, [channel.port2]);
}

async function handle(message) {
  if (message.type === "invoke") {
    try {
      const result = await ipcRenderer.invoke(message.channel, ...message.args);
      send({
        type: "result",
        clientId: message.clientId,
        requestId: message.requestId,
        ok: true,
        result,
      });
    } catch (error) {
      send({
        type: "result",
        clientId: message.clientId,
        requestId: message.requestId,
        ok: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
    return;
  }
  if (message.type === "send") {
    ipcRenderer.send(message.channel, ...message.args);
    return;
  }
  if (message.type === "subscribe") {
    subscribe(message.channel);
    return;
  }
  if (message.type === "unsubscribe") {
    unsubscribe(message.channel);
    return;
  }
  if (message.type === "post-message-port") {
    createTransferredPort(message);
    return;
  }
  if (message.type === "port-message") {
    messagePorts.get(message.portId)?.postMessage(message.data);
    return;
  }
  if (message.type === "port-close") {
    messagePorts.get(message.portId)?.close();
    messagePorts.delete(message.portId);
  }
}

function connect() {
  socket = new WebSocket(relayUrl, {
    headers: {
      "x-codex-relay-secret": relaySecret,
      "x-codex-relay-primary": bootstrap[
        "codex_desktop:get-initial-sidebar-bootstrap"
      ]
        ? "1"
        : "0",
    },
  });
  socket.on("open", () => {
    send({ type: "relay-ready", bootstrap });
    for (const channel of channelListeners.keys()) {
      send({ type: "relay-subscription-ready", channel });
    }
  });
  socket.on("message", (payload) => {
    try {
      void handle(decode(payload));
    } catch (error) {
      send({
        type: "relay-error",
        error: error instanceof Error ? error.message : String(error),
      });
    }
  });
  socket.on("close", (code) => {
    if (code === 1008) return;
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, 500);
  });
  socket.on("error", (error) => {
    console.error("[codex-web] relay error", error);
  });
}

connect();
