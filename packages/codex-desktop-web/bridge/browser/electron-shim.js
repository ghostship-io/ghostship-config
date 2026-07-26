(() => {
  "use strict";

  const listeners = new Map();
  const pendingInvokes = new Map();
  const outbound = [];
  const virtualPorts = new Map();
  const pendingUploads = new Set();
  const auxiliaryWindows = new Map();
  const browserNotifications = new Map();
  const controlListeners = new Set();
  const outboundMessageListeners = new Set();
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
  let notificationPrompt;
  let projectMutationReloadTimer;

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
      activeDialog.overlay.remove();
      activeDialog = undefined;
    }
  }

  function sendDialogResult(dialogId, result) {
    send({ type: "dialog-result", dialogId, result });
    closeDialog(dialogId);
  }

  function showMessageDialog(message) {
    const options = message.options || {};
    const overlay = document.createElement("div");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    for (const eventName of ["pointerdown", "mousedown", "click"]) {
      overlay.addEventListener(eventName, (event) => event.stopPropagation());
    }
    const panel = document.createElement("div");
    const title = document.createElement("h2");
    const body = document.createElement("div");
    const detail = document.createElement("div");
    const footer = document.createElement("div");
    const buttons =
      Array.isArray(options.buttons) && options.buttons.length > 0
        ? options.buttons
        : ["OK"];

    overlay.style.cssText =
      "position:fixed;inset:0;z-index:2147483647;width:100vw;height:100vh;max-width:none;max-height:none;margin:0;padding:0;border:0;place-items:center;background:rgba(0,0,0,.55);font:14px system-ui,sans-serif;color:#ececec;pointer-events:auto";
    panel.style.cssText =
      "width:min(520px,calc(100vw - 32px));display:flex;flex-direction:column;gap:12px;padding:22px;border:1px solid #444;border-radius:12px;background:#202020;box-shadow:0 20px 70px #000;pointer-events:auto";
    title.textContent = options.title || "Codex";
    title.style.cssText = "font-size:18px;margin:0";
    body.textContent = options.message || "";
    body.style.cssText = "font-size:15px;font-weight:600;white-space:pre-wrap";
    detail.textContent = options.detail || "";
    detail.style.cssText =
      "color:#b8b8b8;line-height:1.45;max-height:40vh;overflow:auto;white-space:pre-wrap";
    footer.style.cssText = "display:flex;justify-content:flex-end;gap:8px";
    buttons.forEach((label, index) => {
      const button = document.createElement("button");
      button.textContent = label;
      button.style.cssText =
        "padding:8px 13px;border:1px solid #555;border-radius:7px;background:#303030;color:inherit;cursor:pointer";
      if (index === (options.defaultId ?? 0)) {
        button.style.background = "#e7e7e7";
        button.style.color = "#111";
        button.autofocus = true;
      }
      button.onclick = () =>
        sendDialogResult(message.dialogId, {
          checkboxChecked: false,
          response: index,
        });
      footer.append(button);
    });
    panel.append(title, body);
    if (options.detail) panel.append(detail);
    panel.append(footer);
    overlay.append(panel);
    document.body.append(overlay);
    overlay.style.display = "grid";
    activeDialog = { dialogId: message.dialogId, overlay };
  }

  function showDialog(message) {
    closeDialog(activeDialog?.dialogId);
    if (message.dialogType === "message") {
      showMessageDialog(message);
      return;
    }
    const directoryMode =
      message.dialogType === "open" &&
      (message.options?.properties || []).includes("openDirectory");
    const overlay = document.createElement("div");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    for (const eventName of ["pointerdown", "mousedown", "click"]) {
      overlay.addEventListener(eventName, (event) => event.stopPropagation());
    }
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
      "position:fixed;inset:0;z-index:2147483647;width:100vw;height:100vh;max-width:none;max-height:none;margin:0;padding:0;border:0;place-items:center;background:rgba(0,0,0,.55);font:14px system-ui,sans-serif;color:#ececec;pointer-events:auto";
    panel.style.cssText =
      "width:min(680px,calc(100vw - 32px));height:min(560px,calc(100vh - 32px));display:flex;flex-direction:column;gap:12px;padding:20px;border:1px solid #444;border-radius:12px;background:#202020;box-shadow:0 20px 70px #000;pointer-events:auto";
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
    overlay.style.display = "grid";
    activeDialog = { dialogId: message.dialogId, overlay };
    void loadDirectory(currentPath);
  }

  function inputPosition(element, event) {
    const bounds = element.getBoundingClientRect();
    return {
      xRatio: bounds.width > 0 ? (event.clientX - bounds.left) / bounds.width : 0,
      yRatio: bounds.height > 0 ? (event.clientY - bounds.top) / bounds.height : 0,
    };
  }

  function sendAuxiliaryInput(surface, input) {
    send({
      type: "auxiliary-window-command",
      windowId: surface.windowId,
      command: "input",
      input,
    });
  }

  function createAuxiliaryWindow(message) {
    const element = document.createElement("div");
    const image = document.createElement("img");
    const surface = { element, image, windowId: message.windowId };
    element.dataset.codexAuxiliaryWindow = message.windowId;
    element.tabIndex = 0;
    element.style.cssText =
      "position:fixed;z-index:2147483645;display:none;overflow:hidden;outline:none;pointer-events:auto;background:transparent";
    image.alt = message.title || "";
    image.draggable = false;
    image.style.cssText =
      "display:block;width:100%;height:100%;object-fit:fill;user-select:none;-webkit-user-drag:none";
    element.append(image);
    document.body.append(element);
    element.addEventListener("pointerdown", (event) => {
      element.focus();
      element.setPointerCapture?.(event.pointerId);
      sendAuxiliaryInput(surface, {
        type: "mouseDown",
        button: event.button === 2 ? "right" : event.button === 1 ? "middle" : "left",
        clickCount: event.detail || 1,
        ...inputPosition(element, event),
      });
      event.preventDefault();
    });
    element.addEventListener("pointermove", (event) => {
      sendAuxiliaryInput(surface, {
        type: "mouseMove",
        ...inputPosition(element, event),
      });
    });
    element.addEventListener("pointerup", (event) => {
      sendAuxiliaryInput(surface, {
        type: "mouseUp",
        button: event.button === 2 ? "right" : event.button === 1 ? "middle" : "left",
        clickCount: event.detail || 1,
        ...inputPosition(element, event),
      });
      event.preventDefault();
    });
    element.addEventListener("wheel", (event) => {
      sendAuxiliaryInput(surface, {
        type: "mouseWheel",
        deltaX: event.deltaX,
        deltaY: event.deltaY,
        ...inputPosition(element, event),
      });
      event.preventDefault();
    }, { passive: false });
    element.addEventListener("keydown", (event) => {
      sendAuxiliaryInput(surface, {
        type: "keyDown",
        keyCode: event.key,
        modifiers: [
          event.altKey && "alt",
          event.ctrlKey && "control",
          event.metaKey && "meta",
          event.shiftKey && "shift",
        ].filter(Boolean),
      });
      if (event.key.length === 1) {
        sendAuxiliaryInput(surface, { type: "char", keyCode: event.key });
      }
      event.preventDefault();
    });
    element.addEventListener("keyup", (event) => {
      sendAuxiliaryInput(surface, { type: "keyUp", keyCode: event.key });
      event.preventDefault();
    });
    return surface;
  }

  function updateAuxiliaryWindow(message) {
    let surface = auxiliaryWindows.get(message.windowId);
    if (!surface) {
      surface = createAuxiliaryWindow(message);
      auxiliaryWindows.set(message.windowId, surface);
    }
    if (!message.visible) {
      surface.element.style.display = "none";
      surface.element.remove();
      auxiliaryWindows.delete(message.windowId);
      return;
    }
    const width = Math.min(
      Number(message.bounds?.width) || 420,
      Math.max(240, window.innerWidth - 24),
    );
    const height = Math.min(
      Number(message.bounds?.height) || 240,
      Math.max(120, window.innerHeight - 24),
    );
    surface.element.style.width = `${width}px`;
    surface.element.style.height = `${height}px`;
    surface.element.style.display = "block";
    if (message.modal || !message.transparent) {
      surface.element.style.left = "50%";
      surface.element.style.top = "50%";
      surface.element.style.right = "auto";
      surface.element.style.bottom = "auto";
      surface.element.style.transform = "translate(-50%,-50%)";
      surface.element.style.borderRadius = "10px";
      surface.element.style.boxShadow = "0 20px 70px rgba(0,0,0,.55)";
    } else {
      surface.element.style.left = "auto";
      surface.element.style.top = "auto";
      surface.element.style.right = "max(12px,env(safe-area-inset-right))";
      surface.element.style.bottom = "max(12px,env(safe-area-inset-bottom))";
      surface.element.style.transform = "none";
      surface.element.style.borderRadius = "0";
      surface.element.style.boxShadow = "none";
    }
  }

  function updateAuxiliaryFrame(message) {
    const surface = auxiliaryWindows.get(message.windowId);
    if (!surface || !message.frame?.data) return;
    surface.image.src =
      `data:${message.frame.mimeType || "image/png"};base64,${message.frame.data}`;
  }

  function ensureNotificationPrompt() {
    if (
      notificationPrompt ||
      !("Notification" in window) ||
      Notification.permission !== "default"
    ) {
      return;
    }
    const prompt = document.createElement("div");
    const label = document.createElement("span");
    const enable = document.createElement("button");
    const dismiss = document.createElement("button");
    prompt.style.cssText =
      "position:fixed;z-index:2147483646;top:max(48px,calc(env(safe-area-inset-top) + 12px));right:max(12px,env(safe-area-inset-right));display:flex;flex-wrap:wrap;align-items:center;gap:10px;max-width:calc(100vw - 24px);padding:11px 12px;border:1px solid #444;border-radius:10px;background:#202020;color:#ececec;box-shadow:0 12px 40px rgba(0,0,0,.5);font:13px system-ui,sans-serif;pointer-events:auto";
    label.textContent = "Enable Codex notifications for completed and scheduled tasks.";
    enable.textContent = "Enable";
    dismiss.textContent = "Not now";
    for (const button of [enable, dismiss]) {
      button.style.cssText =
        "padding:6px 9px;border:1px solid #555;border-radius:6px;background:#303030;color:inherit;cursor:pointer;white-space:nowrap";
    }
    enable.onclick = async () => {
      await Notification.requestPermission();
      prompt.remove();
      notificationPrompt = undefined;
      if (Notification.permission === "granted") {
        for (const notification of browserNotifications.values()) {
          void showBrowserNotification(notification);
        }
      }
    };
    dismiss.onclick = () => {
      prompt.remove();
      notificationPrompt = undefined;
    };
    prompt.append(label, enable, dismiss);
    document.body.append(prompt);
    notificationPrompt = prompt;
  }

  async function showBrowserNotification(message) {
    browserNotifications.set(message.notificationId, message);
    if (!("Notification" in window) || Notification.permission !== "granted") {
      ensureNotificationPrompt();
      return;
    }
    const options = message.options || {};
    const notificationOptions = {
      actions: options.actions || [],
      body: options.body || "",
      data: { codexNotificationId: message.notificationId },
      icon: options.icon || "/__bridge/icon-192.png",
      silent: options.silent === true,
      tag: `codex-${message.notificationId}`,
    };
    if ("serviceWorker" in navigator) {
      const registration = await navigator.serviceWorker.ready;
      await registration.showNotification(options.title || "Codex", notificationOptions);
      return;
    }
    const notification = new Notification(options.title || "Codex", notificationOptions);
    notification.onclick = () => {
      window.focus();
      send({
        type: "notification-action",
        notificationId: message.notificationId,
        action: "click",
      });
    };
    notification.onclose = () => {
      send({
        type: "notification-action",
        notificationId: message.notificationId,
        action: "close",
      });
    };
  }

  async function closeBrowserNotification(notificationId) {
    browserNotifications.delete(notificationId);
    if (!("serviceWorker" in navigator)) return;
    const registration = await navigator.serviceWorker.ready;
    const notifications = await registration.getNotifications({
      tag: `codex-${notificationId}`,
    });
    for (const notification of notifications) notification.close();
  }

  async function setBrowserFullscreen(enabled) {
    try {
      if (enabled && !document.fullscreenElement) {
        await document.documentElement.requestFullscreen();
      } else if (!enabled && document.fullscreenElement) {
        await document.exitFullscreen();
      }
    } catch {
      document.documentElement.toggleAttribute(
        "data-codex-web-fullscreen",
        enabled,
      );
    }
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
      for (const listener of controlListeners) {
        listener(message);
      }
      if (message.action === "open-external" && message.url) {
        window.open(message.url, "_blank", "noopener,noreferrer");
      } else if (message.action === "show-dialog") {
        showDialog(message);
      } else if (message.action === "dialog-complete") {
        closeDialog(message.dialogId);
      } else if (message.action === "auxiliary-window-state") {
        updateAuxiliaryWindow(message);
      } else if (message.action === "auxiliary-window-frame") {
        updateAuxiliaryFrame(message);
      } else if (message.action === "show-notification") {
        void showBrowserNotification(message);
      } else if (message.action === "close-notification") {
        void closeBrowserNotification(message.notificationId);
      } else if (message.action === "set-fullscreen") {
        void setBrowserFullscreen(message.enabled === true);
      } else if (message.action === "update-bootstrap") {
        const sidebarChannel = "codex_desktop:get-initial-sidebar-bootstrap";
        const previousSidebar = JSON.stringify(bootstrap[sidebarChannel]);
        const projectMutationDialogOpen = [...document.querySelectorAll(
          '[role="dialog"] h2',
        )].some((heading) =>
          heading.textContent === "Create project" ||
          /^Remove .+\?$/.test(heading.textContent || "")
        );
        Object.assign(bootstrap, message.bootstrap || {});
        if (
          projectMutationDialogOpen &&
          Object.prototype.hasOwnProperty.call(
            message.bootstrap || {},
            sidebarChannel,
          ) &&
          JSON.stringify(bootstrap[sidebarChannel]) !== previousSidebar
        ) {
          clearTimeout(projectMutationReloadTimer);
          projectMutationReloadTimer = setTimeout(() => location.reload(), 1500);
        }
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
      if (channel === "codex_desktop:message-from-view") {
        for (const listener of outboundMessageListeners) {
          listener(args[0]);
        }
      }
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
  Object.defineProperty(window, "__codexWebTransport", {
    configurable: false,
    value: {
      onControl(listener) {
        controlListeners.add(listener);
        return () => controlListeners.delete(listener);
      },
      onMessageFromView(listener) {
        outboundMessageListeners.add(listener);
        return () => outboundMessageListeners.delete(listener);
      },
      send,
    },
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

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.addEventListener("message", (event) => {
      if (event.data?.type !== "codex-notification-action") return;
      send({
        type: "notification-action",
        notificationId: event.data.notificationId,
        action: "click",
        actionId: event.data.actionId || null,
      });
    });
  }
  document.addEventListener("fullscreenchange", () => {
    document.documentElement.removeAttribute("data-codex-web-fullscreen");
    send({
      type: "browser-fullscreen-state",
      enabled: Boolean(document.fullscreenElement),
    });
  });
  window.addEventListener("keydown", (event) => {
    if (event.key !== "F11") return;
    event.preventDefault();
    void setBrowserFullscreen(!document.fullscreenElement);
  }, true);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ensureNotificationPrompt, {
      once: true,
    });
  } else {
    ensureNotificationPrompt();
  }

  const browserUsabilityStyle = document.createElement("style");
  browserUsabilityStyle.textContent = `
    button[aria-label="Add new project"],
    div:has(> div > button[aria-label="Add new project"]) {
      opacity: 1 !important;
      pointer-events: auto !important;
    }
    button[aria-haspopup] > * {
      pointer-events: none !important;
    }
  `;
  document.head.append(browserUsabilityStyle);

  connect();
})();
