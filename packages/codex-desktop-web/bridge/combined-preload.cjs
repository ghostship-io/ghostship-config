"use strict";

const { ipcRenderer } = require("electron");
const channelListeners = new Map();
const messagePorts = new Map();
const bootstrapRefreshMessageTypes = new Set([
  "active-workspace-roots-updated",
  "global-state-updated",
  "workspace-root-option-added",
  "workspace-root-options-updated",
]);
let connected = false;

function isProjectStateFetchResponse(message) {
  if (
    message?.type !== "fetch-response" ||
    message.responseType !== "success" ||
    typeof message.bodyJsonString !== "string"
  ) {
    return false;
  }
  try {
    const value = JSON.parse(message.bodyJsonString)?.value;
    if (!value || Array.isArray(value) || typeof value !== "object") {
      return false;
    }
    return Object.values(value).every(
      (project) =>
        project &&
        typeof project.id === "string" &&
        typeof project.name === "string" &&
        Array.isArray(project.rootPaths),
    );
  } catch {
    return false;
  }
}

function readBootstrap() {
  const channels = [
    "codex_desktop:get-sentry-init-options",
    "codex_desktop:get-build-flavor",
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
  if (connected) ipcRenderer.send("ghostship-native:relay-send", message);
}

function subscribe(channel) {
  if (channelListeners.has(channel)) {
    return;
  }
  const listener = (_event, ...args) => {
    if (
      channel === "codex_desktop:message-for-view" &&
      (
        bootstrapRefreshMessageTypes.has(args[0]?.type) ||
        isProjectStateFetchResponse(args[0])
      )
    ) {
      const nextBootstrap = readBootstrap();
      Object.assign(bootstrap, nextBootstrap);
      send({ type: "bootstrap-update", bootstrap: nextBootstrap });
    }
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
  if (["invoke", "send", "subscribe", "unsubscribe", "post-message-port"].includes(message.type) &&
      !message.channel?.startsWith("codex_desktop:")) {
    throw new Error("Browser request used a private native channel");
  }
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

ipcRenderer.on("ghostship-native:relay-state", (_event, ready) => {
  connected = ready === true;
  if (connected) {
    send({ type: "relay-ready", bootstrap });
    for (const channel of channelListeners.keys()) {
      send({ type: "relay-subscription-ready", channel });
    }
  }
});
ipcRenderer.on("ghostship-native:relay-message", (_event, message) => {
  void handle(message).catch((error) => send({ type: "relay-error", error: String(error) }));
});
ipcRenderer.send("ghostship-native:relay-open");
