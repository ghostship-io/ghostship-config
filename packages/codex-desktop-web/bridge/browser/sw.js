const CACHE_NAME = "codex-desktop-web-v6";

self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(
        names.filter((name) => name !== CACHE_NAME).map((name) => caches.delete(name)),
      ),
    ).then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (
    event.request.method !== "GET" ||
    url.origin !== self.location.origin ||
    url.pathname.startsWith("/__bridge/") ||
    url.pathname === "/health"
  ) {
    return;
  }
  if (event.request.mode === "navigate") {
    event.respondWith(fetch(event.request));
    return;
  }
  event.respondWith(
    caches.open(CACHE_NAME).then(async (cache) => {
      const cached = await cache.match(event.request);
      if (cached) return cached;
      const response = await fetch(event.request);
      if (response.ok) cache.put(event.request, response.clone());
      return response;
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  const notificationId = event.notification.data?.codexNotificationId;
  const actionId = event.action || null;
  event.notification.close();
  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then(async (windowClients) => {
        const client = windowClients[0];
        if (!client) return;
        client.postMessage({
          type: "codex-notification-action",
          notificationId,
          actionId,
        });
        await client.focus();
      }),
  );
});
