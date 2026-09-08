const test = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");
const net = require("node:net");
const { once } = require("node:events");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { gzipSync } = require("node:zlib");
const { createProxy, trustedPeer, sessionProvider } = require("../packages/t3code/access-proxy.cjs");

async function fixture(t, trust) {
  const received = [];
  const sockets = new Set();
  const backend = http.createServer((req, res) => {
    received.push(req.headers);
    res.setHeader("content-type", "application/json");
    res.end(JSON.stringify({ authenticated: req.headers.authorization === "Bearer private-token" }));
  });
  backend.on("connection", (socket) => {
    sockets.add(socket);
    socket.on("close", () => sockets.delete(socket));
  });
  backend.on("upgrade", (req, socket) => {
    received.push(req.headers);
    socket.write("HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n");
    socket.on("data", (data) => socket.write(data));
  });
  backend.listen(0, "127.0.0.1");
  await once(backend, "listening");
  const proxy = createProxy(backend.address().port, () => "private-token", trust);
  proxy.listen(0, "127.0.0.1");
  await once(proxy, "listening");
  t.after(() => { for (const socket of sockets) socket.destroy(); proxy.closeAllConnections(); proxy.close(); backend.closeAllConnections(); backend.close(); });
  return { proxy, backend, received, url: `http://127.0.0.1:${proxy.address().port}` };
}

test("fresh browsers get an authenticated session without seeing the bearer token", async (t) => {
  const { url, received } = await fixture(t);
  const response = await fetch(`${url}/api/auth/session`, {
    headers: { authorization: "Bearer stale-client", cookie: "t3_session_old=stale; preference=keep" },
  });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { authenticated: true });
  assert.equal(received[0].authorization, "Bearer private-token");
  assert.equal(received[0].cookie.trim(), "preference=keep");
  assert.equal(response.headers.get("authorization"), null);
});

test("other containers cannot acquire gateway authorization using forwarded headers", async (t) => {
  const { url, received } = await fixture(t, async () => false);
  const response = await fetch(`${url}/api/auth/session`, {
    headers: { "x-forwarded-for": "127.0.0.1", "cf-access-jwt-assertion": "forged" },
  });
  assert.deepEqual(await response.json(), { authenticated: false });
  assert.equal(received[0].authorization, undefined);
});

test("tunnel trust follows actual peer addresses and fails closed on DNS errors", async () => {
  const request = (remoteAddress) => ({ socket: { remoteAddress } });
  const lookup = async () => [{ address: "10.89.0.12" }];
  assert.equal(await trustedPeer(request("::ffff:10.89.0.12"), lookup), true);
  assert.equal(await trustedPeer(request("10.89.0.13"), lookup), false);
  assert.equal(await trustedPeer(request("127.0.0.1"), lookup), true);
  assert.equal(await trustedPeer(request("10.89.0.12"), async () => { throw new Error("DNS unavailable"); }), false);
});

test("cross-origin requests are rejected before reaching the backend", async (t) => {
  const { url, received } = await fixture(t);
  const response = await fetch(url, { method: "POST", headers: { origin: "https://unrelated.example" } });
  assert.equal(response.status, 403);
  assert.equal(received.length, 0);
});

test("websocket upgrade supplies the credential and forwards traffic", async (t) => {
  const { proxy, received } = await fixture(t);
  const socket = net.connect(proxy.address().port, "127.0.0.1");
  t.after(() => socket.destroy());
  await once(socket, "connect");
  socket.write(`GET /ws HTTP/1.1\r\nHost: 127.0.0.1:${proxy.address().port}\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n`);
  const [upgrade] = await once(socket, "data");
  assert.match(upgrade.toString(), /101 Switching Protocols/);
  assert.equal(received[0].authorization, "Bearer private-token");
  socket.write("terminal-output");
  const [message] = await once(socket, "data");
  assert.equal(message.toString(), "terminal-output");
});

test("backend failure returns 502 without leaking credentials", async (t) => {
  const { backend, url } = await fixture(t);
  await new Promise((resolve) => backend.close(resolve));
  const response = await fetch(url);
  assert.equal(response.status, 502);
  assert.doesNotMatch(await response.text(), /private-token/);
});

test("revoked persisted sessions renew once for concurrent requests", async (t) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "t3-session-test-"));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const expiresAt = new Date(Date.now() + 30 * 86400000).toISOString();
  await fs.writeFile(path.join(directory, "session.json"), JSON.stringify({ token: "revoked", expiresAt }));
  let issued = 0;
  const getToken = await sessionProvider(directory, async () => {
    issued++;
    return { token: "renewed", expiresAt };
  }, async (token) => token !== "revoked");
  assert.deepEqual(await Promise.all([getToken(), getToken(), getToken()]), ["renewed", "renewed", "renewed"]);
  assert.equal(await getToken(), "renewed");
  assert.equal(issued, 1);
  assert.equal((await fs.stat(path.join(directory, "session.json"))).mode & 0o777, 0o600);
  const restarted = await sessionProvider(directory, async () => { throw new Error("unexpected renewal"); }, async () => true);
  assert.equal(await restarted(), "renewed");
});

test("PWA metadata supplies real Android icons and root service worker scope", async (t) => {
  const { url, received } = await fixture(t);
  const response = await fetch(`${url}/manifest.webmanifest`);
  assert.match(response.headers.get("content-type"), /application\/manifest\+json/);
  const manifest = await response.json();
  assert.equal(manifest.name, "T3 Code");
  assert.equal(manifest.display, "standalone");
  assert.equal(manifest.start_url, "/");
  assert.equal(manifest.scope, "/");
  assert.equal(manifest.prefer_related_applications, false);
  for (const icon of manifest.icons) {
    const image = await fetch(url + icon.src);
    const png = Buffer.from(await image.arrayBuffer());
    assert.equal(png.toString("hex", 0, 8), "89504e470d0a1a0a");
    assert.equal(`${png.readUInt32BE(16)}x${png.readUInt32BE(20)}`, icon.sizes);
  }
  const worker = await fetch(`${url}/__t3_pwa/sw.js`);
  assert.equal(worker.headers.get("service-worker-allowed"), "/");
  assert.equal(worker.headers.get("cache-control"), "no-cache");
  assert.equal(received.length, 0);
});

test("compressed upstream HTML gets one credentialed manifest and fresh cache headers", async (t) => {
  const { url, backend } = await fixture(t);
  backend.removeAllListeners("request");
  backend.on("request", (request, response) => {
    assert.equal(request.headers["if-none-match"], undefined);
    const body = gzipSync('<html><head><link rel="manifest" href="/upstream.json"></head><body>T3</body></html>');
    response.writeHead(200, { "content-type": "text/html", "content-encoding": "gzip",
      "content-length": body.length, etag: '"upstream"' });
    response.end(body);
  });
  const response = await fetch(url, { headers: { accept: "text/html", "if-none-match": '"upstream"' } });
  const html = await response.text();
  assert.equal((html.match(/rel="manifest"/g) || []).length, 1);
  assert.match(html, /crossorigin="use-credentials"/);
  assert.match(html, /\/__t3_pwa\/register.js/);
  assert.equal(response.headers.get("content-encoding"), null);
  assert.equal(response.headers.get("etag"), null);
  assert.equal(response.headers.get("cache-control"), "no-store");
});
