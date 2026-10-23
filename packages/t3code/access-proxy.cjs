// Cloudflare Access authenticates the public site. Keep the upstream T3 server
// on loopback and supply its native bearer session only on the server side.
const http = require("node:http");
const fs = require("node:fs/promises");
const path = require("node:path");
const dns = require("node:dns/promises");
const zlib = require("node:zlib");
const { servePwa, enhanceHtml } = require("./pwa.cjs");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const exec = promisify(execFile);

function sameOrigin(request) {
  if (!request.headers.origin) return true;
  try {
    const origin = new URL(request.headers.origin);
    return origin.host === request.headers.host &&
      (origin.protocol === "https:" ||
        (origin.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname)));
  } catch { return false; }
}

async function trustedPeer(request, lookup = dns.lookup) {
  const address = request.socket.remoteAddress?.replace(/^::ffff:/, "");
  if (address === "127.0.0.1" || address === "::1") return true;
  try {
    const peers = await lookup("cloudflared", { all: true });
    return peers.some((peer) => peer.address === address);
  } catch { return false; }
}

function createProxy(upstreamPort, getToken, trust = trustedPeer) {
  function appNavigation(request) {
    return request.method === "GET" && request.headers["sec-fetch-dest"] === "document" &&
      !/^\/api(?:\/|\?|$)/.test(request.url);
  }
  async function options(request) {
    const headers = { ...request.headers };
    if (appNavigation(request)) {
      headers["accept-encoding"] = "identity";
      delete headers["if-none-match"];
      delete headers["if-modified-since"];
    }
    // Other containers retain native T3 authentication. Never trust forwarded
    // headers to identify the tunnel: only its actual TCP peer may bypass pairing.
    if (!await trust(request)) {
      return { hostname: "127.0.0.1", port: upstreamPort, method: request.method,
        path: request.url, headers };
    }
    headers.authorization = `Bearer ${await getToken()}`;
    delete headers.dpop;
    // Previously paired browsers must not override the gateway's credential.
    if (headers.cookie) {
      headers.cookie = headers.cookie.split(";").filter((entry) =>
        !entry.trim().split("=")[0].startsWith("t3_session")).join(";");
    }
    return { hostname: "127.0.0.1", port: upstreamPort, method: request.method,
      path: request.url, headers };
  }
  const server = http.createServer(async (request, response) => {
    if (!sameOrigin(request)) { response.writeHead(403).end(); return; }
    if (servePwa(request, response)) return;
    let forwarding;
    try { forwarding = await options(request); }
    catch { response.writeHead(502).end("T3 Code backend unavailable"); return; }
    const upstream = http.request(forwarding, (incoming) => {
      if (appNavigation(request) && !incoming.headers["content-disposition"] && incoming.statusCode === 200 &&
          incoming.headers["content-type"]?.includes("text/html")) {
        const chunks = [];
        incoming.on("error", () => response.destroy());
        incoming.on("data", (chunk) => chunks.push(chunk));
        incoming.on("end", () => {
          try {
            let body = Buffer.concat(chunks);
            const decoder = { gzip: zlib.gunzipSync, br: zlib.brotliDecompressSync, deflate: zlib.inflateSync }[incoming.headers["content-encoding"]];
            if (decoder) body = decoder(body);
            const headers = { ...incoming.headers, "cache-control": "no-store" };
            for (const name of ["content-length", "content-encoding", "etag", "last-modified"]) delete headers[name];
            response.writeHead(200, headers).end(enhanceHtml(body.toString("utf8")));
          } catch { response.writeHead(502).end("T3 Code page unavailable"); }
        });
        return;
      }
      response.writeHead(incoming.statusCode, incoming.headers);
      incoming.pipe(response);
    });
    upstream.on("error", () => {
      if (!response.headersSent) response.writeHead(502);
      response.end("T3 Code backend unavailable");
    });
    request.on("aborted", () => upstream.destroy());
    response.on("close", () => upstream.destroy());
    request.pipe(upstream);
  });
  server.on("upgrade", async (request, socket, head) => {
    if (!sameOrigin(request)) { socket.end("HTTP/1.1 403 Forbidden\r\n\r\n"); return; }
    let forwarding;
    try { forwarding = await options(request); }
    catch { socket.end("HTTP/1.1 502 Bad Gateway\r\n\r\n"); return; }
    const upstream = http.request(forwarding);
    socket.on("error", () => upstream.destroy());
    upstream.on("upgrade", (response, peer, upstreamHead) => {
      socket.write(`HTTP/1.1 ${response.statusCode} ${response.statusMessage}\r\n`);
      for (let index = 0; index < response.rawHeaders.length; index += 2) {
        socket.write(`${response.rawHeaders[index]}: ${response.rawHeaders[index + 1]}\r\n`);
      }
      socket.write("\r\n");
      if (head.length) peer.write(head);
      if (upstreamHead.length) socket.write(upstreamHead);
      peer.on("error", () => socket.destroy());
      peer.on("close", () => socket.destroy());
      socket.on("close", () => peer.destroy());
      socket.pipe(peer).pipe(socket);
    });
    upstream.on("response", (response) => {
      response.resume();
      socket.end(`HTTP/1.1 ${response.statusCode} ${response.statusMessage}\r\n\r\n`);
    });
    upstream.on("error", () => socket.end("HTTP/1.1 502 Bad Gateway\r\n\r\n"));
    upstream.end();
  });
  return server;
}

async function sessionProvider(directory, issue, validate) {
  const filename = path.join(directory, "session.json");
  await fs.mkdir(directory, { recursive: true, mode: 0o700 });
  let session;
  try { session = JSON.parse(await fs.readFile(filename, "utf8")); } catch {}
  async function refresh() {
    if (session?.token && Date.parse(session.expiresAt) > Date.now() + 7 * 86400000 &&
        await validate(session.token)) return session.token;
    const next = await issue();
    if (typeof next.token !== "string" || !(Date.parse(next.expiresAt) > Date.now())) {
      throw new Error("Invalid proxy session response");
    }
    await fs.writeFile(`${filename}.tmp`, JSON.stringify(next), { mode: 0o600 });
    await fs.rename(`${filename}.tmp`, filename);
    session = next;
    return session.token;
  }
  let pending;
  // Check native session validity before granting access, including revocation.
  // Concurrent requests share one validation/renewal operation.
  return () => pending ??= refresh().finally(() => { pending = undefined; });
}

async function main() {
  const getToken = await sessionProvider(
    path.join(process.env.HOME, ".t3code-container/access"),
    async () => {
      // Capture stdout: bearer credentials must never appear in the journal.
      const { stdout } = await exec(path.join(process.env.HOME, ".local/bin/t3"), [
        "auth", "session", "issue", "--base-dir", process.env.T3CODE_HOME,
        "--ttl", "30d", "--label", "cloudflare-access-proxy", "--json",
      ], { timeout: 30000 });
      return JSON.parse(stdout);
    },
    async (token) => {
      const response = await fetch("http://127.0.0.1:3774/api/auth/session", {
        headers: { authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(5000),
      });
      if (response.status === 401) return false;
      if (!response.ok) throw new Error("Session validation unavailable");
      return (await response.json()).authenticated === true;
    },
  );
  await getToken();
  const server = createProxy(3774, getToken);
  server.listen(3773, "0.0.0.0");
  setInterval(() => getToken().catch(() => console.error("T3 proxy session renewal failed")), 4 * 3600000).unref();
}

module.exports = { createProxy, sameOrigin, trustedPeer, sessionProvider };
if (require.main === module) {
  main().catch(() => { console.error("T3 access proxy could not start"); process.exit(1); });
}
