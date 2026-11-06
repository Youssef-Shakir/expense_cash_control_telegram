/* Owner App service worker: keeps the app shell for a fast, installable start.
   Money actions (/ecc/owner/api/) always go to the server and are never cached. */
const VERSION = 'owner-app-{{VERSION}}';
const SHELL = [
    '/ecc/owner/app',
    '{{ASSET}}/app.css?v={{VERSION}}',
    '{{ASSET}}/app.js?v={{VERSION}}',
    '{{ASSET}}/icon-192.png',
    '{{ASSET}}/icon-180.png',
    '{{ASSET}}/favicon-32.png',
    '{{ASSET}}/donialink-logo-white.png',
    '{{ASSET}}/fonts/IBMPlexSansArabic-400.woff2',
    '{{ASSET}}/fonts/IBMPlexSansArabic-500.woff2',
    '{{ASSET}}/fonts/IBMPlexSansArabic-600.woff2',
    '{{ASSET}}/fonts/ReadexPro-500.woff2',
    '{{ASSET}}/fonts/ReadexPro-600.woff2',
];

self.addEventListener('install', (event) => {
    event.waitUntil(caches.open(VERSION).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
    event.waitUntil(caches.keys()
        .then((keys) => Promise.all(keys.filter((k) => k.startsWith('owner-app-') && k !== VERSION)
            .map((k) => caches.delete(k))))
        .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
    const request = event.request;
    if (request.method !== 'GET') {
        return;
    }
    const url = new URL(request.url);
    if (url.origin !== self.location.origin || url.pathname.startsWith('/ecc/owner/api/')) {
        return;
    }
    if (request.mode === 'navigate') {
        // network first: a new version shows at once; the cached page opens without internet
        event.respondWith(fetch(request)
            .then((response) => {
                const copy = response.clone();
                if (response.ok) {
                    caches.open(VERSION).then((cache) => cache.put('/ecc/owner/app', copy));
                }
                return response;
            })
            .catch(() => caches.match('/ecc/owner/app')));
        return;
    }
    if (url.pathname.startsWith('{{ASSET}}/')) {
        event.respondWith(caches.match(request).then((hit) => hit || fetch(request).then((response) => {
            const copy = response.clone();
            if (response.ok) {
                caches.open(VERSION).then((cache) => cache.put(request, copy));
            }
            return response;
        })));
    }
});
