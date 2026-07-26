"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { URL } = require("node:url");
const { WebSocketServer, WebSocket } = require("ws");
const { decode, encode } = require("./codec.cjs");

const SIDEBAR_CHANNEL = "codex_desktop:get-initial-sidebar-bootstrap";
const PROJECT_STATE_KEYS = new Set([
  "local-projects",
  "remote-projects",
  "project-order",
  "connection-group-order",
]);

function projectStateSignature(sidebar) {
  const projectEntries = Array.isArray(sidebar?.globalStateEntries)
    ? sidebar.globalStateEntries.filter((entry) => PROJECT_STATE_KEYS.has(entry?.key))
    : [];
  return JSON.stringify({
    projectEntries,
    workspaceRootOptions: sidebar?.workspaceRootOptions,
  });
}

const MIME_TYPES = new Map([
  [".css", "text/css; charset=utf-8"],
  [".gif", "image/gif"],
  [".html", "text/html; charset=utf-8"],
  [".ico", "image/x-icon"],
  [".jpeg", "image/jpeg"],
  [".jpg", "image/jpeg"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".map", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml"],
  [".ttf", "font/ttf"],
  [".wasm", "application/wasm"],
  [".wav", "audio/wav"],
  [".woff", "font/woff"],
  [".woff2", "font/woff2"],
]);

function safeStaticPath(root, requestPath) {
  const decoded = decodeURIComponent(requestPath);
  const relative = decoded === "/" ? "index.html" : decoded.replace(/^\/+/, "");
  const resolved = path.resolve(root, relative);
  const normalizedRoot = `${path.resolve(root)}${path.sep}`;
  if (resolved !== path.resolve(root) && !resolved.startsWith(normalizedRoot)) {
    return null;
  }
  return resolved;
}

function transformIndex(source, bootstrap = {}) {
  const bridgeScripts = [
    '<link rel="manifest" href="/manifest.webmanifest">',
    '<meta name="theme-color" content="#0d0d0d">',
    '<meta name="mobile-web-app-capable" content="yes">',
    '<link rel="apple-touch-icon" href="/__bridge/icon-192.png">',
    `<script>window.__CODEX_WEB_BOOTSTRAP__=${JSON.stringify(bootstrap).replaceAll("<", "\\u003c")}</script>`,
    '<script src="/__bridge/electron-shim.js"></script>',
    '<script src="/__bridge/webview-bridge.js"></script>',
    '<script src="/__bridge/browser-preload.js"></script>',
    '<script defer src="/__bridge/pwa-register.js"></script>',
  ].join("\n    ");
  return source
    .replace("connect-src ", "connect-src ws: wss: ")
    .replace("<script type=\"module\"", `${bridgeScripts}\n    <script type="module"`);
}

function isBrowserOriginAllowed(request, configuredOrigins = "") {
  const origin = request.headers.origin;
  if (typeof origin !== "string") return false;
  const allowedOrigins = new Set(
    configuredOrigins
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean),
  );
  if (allowedOrigins.has(origin)) return true;
  try {
    return new URL(origin).host.toLowerCase() ===
      String(request.headers.host || "").toLowerCase();
  } catch {
    return false;
  }
}

function jsonResponse(response, statusCode, value) {
  const body = JSON.stringify(value);
  response.writeHead(statusCode, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
    "cache-control": "no-store",
  });
  response.end(body);
}

function browserSurfaceKey(conversationId, browserTabId) {
  if (
    typeof conversationId !== "string" ||
    typeof browserTabId !== "string" ||
    conversationId.length === 0 ||
    browserTabId.length === 0 ||
    conversationId.length > 512 ||
    browserTabId.length > 512
  ) {
    return null;
  }
  return `${conversationId}\0${browserTabId}`;
}

async function createGateway(options) {
  const browserClients = new Map();
  const browserSurfaces = new Map();
  const auxiliaryWindows = new Map();
  const browserNotifications = new Map();
  const pendingBrowserSurfaces = new Map();
  const pendingRelayMessages = [];
  const channelSubscribers = new Map();
  const eventHistory = [];
  const pendingDialogs = new Map();
  const uploadRoot = process.env.CODEX_WEB_UPLOAD_ROOT || "/tmp/codex-web-uploads";
  const fileRoots = (process.env.CODEX_WEB_FILE_ROOTS || "/workspace,/home/codex")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean)
    .map((value) => fs.realpathSync(value));
  let eventSequence = 0;
  let relayBootstrap = {};
  let relayProjectState = projectStateSignature();
  let relaySocket;
  let surfaceGeneration = 0;
  let auxiliaryWindowGeneration = 0;
  let browserGuestFactory;
  let browserFullscreenStateHandler;

  fs.mkdirSync(uploadRoot, { recursive: true, mode: 0o700 });

  function send(socket, message) {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(encode(message));
    }
  }

  function sendRelay(message) {
    if (relaySocket?.readyState === WebSocket.OPEN) {
      send(relaySocket, message);
      return;
    }
    pendingRelayMessages.push(message);
  }

  function broadcastControl(message) {
    const { type: action, ...details } = message;
    for (const client of browserClients.values()) {
      send(client.socket, { type: "control", action, ...details });
    }
  }

  function sendAuxiliaryWindowState(client, surface, includeFrame = true) {
    send(client?.socket, {
      type: "control",
      action: "auxiliary-window-state",
      windowId: surface.id,
      visible: surface.visible,
      modal: surface.modal,
      transparent: surface.transparent,
      title: surface.window.isDestroyed() ? surface.title : surface.window.getTitle(),
      bounds: surface.window.isDestroyed()
        ? surface.bounds
        : surface.window.getContentBounds(),
    });
    if (includeFrame && surface.visible && surface.frame) {
      send(client?.socket, {
        type: "control",
        action: "auxiliary-window-frame",
        windowId: surface.id,
        frame: surface.frame,
      });
    }
  }

  function publishAuxiliaryWindowState(surface, includeFrame = true) {
    for (const client of browserClients.values()) {
      sendAuxiliaryWindowState(client, surface, includeFrame);
    }
  }

  async function captureAuxiliaryWindow(surface) {
    if (
      surface.capturePending ||
      !surface.visible ||
      browserClients.size === 0 ||
      surface.window.isDestroyed() ||
      surface.webContents.isDestroyed()
    ) {
      return;
    }
    surface.capturePending = true;
    try {
      const image = await surface.webContents.capturePage();
      if (image.isEmpty()) return;
      const size = image.getSize();
      surface.frame = {
        data: image.toPNG().toString("base64"),
        height: size.height,
        mimeType: "image/png",
        width: size.width,
      };
      surface.bounds = surface.window.getContentBounds();
      surface.captureErrorLogged = false;
      publishAuxiliaryWindowState(surface);
    } catch (error) {
      if (!surface.window.isDestroyed() && !surface.captureErrorLogged) {
        surface.captureErrorLogged = true;
        console.error("[codex-web] auxiliary window capture failed", error);
      }
    } finally {
      surface.capturePending = false;
    }
  }

  function registerAuxiliaryWindow(window, metadata = {}) {
    auxiliaryWindowGeneration += 1;
    const id = `window-${auxiliaryWindowGeneration}`;
    const surface = {
      bounds: window.getContentBounds(),
      captureErrorLogged: false,
      capturePending: false,
      frame: null,
      id,
      modal: metadata.modal === true,
      title: metadata.title || "",
      transparent: metadata.transparent === true,
      visible: false,
      webContents: window.webContents,
      window,
    };
    auxiliaryWindows.set(id, surface);
    const update = () => {
      if (auxiliaryWindows.get(id) !== surface || window.isDestroyed()) return;
      surface.visible = window.isVisible();
      surface.bounds = window.getContentBounds();
      publishAuxiliaryWindowState(surface, false);
      void captureAuxiliaryWindow(surface);
    };
    for (const eventName of ["show", "hide", "resize", "move"]) {
      window.on(eventName, update);
    }
    for (const eventName of [
      "did-finish-load",
      "did-navigate",
      "did-navigate-in-page",
      "page-title-updated",
    ]) {
      window.webContents.on(eventName, update);
    }
    window.once("closed", () => {
      surface.visible = false;
      publishAuxiliaryWindowState(surface, false);
      auxiliaryWindows.delete(id);
    });
    console.log("[codex-web] auxiliary window registered", {
      id,
      modal: surface.modal,
      title: surface.title || null,
      transparent: surface.transparent,
    });
    return id;
  }

  function showNotification(notificationId, options, onEvent) {
    browserNotifications.set(notificationId, onEvent);
    broadcastControl({
      type: "show-notification",
      notificationId,
      options: {
        actions: Array.isArray(options.actions)
          ? options.actions.map((action, index) => ({
              action: String(index),
              title: action.text || action.title || `Action ${index + 1}`,
            }))
          : [],
        body: options.body || "",
        icon:
          typeof options.icon === "string" && options.icon.startsWith("data:")
            ? options.icon
            : "/__bridge/icon-192.png",
        silent: options.silent === true,
        title: options.title || "Codex",
      },
    });
  }

  function closeNotification(notificationId) {
    browserNotifications.delete(notificationId);
    broadcastControl({ type: "close-notification", notificationId });
  }

  function sendBrowserSurface(client, surface, includeFrame = true) {
    send(client?.socket, {
      type: "control",
      action: "browser-surface-state",
      conversationId: surface.conversationId,
      browserTabId: surface.browserTabId,
      generation: surface.generation,
      state: surface.state,
    });
    if (includeFrame && surface.frame) {
      send(client?.socket, {
        type: "control",
        action: "browser-surface-frame",
        conversationId: surface.conversationId,
        browserTabId: surface.browserTabId,
        generation: surface.generation,
        frame: surface.frame,
      });
    }
  }

  function publishBrowserSurfaceState(surface) {
    surface.state = {
      canGoBack: surface.webContents.navigationHistory?.canGoBack?.() || false,
      canGoForward:
        surface.webContents.navigationHistory?.canGoForward?.() || false,
      isLoading: surface.webContents.isLoading(),
      title: surface.webContents.getTitle(),
      url: surface.webContents.getURL(),
    };
    for (const client of browserClients.values()) {
      if (client.surfaceKeys.has(surface.key)) {
        sendBrowserSurface(client, surface, false);
      }
    }
  }

  async function captureBrowserSurface(surface) {
    if (
      surface.capturePending ||
      surface.webContents.isDestroyed() ||
      ![...browserClients.values()].some((client) =>
        client.surfaceKeys.has(surface.key)
      )
    ) {
      return;
    }
    surface.capturePending = true;
    try {
      const image = await surface.webContents.capturePage();
      if (image.isEmpty()) return;
      const size = image.getSize();
      surface.frame = {
        data: image.toJPEG(72).toString("base64"),
        height: size.height,
        mimeType: "image/jpeg",
        width: size.width,
      };
      surface.captureErrorLogged = false;
      for (const client of browserClients.values()) {
        if (client.surfaceKeys.has(surface.key)) {
          send(client.socket, {
            type: "control",
            action: "browser-surface-frame",
            conversationId: surface.conversationId,
            browserTabId: surface.browserTabId,
            generation: surface.generation,
            frame: surface.frame,
          });
        }
      }
    } catch (error) {
      if (!surface.webContents.isDestroyed() && !surface.captureErrorLogged) {
        surface.captureErrorLogged = true;
        console.error("[codex-web] browser surface capture failed", error);
      }
    } finally {
      surface.capturePending = false;
    }
  }

  function registerBrowserGuest(metadata, webContents) {
    const key = browserSurfaceKey(
      metadata?.conversationId,
      metadata?.browserTabId,
    );
    if (!key) return;
    surfaceGeneration += 1;
    const surface = {
      browserTabId: metadata.browserTabId,
      captureErrorLogged: false,
      capturePending: false,
      conversationId: metadata.conversationId,
      frame: null,
      generation: surfaceGeneration,
      key,
      ownerWindow: metadata.ownerWindow || null,
      state: {},
      webContents,
    };
    browserSurfaces.set(key, surface);
    const update = () => {
      if (browserSurfaces.get(key) !== surface) return;
      publishBrowserSurfaceState(surface);
      void captureBrowserSurface(surface);
    };
    for (const eventName of [
      "did-finish-load",
      "did-navigate",
      "did-navigate-in-page",
      "did-start-loading",
      "did-stop-loading",
      "page-title-updated",
    ]) {
      webContents.on(eventName, update);
    }
    webContents.once("destroyed", () => {
      if (browserSurfaces.get(key) === surface) {
        browserSurfaces.delete(key);
      }
    });
    publishBrowserSurfaceState(surface);
    for (const client of browserClients.values()) {
      if (client.surfaceKeys.has(key)) {
        sendBrowserSurface(client, surface, false);
      }
    }
    console.log("[codex-web] browser surface attached", {
      browserTabId: metadata.browserTabId,
      conversationId: metadata.conversationId,
      webContentsId: webContents.id,
    });
    void captureBrowserSurface(surface);
  }

  function ensureBrowserGuest(conversationId, browserTabId) {
    const key = browserSurfaceKey(conversationId, browserTabId);
    if (
      !key ||
      browserSurfaces.has(key) ||
      pendingBrowserSurfaces.has(key) ||
      !browserGuestFactory
    ) {
      return;
    }
    const pending = Promise.resolve(
      browserGuestFactory({ browserTabId, conversationId }),
    )
      .then((guest) => {
        if (!guest || browserSurfaces.has(key)) {
          guest?.ownerWindow?.close();
          return;
        }
        registerBrowserGuest(
          { browserTabId, conversationId, ownerWindow: guest.ownerWindow },
          guest.webContents,
        );
      })
      .catch((error) => {
        console.error("[codex-web] browser surface creation failed", error);
      })
      .finally(() => {
        pendingBrowserSurfaces.delete(key);
      });
    pendingBrowserSurfaces.set(key, pending);
  }

  async function handleBrowserSurfaceCommand(client, message) {
    const key = browserSurfaceKey(message.conversationId, message.browserTabId);
    const surface = key ? browserSurfaces.get(key) : null;
    if (!surface || !client.surfaceKeys.has(key)) return;
    const guest = surface.webContents;
    switch (message.command) {
      case "navigate": {
        let target;
        try {
          target = new URL(message.url);
        } catch {
          return;
        }
        if (!["http:", "https:", "about:"].includes(target.protocol)) return;
        await guest.loadURL(target.href);
        break;
      }
      case "go-back":
        if (guest.navigationHistory?.canGoBack()) {
          guest.navigationHistory.goBack();
        }
        break;
      case "go-forward":
        if (guest.navigationHistory?.canGoForward()) {
          guest.navigationHistory.goForward();
        }
        break;
      case "reload":
        guest.reload();
        break;
      case "stop":
        guest.stop();
        break;
      case "focus":
        guest.focus();
        break;
      case "input": {
        const input = message.input;
        if (!input || typeof input.type !== "string") return;
        const allowedTypes = new Set([
          "char",
          "keyDown",
          "keyUp",
          "mouseDown",
          "mouseMove",
          "mouseUp",
          "mouseWheel",
        ]);
        if (!allowedTypes.has(input.type)) return;
        if (
          typeof input.xRatio === "number" &&
          typeof input.yRatio === "number"
        ) {
          const size = surface.frame || { width: 1280, height: 720 };
          input.x = Math.round(
            Math.max(0, Math.min(1, input.xRatio)) * size.width,
          );
          input.y = Math.round(
            Math.max(0, Math.min(1, input.yRatio)) * size.height,
          );
        }
        delete input.xRatio;
        delete input.yRatio;
        guest.sendInputEvent(input);
        break;
      }
      default:
        return;
    }
    publishBrowserSurfaceState(surface);
    void captureBrowserSurface(surface);
  }

  function confinedFilePath(candidate, allowMissing = false) {
    try {
      const realPath = fs.realpathSync(candidate);
      return fileRoots.some(
        (root) => realPath === root || realPath.startsWith(`${root}${path.sep}`),
      )
        ? realPath
        : null;
    } catch {
      if (allowMissing) {
        try {
          const parent = fs.realpathSync(path.dirname(candidate));
          if (
            fileRoots.some(
              (root) => parent === root || parent.startsWith(`${root}${path.sep}`),
            )
          ) {
            return path.join(parent, path.basename(candidate));
          }
        } catch {
          // The prospective file's parent must already exist inside a shared root.
        }
      }
      return null;
    }
  }

  function requestDialog(dialogType, dialogOptions = {}) {
    if (browserClients.size === 0) {
      return Promise.resolve(
        dialogType === "message"
          ? {
              response: dialogOptions.cancelId ?? dialogOptions.defaultId ?? 0,
              checkboxChecked: false,
            }
          : dialogType === "save"
            ? { canceled: true, filePath: undefined }
            : { canceled: true, filePaths: [] },
      );
    }
    const dialogId = crypto.randomUUID();
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        pendingDialogs.delete(dialogId);
        resolve(
          dialogType === "message"
            ? {
                response:
                  dialogOptions.cancelId ?? dialogOptions.defaultId ?? 0,
                checkboxChecked: false,
              }
            : dialogType === "save"
              ? { canceled: true, filePath: undefined }
              : { canceled: true, filePaths: [] },
        );
        broadcastControl({ type: "dialog-complete", dialogId });
      }, 5 * 60 * 1000);
      pendingDialogs.set(dialogId, {
        dialogType,
        resolve(result) {
          clearTimeout(timer);
          resolve(result);
        },
      });
      broadcastControl({
        type: "show-dialog",
        dialogId,
        dialogType,
        options: dialogOptions,
      });
    });
  }

  function publishEvent(channel, args) {
    eventSequence += 1;
    const message = {
      type: "event",
      sequence: eventSequence,
      channel,
      args,
    };
    eventHistory.push(message);
    if (eventHistory.length > 1000) {
      eventHistory.shift();
    }
    for (const clientId of channelSubscribers.get(channel) || []) {
      const client = browserClients.get(clientId);
      send(client?.socket, message);
    }
  }

  function handleRelayMessage(message) {
    if (message.type === "relay-ready") {
      relayBootstrap = message.bootstrap || {};
      relayProjectState = projectStateSignature(relayBootstrap[SIDEBAR_CHANNEL]);
      for (const queued of pendingRelayMessages.splice(0)) {
        sendRelay(queued);
      }
      return;
    }
    if (message.type === "bootstrap-update") {
      const nextSidebar = message.bootstrap?.[SIDEBAR_CHANNEL];
      let projectsChanged = false;
      if (nextSidebar !== undefined) {
        const nextProjectState = projectStateSignature(nextSidebar);
        projectsChanged = nextProjectState !== relayProjectState;
        relayProjectState = nextProjectState;
      }
      Object.assign(relayBootstrap, message.bootstrap || {});
      broadcastControl({
        type: "update-bootstrap",
        bootstrap: message.bootstrap || {},
      });
      if (projectsChanged) {
        broadcastControl({ type: "project-state-changed" });
      }
      return;
    }
    if (message.type === "result") {
      const client = browserClients.get(message.clientId);
      send(client?.socket, message);
      return;
    }
    if (message.type === "event") {
      publishEvent(message.channel, message.args);
      return;
    }
    if (message.type === "port-message") {
      for (const client of browserClients.values()) {
        if (client.portIds.has(message.portId)) {
          send(client.socket, message);
          return;
        }
      }
    }
  }

  function handleBrowserMessage(client, message) {
    if (message.type === "invoke" || message.type === "send") {
      sendRelay({ ...message, clientId: client.id });
      return;
    }
    if (message.type === "subscribe") {
      const subscribers = channelSubscribers.get(message.channel) || new Set();
      const wasEmpty = subscribers.size === 0;
      subscribers.add(client.id);
      channelSubscribers.set(message.channel, subscribers);
      if (wasEmpty) {
        sendRelay(message);
      }
      return;
    }
    if (message.type === "unsubscribe") {
      const subscribers = channelSubscribers.get(message.channel);
      subscribers?.delete(client.id);
      if (subscribers?.size === 0) {
        channelSubscribers.delete(message.channel);
        sendRelay(message);
      }
      return;
    }
    if (message.type === "post-message-port") {
      client.portIds.add(message.portId);
      sendRelay(message);
      return;
    }
    if (message.type === "port-message" || message.type === "port-close") {
      sendRelay(message);
      return;
    }
    if (message.type === "dialog-result") {
      const pending = pendingDialogs.get(message.dialogId);
      if (pending) {
        if (pending.dialogType === "message") {
          pendingDialogs.delete(message.dialogId);
          pending.resolve({
            response: Number.isInteger(message.result?.response)
              ? message.result.response
              : 0,
            checkboxChecked: message.result?.checkboxChecked === true,
          });
          broadcastControl({
            type: "dialog-complete",
            dialogId: message.dialogId,
          });
          return;
        }
        const selectedPaths = Array.isArray(message.result?.filePaths)
          ? message.result.filePaths
          : message.result?.filePath
            ? [message.result.filePath]
            : [];
        const confinedPaths = selectedPaths
          .map((candidate) =>
            confinedFilePath(candidate, pending.dialogType === "save")
          )
          .filter(Boolean);
        const canceled =
          message.result?.canceled !== false ||
          confinedPaths.length !== selectedPaths.length;
        pendingDialogs.delete(message.dialogId);
        pending.resolve(
          pending.dialogType === "save"
            ? { canceled, filePath: canceled ? undefined : confinedPaths[0] }
            : { canceled, filePaths: canceled ? [] : confinedPaths },
        );
        broadcastControl({ type: "dialog-complete", dialogId: message.dialogId });
      }
      return;
    }
    if (message.type === "notification-action") {
      const notify = browserNotifications.get(message.notificationId);
      if (notify) {
        notify({
          type: message.action === "close" ? "close" : "click",
          actionIndex:
            message.action === "click" && /^\d+$/.test(message.actionId || "")
              ? Number(message.actionId)
              : null,
        });
        if (message.action !== "close") {
          browserNotifications.delete(message.notificationId);
        }
      }
      return;
    }
    if (message.type === "browser-fullscreen-state") {
      browserFullscreenStateHandler?.(message.enabled === true);
      return;
    }
    if (message.type === "auxiliary-window-command") {
      const surface = auxiliaryWindows.get(message.windowId);
      if (!surface || !surface.visible || surface.window.isDestroyed()) return;
      if (message.command === "close") {
        surface.window.close();
        return;
      }
      if (message.command !== "input" || !message.input) return;
      const input = { ...message.input };
      const allowedTypes = new Set([
        "char",
        "keyDown",
        "keyUp",
        "mouseDown",
        "mouseMove",
        "mouseUp",
        "mouseWheel",
      ]);
      if (!allowedTypes.has(input.type)) return;
      if (
        typeof input.xRatio === "number" &&
        typeof input.yRatio === "number"
      ) {
        const size = surface.frame || surface.bounds || { width: 1, height: 1 };
        input.x = Math.round(
          Math.max(0, Math.min(1, input.xRatio)) * size.width,
        );
        input.y = Math.round(
          Math.max(0, Math.min(1, input.yRatio)) * size.height,
        );
      }
      delete input.xRatio;
      delete input.yRatio;
      surface.webContents.sendInputEvent(input);
      void captureAuxiliaryWindow(surface);
      return;
    }
    if (message.type === "browser-surface-subscribe") {
      const key = browserSurfaceKey(message.conversationId, message.browserTabId);
      if (!key) return;
      client.surfaceKeys.add(key);
      const surface = browserSurfaces.get(key);
      if (surface) {
        sendBrowserSurface(client, surface);
        void captureBrowserSurface(surface);
      } else {
        ensureBrowserGuest(message.conversationId, message.browserTabId);
      }
      return;
    }
    if (message.type === "browser-surface-unsubscribe") {
      const key = browserSurfaceKey(message.conversationId, message.browserTabId);
      if (key) client.surfaceKeys.delete(key);
      return;
    }
    if (message.type === "browser-surface-command") {
      void handleBrowserSurfaceCommand(client, message).catch((error) => {
        console.error("[codex-web] browser surface command failed", error);
      });
    }
  }

  const nativeHostPort = Number(process.env.CODEX_WEB_NATIVE_HOST_PORT || "5175");
  const handleHttpRequest = async (request, response) => {
    const requestUrl = new URL(request.url || "/", "http://localhost");
    if (requestUrl.pathname === "/health") {
      jsonResponse(response, 200, {
        status: relaySocket?.readyState === WebSocket.OPEN ? "ok" : "starting",
        version: options.appVersion,
        relayConnected: relaySocket?.readyState === WebSocket.OPEN,
        browserClients: browserClients.size,
        pendingDialogs: pendingDialogs.size,
      });
      return;
    }
    if (requestUrl.pathname === "/auth/callback" && request.method === "GET") {
      for (const port of [1455, 1457]) {
        try {
          const callback = await fetch(
            `http://127.0.0.1:${port}${requestUrl.pathname}${requestUrl.search}`,
          );
          const body = Buffer.from(await callback.arrayBuffer());
          response.writeHead(callback.status, {
            "content-type": callback.headers.get("content-type") || "text/html; charset=utf-8",
            "content-length": body.length,
            "cache-control": "no-store",
          });
          response.end(body);
          return;
        } catch {
          // Try the other loopback port used by the upstream desktop login.
        }
      }
      jsonResponse(response, 503, { error: "no desktop authentication is pending" });
      return;
    }
    if (requestUrl.pathname === "/manifest.webmanifest") {
      jsonResponse(response, 200, {
        id: "/",
        name: "Codex",
        short_name: "Codex",
        description: "Codex desktop in the browser",
        start_url: "/",
        scope: "/",
        display: "standalone",
        background_color: "#0d0d0d",
        theme_color: "#0d0d0d",
        categories: ["developer", "productivity"],
        icons: [
          {
            src: "/__bridge/icon-192.png",
            sizes: "192x192",
            type: "image/png",
            purpose: "any maskable",
          },
          {
            src: "/__bridge/icon-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "any maskable",
          },
        ],
      });
      return;
    }
    if (requestUrl.pathname === "/__bridge/files" && request.method === "GET") {
      const requestedPath = requestUrl.searchParams.get("path") || fileRoots[0];
      const directory = confinedFilePath(requestedPath);
      if (!directory || !fs.statSync(directory).isDirectory()) {
        jsonResponse(response, 403, { error: "path is outside the shared filesystem" });
        return;
      }
      const parentCandidate = confinedFilePath(path.dirname(directory));
      const entries = fs.readdirSync(directory, { withFileTypes: true })
        .filter((entry) => entry.isDirectory() || entry.isFile())
        .map((entry) => ({
          name: entry.name,
          type: entry.isDirectory() ? "directory" : "file",
        }))
        .sort((left, right) =>
          left.type === right.type
            ? left.name.localeCompare(right.name)
            : left.type === "directory" ? -1 : 1
        );
      jsonResponse(response, 200, {
        path: directory,
        parent: parentCandidate === directory ? null : parentCandidate,
        entries,
      });
      return;
    }
    if (requestUrl.pathname.startsWith("/__bridge/upload/") && request.method === "PUT") {
      const parts = requestUrl.pathname.split("/").filter(Boolean).slice(2);
      if (parts.length !== 3 || parts.some((part) => !/^[A-Za-z0-9._-]+$/.test(part))) {
        jsonResponse(response, 400, { error: "invalid upload path" });
        return;
      }
      const targetDirectory = path.join(uploadRoot, parts[0], parts[1]);
      fs.mkdirSync(targetDirectory, { recursive: true, mode: 0o700 });
      const targetPath = path.join(targetDirectory, parts[2]);
      const contentLength = Number(request.headers["content-length"] || "0");
      if (contentLength > 100 * 1024 * 1024) {
        jsonResponse(response, 413, { error: "upload exceeds 100 MiB" });
        return;
      }
      const stream = fs.createWriteStream(targetPath, { mode: 0o600 });
      let size = 0;
      let failed = false;
      request.on("data", (chunk) => {
        size += chunk.length;
        if (!failed && size > 100 * 1024 * 1024) {
          failed = true;
          request.unpipe(stream);
          stream.destroy();
          fs.rm(targetPath, { force: true }, () => {});
          jsonResponse(response, 413, { error: "upload exceeds 100 MiB" });
          request.resume();
        }
      });
      request.pipe(stream);
      stream.on("finish", () => {
        if (!failed) jsonResponse(response, 200, { path: targetPath });
      });
      stream.on("error", (error) => {
        if (!failed) jsonResponse(response, 500, { error: error.message });
      });
      return;
    }
    if (requestUrl.pathname.startsWith("/__bridge/")) {
      const bridgeFile = requestUrl.pathname.slice("/__bridge/".length);
      const target = safeStaticPath(path.join(__dirname, "browser"), bridgeFile);
      if (!target || !fs.existsSync(target) || !fs.statSync(target).isFile()) {
        response.writeHead(404);
        response.end("not found");
        return;
      }
      const body = fs.readFileSync(target);
      const headers = {
        "content-type": MIME_TYPES.get(path.extname(target)) || "application/octet-stream",
        "content-length": body.length,
        "cache-control": "no-cache",
      };
      if (bridgeFile === "sw.js") {
        headers["service-worker-allowed"] = "/";
      }
      response.writeHead(200, headers);
      response.end(body);
      return;
    }

    let target = safeStaticPath(options.webviewRoot, requestUrl.pathname);
    if (!target || !fs.existsSync(target) || !fs.statSync(target).isFile()) {
      target = path.join(options.webviewRoot, "index.html");
    }
    let body = fs.readFileSync(target);
    if (target.endsWith("index.html")) {
      body = Buffer.from(
        request.socket.localPort === nativeHostPort
          ? body.toString("utf8")
          : transformIndex(body.toString("utf8"), relayBootstrap),
      );
    }
    response.writeHead(200, {
      "content-type": MIME_TYPES.get(path.extname(target)) || "application/octet-stream",
      "content-length": body.length,
      "cache-control": target.endsWith("index.html")
        ? "no-cache"
        : "public, max-age=31536000, immutable",
    });
    response.end(body);
  };
  const server = http.createServer(handleHttpRequest);
  const nativeServer = http.createServer(handleHttpRequest);

  const browserWebSockets = new WebSocketServer({ noServer: true });
  const relayWebSockets = new WebSocketServer({ noServer: true });

  server.on("upgrade", (request, socket, head) => {
    const requestUrl = new URL(request.url || "/", "http://localhost");
    if (requestUrl.pathname === "/__bridge/relay") {
      if (request.headers["x-codex-relay-secret"] !== options.relaySecret) {
        socket.destroy();
        return;
      }
      relayWebSockets.handleUpgrade(request, socket, head, (webSocket) => {
        relayWebSockets.emit("connection", webSocket, request);
      });
      return;
    }
    if (requestUrl.pathname === "/__bridge/ipc") {
      if (!isBrowserOriginAllowed(request, process.env.CODEX_WEB_ALLOWED_ORIGINS)) {
        socket.destroy();
        return;
      }
      browserWebSockets.handleUpgrade(request, socket, head, (webSocket) => {
        browserWebSockets.emit("connection", webSocket, request, requestUrl);
      });
      return;
    }
    socket.destroy();
  });

  relayWebSockets.on("connection", (socket, request) => {
    if (
      request.headers["x-codex-relay-primary"] !== "1" ||
      relaySocket?.readyState === WebSocket.OPEN
    ) {
      socket.close(1008, "relay already connected");
      return;
    }
    relaySocket = socket;
    socket.on("message", (payload) => {
      handleRelayMessage(decode(payload));
    });
    socket.on("close", () => {
      if (relaySocket === socket) {
        relaySocket = undefined;
      }
    });
  });

  browserWebSockets.on("connection", (socket, _request, requestUrl) => {
    const clientId = crypto.randomUUID();
    const deviceId = requestUrl.searchParams.get("device") || crypto.randomUUID();
    const client = {
      id: clientId,
      deviceId,
      socket,
      portIds: new Set(),
      surfaceKeys: new Set(),
    };
    browserClients.set(clientId, client);
    const since = Number(requestUrl.searchParams.get("since") || "0");
    send(socket, {
      type: "hello",
      clientId,
      deviceId,
      sequence: eventSequence,
      relayConnected: relaySocket?.readyState === WebSocket.OPEN,
    });
    for (const surface of auxiliaryWindows.values()) {
      if (surface.visible) sendAuxiliaryWindowState(client, surface);
    }
    for (const event of eventHistory) {
      if (event.sequence > since) {
        send(socket, event);
      }
    }
    socket.on("message", (payload) => {
      handleBrowserMessage(client, decode(payload));
    });
    socket.on("close", () => {
      browserClients.delete(clientId);
      for (const [channel, subscribers] of channelSubscribers) {
        subscribers.delete(clientId);
        if (subscribers.size === 0) {
          channelSubscribers.delete(channel);
          sendRelay({ type: "unsubscribe", channel });
        }
      }
      for (const portId of client.portIds) {
        sendRelay({ type: "port-close", portId });
      }
    });
  });

  await Promise.all([
    new Promise((resolve, reject) => {
      server.once("error", reject);
      server.listen(options.port, options.host, resolve);
    }),
    new Promise((resolve, reject) => {
      nativeServer.once("error", reject);
      nativeServer.listen(nativeHostPort, "127.0.0.1", resolve);
    }),
  ]);

  console.log(`[codex-web] listening on http://${options.host}:${options.port}`);
  console.log(
    `[codex-web] native renderer host listening on http://127.0.0.1:${nativeHostPort}`,
  );
  const captureTimer = setInterval(() => {
    for (const surface of browserSurfaces.values()) {
      void captureBrowserSurface(surface);
    }
    for (const surface of auxiliaryWindows.values()) {
      void captureAuxiliaryWindow(surface);
    }
  }, 250);
  captureTimer.unref();
  return {
    broadcastControl,
    close: () => {
      clearInterval(captureTimer);
      for (const surface of browserSurfaces.values()) {
        if (surface.ownerWindow && !surface.ownerWindow.isDestroyed?.()) {
          surface.ownerWindow.close();
        }
      }
      return Promise.all([
        new Promise((resolve) => server.close(resolve)),
        new Promise((resolve) => nativeServer.close(resolve)),
      ]);
    },
    registerBrowserGuest,
    registerAuxiliaryWindow,
    requestDialog,
    closeNotification,
    nativeServer,
    setBrowserFullscreenStateHandler(handler) {
      browserFullscreenStateHandler = handler;
    },
    setBrowserGuestFactory(factory) {
      browserGuestFactory = factory;
    },
    showNotification,
    server,
  };
}

module.exports = {
  createGateway,
  isBrowserOriginAllowed,
  safeStaticPath,
  transformIndex,
};
