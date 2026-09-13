const CACHE = 'photo-curator-v2';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(
  caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim())
));

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  // Network-first: always try to fetch fresh, fall back to cache when offline
  e.respondWith(
    fetch(e.request).then(res => {
      // Only cache real, cacheable responses — opaque/error responses would
      // otherwise be served back as the offline copy.
      if (res.ok && res.type === 'basic') {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy));
      }
      return res;
    }).catch(() => caches.match(e.request))
  );
});
