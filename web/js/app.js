// Router + app shell. Hash routes: #report #map #dashboard #about
import { icon } from './icons.js';
import { MOCK } from './api.js';
import { mountReport, bindReport } from './report.js';

const PAGES = ['report', 'map', 'dashboard', 'about'];
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
  const titles = { report: 'Report', map: 'Map', dashboard: 'Creeks', about: 'About the data' };
  document.title = `${titles[page]} · Creek Watch`;

  if (page === 'report' && !mounted.has(page)) {
    bindReport(el);
    mountReport(el);
  } else if (page === 'map') {
    const first = !mounted.has('map');
    import('./map.js').then((m) => (first ? m.mountMap(el, qs) : m.showMap(qs)));
  } else if (page === 'dashboard' && !mounted.has(page)) {
    import('./dashboard.js').then((m) => m.mountDashboard(el));
  }
  mounted.add(page);
}

addEventListener('hashchange', route);
route();

if ('serviceWorker' in navigator && !MOCK && location.protocol !== 'file:') {
  addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));
}
