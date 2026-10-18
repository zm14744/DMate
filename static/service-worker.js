const CACHE_NAME = "dmate-pwa-unified-v11-20261019";
const SHELL_ASSETS = [
  "/",
  "/pwa/",
  "/manifest.webmanifest",
  "/favicon.ico",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/icon-maskable-512.png",
  "/static/icons/dmate-mark.svg",
  "/static/icons/dmate-transparent.svg",
  "/static/icons/dmate-favicon-mac-light.svg?v=mac-favicon-v7-20261019&mode=light",
  "/static/icons/dmate-favicon-mac-dark.svg?v=mac-favicon-v7-20261019&mode=dark",
  "/static/icons/dmate-favicon-mac.svg?v=mac-adaptive-lines-v4-20261019",
  "/static/icons/apple-touch-icon.png",
  "/static/icons/apple-touch-mac-light.png?v=mac-touch-light-v5-20261019",
  "/static/icons/apple-touch-mac-dark.png?v=mac-touch-dark-v5-20261019",
  "/static/icons/favicon-32.png",
  "/static/icons/favicon-32.png?v=dmate-favicon-v6-20261019",
  "/static/icons/favicon-128.png",
  "/static/icons/favicon-128.png?v=dmate-favicon-v6-20261019",
  "/static/icons/icon-192.png?v=dmate-pwa-unified-v11-20261019",
  "/static/icons/icon-512.png?v=dmate-pwa-unified-v11-20261019",
  "/static/icons/icon-maskable-512.png?v=dmate-pwa-unified-v11-20261019"
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
