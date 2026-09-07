"use strict";

const { ipcRenderer } = require("electron");
const channelListeners = new Map();
const messagePorts = new Map();
const chunkTransfers = new Map();
const sidebarChannel = "codex_desktop:get-initial-sidebar-bootstrap";
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

// The native renderer owns acknowledgements. Browser sessions receive complete
// messages, so joining mid-transfer cannot leave a partial stream in their UI.
function readChunk(part, channel) {
  if (part.kind === "start") {
    for (const [id, transfer] of chunkTransfers) {
      if (transfer.channel === channel) chunkTransfers.delete(id);
    }
    chunkTransfers.set(part.transferId, { channel, sequence: part.sequence, stack: [], value: undefined });
    return;
  }
  const transfer = chunkTransfers.get(part.transferId);
  if (!transfer) return;
  if (part.sequence !== transfer.sequence + 1) {
    chunkTransfers.delete(part.transferId);
    throw new Error("Out-of-order native chunk transfer");
  }
  transfer.sequence = part.sequence;
  function append(value) {
    const parent = transfer.stack.at(-1);
    if (!parent) transfer.value = value;
    else if (Array.isArray(parent.value)) parent.value.push(value);
    else {
      Object.defineProperty(parent.value, parent.key, {
        configurable: true, enumerable: true, writable: true, value,
      });
      parent.key = undefined;
    }
  }
  for (const token of part.tokens || []) {
    switch (token.type) {
      case "object-start":
      case "array-start": {
        const value = token.type === "array-start" ? [] : {};
        append(value);
        transfer.stack.push({ value });
        break;
      }
      case "container-end": transfer.stack.pop(); break;
      case "key": transfer.stack.at(-1).key = token.value; break;
      case "value": append(token.value); break;
      case "string-start": transfer.string = { target: token.target, parts: [] }; break;
      case "string-chunk": transfer.string.parts.push(token.value); break;
      case "string-end": {
        const value = transfer.string.parts.join("");
        if (transfer.string.target === "key") transfer.stack.at(-1).key = value;
        else append(value);
        transfer.string = undefined;
        break;
      }
      default: throw new Error(`Unsupported native chunk token: ${token.type}`);
    }
  }
  if (part.kind === "end") {
    chunkTransfers.delete(part.transferId);
    if (transfer.stack.length || transfer.string) throw new Error("Incomplete native chunk transfer");
    return transfer.value;
  }
}

function send(message) {
  if (connected) ipcRenderer.send("ghostship-native:relay-send", message);
}

function subscribe(channel) {
  if (channelListeners.has(channel)) {
    return;
  }
  const listener = (_event, ...args) => {
    if (args[0]?.marker === "codex-host-chunked-message-v1") {
      try {
        const value = readChunk(args[0], channel);
        if (value === undefined) return;
        args = [value];
      } catch (error) {
        chunkTransfers.delete(args[0].transferId);
        console.error("[codex-web] native chunk decode failed", error);
        return;
      }
    }
    if (channel === "codex_desktop:message-for-view" && args[0]?.type === "shared-object-updated") {
      const snapshot = bootstrap["codex_desktop:get-shared-object-snapshot"];
      if (snapshot) {
        if (args[0].value === undefined) delete snapshot[args[0].key];
        else snapshot[args[0].key] = args[0].value;
      }
    }
    if (
      channel === "codex_desktop:message-for-view" &&
      (
        bootstrapRefreshMessageTypes.has(args[0]?.type) ||
        isProjectStateFetchResponse(args[0])
      )
    ) {
      // Project updates need only the sidebar, not the multi-megabyte shared
      // object snapshot, diagnostics, and other unchanged startup metadata.
      const nextBootstrap = { [sidebarChannel]: ipcRenderer.sendSync(sidebarChannel) };
      Object.assign(bootstrap, nextBootstrap);
      send({ type: "bootstrap-update", bootstrap: nextBootstrap });
    }
    send({ type: "event", channel, args });
  };
  channelListeners.set(channel, listener);
  ipcRenderer.on(channel, listener);
}

function unsubscribe(channel) {
  // Keep startup snapshots current even while no browser is connected.
  if (channel === "codex_desktop:message-for-view") return;
  const listener = channelListeners.get(channel);
  if (!listener) {
    return;
  }
  ipcRenderer.removeListener(channel, listener);
  channelListeners.delete(channel);
  for (const [id, transfer] of chunkTransfers) {
    if (transfer.channel === channel) chunkTransfers.delete(id);
  }
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
    if (message.channel === "codex_desktop:chunked-message-ack") return;
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

subscribe("codex_desktop:message-for-view");
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
setInterval(() => send({ type: "relay-heartbeat" }), 5000);
