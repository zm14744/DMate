/*
 * Legacy DMate worker retirement only.  PWA was removed on 2026-10-19.
 * Never cache, intercept fetch, or register a replacement service worker.
 * This script is served at the ORIGINAL /service-worker.js URL so existing
 * Android/desktop/web clients can update their old worker automatically.
 */
'use strict';

self.addEventListener('install', event => {
    event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', event => {
    event.waitUntil((async () => {
        try {
            const keys = await caches.keys();
            await Promise.all(keys.filter(key => /^dmate-pwa-/i.test(key))
                .map(key => caches.delete(key)));
        } catch (_error) {
            // CacheStorage can be unavailable; retirement still must proceed.
        }
        try {
            await self.registration.unregister();
        } catch (_error) {}
        try {
            const clients = await self.clients.matchAll({
                type:'window', includeUncontrolled:true
            });
            // Existing pages may be mid-edit.  Notify, never forcibly navigate
            // them; their next navigation now uses the live Zeabur resources.
            for (const client of clients) {
                client.postMessage({ type:'dmate-old-worker-retired' });
            }
        } catch (_error) {}
    })());
});
