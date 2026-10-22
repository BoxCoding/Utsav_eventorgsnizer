// Utsav service worker: instant repeat loads and an offline shell.
// - /v/<build>/… assets are immutable (the URL changes on every deploy): cache-first.
// - Pages: network-first, falling back to the last cached copy when offline.
// - /api/…: never cached (plans, budgets and auth must always be live).
const CACHE = 'utsav-v1';

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(['/'])).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;

  if (url.pathname.startsWith('/v/') || url.pathname.startsWith('/icons/')) {
    event.respondWith(caches.match(request).then((hit) => hit || fetch(request).then((res) => {
      if (res.ok) caches.open(CACHE).then((c) => c.put(request, res.clone()));
      return res;
    })));
    return;
  }
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).then((res) => {
      caches.open(CACHE).then((c) => c.put('/', res.clone()));
      return res;
    }).catch(() => caches.match('/')));
  }
});
