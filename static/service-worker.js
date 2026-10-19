const CACHE_NAME = "dmate-pwa-icons-v21-20261019";
const SHELL_ASSETS = [
  "/",
  "/pwa/",
  "/manifest.webmanifest",
  "/manifest-mobile.webmanifest",
  "/favicon.ico",
  "/static/icons/dmate-transparent.svg",
  "/static/icons/dmate-favicon-mac.svg?v=dmate-tab-v21-20261019",
  "/static/icons/favicon-32.png?v=dmate-tab-v21-20261019",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/apple-touch-icon.png",
  "/static/icons/windows-shortcut-192-v20.png",
  "/static/icons/mobile-favicon-32-v17.png",
  "/static/icons/mobile-favicon-192-v17.png",
  "/static/icons/android-edge-32-v21.png",
  "/static/icons/android-edge-192-v21.png",
  "/static/icons/android-edge-512-v21.png",
  "/static/icons/android-fennec-32-v21.png",
  "/static/icons/android-fennec-192-v21.png",
  "/static/icons/android-fennec-512-v21.png"
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  const cacheable = url.pathname === "/" || url.pathname === "/pwa/" || url.pathname.startsWith("/static/");
  if (!cacheable) return;

  event.respondWith((async () => {
    try {
      const response = await fetch(request, { cache: "no-store" });
      if (response && response.ok) {
        const cache = await caches.open(CACHE_NAME);
        cache.put(request, response.clone()).catch(() => {});
      }
      return response;
    } catch (_error) {
      const cached = await caches.match(request);
      if (cached) return cached;
      if (request.mode === "navigate") {
        const shell = await caches.match("/");
        if (shell) return shell;
      }
      throw _error;
    }
  })());
});
