// Creek Watch service worker: app shell cache-first, API network-first with
// a cached fallback for GETs. POSTs (reports) always go to the network; the
// page keeps its own offline outbox in IndexedDB.
const VERSION = 'cw-v4';
const SHELL = [
  './', 'index.html', 'css/app.css', 'manifest.webmanifest',
  'js/app.js', 'js/api.js', 'js/ui.js', 'js/icons.js', 'js/store.js',
  'js/report.js', 'js/map.js', 'js/dashboard.js', 'js/alerts.js', 'js/subscribe.js',
  'icons/favicon.svg', 'icons/icon-192.png', 'icons/icon-512.png', 'icons/badge-96.png',
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

/* ---------- Web Push (docs/ALERTS-SPEC.md) ---------- */
// Payload: {alert_id, title, body, severity, url:"/#alerts?id=…", tag}. Anything malformed still
// shows a generic, safe notification: a push must always produce a visible notification.
const SEV_LABEL = { alert: 'Alert', watch: 'Watch', advisory: 'Advisory', info: 'Info' };

function safeTarget(u) {
  try {
    const x = new URL(u || '/#alerts', self.location.origin);
    return x.origin === self.location.origin ? x.href : new URL('/#alerts', self.location.origin).href; // never open off-site
  } catch { return new URL('/#alerts', self.location.origin).href; }
}

self.addEventListener('push', (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { d = { body: e.data ? e.data.text() : '' }; }
  const sev = SEV_LABEL[d.severity] ? d.severity : 'info';
  const title = String(d.title || 'Creek Watch alert').slice(0, 120);
  const body = String(d.body || 'Open Creek Watch for details.').slice(0, 240);
  e.waitUntil(self.registration.showNotification(`${SEV_LABEL[sev]}: ${title}`, {
    body,
    tag: String(d.tag || d.alert_id || 'creekwatch'),
    renotify: sev === 'alert',
    requireInteraction: sev === 'alert',
    icon: 'icons/icon-192.png',
    badge: 'icons/badge-96.png',
    data: { url: safeTarget(d.url || (d.alert_id ? `/#alerts?id=${encodeURIComponent(d.alert_id)}` : '/#alerts')), alert_id: d.alert_id || null },
  }));
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const target = safeTarget(e.notification.data && e.notification.data.url);
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const w of wins) {
      if (new URL(w.url).origin === self.location.origin) {
        await w.focus();
        try { await w.navigate(target); } catch { w.postMessage({ type: 'open', url: target }); }
        return;
      }
    }
    await self.clients.openWindow(target);
  })());
});

// The push service rotated our subscription: re-subscribe and re-register the saved filters.
self.addEventListener('pushsubscriptionchange', (e) => {
  e.waitUntil((async () => {
    const old = e.oldSubscription;
    const key = old && old.options && old.options.applicationServerKey;
    const sub = e.newSubscription || (key ? await self.registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key }) : null);
    if (!sub) return;
    const filters = await new Promise((res) => {
      const r = indexedDB.open('creekwatch', 1);
      r.onsuccess = () => { try { const g = r.result.transaction('kv').objectStore('kv').get('push-filters'); g.onsuccess = () => res(g.result || null); g.onerror = () => res(null); } catch { res(null); } };
      r.onerror = () => res(null);
    });
    if (!filters) return;
    if (old) await fetch('/api/push/unsubscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ endpoint: old.endpoint }) }).catch(() => {});
    await fetch('/api/push/subscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ subscription: sub.toJSON(), filters }) }).catch(() => {});
  })());
});
