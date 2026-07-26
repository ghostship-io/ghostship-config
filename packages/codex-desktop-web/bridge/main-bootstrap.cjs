"use strict";

const crypto = require("node:crypto");
const childProcess = require("node:child_process");
const electron = require("electron");
const path = require("node:path");
const { createGateway } = require("./gateway.cjs");
const { installElectronProxy } = require("./electron-proxy.cjs");

function installCodexCliOverride() {
  const cliOverride = process.env.CODEX_CLI_PATH;
  if (!cliOverride) return;
  const originalSpawn = childProcess.spawn;
  childProcess.spawn = function spawn(command, args = [], options) {
    if (
      command !== cliOverride &&
      Array.isArray(args) &&
      args.includes("app-server")
    ) {
      return originalSpawn.call(this, cliOverride, args, options);
    }
    return originalSpawn.call(this, command, args, options);
  };
}

async function start() {
  process.env.CODEX_WEB_RELAY_SECRET ||= crypto.randomBytes(32).toString("hex");
  process.env.CODEX_WEB_PORT ||= "8214";
  process.env.CODEX_WEB_HOST ||= "0.0.0.0";
  process.env.CODEX_HOME ||= path.join(electron.app.getPath("home"), ".codex");
  process.env.CODEX_ELECTRON_DISABLE_QUIT_CONFIRMATION ||= "1";

  installCodexCliOverride();
  const gateway = await createGateway({
    appVersion: require("../package.json").version,
    host: process.env.CODEX_WEB_HOST,
    port: Number(process.env.CODEX_WEB_PORT),
    relaySecret: process.env.CODEX_WEB_RELAY_SECRET,
    webviewRoot: path.join(__dirname, "..", "webview"),
  });

  installElectronProxy(electron, gateway);
  electron.app.whenReady().then(() => {
    console.log("[codex-web] Electron ready");
  });
  require("../.vite/build/early-bootstrap.js");
}

start().catch((error) => {
  console.error("[codex-web] startup failed", error);
  process.exitCode = 1;
});
