// Network-only: never retain account pages, clipboard data, or workstation traffic.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
