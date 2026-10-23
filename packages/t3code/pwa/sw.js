// Network-only: never retain private code, messages, credentials, or old bundles.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate" || event.request.method !== "GET") return;
  event.respondWith(fetch(event.request).catch(() => new Response(`<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#161616"><title>T3 Code · Offline</title>
<style>html{color-scheme:dark;background:#161616;color:#fafafa;font:17px system-ui}body{margin:0;min-height:100dvh;display:grid;place-items:center}main{max-width:28rem;padding:2rem}h1{font-size:2rem}p{line-height:1.6;color:#bbb}a{display:inline-block;padding:.75rem 1.25rem;background:#fafafa;color:#161616;border-radius:.6rem;text-decoration:none}</style></head>
<body><main><h1>T3 Code is offline</h1><p>Reconnect to the internet to return to your workspace. Your projects and agents remain on the server.</p><a href="/">Try again</a></main></body></html>`, {
    headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" },
  })));
});
