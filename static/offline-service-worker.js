"use strict";
const CACHE_NAME = "dmate-offline-shell-v4";
const PRECACHE = [
  "/offline",
  "/static/dmate-main.css?v=4",
  "/static/dmate-shared-overrides.css?v=4",
  "/static/offline.css?v=4",
  "/static/offline.js?v=4",
  "/static/offline-shell.js?v=4",
  "/static/offline-knowledge-graph.js?v=4",
  "/static/offline-knowledge-graph.css?v=4",
  "/static/offline-entry.js",
  "/static/icons/dmate-brand-v52.svg",
  "/static/offline-content/concepts.zh-CN.json",
  "/static/offline-content/questions.zh-CN.json",
  "/static/offline-content/knowledge_graph.json",
  "/static/graph-editor.css",
  "/static/drawing-workspace.css",
  "/static/modal-chrome.css",
  "/static/concept-notebook.css",
  "/static/button-themes.css",
  "/static/ai-answer-renderer.css",
  "/static/red-circle-controls.css",
  "/static/ui-tooltip.css",
  "/static/ui-tooltip.js",
  "/static/graph-editor-model.js",
  "/static/graph-editor-format.js",
  "/static/graph-editor-overlay.js",
  "/static/ai-answer-renderer.js",
  "/static/delete-confirm.js",
  "/static/drawing-export.js",
  "/static/graph-editor.js",
  "/static/drawing-workspace.js",
  "/static/vendor/marked-15.0.12/marked.umd.js",
  "/static/vendor/dompurify-3.2.6/purify.min.js",
  "/static/vendor/mathjax-3.2.2/es5/tex-svg.js",
  "/static/vendor/mathjax-3.2.2/es5/output/svg/fonts/tex.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/action.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/all-packages.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/ams.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/amscd.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/autoload.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/bbox.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/boldsymbol.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/braket.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/bussproofs.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/cancel.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/cases.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/centernot.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/color.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/colortbl.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/colorv2.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/configmacros.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/empheq.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/enclose.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/extpfeil.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/gensymb.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/html.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/mathtools.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/mhchem.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/newcommand.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/noerrors.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/noundefined.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/physics.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/require.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/setoptions.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/tagformat.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/textcomp.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/textmacros.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/unicode.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/upgreek.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/verb.js"
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
        const cache = await caches.open(CACHE_NAME);
        const cached = await cache.match("/offline");
        if (cached) return cached;
        return new Response(
          "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>DMate 离线</title><body><p>离线学习资源尚未准备。请在有网络时打开 DMate 并进入离线版完成准备。</p></body></html>",
          {headers:{"Content-Type":"text/html; charset=utf-8"},status:503}
        );
      }
    })());
    return;
  }

  const canonicalPath = PRECACHE.find(path => new URL(path, self.location.origin).pathname === url.pathname);
  if (canonicalPath) {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE_NAME);
      const canonicalURL = new URL(canonicalPath, self.location.origin).href;
      // The offline shell pins its assets. Online pages use revision queries:
      // fetch those fresh instead of letting an old offline copy mask updates.
      if (url.href === canonicalURL) {
        const cached = await cache.match(request);
        if (cached) return cached;
      }
      try {
        const response = await fetch(request);
        if (response && response.ok) {
          // A cache write failure must not replace a fresh network response.
          await cache.put(request, response.clone()).catch(() => {});
        }
        return response;
      } catch (error) {
        const cached = await cache.match(request) || await cache.match(canonicalURL);
        if (cached) return cached;
        throw error;
      }
    })());
  }
});
