self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(
        names.filter((name) => name.startsWith("codex-desktop-web-")).map((name) => caches.delete(name)),
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
  // The app needs its live host; a stale cached renderer can speak the wrong
  // IPC contract after an upgrade. Normal HTTP caching handles hashed assets.
  event.respondWith(fetch(event.request));
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
