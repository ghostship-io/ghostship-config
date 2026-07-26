import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);
const { isBrowserOriginAllowed, safeStaticPath, transformIndex } = require(
  path.join(packageRoot, "bridge", "gateway.cjs"),
);

test("static paths stay within the upstream renderer", () => {
  assert.equal(safeStaticPath("/app/webview", "/assets/app.js"), "/app/webview/assets/app.js");
  assert.equal(safeStaticPath("/app/webview", "/../../etc/passwd"), null);
  assert.equal(safeStaticPath("/app/webview", "/%2e%2e/%2e%2e/etc/passwd"), null);
});

test("index transformation injects transport and PWA without replacing renderer", () => {
  const source =
    `<head><meta http-equiv="Content-Security-Policy" content="connect-src 'self' https://chatgpt.com;"><script type="module" src="./assets/index.js"></script></head>`;
  const transformed = transformIndex(source);
  assert.match(transformed, /electron-shim\.js/);
  assert.match(transformed, /webview-bridge\.js/);
  assert.match(transformed, /browser-preload\.js/);
  assert.match(transformed, /manifest\.webmanifest/);
  assert.match(transformed, /src="\.\/assets\/index\.js"/);
  assert.match(transformed, /connect-src ws: wss: 'self' https:\/\/chatgpt\.com/);
});

test("index transformation preserves HTML-escaped CSP sources", () => {
  const source =
    `<meta http-equiv="Content-Security-Policy" content="connect-src &#39;self&#39; https://chatgpt.com;"><script type="module"></script>`;
  const transformed = transformIndex(source);
  assert.match(
    transformed,
    /connect-src ws: wss: &#39;self&#39; https:\/\/chatgpt\.com;/,
  );
});

test("browser IPC accepts only same-origin or explicitly allowed clients", () => {
  assert.equal(
    isBrowserOriginAllowed({
      headers: { host: "codex.example.test", origin: "https://codex.example.test" },
    }),
    true,
  );
  assert.equal(
    isBrowserOriginAllowed({
      headers: { host: "codex.example.test", origin: "https://attacker.example" },
    }),
    false,
  );
  assert.equal(
    isBrowserOriginAllowed(
      { headers: { host: "internal:8214", origin: "https://codex.example.test" } },
      "https://codex.example.test",
    ),
    true,
  );
  assert.equal(isBrowserOriginAllowed({ headers: { host: "codex.example.test" } }), false);
});
