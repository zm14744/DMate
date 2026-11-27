"use strict";
const CACHE_NAME = "dmate-offline-shell-v155";
const PREVIOUS_CACHE_NAME = "dmate-offline-shell-v154";
const CACHE_READY = "/__dmate_offline_ready__/"+CACHE_NAME;
const PRECACHE = [
  "/static/appearance-bootstrap.js?v=5",
  "/static/offline-appearance-preload.js?v=1",
  "/offline",
  "/static/icons/dmate-app-v52.ico",
  "/static/icons/dmate-app-v52-16.png",
  "/static/icons/dmate-app-v52-32.png",
  "/static/icons/dmate-app-v52-48.png",
  "/static/icons/dmate-app-v52-192.png",
  "/static/icons/dmate-app-v52-180.png",
  "/static/dmate-main.css?v=97",
  "/static/graph-editor.css?v=29",
  "/static/drawing-workspace.css?v=60",
  "/static/modal-chrome.css",
  "/static/concept-notebook.css?v=16",
  "/static/ai-answer-renderer.css?v=22",
  "/static/red-circle-controls.css",
  "/static/ui-tooltip.css",
  "/static/appearance-panels.css?v=4",
  "/static/dmate-shared-overrides.css?v=26",
  "/static/button-themes.css?v=72",
  "/static/offline-knowledge-graph.css?v=56",
  "/static/knowledge-graph-sheet.css?v=8",
  "/static/offline.css?v=78",
  "/static/search-controls.css?v=30",
  "/static/search-controls.js?v=29",
  "/static/select-controls.css?v=46",
  "/static/control-focus.js?v=1",
  "/static/mobile-select.js?v=26",
  "/static/textarea-autosize.css?v=1",
  "/static/textarea-autosize.js?v=1",
  "/static/scrollbars.css?v=27",
  "/static/scrollbars.js?v=27",
  "/static/graph-editor-model.js",
  "/static/graph-editor-format.js?v=32",
  "/static/graph-editor-overlay.js?v=43",
  "/static/math-markdown.js?v=23",
  "/static/ai-answer-renderer.js?v=22",
  "/static/modal-text.js?v=53",
  "/static/delete-confirm.js",
  "/static/drawing-export.js?v=39",
  "/static/graph-editor.js?v=56",
  "/static/drawing-workspace.js?v=65",
  "/static/vendor/mathjax-3.2.2/es5/tex-svg.js",
  "/static/vendor/marked-15.0.12/marked.umd.js",
  "/static/vendor/dompurify-3.2.6/purify.min.js",
  "/static/ui-tooltip.js?v=50",
  "/static/guest-session.js?v=53",
  "/static/offline-interface-state.js?v=1",
  "/static/language-catalog.js?v=76",
  "/static/language-knowledge.js",
  "/static/language.js?v=59",
  "/static/knowledge-graph-labels.js?v=22",
  "/static/knowledge-graph-sheet.js?v=6",
  "/static/knowledge-graph-desktop.js?v=1",
  "/static/offline-appearance.js?v=15",
  "/static/offline-privacy-motion.js?v=4",
  "/static/offline-shell.js?v=42",
  "/static/offline-knowledge-graph.js?v=70",
  "/static/offline-vault.js?v=2",
  "/static/offline-handoff.js?v=1",
  "/static/offline-storage.js?v=4",
  "/static/vendor/fflate-0.8.2/fflate.min.js",
  "/static/offline-backup.js?v=3",
  "/static/backup-download.js?v=1",
  "/static/offline-entry.js?v=50",
  "/static/notebook-sheet.js?v=3",
  "/static/offline.js?v=84",
  "/static/offline-content/concepts.zh-CN.json?v=34",
  "/static/offline-content/questions.zh-CN.json?v=34",
  "/static/offline-content/knowledge_graph.json?v=28",
  "/static/offline-content/translations.en.json?v=34",
  "/static/offline-content/references.zh-CN.json",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/action.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/all-packages.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/amscd.js",
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
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/empheq.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/enclose.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/extpfeil.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/gensymb.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/html.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/mathtools.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/mhchem.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/noerrors.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/physics.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/setoptions.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/tagformat.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/textcomp.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/textmacros.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/unicode.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/upgreek.js",
  "/static/vendor/mathjax-3.2.2/es5/input/tex/extensions/verb.js",
  "/static/icons/dmate-tab-black-v52.ico",
  "/static/icons/dmate-tab-black-v52-64.png",
  "/static/icons/dmate-tab-black-v52.svg",
  "/static/icons/dmate-tab-white-v52.ico",
  "/static/icons/dmate-tab-white-v52-32.png",
  "/static/icons/dmate-tab-white-v52.svg",
  "/static/icons/dmate-app-v52-64.png",
  "/static/icons/dmate-search-v53.ico",
  "/static/icons/dmate-search-v53-16.png",
  "/static/icons/dmate-search-v53-32.png",
  "/static/icons/dmate-search-v53-48.png",
  "/static/icons/dmate-search-v53-64.png",
  "/static/icons/dmate-search-v53-96.png",
  "/static/icons/dmate-search-v53-192.png",
  "/static/icons/dmate-bing-v55.ico",
  "/static/icons/dmate-bing-v55-16.png",
  "/static/icons/dmate-bing-v55-32.png",
  "/static/icons/dmate-bing-v55-48.png",
  "/static/icons/dmate-bing-v55-64.png",
  "/static/icons/dmate-bing-v55-96.png",
  "/static/icons/dmate-bing-v55-192.png"
];

function immutableAsset(path) {
  const url = new URL(path,self.location.origin);
  // App revisions must be bumped when their content changes. Never promote an
  // online revision URL to an unrelated offline key or reuse unversioned code.
  return url.pathname.startsWith("/static/") && (url.searchParams.has("v")
    || /^\/static\/vendor\/[^/]+-\d[^/]*\//.test(url.pathname)
    || /^\/static\/icons\/[^/]*-v\d/.test(url.pathname));
}

async function prepareCache() {
  const cache = await caches.open(CACHE_NAME);
  const previous = (await caches.keys()).includes(PREVIOUS_CACHE_NAME) ? await caches.open(PREVIOUS_CACHE_NAME) : null;
  const reusePrevious = previous && !!await previous.match("/__dmate_offline_ready__/"+PREVIOUS_CACHE_NAME);
  const currentURLs = new Set((await cache.keys()).map(request => request.url));
  const previousURLs = new Set(reusePrevious ? (await previous.keys()).map(request => request.url) : []);
  const pending = [];
  await Promise.all(PRECACHE.map(async path => {
    if (immutableAsset(path)) {
      const href = new URL(path,self.location.origin).href;
      const current = currentURLs.has(href) && await cache.match(href);
      if (current?.ok) return;
      const reusable = previousURLs.has(href) && await previous.match(href);
      if (reusable?.ok) { await cache.put(href,reusable); return; }
    }
    // The HTML, changed versions and unversioned app code always reach the
    // current deployment. A failed update leaves the old complete cache intact.
    pending.push(path);
  }));
  if (pending.length) await cache.addAll(pending);
  await cache.put(CACHE_READY,new Response("ready"));
}

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    await prepareCache();
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

let preparingCache = null;
self.addEventListener("message",event => {
  if (event.data?.type !== "dmate:prepare-offline") return;
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    // Installation populates this cache atomically. Repair a cleared cache
    // once on reconnection instead of downloading the study pack on every load.
    if (!await cache.match(CACHE_READY)) {
      if (!preparingCache) preparingCache = prepareCache().finally(() => { preparingCache = null; });
      await preparingCache;
    }
    for (const client of await self.clients.matchAll({type:"window",includeUncontrolled:true}))
      client.postMessage({type:"dmate:offline-ready"});
  })().catch(() => {}));
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
        if (cached && await cache.match(CACHE_READY)) {
          // Serving offline HTML under '/' leaves native vault authorization
          // on the wrong path. Redirect once, then serve the canonical shell.
          if (url.pathname !== "/offline") return Response.redirect(new URL("/offline",self.location.origin).href,302);
          return cached;
        }
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
