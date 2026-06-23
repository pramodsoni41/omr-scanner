// Minimal service worker for "Add to Home Screen". Caches only the static shell
// (same-origin GETs); all backend calls go straight to the network (cross-origin).
const CACHE = "omr-shell-v1";
const SHELL = ["./", "index.html", "manifest.webmanifest", "icon.svg"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== self.location.origin) return;
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
