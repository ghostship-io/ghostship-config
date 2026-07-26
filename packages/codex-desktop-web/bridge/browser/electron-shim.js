(() => {
  "use strict";

  const listeners = new Map();
  const pendingInvokes = new Map();
  const outbound = [];
  const virtualPorts = new Map();
  const pendingUploads = new Set();
  const nativeFetch = window.fetch.bind(window);
  const bootstrap = window.__CODEX_WEB_BOOTSTRAP__ || {};
  const deviceKey = "codex-web-device-id";
  const sequenceKey = "codex-web-event-sequence";
  const nativeRandomUUID =
    typeof crypto.randomUUID === "function" ? crypto.randomUUID.bind(crypto) : null;

  function randomId() {
    if (nativeRandomUUID) return nativeRandomUUID();
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  if (typeof crypto.randomUUID !== "function") {
    Object.defineProperty(crypto, "randomUUID", {
      configurable: true,
      value: randomId,
    });
  }

  const deviceId = localStorage.getItem(deviceKey) || randomId();
  localStorage.setItem(deviceKey, deviceId);
  let requestCounter = 0;
  let reconnectTimer;
  let socket;
  let activeDialog;

  function nextId(prefix) {
    requestCounter += 1;
    return `${prefix}-${deviceId}-${requestCounter}`;
  }

  function send(message) {
    const encoded = JSON.stringify(message, (_key, item) => {
      if (item instanceof Uint8Array) {
        let binary = "";
        for (const byte of item) binary += String.fromCharCode(byte);
        return { __codexBridgeType: "uint8array", base64: btoa(binary) };
      }
      if (item instanceof ArrayBuffer) {
        const bytes = new Uint8Array(item);
        let binary = "";
        for (const byte of bytes) binary += String.fromCharCode(byte);
        return { __codexBridgeType: "arraybuffer", base64: btoa(binary) };
      }
      return item;
    });
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(encoded);
    } else {
      outbound.push(encoded);
      connect();
    }
  }

  function emit(channel, args) {
    const event = { sender: null };
    for (const listener of listeners.get(channel) || []) {
      listener(event, ...args);
    }
  }

  function closeDialog(dialogId) {
    if (activeDialog && activeDialog.dialogId === dialogId) {
      if (activeDialog.overlay.open) activeDialog.overlay.close();
      activeDialog.overlay.remove();
      activeDialog = undefined;
    }
  }

  function sendDialogResult(dialogId, result) {
    send({ type: "dialog-result", dialogId, result });
    closeDialog(dialogId);
  }

  function showDialog(message) {
    closeDialog(activeDialog?.dialogId);
    const directoryMode =
      message.dialogType === "open" &&
      (message.options?.properties || []).includes("openDirectory");
    const overlay = document.createElement("dialog");
    const panel = document.createElement("div");
    const title = document.createElement("h2");
    const locationRow = document.createElement("div");
    const location = document.createElement("input");
    const go = document.createElement("button");
    const entries = document.createElement("div");
    const footer = document.createElement("div");
    const cancel = document.createElement("button");
    const select = document.createElement("button");
    let currentPath = message.options?.defaultPath || "/workspace";
    let selectedFile;

    overlay.style.cssText =
      "position:fixed;inset:0;z-index:2147483647;width:100vw;height:100vh;max-width:none;max-height:none;margin:0;padding:0;border:0;place-items:center;background:rgba(0,0,0,.55);font:14px system-ui,sans-serif;color:#ececec";
    panel.style.cssText =
      "width:min(680px,calc(100vw - 32px));height:min(560px,calc(100vh - 32px));display:flex;flex-direction:column;gap:12px;padding:20px;border:1px solid #444;border-radius:12px;background:#202020;box-shadow:0 20px 70px #000";
    title.textContent = message.options?.title || (directoryMode ? "Choose folder" : "Choose file");
    title.style.cssText = "font-size:18px;margin:0";
    locationRow.style.cssText = "display:flex;gap:8px";
    location.style.cssText =
      "flex:1;min-width:0;padding:9px 11px;border:1px solid #555;border-radius:7px;background:#151515;color:inherit";
    go.textContent = "Go";
    entries.style.cssText =
      "flex:1;overflow:auto;padding:4px;border:1px solid #3c3c3c;border-radius:8px;background:#181818";
    footer.style.cssText = "display:flex;justify-content:flex-end;gap:8px";
    cancel.textContent = "Cancel";
    select.textContent = directoryMode ? "Select this folder" : "Select";
    for (const button of [go, cancel, select]) {
      button.style.cssText =
        "padding:8px 13px;border:1px solid #555;border-radius:7px;background:#303030;color:inherit;cursor:pointer";
    }
    select.style.background = "#e7e7e7";
    select.style.color = "#111";

    async function loadDirectory(target) {
      entries.textContent = "Loading…";
      const response = await nativeFetch(
        `/__bridge/files?path=${encodeURIComponent(target)}`,
      );
      if (!response.ok) {
        entries.textContent = "This location is not available.";
        return;
      }
      const listing = await response.json();
      currentPath = listing.path;
      selectedFile = undefined;
      location.value = currentPath;
      entries.replaceChildren();
      if (listing.parent) {
        const up = document.createElement("button");
        up.textContent = "↰  Parent folder";
        up.onclick = () => void loadDirectory(listing.parent);
        entries.append(up);
      }
      for (const entry of listing.entries) {
        if (directoryMode && entry.type !== "directory") continue;
        const item = document.createElement("button");
        item.textContent = `${entry.type === "directory" ? "▸" : "·"}  ${entry.name}`;
        item.style.cssText =
          "display:block;width:100%;padding:8px;border:0;border-radius:5px;background:transparent;color:inherit;text-align:left;cursor:pointer";
        item.onmouseenter = () => { item.style.background = "#303030"; };
        item.onmouseleave = () => {
          item.style.background =
            selectedFile === entry.name ? "#3b4d66" : "transparent";
        };
        if (entry.type === "directory") {
          item.onclick = () =>
            void loadDirectory(`${currentPath.replace(/\/$/, "")}/${entry.name}`);
        } else {
          item.onclick = () => {
            selectedFile = entry.name;
            for (const child of entries.children) child.style.background = "transparent";
            item.style.background = "#3b4d66";
          };
        }
        entries.append(item);
      }
    }

    go.onclick = () => void loadDirectory(location.value);
    location.onkeydown = (event) => {
      if (event.key === "Enter") void loadDirectory(location.value);
    };
    cancel.onclick = () =>
      sendDialogResult(
        message.dialogId,
        message.dialogType === "save"
          ? { canceled: true }
          : { canceled: true, filePaths: [] },
      );
    select.onclick = () => {
      const selectedPath =
        directoryMode || !selectedFile
          ? currentPath
          : `${currentPath.replace(/\/$/, "")}/${selectedFile}`;
      sendDialogResult(
        message.dialogId,
        message.dialogType === "save"
          ? { canceled: false, filePath: selectedPath }
          : { canceled: false, filePaths: [selectedPath] },
      );
    };

    locationRow.append(location, go);
    footer.append(cancel, select);
    panel.append(title, locationRow, entries, footer);
    overlay.append(panel);
    document.body.append(overlay);
    overlay.showModal();
    overlay.style.display = "grid";
    activeDialog = { dialogId: message.dialogId, overlay };
    void loadDirectory(currentPath);
  }

  function handle(message) {
    if (message.type === "hello") {
      while (outbound.length > 0) socket.send(outbound.shift());
      for (const channel of listeners.keys()) {
        send({ type: "subscribe", channel });
      }
      return;
    }
    if (message.type === "result") {
      const pending = pendingInvokes.get(message.requestId);
      if (!pending) return;
      pendingInvokes.delete(message.requestId);
      if (message.ok) pending.resolve(message.result);
      else pending.reject(new Error(message.error));
      return;
    }
    if (message.type === "event") {
      sessionStorage.setItem(sequenceKey, String(message.sequence));
      emit(message.channel, message.args);
      return;
    }
    if (message.type === "port-message") {
      virtualPorts.get(message.portId)?.postMessage(message.data);
      return;
    }
    if (message.type === "control") {
      if (message.action === "open-external" && message.url) {
        window.open(message.url, "_blank", "noopener,noreferrer");
      } else if (message.action === "show-dialog") {
        showDialog(message);
      } else if (message.action === "dialog-complete") {
        closeDialog(message.dialogId);
      }
    }
  }

  function connect() {
    if (
      socket &&
      (socket.readyState === WebSocket.OPEN ||
        socket.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const since = sessionStorage.getItem(sequenceKey) || "0";
    socket = new WebSocket(
      `${protocol}//${location.host}/__bridge/ipc?device=${encodeURIComponent(deviceId)}&since=${encodeURIComponent(since)}`,
    );
    socket.addEventListener("message", (event) => {
      try {
        handle(JSON.parse(String(event.data)));
      } catch (error) {
        console.error("[codex-web] invalid bridge message", error);
      }
    });
    socket.addEventListener("close", () => {
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, 500);
    });
    socket.addEventListener("error", () => {});
  }

  function addListener(channel, listener) {
    const channelListeners = listeners.get(channel) || new Set();
    const first = channelListeners.size === 0;
    channelListeners.add(listener);
    listeners.set(channel, channelListeners);
    if (first) send({ type: "subscribe", channel });
  }

  function removeListener(channel, listener) {
    const channelListeners = listeners.get(channel);
    channelListeners?.delete(listener);
    if (channelListeners?.size === 0) {
      listeners.delete(channel);
      send({ type: "unsubscribe", channel });
    }
  }

  async function waitForUploads() {
    if (pendingUploads.size > 0) {
      await Promise.all([...pendingUploads]);
    }
  }

  const ipcRenderer = {
    async invoke(channel, ...args) {
      await waitForUploads();
      const requestId = nextId("invoke");
      return new Promise((resolve, reject) => {
        pendingInvokes.set(requestId, { resolve, reject });
        send({ type: "invoke", requestId, channel, args });
      });
    },
    send(channel, ...args) {
      send({ type: "send", channel, args });
    },
    sendSync(channel) {
      if (Object.prototype.hasOwnProperty.call(bootstrap, channel)) {
        return bootstrap[channel];
      }
      if (channel === "codex_desktop:get-sentry-init-options") {
        return {
          codexAppSessionId: deviceId,
          buildFlavor: "prod",
          buildNumber: null,
          appVersion: document.documentElement.dataset.build || "web",
          enabled: false,
        };
      }
      if (channel === "codex_desktop:get-build-flavor") return "prod";
      if (channel === "codex_desktop:get-uses-owl-app-shell") return false;
      if (channel === "codex_desktop:get-system-theme-variant") {
        return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
      }
      if (channel === "codex_desktop:get-shared-object-snapshot") {
        return {
          host_config: { id: "local", display_name: "Local", kind: "local" },
          remote_ssh_connections: [],
          remote_wsl_connections: [],
          remote_control_connections_state: {
            available: false,
            accessRequired: false,
            authRequired: false,
            clientAuthorized: false,
          },
          local_remote_control_client_id: null,
          pending_worktrees: [],
        };
      }
      if (channel === "codex_desktop:get-initial-sidebar-bootstrap") return undefined;
      if (channel === "codex_desktop:start-file-drag") return false;
      return undefined;
    },
    on(channel, listener) {
      addListener(channel, listener);
      return this;
    },
    once(channel, listener) {
      const wrapped = (event, ...args) => {
        removeListener(channel, wrapped);
        listener(event, ...args);
      };
      addListener(channel, wrapped);
      return this;
    },
    addListener(channel, listener) {
      addListener(channel, listener);
      return this;
    },
    removeListener(channel, listener) {
      removeListener(channel, listener);
      return this;
    },
    off(channel, listener) {
      removeListener(channel, listener);
      return this;
    },
    postMessage(channel, message, transfer = []) {
      if (transfer.length === 0) {
        send({ type: "send", channel, args: [message] });
        return;
      }
      for (const port of transfer) {
        const portId = nextId("port");
        virtualPorts.set(portId, port);
        port.onmessage = (event) => {
          void waitForUploads().then(() => {
            send({ type: "port-message", portId, data: event.data });
          });
        };
        port.start();
        send({ type: "post-message-port", channel, message, portId });
      }
    },
  };

  const electronModule = {
    contextBridge: {
      exposeInMainWorld(key, api) {
        Object.defineProperty(window, key, {
          configurable: false,
          enumerable: true,
          value: api,
          writable: false,
        });
      },
    },
    ipcRenderer,
    webUtils: {
      getPathForFile(file) {
        if (!(file instanceof File)) return null;
        const uploadId = randomId();
        const safeName = file.name.replace(/[^A-Za-z0-9._-]/g, "_") || "upload";
        const targetPath = `/tmp/codex-web-uploads/${deviceId}/${uploadId}/${safeName}`;
        const upload = nativeFetch(
          `/__bridge/upload/${encodeURIComponent(deviceId)}/${uploadId}/${encodeURIComponent(safeName)}`,
          { method: "PUT", body: file },
        ).then((response) => {
          if (!response.ok) throw new Error(`upload failed: ${response.status}`);
        });
        pendingUploads.add(upload);
        upload.finally(() => pendingUploads.delete(upload));
        return targetPath;
      },
    },
  };

  Object.defineProperty(window, "__codexElectronModule", {
    configurable: false,
    value: electronModule,
    writable: false,
  });
  Object.defineProperty(window, "process", {
    configurable: false,
    value: {
      arch: bootstrap.__codexWebPlatform?.arch || "x64",
      platform: bootstrap.__codexWebPlatform?.platform || "linux",
      versions: {
        electron: bootstrap.__codexWebPlatform?.electron || "42.3.0",
      },
    },
    writable: false,
  });

  connect();
})();
