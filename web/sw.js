// Creek Watch service worker: app shell cache-first, API network-first with
// a cached fallback for GETs. POSTs (reports) always go to the network; the
// page keeps its own offline outbox in IndexedDB.
importScripts('js/idb-schema.js');
const VERSION = 'cw-v14';
const SHELL = [
  './', 'index.html', 'css/app.css', 'manifest.webmanifest',
  'js/app.js', 'js/api.js', 'js/ui.js', 'js/icons.js', 'js/store.js',
  'js/report.js', 'js/map.js', 'js/dashboard.js', 'js/alerts.js', 'js/subscribe.js', 'js/idb-schema.js', 'js/badges.js',
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

/* ---------- Web Push (docs/ALERTS-SPEC.md, contract from the api lane) ---------- */
// Payload: {id, kind:"new"|"escalated", severity, category, title, summary, source_name, url:"/#alerts", source_url, creek_ids}.
// Untrusted: everything is treated as plain text; the target URL must be same-origin. A push must always
// produce a visible notification, so malformed payloads fall back to a generic one.
const SEV_LABEL = { alert: 'ALERT', watch: 'WATCH', advisory: 'ADVISORY', info: 'INFO' };
const OFFICIAL_SUFFIX = ' · Emergencies: Nevada County Alerts, AwareCA, 911.';

function safeTarget(u) {
  try {
    const x = new URL(u || '/#alerts', self.location.origin);
    return x.origin === self.location.origin ? x.href : new URL('/#alerts', self.location.origin).href; // never open off-site
  } catch { return new URL('/#alerts', self.location.origin).href; }
}

self.addEventListener('push', (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { d = { summary: e.data ? e.data.text() : '' }; }
  if (!d || typeof d !== 'object') d = {};
  const sev = SEV_LABEL[d.severity] ? d.severity : 'info';
  const id = d.id || d.alert_id || null;
  const title = String(d.title || 'Creek Watch alert').slice(0, 110);
  let body = String(d.summary || d.body || 'Open Creek Watch for details.').slice(0, 200);
  // Never imply we replace official warnings: use the backend's notice when sent, else our own line (alert level).
  // Skip it when the body already carries the deferral (e.g. kind "welcome"), so it's never said twice.
  const welcome = d.kind === 'welcome';
  const hasDeferral = /Nevada County Alerts/i.test(body);
  if (!welcome && !hasDeferral) {
    if (typeof d.notice === 'string' && d.notice) body += ' · ' + d.notice.slice(0, 120);
    else if (sev === 'alert') body += OFFICIAL_SUFFIX;
  }
  // Backend sends url "/#alerts?id=<id>" (same-origin enforced below); build it from id if it doesn't. source_url is ignored.
  // Prefer the backend's url (alerts: "/#alerts?id=…"; welcome: "/#alerts"); build from id only if none was sent.
  const deep = typeof d.url === 'string' && d.url ? d.url : id ? `/#alerts?id=${encodeURIComponent(id)}` : '/#alerts';
  // A welcome is a confirmation, not an alert: no severity prefix, never sticky or re-alerting.
  e.waitUntil(self.registration.showNotification(welcome ? title : `${SEV_LABEL[sev]}: ${title}`, {
    body,
    tag: String(d.tag || id || 'creekwatch'),        // same tag/id → an escalation replaces the earlier notification
    renotify: !welcome && (sev === 'alert' || d.kind === 'escalated'),
    requireInteraction: !welcome && sev === 'alert',
    icon: 'icons/icon-192.png',
    badge: 'icons/badge-96.png',
    data: { url: safeTarget(deep), id },
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
      const r = indexedDB.open(self.CW_IDB.NAME, self.CW_IDB.VERSION);
      r.onupgradeneeded = () => self.CW_IDB.upgrade(r.result); // same schema as the page: never an empty DB
      r.onsuccess = () => { try { const g = r.result.transaction('kv').objectStore('kv').get('push-filters'); g.onsuccess = () => res(g.result || null); g.onerror = () => res(null); } catch { res(null); } };
      r.onerror = () => res(null);
    });
    if (!filters) return;
    if (old) await fetch('/api/push/subscriptions', { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ endpoint: old.endpoint }) }).catch(() => {});
    const { creek_ids = [], min_severity = 'watch', quiet_hours = null } = filters;
    await fetch('/api/push/subscriptions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ subscription: sub.toJSON(), creek_ids, min_severity, quiet_hours }) }).catch(() => {});
  })());
});
