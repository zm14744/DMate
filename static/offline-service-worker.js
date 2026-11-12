"use strict";
const CACHE_NAME = "dmate-offline-shell-v2";
const PRECACHE = [
  "/offline",
  "/static/dmate-main.css?v=1",
  "/static/offline.css?v=2",
  "/static/icons/dmate-brand-v52.svg",
  "/static/offline.js?v=2",
  "/static/offline-content/concepts.zh-CN.json",
  "/static/offline-content/questions.zh-CN.json",
  "/static/offline-content/knowledge_graph.json",
  "/static/graph-editor.css",
  "/static/drawing-workspace.css",
  "/static/modal-chrome.css",
  "/static/graph-editor-model.js",
  "/static/graph-editor-format.js",
  "/static/graph-editor-overlay.js",
  "/static/ai-answer-renderer.js",
  "/static/delete-confirm.js",
  "/static/drawing-export.js",
  "/static/graph-editor.js",
  "/static/drawing-workspace.js"
];

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    await cache.addAll(PRECACHE);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(key => key.startsWith("dmate-offline-shell-") && key !== CACHE_NAME)
      .map(key => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith((async () => {
      try {
        const response = await fetch(request);
        if (response && response.ok && url.pathname === "/offline") {
          const cache = await caches.open(CACHE_NAME);
          await cache.put("/offline", response.clone());
        }
        return response;
      } catch (_) {
        const cached = await caches.match("/offline");
        if (cached) return cached;
        return new Response(
          "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>DMate 离线</title><body><p>离线学习资源尚未准备。请在有网络时打开 DMate 并进入离线版完成准备。</p></body></html>",
          {headers:{"Content-Type":"text/html; charset=utf-8"},status:503}
        );
      }
    })());
    return;
  }

  if (PRECACHE.some(path => new URL(path, self.location.origin).pathname === url.pathname)) {
    event.respondWith((async () => {
      const cached = await caches.match(request) || await caches.match(url.pathname);
      if (cached) return cached;
      const response = await fetch(request);
      if (response && response.ok) {
        const cache = await caches.open(CACHE_NAME);
        await cache.put(request, response.clone());
      }
      return response;
    })());
  }
});