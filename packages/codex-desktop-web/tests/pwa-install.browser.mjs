import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

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
  const server = createServer((request, response) => {
    if (request.url === "/pwa-register.js") {
      response.writeHead(200, {
        "content-type": "text/javascript; charset=utf-8",
      });
      response.end(register);
      return;
    }
    response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    response.end(`<!doctype html>
      <html><body>
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
