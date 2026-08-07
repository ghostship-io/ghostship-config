import assert from "node:assert/strict";
import {
  existsSync,
  mkdtempSync,
  readdirSync,
  rmSync,
  statSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright-core";

const targetUrl = process.env.CODEX_WEB_URL || "http://127.0.0.1:8214";
const projectName = `Browser acceptance ${Date.now()}`;

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

function recordPageErrors(page, errors) {
  page.on("pageerror", (error) => errors.push(error.message));
}

async function waitForApp(page) {
  const currentUrl = new URL(page.url());
  if (currentUrl.origin !== new URL(targetUrl).origin) {
    try {
      await page.goto(targetUrl, { waitUntil: "domcontentloaded" });
    } catch (error) {
      if (!String(error).includes("net::ERR_ABORTED")) throw error;
    }
  }
  await page.waitForFunction(
    () =>
      document.querySelector('[aria-label="Add new project"]') ||
      document.body.innerText.includes("What should we build?"),
    undefined,
    {
      timeout: 30_000,
    },
  );
}

async function openAppMenu(page, name) {
  await page.getByRole("menuitem", { exact: true, name }).click();
  const menu = page.locator('[role="menu"]:visible').last();
  await menu.waitFor();
  await menu.getByRole("menuitem").first().waitFor();
  await page.keyboard.press("Escape");
}

async function ensureProjectsExpanded(page) {
  const toggle = page.getByRole("button", {
    exact: true,
    name: "Projects",
  });
  await toggle.waitFor();
  if ((await toggle.getAttribute("aria-expanded")) !== "true") {
    await toggle.click();
  }
  await page.waitForFunction(
    () => {
      const toggles = document.querySelectorAll(
        "[data-app-action-sidebar-section-toggle]",
      );
      return [...toggles].some(
        (element) =>
          element.textContent?.trim().startsWith("Projects") &&
          element.getAttribute("aria-expanded") === "true",
      );
    },
  );
}

async function removeProject(page, name = projectName) {
  const actions = page.getByRole("button", {
    name: `Project actions for ${name}`,
  });
  if (await actions.count() === 0) return;
  const action = actions.first();
  await action.focus();
  await page.keyboard.press("Enter");
  const remove = page.getByRole("menuitem", {
    name: /^Remove(?: project)?$/i,
  });
  await remove.waitFor();
  await remove.click();
  const confirm = page.getByRole("button", { name: /Remove|Delete/i }).last();
  if (await confirm.isVisible().catch(() => false)) await confirm.click();
  await actions.first().waitFor({
    state: "detached",
    timeout: 15_000,
  });
}

async function removeAcceptanceProjects(page) {
  await ensureProjectsExpanded(page);
  for (let remaining = 25; remaining > 0; remaining -= 1) {
    const action = page
      .getByRole("button", {
        name: /^Project actions for Browser acceptance /,
      })
      .first();
    if ((await action.count()) === 0) return;
    const label = await action.getAttribute("aria-label");
    assert.ok(label);
    await removeProject(page, label.replace(/^Project actions for /, ""));
  }
  assert.fail("too many stale browser acceptance projects");
}

const browserExecutable = findBrowserExecutable();
const profileDirectory = mkdtempSync(
  path.join(os.tmpdir(), "codex-web-acceptance-"),
);
const androidContextOptions = {
  deviceScaleFactor: 2.625,
  hasTouch: true,
  isMobile: true,
  userAgent:
    "Mozilla/5.0 (Linux; Android 15; Pixel 9 Pro) AppleWebKit/537.36 " +
    "(KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36",
  viewport: { height: 915, width: 412 },
};
const pwaContext = await chromium.launchPersistentContext(profileDirectory, {
  ...androidContextOptions,
  executablePath: browserExecutable,
  headless: true,
});
const secondaryBrowser = await chromium.launch({
  executablePath: browserExecutable,
  headless: true,
});
const desktopContext = await secondaryBrowser.newContext({
  viewport: { height: 1000, width: 1440 },
});
const contextB = await secondaryBrowser.newContext({
  ...androidContextOptions,
});
const pwaPage = pwaContext.pages()[0] || (await pwaContext.newPage());
const pageA = await desktopContext.newPage();
const pageB = await contextB.newPage();
const errors = [];
recordPageErrors(pwaPage, errors);
recordPageErrors(pageA, errors);
recordPageErrors(pageB, errors);

try {
  await Promise.all([
    waitForApp(pwaPage),
    waitForApp(pageA),
    waitForApp(pageB),
  ]);
  await removeAcceptanceProjects(pageA);
  await pageA.waitForTimeout(2_000);
  await Promise.all([
    waitForApp(pwaPage),
    waitForApp(pageA),
    waitForApp(pageB),
  ]);

  const manifestResponse = await pwaPage.evaluate(async () => {
    const response = await fetch("/manifest.webmanifest");
    return {
      contentType: response.headers.get("content-type"),
      manifest: await response.json(),
    };
  });
  const { manifest } = manifestResponse;
  assert.match(manifestResponse.contentType, /^application\/manifest\+json\b/);
  assert.equal(manifest.id, "/");
  assert.equal(manifest.scope, "/");
  assert.equal(manifest.start_url, "/");
  assert.equal(manifest.display, "standalone");
  assert.equal(manifest.prefer_related_applications, false);
  assert.deepEqual(
    manifest.icons.map(({ purpose, sizes }) => `${sizes}:${purpose}`),
    [
      "192x192:any",
      "512x512:any",
      "192x192:maskable",
      "512x512:maskable",
    ],
  );
  await pwaPage.evaluate(async () => {
    await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller) location.reload();
  });
  await pwaPage.waitForFunction(
    () => navigator.serviceWorker.controller,
    null,
    { timeout: 15_000 },
  );
  const devtools = await pwaContext.newCDPSession(pwaPage);
  const installOffer = pwaPage.locator("[data-codex-install-prompt]");
  await installOffer.waitFor();
  let installabilityErrors = [];
  for (let remaining = 30; remaining > 0; remaining -= 1) {
    ({ installabilityErrors } = await devtools.send(
      "Page.getInstallabilityErrors",
    ));
    if (installabilityErrors.length === 0) break;
    await pwaPage.waitForTimeout(500);
  }
  assert.deepEqual(installabilityErrors, []);
  await installOffer.getByRole("button", { name: "Install" }).waitFor();
  await installOffer.getByRole("button", { name: "Dismiss" }).click();
  await installOffer.waitFor({ state: "detached" });
  console.log(
    "ok PWA manifest, worker, Chrome installability, and install offer",
  );

  await pwaContext.grantPermissions(["notifications"], {
    origin: new URL(targetUrl).origin,
  });
  const notificationResult = await pwaPage.evaluate(async () => {
    const registration = await navigator.serviceWorker.ready;
    await registration.showNotification("Codex browser acceptance", {
      body: "Service-worker notification test",
      tag: "codex-browser-acceptance",
    });
    const notifications = await registration.getNotifications({
      tag: "codex-browser-acceptance",
    });
    notifications.forEach((notification) => notification.close());
    return {
      count: notifications.length,
      permission: Notification.permission,
    };
  });
  assert.equal(notificationResult.permission, "granted");
  assert.equal(notificationResult.count, 1);
  console.log("ok notification permission and service-worker delivery");
  const notificationPromptDismiss = pageA.getByRole("button", {
    name: "Not now",
  });
  if (await notificationPromptDismiss.isVisible().catch(() => false)) {
    await notificationPromptDismiss.click();
  }
  for (const menuName of ["File", "Edit", "View", "Help"]) {
    await openAppMenu(pageA, menuName);
  }
  for (const buttonName of ["Open profile menu", "Open help menu"]) {
    await pageA.getByRole("button", { name: buttonName }).click();
    await pageA.getByRole("menu").waitFor();
    await pageA.keyboard.press("Escape");
  }
  console.log("ok application, profile, and help dropdowns");

  await pageA.getByRole("button", { exact: true, name: "Scheduled" }).click();
  await pageA.getByRole("heading", { name: "Scheduled tasks" }).waitFor();
  await pageA.getByRole("button", { exact: true, name: "Create" }).waitFor();
  await pageA.getByRole("button", { name: "Back" }).click();
  await pageA.getByRole("button", { name: "Add new project" }).waitFor();
  console.log("ok scheduled-task navigation and creation entrypoint");

  await pageA
    .getByRole("button", { name: "Add new project" })
    .dispatchEvent("click");
  await pageA.getByRole("heading", { name: "Create project" }).waitFor();
  await pageA.getByRole("textbox", { name: "Project name" }).fill(projectName);
  await pageA.getByRole("button", { name: "Choose source folders" }).click();
  await pageA.getByRole("heading", { name: "Select Project Root" }).waitFor();
  assert.ok(
    await pageA.locator(
      '[role="dialog"] [data-codex-web-dialog=""]',
    ).count(),
  );
  await pageA.getByRole("button", { name: "Select this folder" }).click();
  await pageA.getByRole("heading", { name: "Create project" }).waitFor();
  await pageA.getByRole("button", { name: "Create project" }).click();
  await Promise.all([
    ensureProjectsExpanded(pageA),
    ensureProjectsExpanded(pageB),
  ]);
  await Promise.all([
    pageA
      .getByRole("button", {
        exact: true,
        name: projectName,
      })
      .first()
      .waitFor({ timeout: 20_000 }),
    pageB
      .getByRole("button", {
        exact: true,
        name: projectName,
      })
      .first()
      .waitFor({ timeout: 20_000 }),
  ]);
  console.log("ok project creation, folder selection, and multi-device sync");

  await pageA.getByRole("button", {
    name: `Start new chat in ${projectName}`,
  }).click();
  const modelButton = pageA.locator("button:visible").filter({
    hasText: /(?:5\.\d|GPT|Ollama)/,
  }).last();
  await modelButton.click();
  const modelMenu = pageA.getByRole("menu").last();
  await modelMenu.getByRole("menuitem").first().waitFor();
  await modelMenu.getByText("5.6 Sol", { exact: true }).click();
  const providerMenu = pageA.getByRole("menu").last();
  await providerMenu.getByText(/Ollama/i).first().waitFor();
  assert.match(await providerMenu.innerText(), /Ollama/i);
  await pageA.keyboard.press("Escape");
  console.log("ok model dropdown and Ollama model availability");

  await pageA.getByRole("menuitem", { exact: true, name: "View" }).click();
  await pageA.getByRole("menuitem", { name: /Terminal/i }).click();
  await pageA.locator(".xterm").first().waitFor();
  await pageA.getByRole("menuitem", { exact: true, name: "Help" }).click();
  await pageA.getByRole("menuitem", { name: "About ChatGPT" }).click();
  await pageA
    .locator('[data-codex-auxiliary-window] img[alt="About ChatGPT"]')
    .waitFor();
  await pageA.getByRole("button", { name: "Close About ChatGPT" }).click();
  await pageA
    .locator('[data-codex-auxiliary-window] img[alt="About ChatGPT"]')
    .waitFor({ state: "detached" });
  console.log("ok terminal panel and About native window");

  const pet = pageA.locator("[data-codex-auxiliary-window]").filter({
    hasNot: pageA.locator('img[alt="About ChatGPT"]'),
  });
  if (!(await pet.first().isVisible().catch(() => false))) {
    await pageA.getByRole("button", { name: "Open profile menu" }).click();
    await pageA.getByRole("menuitem", { name: "Show pet" }).click();
  }
  await pet.first().waitFor();
  console.log("ok desktop pet surface");

  await pageA.getByRole("menuitem", { exact: true, name: "View" }).click();
  await pageA.getByRole("menuitem", { name: "Toggle Full Screen" }).click();
  await pageA.waitForFunction(
    () =>
      Boolean(document.fullscreenElement) ||
      document.documentElement.dataset.codexWebFullscreen === "true",
  );
  await pageA.getByRole("menuitem", { exact: true, name: "View" }).click();
  await pageA.getByRole("menuitem", { name: "Toggle Full Screen" }).click();
  await pageA.waitForFunction(
    () =>
      !document.fullscreenElement &&
      document.documentElement.dataset.codexWebFullscreen !== "true",
  );
  console.log("ok browser full-screen bridge");

  await removeProject(pageA);
  await pageB
    .getByRole("button", {
      name: `Project actions for ${projectName}`,
    })
    .first()
    .waitFor({
      state: "detached",
      timeout: 20_000,
    });
  assert.deepEqual(errors, []);
  console.log("ok project cleanup, multi-device removal, and page errors");
} finally {
  await removeAcceptanceProjects(pageA).catch(() => {});
  await pwaContext.close();
  await desktopContext.close();
  await contextB.close();
  await secondaryBrowser.close();
  rmSync(profileDirectory, { force: true, recursive: true });
}
