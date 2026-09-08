import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { chromium } from "playwright-core";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const { transformIndex } = createRequire(import.meta.url)("../bridge/gateway.cjs");

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

async function dispatchInstallEvent(page, outcome) {
  return page.evaluate((choice) => {
    window.__codexPromptCalls = 0;
    const event = new Event("beforeinstallprompt", {
      cancelable: true,
    });
    Object.defineProperties(event, {
      prompt: {
        value: async () => {
          window.__codexPromptCalls += 1;
        },
      },
      userChoice: {
        value: Promise.resolve({ outcome: choice, platform: "web" }),
      },
    });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  }, outcome);
}

test("Codex offers and invokes Chrome PWA installation", async () => {
  const register = readFileSync(
    path.join(packageRoot, "bridge", "browser", "pwa-register.js"),
  );
  const manifestLink = transformIndex('<script type="module">', {})
    .match(/<link rel="manifest"[^>]+>/)[0];
  const server = createServer((request, response) => {
    if (request.url === '/manifest.webmanifest') {
      const authorized = request.headers.cookie?.includes('acceptance_access=allowed');
      response.writeHead(authorized ? 200 : 401, { 'content-type': 'application/manifest+json' });
      response.end(JSON.stringify(authorized ? { name: 'Authenticated Codex', start_url: '/', display: 'standalone' } : {}));
      return;
    }
    if (request.url === "/pwa-register.js") {
      response.writeHead(200, {
        "content-type": "text/javascript; charset=utf-8",
      });
      response.end(register);
      return;
    }
    response.writeHead(200, { "content-type": "text/html; charset=utf-8",
      'set-cookie': 'acceptance_access=allowed; Path=/; SameSite=Lax; HttpOnly' });
    response.end(`<!doctype html>
      <html><head>${manifestLink}</head><body>
        <main>Codex</main>
        <div data-codex-notification-prompt
          style="position:fixed;top:20px;right:20px;height:60px">
          Enable notifications
        </div>
        <script src="/pwa-register.js"></script>
      </body></html>`);
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
    const devtools = await page.context().newCDPSession(page);
    const manifest = await devtools.send('Page.getAppManifest');
    assert.equal(JSON.parse(manifest.data).name, 'Authenticated Codex',
      'Chrome must include access cookies when fetching the installation manifest');

    assert.equal(await dispatchInstallEvent(page, "accepted"), true);
    const offer = page.getByRole("status", { name: "Install Codex" });
    await offer.waitFor();
    assert.match(await offer.innerText(), /Install Codex for quicker access/);
    const stackedPosition = await page.evaluate(() => {
      const notification = document.querySelector(
        "[data-codex-notification-prompt]",
      );
      const install = document.querySelector("[data-codex-install-prompt]");
      return {
        notificationBottom: notification.getBoundingClientRect().bottom,
        installTop: install.getBoundingClientRect().top,
      };
    });
    assert.ok(
      stackedPosition.installTop >= stackedPosition.notificationBottom + 11,
    );
    await page.evaluate(() =>
      document.querySelector("[data-codex-install-prompt]").remove(),
    );
    await offer.waitFor();
    await page.evaluate(() =>
      document.querySelector("[data-codex-notification-prompt]").remove(),
    );
    await page.waitForFunction(
      (previousTop) =>
        document
          .querySelector("[data-codex-install-prompt]")
          .getBoundingClientRect().top < previousTop,
      stackedPosition.installTop,
    );
    await offer.getByRole("button", { name: "Install" }).click();
    await page.waitForFunction(
      () => document.documentElement.dataset.codexInstallPrompt === "requested",
    );
    assert.equal(await page.evaluate(() => window.__codexPromptCalls), 1);
    await offer.waitFor({ state: "detached" });

    assert.equal(await dispatchInstallEvent(page, "dismissed"), true);
    await offer.waitFor();
    await offer.getByRole("button", { name: "Dismiss" }).click();
    await offer.waitFor({ state: "detached" });
    assert.equal(
      await page.evaluate(
        () => localStorage.getItem("codex:pwa-install-dismissed"),
      ),
      "true",
    );

    assert.equal(await dispatchInstallEvent(page, "dismissed"), true);
    assert.equal(await offer.count(), 0);
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
});

test('background push wakes the service worker and displays a notification', async () => {
  const worker = readFileSync(path.join(packageRoot, 'bridge/browser/sw.js'));
  const server = createServer((request, response) => {
    response.writeHead(200, { 'content-type': request.url === '/sw.js' ? 'text/javascript' : 'text/html' });
    response.end(request.url === '/sw.js' ? worker : '<script>navigator.serviceWorker.register("/sw.js")</script>');
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({ executablePath: findBrowserExecutable(), headless: true });
  try {
    const context = await browser.newContext({ permissions: ['notifications'] });
    const page = await context.newPage();
    const cdp = await context.newCDPSession(page);
    let registrationId;
    cdp.on('ServiceWorker.workerRegistrationUpdated', ({ registrations }) => {
      registrationId = registrations.find((r) => r.scopeURL === origin + '/')?.registrationId || registrationId;
    });
    await cdp.send('ServiceWorker.enable');
    await page.goto(origin);
    await page.evaluate(() => navigator.serviceWorker.ready);
    assert.ok(registrationId);
    await cdp.send('ServiceWorker.stopAllWorkers');
    await cdp.send('ServiceWorker.deliverPushMessage', { origin, registrationId,
      data: JSON.stringify({ notificationId: 'background-proof', notificationTag: 'upstream-turn', navigationPath: '/thread/shared', options: { title: 'Task finished', body: 'Available on every device' } }) });
    await page.waitForFunction(async () => (await (await navigator.serviceWorker.ready).getNotifications()).length === 1);
    const shown = await page.evaluate(async () => {
      const [n] = await (await navigator.serviceWorker.ready).getNotifications();
      const result = { title: n.title, body: n.body, tag: n.tag, data: n.data }; n.close(); return result;
    });
    assert.deepEqual(shown, { title: 'Task finished', body: 'Available on every device',
      tag: 'codex-upstream-turn', data: { codexNotificationId: 'background-proof', navigationPath: '/thread/shared' } });
  } finally { await browser.close(); await new Promise((resolve) => server.close(resolve)); }
});
