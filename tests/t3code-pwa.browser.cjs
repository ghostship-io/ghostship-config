const test = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");
const { once } = require("node:events");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { chromium, devices } = require(process.env.PLAYWRIGHT_MODULE);
const { createProxy } = require("../packages/t3code/access-proxy.cjs");

test("Android Chrome recognizes authenticated installation and reconnects without stale data", { timeout: 60000 }, async (t) => {
  let release = 1;
  const upstream = http.createServer((req, res) => {
    res.writeHead(200, { "content-type": "text/html" });
    res.end(`<html><head><title>T3 Code</title><link rel="manifest" href="/manifest.webmanifest"></head><body><button>Workspace ${release}</button></body></html>`);
  });
  upstream.listen(0, "127.0.0.1");
  await once(upstream, "listening");
  const gateway = createProxy(upstream.address().port, () => "fixture-token");
  gateway.listen(0, "127.0.0.1");
  await once(gateway, "listening");
  // Emulate Access gating the entire origin, including the manifest and icons.
  const access = http.createServer((req, res) => {
    if (!req.headers.cookie?.includes("access=allowed")) { res.writeHead(401).end(); return; }
    const forwarded = http.request({ hostname: "127.0.0.1", port: gateway.address().port,
      path: req.url, method: req.method, headers: req.headers }, (response) => {
      res.writeHead(response.statusCode, response.headers); response.pipe(res);
    });
    req.pipe(forwarded);
  });
  access.listen(0, "127.0.0.1");
  await once(access, "listening");
  t.after(() => { for (const server of [access, gateway, upstream]) { server.closeAllConnections(); server.close(); } });
  const origin = `http://127.0.0.1:${access.address().port}`;
  // Installation is unavailable in Playwright's default incognito contexts.
  const profile = await fs.mkdtemp(path.join(os.tmpdir(), "t3-pwa-"));
  const context = await chromium.launchPersistentContext(profile, {
    ...devices["Pixel 7"], channel: "chromium", headless: true,
    args: ["--no-sandbox", "--bypass-app-banner-engagement-checks"],
  });
  t.after(async () => { await context.close(); await fs.rm(profile, { recursive: true, force: true }); });
  await context.addCookies([{ name: "access", value: "allowed", url: origin, httpOnly: true }]);
  const page = await context.newPage();
  await page.addInitScript(() => {
    window.addEventListener("beforeinstallprompt", (event) => { event.preventDefault(); window.installOfferReceived = true; });
  });
  await page.goto(origin);
  await page.getByRole("button", { name: "Workspace 1" }).click();
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.waitForFunction(() => navigator.serviceWorker.controller);
  const cdp = await context.newCDPSession(page);
  const manifest = await cdp.send("Page.getAppManifest");
  assert.deepEqual(manifest.errors, []);
  assert.equal(JSON.parse(manifest.data).name, "T3 Code");
  assert.deepEqual((await cdp.send("Page.getInstallabilityErrors")).installabilityErrors, []);
  await page.waitForFunction(() => window.installOfferReceived);
  await context.setOffline(true);
  await page.goto(`${origin}/threads/example`);
  await page.getByRole("heading", { name: "T3 Code is offline" }).waitFor();
  assert.deepEqual(await page.evaluate(() => caches.keys()), []);
  assert.equal(await page.evaluate(() => fetch("/api/private").then(() => true, () => false)), false);
  release = 2;
  await context.setOffline(false);
  await page.getByRole("link", { name: "Try again" }).click();
  await page.getByRole("button", { name: "Workspace 2" }).waitFor();
});
