import assert from "node:assert/strict";
import { existsSync, readdirSync, statSync } from "node:fs";
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
  await page.goto(targetUrl, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Add new project" }).waitFor({
    timeout: 30_000,
  });
}

async function openAppMenu(page, name) {
  await page.getByRole("menuitem", { exact: true, name }).click();
  const menu = page.getByRole("menu");
  await menu.waitFor();
  assert.ok((await menu.getByRole("menuitem").count()) > 0);
  await page.keyboard.press("Escape");
}

async function removeProject(page) {
  const actions = page.getByRole("button", {
    name: `Project actions for ${projectName}`,
  });
  if (await actions.count() === 0) return;
  await actions.first().dispatchEvent("click");
  const remove = page.getByRole("menuitem", { name: /Remove project/i });
  await remove.waitFor();
  await remove.click();
  const confirm = page.getByRole("button", { name: /Remove|Delete/i }).last();
  if (await confirm.isVisible().catch(() => false)) await confirm.click();
  await page.getByText(projectName, { exact: true }).waitFor({
    state: "detached",
    timeout: 15_000,
  });
}

const browser = await chromium.launch({
  executablePath: findBrowserExecutable(),
  headless: true,
});
const errors = [];
const contextA = await browser.newContext({
  viewport: { height: 915, width: 412 },
});
const contextB = await browser.newContext({
  viewport: { height: 915, width: 412 },
});
const pageA = await contextA.newPage();
const pageB = await contextB.newPage();
recordPageErrors(pageA, errors);
recordPageErrors(pageB, errors);

try {
  await Promise.all([waitForApp(pageA), waitForApp(pageB)]);

  const manifest = await pageA.evaluate(async () => {
    const response = await fetch("/manifest.webmanifest");
    return response.json();
  });
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
  await pageA.evaluate(async () => {
    await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller) location.reload();
  });
  await pageA.waitForFunction(() => navigator.serviceWorker.controller, null, {
    timeout: 15_000,
  });
  const devtools = await contextA.newCDPSession(pageA);
  const { installabilityErrors } = await devtools.send(
    "Page.getInstallabilityErrors",
  );
  assert.deepEqual(installabilityErrors, []);
  console.log("ok PWA manifest, worker, and Chrome installability");

  for (const menuName of ["File", "Edit", "View", "Help"]) {
    await openAppMenu(pageA, menuName);
  }
  for (const buttonName of ["Open profile menu", "Open help menu"]) {
    await pageA.getByRole("button", { name: buttonName }).click();
    await pageA.getByRole("menu").waitFor();
    await pageA.keyboard.press("Escape");
  }
  const modelButton = pageA.locator("button").filter({
    hasText: /(?:5\.\d|GPT|Ollama)/,
  }).last();
  await modelButton.click();
  const modelMenu = pageA.getByRole("menu");
  await modelMenu.waitFor();
  assert.match(await modelMenu.innerText(), /Ollama/i);
  await pageA.keyboard.press("Escape");
  console.log("ok application, profile, help, and model dropdowns");

  await pageA.getByRole("button", { name: "Scheduled" }).click();
  await pageA.getByRole("heading", { name: "Scheduled tasks" }).waitFor();
  await pageA.getByRole("button", { name: "Create" }).waitFor();
  await pageA.getByRole("button", { name: "Back" }).click();
  await pageA.getByRole("button", { name: "Add new project" }).waitFor();
  console.log("ok scheduled-task navigation and creation entrypoint");

  await pageA.getByRole("button", { name: "Add new project" }).dispatchEvent("click");
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
    pageA.getByText(projectName, { exact: true }).waitFor({ timeout: 20_000 }),
    pageB.getByText(projectName, { exact: true }).waitFor({ timeout: 20_000 }),
  ]);
  console.log("ok project creation, folder selection, and multi-device sync");

  await pageA.getByRole("button", { name: "Toggle bottom panel" }).dispatchEvent("click");
  await pageA.getByText(/Terminal/i).first().waitFor();
  await pageA.getByRole("menuitem", { exact: true, name: "Help" }).click();
  await pageA.getByRole("menuitem", { name: "About ChatGPT" }).click();
  await pageA.locator('[data-codex-auxiliary-window] img[alt="About ChatGPT"]').waitFor();
  console.log("ok terminal panel and About native window");

  await pageA.getByRole("button", { name: "Open profile menu" }).click();
  await pageA.getByRole("menuitem", { name: "Show pet" }).click();
  const pet = pageA.locator("[data-codex-auxiliary-window]").filter({
    hasNot: pageA.locator('img[alt="About ChatGPT"]'),
  });
  await pet.first().waitFor();
  console.log("ok desktop pet surface");

  await pageA.getByRole("menuitem", { exact: true, name: "View" }).click();
  await pageA.getByRole("menuitem", { name: "Toggle Full Screen" }).click();
  await pageA.waitForFunction(
    () => document.documentElement.dataset.codexWebFullscreen === "true",
  );
  console.log("ok browser full-screen bridge");

  await removeProject(pageA);
  await pageB.getByText(projectName, { exact: true }).waitFor({
    state: "detached",
    timeout: 20_000,
  });
  assert.deepEqual(errors, []);
  console.log("ok project cleanup, multi-device removal, and page errors");
} finally {
  await removeProject(pageA).catch(() => {});
  await contextA.close();
  await contextB.close();
  await browser.close();
}
