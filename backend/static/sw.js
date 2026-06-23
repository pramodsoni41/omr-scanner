// Minimal service worker — makes the app installable ("Add to Home Screen").
// Network-first: we always want fresh results from the backend; the shell is
// just cached as a fallback when offline.
const CACHE = "omr-shell-v1";
const SHELL = ["/", "/manifest.webmanifest", "/static/icon.svg"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  // never cache API calls (generate/grade/key/downloads)
  if (e.request.method !== "GET" || url.pathname.startsWith("/exams") ||
      url.pathname === "/generate") return;
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
