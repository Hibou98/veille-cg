const CACHE_NAME = 'veille-cg-v1';
const ASSETS = ['/', '/index.html', '/manifest.json'];

// Installation : mise en cache des assets statiques
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS))
    );
    self.skipWaiting();
});

// Activation : suppression des anciens caches
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
            )
        )
    );
    self.clients.claim();
});

// Fetch : stratégie Network First pour news.json, Cache First pour le reste
self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);

    // news.json : toujours aller chercher le plus récent sur le réseau
    if (url.pathname.endsWith('news.json')) {
        event.respondWith(
            fetch(event.request)
                .then(response => {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                    return response;
                })
                .catch(() => caches.match(event.request))
        );
        return;
    }

    // Autres assets : Cache First
    event.respondWith(
        caches.match(event.request).then(cached => cached || fetch(event.request))
    );
});
