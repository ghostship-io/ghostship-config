import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";
import { WebSocketServer } from "ws";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function findBrowserExecutable() {
  if (process.env.CODEX_BROWSER_EXECUTABLE) {
    return process.env.CODEX_BROWSER_EXECUTABLE;
  }
  const roots = [
    process.env.PLAYWRIGHT_BROWSERS_PATH,
    path.join(process.env.HOME || "", ".agent-browser", "browsers"),
    path.join(process.env.HOME || "", ".cache", "ms-playwright"),
  ].filter(Boolean);
  const names = new Set(["chrome-wrapper", "chrome", "chromium", "headless_shell"]);
  for (const root of roots) {
    if (!existsSync(root)) continue;
    const pending = [root];
    while (pending.length > 0) {
      const current = pending.shift();
      for (const entry of readdirSync(current, { withFileTypes: true })) {
        const target = path.join(current, entry.name);
        if (statSync(target).isDirectory()) pending.push(target);
        else if (names.has(entry.name)) return target;
      }
    }
  }
  throw new Error(
    "set CODEX_BROWSER_EXECUTABLE to a Chrome or Chromium executable",
  );
}

test("browser-native dialogs preserve modal and window lifecycles", async () => {
  const shim = readFileSync(
    path.join(packageRoot, "bridge", "browser", "electron-shim.js"),
  );
  const browserMessages = [];
  let resolveAuxiliaryClose;
  const auxiliaryClose = new Promise((resolve) => {
    resolveAuxiliaryClose = resolve;
  });
  const sockets = new Set();
  const server = createServer((request, response) => {
    if (request.url === "/electron-shim.js") {
      response.writeHead(200, { "content-type": "text/javascript; charset=utf-8" });
      response.end(shim);
      return;
    }
    if (request.url?.startsWith("/__bridge/files")) {
      response.writeHead(200, { "content-type": "application/json; charset=utf-8" });
      response.end(JSON.stringify({
        entries: [{ name: "project", type: "directory" }],
        parent: null,
        path: "/workspace",
      }));
      return;
    }
    response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    response.end(`<!doctype html>
      <html><body>
        <div id="project-modal" role="dialog" aria-label="Create project">
          <h1>Create project</h1>
          <p id="project-state">open</p>
        </div>
        <button id="fullscreen-command" role="menuitem">
          Toggle Full Screen
        </button>
        <script>
          for (const type of ["pointerdown", "mousedown", "click"]) {
            document.addEventListener(type, (event) => {
              const modal = document.querySelector("#project-modal");
              if (modal && !modal.contains(event.target)) {
                modal.remove();
              }
            }, true);
          }
        </script>
        <script src="/electron-shim.js"></script>
      </body></html>`);
  });
  const webSockets = new WebSocketServer({ noServer: true });
  server.on("upgrade", (request, socket, head) => {
    webSockets.handleUpgrade(request, socket, head, (client) => {
      sockets.add(client);
      client.on("close", () => sockets.delete(client));
      client.on("message", (payload) => {
        const message = JSON.parse(payload.toString());
        browserMessages.push(message);
        if (
          message.type === "auxiliary-window-command" &&
          message.windowId === "about" &&
          message.command === "close"
        ) {
          resolveAuxiliaryClose();
        }
      });
      client.send(JSON.stringify({ type: "hello" }));
      webSockets.emit("connection", client, request);
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({
    executablePath: findBrowserExecutable(),
    headless: true,
  });
  try {
    const page = await browser.newPage();
    await page.goto(origin);
    await assert.doesNotReject(async () => {
      await page.waitForFunction(() => window.__codexElectronModule, null, {
        timeout: 5_000,
      });
    });
    for (const socket of sockets) {
      socket.send(JSON.stringify({
        action: "show-dialog",
        dialogId: "project-folder",
        dialogType: "open",
        options: {
          defaultPath: "/workspace",
          properties: ["openDirectory"],
          title: "Select Project Root",
        },
        type: "control",
      }));
    }
    await page.getByRole("heading", { name: "Select Project Root" }).waitFor();
    assert.equal(
      await page.locator(
        '#project-modal > [data-codex-web-dialog=""]',
      ).count(),
      1,
    );
    await page.getByRole("button", { name: "Select this folder" }).click();
    await page
      .locator('[data-codex-web-dialog=""]')
      .waitFor({ state: "detached" });
    assert.equal(await page.locator("#project-modal").count(), 1);
    assert.equal(
      await page.getByRole("heading", { name: "Create project" }).isVisible(),
      true,
    );
    for (const socket of sockets) {
      socket.send(JSON.stringify({
        action: "auxiliary-window-state",
        bounds: { height: 250, width: 400 },
        modal: true,
        title: "About ChatGPT",
        transparent: false,
        type: "control",
        visible: true,
        windowId: "about",
      }));
    }
    await page.getByRole("button", { name: "Close About ChatGPT" }).click();
    await auxiliaryClose;
    assert.ok(
      browserMessages.some(
        (message) =>
          message.type === "auxiliary-window-command" &&
          message.windowId === "about" &&
          message.command === "close",
      ),
    );
    for (const socket of sockets) {
      socket.send(JSON.stringify({
        action: "auxiliary-window-state",
        bounds: { height: 300, width: 300 },
        modal: false,
        title: "Codex",
        transparent: true,
        type: "control",
        visible: true,
        windowId: "pet",
      }));
    }
    const pet = page.locator('[data-codex-auxiliary-window="pet"]');
    await pet.waitFor();
    assert.equal(await pet.evaluate((element) => {
      return getComputedStyle(element).pointerEvents;
    }), "none");
    await page.locator("#fullscreen-command").click();
    await page.waitForFunction(
      () =>
        Boolean(document.fullscreenElement) ||
        document.documentElement.dataset.codexWebFullscreen === "true",
    );
    await page.locator("#fullscreen-command").click();
    await page.waitForFunction(
      () =>
        !document.fullscreenElement &&
        document.documentElement.dataset.codexWebFullscreen !== "true",
    );
  } finally {
    await browser.close();
    for (const socket of sockets) socket.close();
    webSockets.close();
    await new Promise((resolve) => server.close(resolve));
  }
});
