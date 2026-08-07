import assert from "node:assert/strict";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  rmSync,
  statSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright-core";

const targetUrl = process.env.CODEX_WEB_URL || "http://127.0.0.1:8214";
const configuredArtifactsDirectory = process.env.CODEX_UI_ARTIFACTS;
const artifactsDirectory = configuredArtifactsDirectory ||
  mkdtempSync(path.join(os.tmpdir(), "codex-web-ui-artifacts-"));

const applicationMenus = {
  File: [
    "New Window",
    "New Chat",
    "Open Folder…",
    "Close",
    "Settings…",
    "Log Out",
    "Quit",
  ],
  Edit: [
    "Undo",
    "Redo",
    "Cut",
    "Copy",
    "Paste",
    "Delete",
    "Select All",
  ],
  View: [
    "Toggle Sidebar",
    "Toggle Bottom Panel",
    "Toggle Pinned Summary",
    "Open Terminal",
    "Toggle File Tree",
    "Toggle Review Panel",
    "Browser",
    "Find",
    "Previous Chat",
    "Next Chat",
    "Back",
    "Forward",
    "Zoom In",
    "Zoom Out",
    "Actual Size",
    "Toggle Full Screen",
  ],
  Help: [
    "Documentation",
    "Keyboard Shortcuts",
    "What's New",
    "Troubleshooting",
    "System Status",
    "Send Feedback",
    "Start Performance Trace",
    "About ChatGPT",
  ],
};

const settingsScreens = [
  "General",
  "Import",
  "Profile",
  "Appearance",
  "Voice",
  "Configuration",
  "Personalization",
  "Pets",
  "Keyboard shortcuts",
  "Usage & billing",
  "Plugins",
  "Browser",
  "Computer use",
  "Hooks",
  "Connections",
  "Git",
  "Environments",
  "Worktrees",
  "Archived chats",
];

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

async function waitForApp(page) {
  try {
    await page.goto(targetUrl, { waitUntil: "domcontentloaded" });
  } catch (error) {
    if (!String(error).includes("net::ERR_ABORTED")) throw error;
  }
  await page.waitForFunction(
    () =>
      document.querySelector('[aria-label="Add new project"]') ||
      document.body.innerText.includes("What should we build?"),
    null,
    { timeout: 30_000 },
  );
  const dismiss = page.getByRole("button", { name: "Not now" });
  if (await dismiss.isVisible().catch(() => false)) await dismiss.click();
}

async function openApplicationMenu(page, name) {
  await page.getByRole("menuitem", { exact: true, name }).click();
  const menu = page.locator('[role="menu"]:visible').last();
  await menu.waitFor();
  await menu.getByRole("menuitem").first().waitFor();
  return menu;
}

async function clickApplicationMenuItem(page, menuName, itemName) {
  const menu = await openApplicationMenu(page, menuName);
  await menu.getByRole("menuitem").filter({ hasText: itemName }).first().click();
}

async function expectBody(page, pattern, timeout = 10_000) {
  await page.waitForFunction(
    ({ flags, source }) => new RegExp(source, flags).test(document.body.innerText),
    { flags: pattern.flags, source: pattern.source },
    { timeout },
  );
}

async function returnHome(page) {
  const back = page.getByRole("button", { name: "Back" }).first();
  if (await back.isVisible().catch(() => false)) {
    await back.click();
  } else {
    await page.goto(targetUrl);
  }
  await page.getByRole("button", { name: "Add new project" }).waitFor();
}

async function testApplicationMenus(page, passivePage) {
  for (const [menuName, expectedItems] of Object.entries(applicationMenus)) {
    const menu = await openApplicationMenu(page, menuName);
    const actual = (await menu.getByRole("menuitem").allInnerTexts())
      .map((item) => item.replace(/\s+/g, " ").trim())
      .filter(Boolean);
    for (const expected of expectedItems) {
      assert.ok(
        actual.some((item) => item === expected || item.startsWith(expected)),
        `${menuName} menu is missing ${expected}: ${actual.join(", ")}`,
      );
    }
    await page.keyboard.press("Escape");
  }

  await clickApplicationMenuItem(page, "File", "Open Folder…");
  await page.getByRole("heading", { name: "Select Project Root" }).waitFor();
  await page.getByRole("button", { name: "Cancel" }).click();
  await page
    .locator('[data-codex-web-dialog=""]')
    .waitFor({ state: "detached" });

  await clickApplicationMenuItem(page, "File", "New Window");
  const newWindow = page.locator("[data-codex-auxiliary-window]").filter({
    has: page.locator('img[alt="ChatGPT"]'),
  });
  await newWindow.waitFor({ timeout: 15_000 });
  await page.getByRole("button", { name: "Close ChatGPT" }).click();
  await newWindow.waitFor({ state: "detached", timeout: 15_000 });
  await page.getByRole("menuitem", { exact: true, name: "File" }).click();
  await page.keyboard.press("Escape");

  await clickApplicationMenuItem(page, "Help", "Keyboard Shortcuts");
  const shortcuts = page.getByRole("dialog").filter({
    hasText: /Keyboard shortcuts/i,
  });
  await shortcuts.waitFor();
  await passivePage.waitForTimeout(250);
  if (process.env.CODEX_ALLOW_BROADCAST_COMMANDS !== "1") {
    assert.equal(
      await passivePage
        .getByRole("dialog")
        .filter({ hasText: /Keyboard shortcuts/i })
        .count(),
      0,
      "desktop-only menu commands must not open dialogs on Android",
    );
  }
  await page.keyboard.press("Escape");
  await shortcuts.waitFor({ state: "detached" });

  await clickApplicationMenuItem(page, "Help", "About ChatGPT");
  const about = page.locator("[data-codex-auxiliary-window]").filter({
    has: page.locator('img[alt="About ChatGPT"]'),
  });
  await about.waitFor();
  await page.getByRole("button", { name: "Close About ChatGPT" }).click();
  await about.waitFor({ state: "detached" });

  await clickApplicationMenuItem(page, "View", "Toggle Full Screen");
  await page.waitForFunction(
    () =>
      Boolean(document.fullscreenElement) ||
      document.documentElement.dataset.codexWebFullscreen === "true",
  );
  await clickApplicationMenuItem(page, "View", "Toggle Full Screen");
  await page.waitForFunction(
    () =>
      !document.fullscreenElement &&
      document.documentElement.dataset.codexWebFullscreen !== "true",
  );
}

async function testMainScreens(page) {
  for (const [buttonName, headingName] of [
    ["Pull requests", "Pull requests"],
    ["Sites", "Sites"],
    ["Scheduled", "Scheduled tasks"],
    ["Plugins", "Plugins"],
  ]) {
    await page.getByRole("button", { exact: true, name: buttonName }).click();
    await page.getByRole("heading", {
      exact: true,
      name: headingName,
    }).waitFor();
    if (buttonName === "Scheduled") {
      await page.getByRole("button", { exact: true, name: "Create" }).waitFor();
    }
    await returnHome(page);
  }

  await page.getByRole("button", { name: "Add new project" }).click();
  await page.getByRole("heading", { name: "Create project" }).waitFor();
  await page.getByRole("button", { name: "Choose source folders" }).click();
  await page.getByRole("heading", { name: "Select Project Root" }).waitFor();
  assert.equal(
    await page.locator('[role="dialog"] [data-codex-web-dialog=""]').count(),
    1,
  );
  await page
    .locator('[data-codex-web-dialog=""]')
    .getByRole("button", { name: "Cancel" })
    .click();
  await page.getByRole("heading", { name: "Create project" }).waitFor();
  await page.keyboard.press("Escape");
  await page
    .getByRole("heading", { name: "Create project" })
    .waitFor({ state: "detached" });
}

async function testSettingsScreens(page) {
  await page.getByRole("button", { name: "Open profile menu" }).click();
  await page.getByRole("menuitem", { name: "Settings" }).click();
  await page.getByRole("heading", { exact: true, name: "General" }).waitFor();
  for (const name of settingsScreens) {
    console.log(`checking settings: ${name}`);
    const target = page.getByText(name, { exact: true }).last();
    await target.waitFor();
    await target.click();
    try {
      await page.getByRole("heading", {
        exact: true,
        name,
      }).waitFor({ timeout: 15_000 });
    } catch (error) {
      throw new Error(`settings screen did not load: ${name}`, {
        cause: error,
      });
    }
  }
  await returnHome(page);
}

async function testDropdowns(page) {
  for (const [buttonName, expected] of [
    ["Open profile menu", /Settings|Log out/i],
    ["Open help menu", /Keyboard shortcuts|What's new/i],
  ]) {
    await page.getByRole("button", { name: buttonName }).click();
    const menu = page.locator('[role="menu"]:visible').last();
    await menu.waitFor();
    assert.match(await menu.innerText(), expected);
    await page.keyboard.press("Escape");
  }

  const permission = page.getByRole("button", { name: /Full access|Default permissions/i });
  if (await permission.isVisible().catch(() => false)) {
    await permission.click();
    await page.locator('[role="menu"]:visible').last().waitFor();
    await page.keyboard.press("Escape");
  }

  const add = page.getByRole("button", { name: "Add files and more" });
  if (await add.isVisible().catch(() => false)) {
    await add.click();
    await expectBody(page, /Files and folders|Work in project/i);
    await page.keyboard.press("Escape");
  }
}

async function testMobile(page) {
  const staleShortcuts = page.getByRole("dialog").filter({
    hasText: /Keyboard shortcuts/i,
  });
  if (await staleShortcuts.isVisible().catch(() => false)) {
    await page.keyboard.press("Escape");
    await staleShortcuts.waitFor({ state: "detached" });
  }
  const showSidebar = page.getByRole("button", { name: "Show sidebar" });
  if (await showSidebar.isVisible().catch(() => false)) await showSidebar.click();
  for (const buttonName of ["Open profile menu", "Open help menu"]) {
    await page.getByRole("button", { name: buttonName }).click();
    await page.locator('[role="menu"]:visible').last().waitFor();
    await page.keyboard.press("Escape");
  }
  const add = page.getByRole("button", { name: "Add files and more" });
  if (await add.isVisible().catch(() => false)) {
    await add.click();
    await expectBody(page, /Files and folders|Work in project/i);
    await page.keyboard.press("Escape");
  }
  const hideSidebar = page.getByRole("button", { name: "Hide sidebar" });
  if (await hideSidebar.isVisible().catch(() => false)) await hideSidebar.click();
}

const browserExecutable = findBrowserExecutable();
const browser = await chromium.launch({
  executablePath: browserExecutable,
  headless: true,
});
const desktopContext = await browser.newContext({
  viewport: { height: 1000, width: 1440 },
});
const mobileContext = await browser.newContext({
  deviceScaleFactor: 2.625,
  hasTouch: true,
  isMobile: true,
  userAgent:
    "Mozilla/5.0 (Linux; Android 15; Pixel 9 Pro) AppleWebKit/537.36 " +
    "(KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36",
  viewport: { height: 915, width: 412 },
});
const desktop = await desktopContext.newPage();
const mobile = await mobileContext.newPage();
const errors = [];
let failed = false;
for (const page of [desktop, mobile]) {
  page.on("pageerror", (error) => errors.push(error.message));
}

try {
  await Promise.all([waitForApp(desktop), waitForApp(mobile)]);
  await testApplicationMenus(desktop, mobile);
  console.log("ok application menus, folder picker, native windows, shortcuts, and full screen");
  await testMainScreens(desktop);
  console.log("ok primary screens and project modals");
  await testSettingsScreens(desktop);
  console.log(`ok ${settingsScreens.length} settings screens`);
  await testDropdowns(desktop);
  console.log("ok desktop profile, help, permission, and attachment controls");
  await testMobile(mobile);
  console.log("ok Android sidebar and dropdown controls");
  assert.deepEqual(errors, []);
  assert.equal(
    await desktop.locator('[data-codex-auxiliary-window][role="dialog"]:visible').count(),
    0,
  );
  console.log("ok no page errors or orphaned opaque auxiliary windows");
  console.log(
    "not invoked: Log Out, Quit, Delete, Send Feedback, plugin installation, or task execution",
  );
} catch (error) {
  failed = true;
  if (configuredArtifactsDirectory) {
    mkdirSync(artifactsDirectory, { mode: 0o700, recursive: true });
  }
  await Promise.allSettled([
    desktop.screenshot({
      fullPage: true,
      path: path.join(artifactsDirectory, "desktop-failure.png"),
    }),
    mobile.screenshot({
      fullPage: true,
      path: path.join(artifactsDirectory, "mobile-failure.png"),
    }),
  ]);
  console.error(`failure screenshots: ${artifactsDirectory}`);
  throw error;
} finally {
  await desktopContext.close();
  await mobileContext.close();
  await browser.close();
  if (!failed && !configuredArtifactsDirectory) {
    rmSync(artifactsDirectory, { force: true, recursive: true });
  }
}
