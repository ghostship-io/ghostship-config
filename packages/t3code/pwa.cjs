const { readFileSync } = require("node:fs");
const path = require("node:path");

const prefix = "/__t3_pwa/";
const manifest = {
  id: "/",
  name: "T3 Code",
  short_name: "T3 Code",
  description: "Your Ghostship coding workspace, projects, and agents.",
  start_url: "/",
  scope: "/",
  display: "standalone",
  background_color: "#161616",
  theme_color: "#161616",
  prefer_related_applications: false,
  icons: [192, 512].flatMap((size) => ["any", "maskable"].map((purpose) => ({
    src: `${prefix}icon-${size}-v1.png`, sizes: `${size}x${size}`, type: "image/png", purpose,
  }))),
};
const resources = new Map([
  ["/manifest.webmanifest", [Buffer.from(JSON.stringify(manifest)), "application/manifest+json"]],
  ...["register.js", "sw.js", "icon-192-v1.png", "icon-512-v1.png"].map((name) => [
    prefix + name,
    [readFileSync(path.join(__dirname, "pwa", name)), name.endsWith(".png") ? "image/png" : "text/javascript"],
  ]),
]);

function servePwa(request, response) {
  const resource = resources.get(request.url.split("?")[0]);
  if (!resource) return false;
  if (!["GET", "HEAD"].includes(request.method)) {
    response.writeHead(405, { allow: "GET, HEAD" }).end();
    return true;
  }
  const [body, type] = resource;
  response.writeHead(200, {
    "content-type": type,
    "content-length": body.length,
    "cache-control": type === "image/png" ? "public, max-age=86400" : "no-cache",
    "x-content-type-options": "nosniff",
    ...(request.url.split("?")[0] === `${prefix}sw.js` ? { "service-worker-allowed": "/" } : {}),
  });
  response.end(request.method === "HEAD" ? undefined : body);
  return true;
}

function enhanceHtml(html) {
  // A manifest fetch needs Access cookies even though it is same-origin.
  const head = '<link rel="manifest" href="/manifest.webmanifest" crossorigin="use-credentials">' +
    `<script defer src="${prefix}register.js"></script>`;
  return html.replace(/<link\b(?=[^>]*\brel\s*=\s*["']manifest["'])[^>]*>/gi, "")
    .replace(/<\/head\s*>/i, `${head}</head>`);
}

module.exports = { servePwa, enhanceHtml, manifest };
