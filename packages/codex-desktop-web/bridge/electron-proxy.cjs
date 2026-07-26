"use strict";

const Module = require("node:module");
const path = require("node:path");

function installElectronProxy(realElectron, gateway) {
  const originalLoad = Module._load;
  const OriginalBrowserWindow = realElectron.BrowserWindow;

  class WebBridgeBrowserWindow extends OriginalBrowserWindow {
    constructor(options = {}) {
      const webPreferences = { ...(options.webPreferences || {}) };
      const preloadName = webPreferences.preload
        ? path.basename(webPreferences.preload)
        : "";
      if (preloadName === "preload.js") {
        webPreferences.preload = path.join(__dirname, "combined-preload.cjs");
        webPreferences.sandbox = false;
      }
      super({
        ...options,
        show: false,
        skipTaskbar: true,
        webPreferences,
      });
      console.log("[codex-web] upstream BrowserWindow created", {
        preload: preloadName || null,
        title: options.title || null,
      });
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
      return Reflect.get(target, property, receiver);
    },
  });

  realElectron.app.on("web-contents-created", (_event, webContents) => {
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
