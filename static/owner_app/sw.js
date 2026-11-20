/* Owner App service worker. The owner app moved into the DoniaLink App (/dl/app#cashbox): /ecc/owner/app now
   redirects there. This worker stays for the phones that turned notifications on in the old app: it still shows
   them, and a tap opens the DoniaLink App. */
const VERSION = 'owner-app-{{VERSION}}';
const SHELL = [
    '{{ASSET}}/icon-192.png',
    '{{ASSET}}/favicon-32.png',
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

// Push notifications (Web Push sent by Odoo's mail.push queue): session closed, card movements, reviewed
// expenses, explained differences, statements. Tapping one opens the app on the right screen.
self.addEventListener('push', (event) => {
    let data = {};
    try {
        data = event.data ? event.data.json() : {};
    } catch (e) {
        data = { title: event.data ? event.data.text() : '' };
    }
    const options = Object.assign({
        icon: '{{ASSET}}/icon-192.png',
        badge: '{{ASSET}}/favicon-32.png',
        dir: 'auto',
    }, data.options || {});
    if (!options.tag) {
        delete options.tag;
    }
    options.data = Object.assign({ url: '/dl/app#cashbox' }, options.data || {});
    event.waitUntil(self.registration.showNotification(data.title || 'DoniaLink', options));
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    // old links (/ecc/owner/app?box=…) redirect to the DoniaLink App too
    const url = (event.notification.data && event.notification.data.url) || '/dl/app#cashbox';
    const target = new URL(url, self.location.origin);
    if (target.origin !== self.location.origin) {
        return;
    }
    event.waitUntil(self.clients.openWindow(target.href));
});
