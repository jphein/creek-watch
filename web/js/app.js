// Router + app shell. Hash routes: #report #map #alerts #dashboard #about
import { icon } from './icons.js';
import { MOCK, getAlerts } from './api.js';
import { mountReport, bindReport } from './report.js';

const PAGES = ['report', 'map', 'alerts', 'dashboard', 'about'];
const mounted = new Set();

document.querySelectorAll('[data-ico]').forEach((el) => (el.innerHTML = icon[el.dataset.ico] || ''));
if (MOCK) document.getElementById('mock-badge').hidden = false;

// Keep ?mock=… when navigating by hash.
function defaultPage() {
  return matchMedia('(max-width: 760px)').matches ? 'report' : 'dashboard';
}

export function route() {
  const [name, query] = (location.hash.slice(1) || defaultPage()).split('?');
  const page = PAGES.includes(name) ? name : defaultPage();
  const qs = new URLSearchParams(query || '');
  for (const p of PAGES) document.getElementById(`page-${p}`).hidden = p !== page;
  document.querySelectorAll('.tabbar a').forEach((a) => {
    if (a.dataset.page === page) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  document.body.dataset.page = page;
  const el = document.getElementById(`page-${page}`);
  const titles = { report: 'Report', map: 'Map', alerts: 'Alerts', dashboard: 'Creeks', about: 'About the data' };
  document.title = `${titles[page]} · Creek Watch`;

  if (page === 'report' && !mounted.has(page)) {
    bindReport(el);
    mountReport(el);
  } else if (page === 'map') {
    const first = !mounted.has('map');
    import('./map.js').then((m) => (first ? m.mountMap(el, qs) : m.showMap(qs)));
  } else if (page === 'alerts') {
    const first = !mounted.has('alerts');
    import('./alerts.js').then((m) => (first ? m.mountAlerts(el, qs) : m.showAlerts(qs)));
  } else if (page === 'dashboard') {
    // Refresh on every visit so a just-sent report shows up (no stale scores).
    const first = !mounted.has('dashboard');
    import('./dashboard.js').then((m) => m.mountDashboard(el, { refresh: !first }));
  }
  mounted.add(page);
}

addEventListener('hashchange', route);
route();

if ('serviceWorker' in navigator && !MOCK && location.protocol !== 'file:') {
  addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));
}

// Alerts tab badge: count of active Alert + Watch items (never colour alone: it's a number).
export async function refreshAlertBadge() {
  const b = document.getElementById('alerts-badge');
  try {
    const n = (await getAlerts()).filter((a) => a.severity === 'alert' || a.severity === 'watch').length;
    b.textContent = n > 9 ? '9+' : String(n);
    b.hidden = n === 0;
    b.setAttribute('aria-label', `${n} active alert${n === 1 ? '' : 's'}`);
  } catch { b.hidden = true; }
}
refreshAlertBadge();

// Fallback when the service worker can't navigate an existing window after a notification tap.
navigator.serviceWorker?.addEventListener('message', (e) => {
  if (e.data?.type === 'open' && typeof e.data.url === 'string') {
    const u = new URL(e.data.url, location.origin);
    if (u.origin === location.origin) location.hash = u.hash || '#alerts';
  }
});
