// Creek Watch service worker: app shell cache-first, API network-first with
// a cached fallback for GETs. POSTs (reports) always go to the network; the
// page keeps its own offline outbox in IndexedDB.
const VERSION = 'cw-v3';
const SHELL = [
  './', 'index.html', 'css/app.css', 'manifest.webmanifest',
  'js/app.js', 'js/api.js', 'js/ui.js', 'js/icons.js', 'js/store.js',
  'js/report.js', 'js/map.js', 'js/dashboard.js',
  'icons/favicon.svg', 'icons/icon-192.png', 'icons/icon-512.png',
];

// Always revalidate with the server, past the browser's HTTP cache: Cloudflare's zone Browser Cache TTL
// stamped max-age=14400 on our assets before 2026-10-03, so phones may still hold 4-hour copies.
// (A navigate-mode Request can't take a RequestInit, so navigations use plain fetch; HTML is no-cache.)
const fresh = (req) => (req.mode === 'navigate' ? fetch(req) : fetch(req, { cache: 'no-cache' }));

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(VERSION)
      .then((c) => c.addAll(SHELL.map((u) => new Request(u, { cache: 'reload' }))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return; // tiles, CDN: browser default

  if (url.pathname.startsWith('/api/')) {
    e.respondWith(
      fresh(req)
        .then((res) => {
          if (res.ok) { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(req, copy)); }
          return res;
        })
        .catch(() => caches.match(req).then((r) => r || Response.error()))
    );
    return;
  }
  // Shell: stale-while-revalidate so deploys show up on the next load.
  e.respondWith(
    caches.match(req, { ignoreSearch: true }).then((cached) => {
      const net = fresh(req)
        .then((res) => {
          if (res.ok && res.type === 'basic') { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(req, copy)); }
          return res;
        })
        .catch(() => cached);
      return cached || net;
    })
  );
});
