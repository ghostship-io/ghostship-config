"use strict";

const crypto = require("node:crypto");
const { EventEmitter } = require("node:events");
const Module = require("node:module");
const path = require("node:path");
const WebSocket = require("ws");
const { encode, decode } = require("./codec.cjs");

function installElectronProxy(realElectron, gateway) {
  const originalLoad = Module._load;
  const OriginalBrowserWindow = realElectron.BrowserWindow;
  let browserPrimaryWindow;
  let browserFullscreen = false;
  let notificationCounter = 0;
  let applicationMenu;
  let nativeRelay;
  let nativeRelayRetry;

  function connectNativeRelay() {
    if (!browserPrimaryWindow || browserPrimaryWindow.isDestroyed()) return;
    const contents = browserPrimaryWindow.webContents;
    const socket = new WebSocket(`ws://127.0.0.1:${process.env.CODEX_WEB_PORT || "8214"}/__bridge/relay`, {
      headers: {
        "x-codex-relay-secret": process.env.CODEX_WEB_RELAY_SECRET,
        "x-codex-relay-primary": "1",
      },
    });
    nativeRelay = socket;
    socket.on("open", () => {
      if (!contents.isDestroyed()) contents.send("ghostship-native:relay-state", true);
    });
    socket.on("message", (data) => {
      if (!contents.isDestroyed()) contents.send("ghostship-native:relay-message", decode(data));
    });
    socket.on("error", (error) => console.error("[codex-web] native relay error", error.message));
    socket.on("close", () => {
      if (nativeRelay !== socket) return;
      nativeRelay = undefined;
      if (!contents.isDestroyed()) contents.send("ghostship-native:relay-state", false);
      nativeRelayRetry = setTimeout(connectNativeRelay, 500);
    });
  }
  realElectron.ipcMain.on("ghostship-native:relay-open", (event) => {
    if (event.sender !== browserPrimaryWindow?.webContents) return;
    clearTimeout(nativeRelayRetry);
    const previous = nativeRelay;
    nativeRelay = undefined;
    previous?.close();
    connectNativeRelay();
  });
  realElectron.ipcMain.on("ghostship-native:relay-send", (event, message) => {
    if (event.sender === browserPrimaryWindow?.webContents && nativeRelay?.readyState === WebSocket.OPEN) {
      nativeRelay.send(encode(message));
    }
  });

  gateway.setBrowserFullscreenStateHandler((enabled) => {
    if (browserFullscreen === enabled) return;
    browserFullscreen = enabled;
    browserPrimaryWindow?.emit(
      enabled ? "enter-full-screen" : "leave-full-screen",
    );
  });

  gateway.setBrowserGuestFactory(async ({ browserTabId, conversationId }) => {
    const ownerWindow = new OriginalBrowserWindow({
      backgroundColor: "#ffffff",
      height: 720,
      show: false,
      skipTaskbar: true,
      webPreferences: {
        backgroundThrottling: false,
        contextIsolation: true,
        nodeIntegration: false,
        offscreen: true,
        partition: `persist:codex-web-browser-${crypto
          .createHash("sha256")
          .update(`${conversationId}\0${browserTabId}`)
          .digest("hex")}`,
        sandbox: true,
      },
      width: 1280,
    });
    ownerWindow.webContents.setWindowOpenHandler(({ url }) => {
      gateway.broadcastControl({ type: "open-external", url });
      return { action: "deny" };
    });
    await ownerWindow.loadURL("about:blank");
    return { ownerWindow, webContents: ownerWindow.webContents };
  });

  class WebBridgeBrowserWindow extends OriginalBrowserWindow {
    constructor(options = {}) {
      const webPreferences = { ...(options.webPreferences || {}) };
      const preloadName = webPreferences.preload
        ? path.basename(webPreferences.preload)
        : "";
      const isBrowserPrimary =
        preloadName === "preload.js" && !browserPrimaryWindow;
      if (isBrowserPrimary) {
        webPreferences.preload = path.join(__dirname, "combined-preload.cjs");
        webPreferences.sandbox = true;
        webPreferences.backgroundThrottling = false;
      }
      super({
        ...options,
        show: false,
        skipTaskbar: true,
        webPreferences,
      });
      if (isBrowserPrimary) {
        browserPrimaryWindow = this;
        this.webContents.on("render-process-gone", () => {
          clearTimeout(nativeRelayRetry);
          const previous = nativeRelay;
          nativeRelay = undefined;
          previous?.close();
        });
        this.on("closed", () => {
          clearTimeout(nativeRelayRetry);
          const previous = nativeRelay;
          nativeRelay = undefined;
          previous?.close();
          browserPrimaryWindow = undefined;
        });
      } else {
        gateway.registerAuxiliaryWindow(this, {
          modal: options.modal === true || Boolean(options.parent),
          title: options.title || "",
          transparent: options.transparent === true,
        });
      }
      console.log("[codex-web] upstream BrowserWindow created", {
        preload: preloadName || null,
        title: options.title || null,
      });
    }

    static getFocusedWindow() {
      return browserPrimaryWindow && !browserPrimaryWindow.isDestroyed()
        ? browserPrimaryWindow
        : OriginalBrowserWindow.getFocusedWindow();
    }

    loadURL(url, options) {
      // Use the same renderer origin that upstream accepts in development.
      // The packaged app:// handler belongs to the desktop shell; our native
      // relay host needs the gateway's initialized HTML as well as its assets.
      if (this === browserPrimaryWindow && new URL(url).protocol === "app:") {
        const target = new URL(`http://localhost:${process.env.CODEX_WEB_NATIVE_HOST_PORT || "5175"}/`);
        const source = new URL(url);
        target.search = source.search;
        target.hash = source.hash;
        return super.loadURL(target.href, options);
      }
      return super.loadURL(url, options);
    }

    isFullScreen() {
      return this === browserPrimaryWindow
        ? browserFullscreen
        : super.isFullScreen();
    }

    setFullScreen(enabled) {
      if (this !== browserPrimaryWindow) {
        return super.setFullScreen(enabled);
      }
      const next = enabled === true;
      if (browserFullscreen === next) return;
      browserFullscreen = next;
      gateway.broadcastControl({ type: "set-fullscreen", enabled: next });
      this.emit(next ? "enter-full-screen" : "leave-full-screen");
    }
  }

  const shell = new Proxy(realElectron.shell, {
    get(target, property, receiver) {
      if (property === "openExternal") {
        return async (url) => {
          gateway.broadcastControl({ type: "open-external", url });
        };
      }
      return Reflect.get(target, property, receiver);
    },
  });

  const menu = new Proxy(realElectron.Menu, {
    get(target, property, receiver) {
      if (property === "setApplicationMenu") {
        return (nextMenu) => {
          applicationMenu = nextMenu;
          return target.setApplicationMenu(nextMenu);
        };
      }
      if (property === "getApplicationMenu") {
        return () => target.getApplicationMenu() || applicationMenu || null;
      }
      return Reflect.get(target, property, receiver);
    },
  });

  const dialog = realElectron.dialog;
  dialog.showOpenDialog = async (...args) => {
    const options = args.length > 1 ? args[1] : args[0];
    console.log("[codex-web] forwarding native open dialog", {
      properties: options?.properties || [],
      title: options?.title || null,
    });
    return gateway.requestDialog("open", options || {});
  };
  dialog.showSaveDialog = async (...args) => {
    const options = args.length > 1 ? args[1] : args[0];
    return gateway.requestDialog("save", options || {});
  };
  dialog.showMessageBox = async (...args) => {
    const options = args.length > 1 ? args[1] : args[0];
    return gateway.requestDialog("message", options || {});
  };

  class WebBridgeNotification extends EventEmitter {
    static isSupported() {
      return true;
    }

    constructor(options = {}) {
      super();
      notificationCounter += 1;
      this.id = `notification-${notificationCounter}`;
      this.options = options;
    }

    show() {
      gateway.showNotification(this.id, this.options, (event) => {
        if (event.type === "close") {
          this.emit("close");
        } else if (event.actionIndex == null) {
          this.emit("click");
        } else {
          this.emit("action", {}, event.actionIndex);
        }
      });
    }

    close() {
      gateway.closeNotification(this.id);
      this.emit("close");
    }
  }

  const electronProxy = new Proxy(realElectron, {
    get(target, property, receiver) {
      if (property === "BrowserWindow") {
        return WebBridgeBrowserWindow;
      }
      if (property === "shell") {
        return shell;
      }
      if (property === "dialog") {
        return dialog;
      }
      if (property === "Menu") {
        return menu;
      }
      if (property === "Notification") {
        return WebBridgeNotification;
      }
      return Reflect.get(target, property, receiver);
    },
  });

  realElectron.app.on("web-contents-created", (_event, webContents) => {
    const pendingWebviews = [];
    webContents.on("will-attach-webview", (_event, _webPreferences, params) => {
      pendingWebviews.push({
        browserTabId:
          params["data-browser-sidebar-browser-tab-id"] ??
          params.attributes?.["data-browser-sidebar-browser-tab-id"],
        conversationId:
          params["data-browser-sidebar-conversation-id"] ??
          params.attributes?.["data-browser-sidebar-conversation-id"],
      });
    });
    webContents.on("did-attach-webview", (_event, guestWebContents) => {
      gateway.registerBrowserGuest(pendingWebviews.shift(), guestWebContents);
    });
    webContents.on("did-fail-load", (_event, code, description, url) => {
      console.error("[codex-web] upstream renderer failed to load", {
        code,
        description,
        url,
      });
    });
    webContents.on("render-process-gone", (_event, details) => {
      console.error("[codex-web] upstream renderer exited", details);
    });
  });

  Module._load = function load(request, parent, isMain) {
    if (
      request === "electron" &&
      parent?.filename &&
      !parent.filename.includes(`${path.sep}bridge${path.sep}`)
    ) {
      return electronProxy;
    }
    return originalLoad.call(this, request, parent, isMain);
  };
}

module.exports = { installElectronProxy };
