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

test("embedded browser resizes and releases keyboard focus to application controls", async () => {
  const browser = await chromium.launch({ executablePath: findBrowserExecutable(), headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent('<div id="host" style="position:relative;width:600px;height:400px"></div><button id="outside">Application action</button>');
    await page.evaluate(() => {
      window.messages = [];
      window.__codexWebTransport = {
        send: (message) => window.messages.push(message),
        onControl: (callback) => { window.control = callback; },
        onMessageFromView: () => {},
      };
      window.clicks = 0;
      document.querySelector('#outside').onclick = () => { window.clicks++; };
    });
    await page.addScriptTag({ path: path.join(packageRoot, 'bridge/browser/webview-bridge.js') });
    await page.evaluate(() => {
      window.shortcutKeys = [];
      window.addEventListener('keydown', (event) => {
        window.shortcutKeys.push(event.key);
        if (event.key.length === 1) document.querySelector('#outside').focus();
      }, true);
    });
    await page.evaluate(() => {
      const view = document.createElement('webview');
      view.setAttribute('data-browser-sidebar-conversation-id', 'conversation');
      view.setAttribute('data-browser-sidebar-browser-tab-id', 'tab');
      document.querySelector('#host').append(view);
    });
    await page.waitForFunction(() => window.messages.some((m) => m.type === 'browser-surface-subscribe'));
    await page.evaluate(() => window.control({ action: 'browser-surface-state', conversationId: 'conversation', browserTabId: 'tab', generation: 1, state: {} }));
    await page.waitForFunction(() => window.messages.some((m) => m.command === 'resize' && m.width === 600 && m.height === 400));
    const view = page.locator('[data-codex-webview-bridge]');
    await view.click();
    await page.keyboard.press('Control+a');
    await page.keyboard.type('browser-input');
    const inputs = await page.evaluate(() => window.messages.filter((m) => m.command === 'input').map((m) => m.input));
    assert.ok(inputs.some((input) => input.keyCode === 'a' && input.modifiers?.includes('control')));
    assert.equal(inputs.filter((input) => input.type === 'char').map((input) => input.keyCode).join(''), 'browser-input');
    assert.deepEqual(await page.evaluate(() => window.shortcutKeys), []);
    await page.evaluate(() => {
      document.body.tabIndex = 0;
      const overlay = document.createElement('div');
      overlay.id = 'cursor-overlay';
      overlay.setAttribute('data-browser-sidebar-webview', 'conversation\0tab');
      overlay.style.cssText = 'position:absolute;left:8px;top:8px;width:600px;height:400px';
      document.body.append(overlay);
    });
    await page.locator('#cursor-overlay').click();
    assert.equal(await view.evaluate((element) => document.activeElement === element), true);
    await page.keyboard.type('overlay-input');
    assert.deepEqual(await page.evaluate(() => window.shortcutKeys), []);
    await page.locator('#cursor-overlay').evaluate((element) => element.remove());
    await page.getByRole('button', { name: 'Application action' }).focus();
    const count = await page.evaluate(() => window.messages.length);
    await page.keyboard.press('Space');
    assert.equal(await page.evaluate(() => window.clicks), 1);
    assert.equal(await page.evaluate(() => window.messages.length), count);
    await view.click();
    await view.evaluate((element) => { element.style.display = 'none'; });
    await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(() => window.messages.at(-1)?.input?.keyCode === 'Enter'), false);
  } finally {
    await browser.close();
  }
});

test("mobile drawer preserves chat width and follows the visible viewport", async () => {
  const browser = await chromium.launch({ executablePath: findBrowserExecutable(), headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 412, height: 780 } });
    await page.setContent(`<style>
      * { box-sizing: border-box; } body { margin: 0; }
      #root, #layout { height: 100%; } #layout { display: flex; position: relative; isolation: isolate; }
      aside { width: 240px; flex-shrink: 0; overflow: hidden; }
      main { flex: 1; display: flex; flex-direction: column; }
      #composer { margin-top: auto; height: 100px; }
    </style><div id="root"><div id="layout" style="--codex-window-zoom:1;height:calc(100vh / var(--codex-window-zoom))">
      <aside class="app-shell-left-panel"><button data-app-action-sidebar-thread-row>Shared chat</button></aside>
      <main data-app-shell-main-surface><button aria-label="Seitenleiste ausblenden" aria-controls="app-shell-sidebar" aria-expanded="true">Hide</button><input id="composer"></main>
    </div></div>`);
    await page.evaluate(() => {
      document.querySelector('[aria-controls="app-shell-sidebar"]').onclick = () => {
        document.querySelector('aside').style.width = '0px';
      };
    });
    await page.addScriptTag({ path: path.join(packageRoot, 'bridge/browser/mobile-layout.js') });
    await page.getByRole('button', { name: 'Close sidebar' }).waitFor();
    assert.equal(await page.locator('main').evaluate((e) => e.inert), true);
    await page.keyboard.press('Tab');
    assert.equal(await page.locator('main').evaluate((e) => e.contains(document.activeElement)), false);
    assert.equal((await page.locator('main').boundingBox()).width, 412);
    await page.getByRole('button', { name: 'Shared chat' }).click();
    await page.getByRole('button', { name: 'Close sidebar' }).waitFor({ state: 'hidden' });
    assert.equal(await page.locator('main').evaluate((e) => e.inert), false);
    await page.evaluate(() => { document.querySelector('aside').style.width = '240px'; });
    await page.getByRole('button', { name: 'Close sidebar' }).click({ position: { x: 390, y: 100 } });
    await page.getByRole('button', { name: 'Close sidebar' }).waitFor({ state: 'hidden' });
    await page.evaluate(() => {
      Object.defineProperty(window.visualViewport, 'height', { configurable: true, value: 350 });
      window.visualViewport.dispatchEvent(new Event('resize'));
    });
    assert.equal((await page.locator('#root').boundingBox()).height, 350);
    const composer = await page.locator('#composer').boundingBox();
    assert.ok(composer.y + composer.height <= 350);
    await page.setViewportSize({ width: 1440, height: 1000 });
    assert.equal(await page.locator('aside').evaluate((e) => getComputedStyle(e).position), 'static');
  } finally { await browser.close(); }
});

test("browser-native dialogs preserve modal and window lifecycles", async () => {
  const shim = readFileSync(
    path.join(packageRoot, "bridge", "browser", "electron-shim.js"),
  );
  const browserMessages = [];
  let resolveAuxiliaryClose;
  const auxiliaryClose = new Promise((resolve) => {
    resolveAuxiliaryClose = resolve;
  });
  let resolveAuxiliaryEscape;
  const auxiliaryEscape = new Promise((resolve) => {
    resolveAuxiliaryEscape = resolve;
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
      const target = new URL(request.url, 'http://localhost').searchParams.get('path');
      setTimeout(() => response.end(JSON.stringify({
        entries: [{ name: "project", type: "directory" }],
        parent: null,
        path: target,
      })), target === '/workspace/project' ? 300 : 0);
      return;
    }
    response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    response.end(`<!doctype html>
      <html><body>
        <div id="project-modal" role="dialog" aria-label="Create project"
          style="position:fixed;left:130px;top:64px;width:520px;height:310px;overflow:hidden;contain:paint;border-radius:20px">
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
        if (message.type === "post-message-port") {
          client.send(JSON.stringify({ type: "port-message", portId: message.portId,
            data: message.message }));
        }
        if (message.type === "invoke" && message.channel === "codex_desktop:binary-test") {
          client.send(JSON.stringify({
            type: "result", requestId: message.requestId, ok: true,
            result: { bytes: { __codexBridgeType: "uint8array", base64: "AAF//w==" },
              buffer: { __codexBridgeType: "arraybuffer", base64: "AAF//w==" } },
          }));
        }
        if (
          message.type === "auxiliary-window-command" &&
          message.windowId === "about" &&
          message.command === "close"
        ) {
          resolveAuxiliaryClose();
        }
        if (
          message.type === "auxiliary-window-command" &&
          message.windowId === "new-window" &&
          message.command === "close"
        ) {
          client.send(JSON.stringify({
            action: "auxiliary-window-state",
            type: "control",
            visible: false,
            windowId: "new-window",
          }));
          resolveAuxiliaryEscape();
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
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto(origin);
    await assert.doesNotReject(async () => {
      await page.waitForFunction(() => window.__codexElectronModule, null, {
        timeout: 5_000,
      });
    });
    const otherTab = await page.context().newPage();
    await otherTab.goto(origin);
    assert.equal(await page.evaluate(() => localStorage.getItem('codex-web-device-id')),
      await otherTab.evaluate(() => localStorage.getItem('codex-web-device-id')));
    for (const [index, tab] of [page, otherTab].entries()) {
      assert.equal(await tab.evaluate((value) => new Promise((resolve) => {
        const channel = new MessageChannel();
        channel.port1.onmessage = (event) => resolve(event.data);
        window.__codexElectronModule.ipcRenderer.postMessage('tab-test', value, [channel.port2]);
      }), index), index);
    }
    const portIds = browserMessages.filter((message) => message.type === 'post-message-port')
      .map((message) => message.portId);
    assert.equal(new Set(portIds).size, 2, 'tabs sharing storage must have distinct native ports');
    await otherTab.close();
    await page.evaluate(() => {
      window.projectEvents = [];
      window.documentMarker = true;
      window.__codexElectronModule.ipcRenderer.on('codex_desktop:message-for-view',
        (_event, message) => window.projectEvents.push(message.type));
    });
    for (const socket of sockets) {
      if (socket.readyState === 1) socket.send(JSON.stringify({
        type: 'control', action: 'project-state-changed',
      }));
    }
    await page.waitForFunction(() => window.projectEvents.length === 2);
    assert.deepEqual(await page.evaluate(() => window.projectEvents),
      ['global-state-updated', 'workspace-root-options-updated']);
    assert.equal(await page.evaluate(() => window.documentMarker), true);
    assert.deepEqual(await page.evaluate(async () => {
      const value = await window.__codexElectronModule.ipcRenderer.invoke("codex_desktop:binary-test");
      return { bytes: value.bytes instanceof Uint8Array ? [...value.bytes] : null,
        buffer: value.buffer instanceof ArrayBuffer ? [...new Uint8Array(value.buffer)] : null };
    }), { bytes: [0, 1, 127, 255], buffer: [0, 1, 127, 255] });
    assert.deepEqual(await page.evaluate(() => {
      window.__codexElectronModule.contextBridge.exposeInMainWorld("electronBridge", {
        showContextMenu: () => { throw new Error("native menu must not run"); },
        getBuildFlavor: () => "prod",
      });
      return { nativeMenu: typeof window.electronBridge.showContextMenu,
        buildFlavor: window.electronBridge.getBuildFlavor() };
    }), { nativeMenu: "undefined", buildFlavor: "prod" });
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
    assert.doesNotMatch(await page.locator('[data-codex-notification-prompt]').innerText(), /object Event/);
    await page.getByRole("heading", { name: "Select Project Root" }).waitFor();
    assert.equal(await page.locator('[data-codex-web-dialog]').evaluate(
      (element) => element.matches(':modal')), true);
    for (const size of [{ width: 780, height: 437 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(size);
      const select = page.getByRole("button", { name: "Select this folder" });
      const bounds = await select.boundingBox();
      assert.ok(bounds.x >= 0 && bounds.y >= 0 &&
        bounds.x + bounds.width <= size.width && bounds.y + bounds.height <= size.height);
      await select.click({ trial: true });
      await page.getByRole("button", { name: /project$/ }).click({ trial: true });
    }
    assert.equal(
      await page.locator(
        '#project-modal > [data-codex-web-dialog=""]',
      ).count(),
      1,
    );
    await page.getByRole("button", { name: /project$/ }).click();
    assert.equal(await page.getByRole("button", { name: "Select this folder" }).isDisabled(), true);
    await page.getByRole("button", { name: "Select this folder" }).click();
    assert.ok(browserMessages.some((message) => message.type === 'dialog-result' &&
      message.result?.filePaths?.[0] === '/workspace/project'));
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
    await page
      .getByRole("dialog", { name: "About ChatGPT" })
      .waitFor({ state: "detached" });
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
        bounds: { height: 700, width: 1200 },
        modal: false,
        title: "ChatGPT",
        transparent: false,
        type: "control",
        visible: true,
        windowId: "new-window",
      }));
    }
    const newWindow = page.getByRole("dialog", { name: "ChatGPT" });
    await newWindow.waitFor();
    assert.equal(await newWindow.evaluate((element) => {
      return document.activeElement === element;
    }), true);
    await page.locator("#fullscreen-command").focus();
    await page.keyboard.press("Escape");
    await auxiliaryEscape;
    await newWindow.waitFor({ state: "detached" });
    assert.equal(await page.locator("#fullscreen-command").evaluate((element) => {
      return document.activeElement === element;
    }), true);
    assert.ok(
      browserMessages.some(
        (message) =>
          message.type === "auxiliary-window-command" &&
          message.windowId === "new-window" &&
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
