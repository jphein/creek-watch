// Source layer control (web/js/sources.js): every map marker belongs to exactly one source layer; each chip
// hides/shows its layer; the Sources panel lists every source with escaped, https-only credit links; a
// report deep link re-enables Reports; mobile layout clears the zoom control. SHOTS=<dir>: 390x844 light/dark.
import fs from 'node:fs';
import { serveWeb, launch, mock } from './harness.mjs';

const SHOTS = process.env.SHOTS || '';
const { base, close } = await serveWeb();
const b = await launch();
const json = (body, status = 200) => ({ status, contentType: 'application/json', body: typeof body === 'string' ? body : JSON.stringify(body) });
const COND = JSON.parse(mock('conditions'));
const HIST = JSON.parse(fs.readFileSync(new URL('./fixtures/wolf-history-109.json', import.meta.url), 'utf8'));
const KEYS = ['reports', 'wq', 'swim', 'study', 'usgs', 'cdec', 'alerts'];
const wolf = { ...COND.wolf, bacteria_history: HIST, gauge: { ...(COND.deer.gauge || {}), site_no: '11424000', name: 'BEAR R NR WHEATLAND CA', on_creek: false } };
const deer = COND.deer;
const REPORTS = JSON.parse(mock('reports'));
const R = {};

async function page(scheme, before) {
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, colorScheme: scheme, serviceWorkers: 'block' });
  await ctx.route('**/api/**', (r) => {
    const u = new URL(r.request().url());
    if (r.request().method() !== 'GET') return r.abort();
    if (u.pathname === '/api/creeks') return r.fulfill(json(mock('creeks')));
    if (u.pathname === '/api/conditions') return r.fulfill(json(u.searchParams.get('creek_id') === 'wolf' ? wolf : deer));
    if (u.pathname === '/api/reports') return r.fulfill(json(REPORTS));
    if (u.pathname === '/api/alerts') return r.fulfill(json(mock('alerts')));
    if (u.pathname.startsWith('/api/health')) return r.fulfill(json(mock('health')));
    return r.fulfill(json('[]'));
  });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
  if (before) { await p.goto(base + '#about'); await p.waitForSelector('#about-h'); await p.evaluate(before); await p.evaluate(() => { location.hash = '#map'; }); }
  else await p.goto(base + '#map');
  await p.waitForSelector('.leaflet-marker-icon.src-alerts', { timeout: 20000 }); await p.waitForTimeout(1200);
  return { ctx, p, errs };
}
const counts = (p) => p.evaluate((keys) => Object.fromEntries(keys.map((k) => [k, document.querySelectorAll(`#map-canvas .src-${k}`).length])), KEYS);

for (const scheme of ['light', 'dark']) {
  const { ctx, p, errs } = await page(scheme);
  const r = {};
  // 1. Every marker icon carries exactly one source class; every interactive path is OSM or an alert area.
  r.membership = await p.evaluate((keys) => {
    const bad = [];
    for (const el of document.querySelectorAll('#map-canvas .leaflet-marker-icon')) {
      const n = keys.filter((k) => el.classList.contains(`src-${k}`)).length;
      if (n !== 1) bad.push(el.title || el.className);
    }
    for (const el of document.querySelectorAll('#map-canvas path.leaflet-interactive')) {
      if (!el.classList.contains('src-osm') && !el.classList.contains('src-alerts')) bad.push('path:' + el.getAttribute('class'));
    }
    return { bad, markers: document.querySelectorAll('#map-canvas .leaflet-marker-icon').length };
  }, KEYS);
  r.base = await counts(p);
  r.chips = await p.locator('.ml-chip').evaluateAll((els) => els.map((e) => [e.dataset.src, e.getAttribute('aria-pressed'), e.textContent.trim()]));
  // 2. Each chip hides only its own layer, then restores it.
  r.toggles = {};
  for (const k of KEYS) {
    await p.locator(`.ml-chip[data-src="${k}"]`).click(); await p.waitForTimeout(150);
    const off = await counts(p), pressed = await p.locator(`.ml-chip[data-src="${k}"]`).getAttribute('aria-pressed');
    if (k === 'usgs' && SHOTS && scheme === 'light') await p.screenshot({ path: `${SHOTS}/layers-usgs-off-${scheme}.png` });
    await p.locator(`.ml-chip[data-src="${k}"]`).click(); await p.waitForTimeout(150);
    const on = await counts(p);
    r.toggles[k] = { hid: off[k] === 0, othersKept: KEYS.every((o) => o === k || off[o] === r.base[o]), pressedOff: pressed === 'false', restored: on[k] === r.base[k] };
  }
  // 3. Layout at 390x844: one-page width, legend clear of the zoom control, compact when closed.
  r.layout = await p.evaluate(() => {
    const lg = document.querySelector('.map-legend').getBoundingClientRect(), z = document.querySelector('.leaflet-control-zoom').getBoundingClientRect();
    return { noHScroll: document.scrollingElement.scrollWidth <= innerWidth, legendH: Math.round(lg.height), clearOfZoom: lg.top > z.bottom, insideW: lg.left >= 0 && lg.right <= innerWidth };
  });
  if (SHOTS) await p.screenshot({ path: `${SHOTS}/layers-closed-${scheme}.png` });
  // 4. Sources panel.
  await p.locator('.ml-info').click(); await p.waitForTimeout(200);
  r.panel = await p.evaluate(() => {
    const lg = document.querySelector('.map-legend').getBoundingClientRect(), z = document.querySelector('.leaflet-control-zoom').getBoundingClientRect();
    const items = [...document.querySelectorAll('#ml-panel .ml-src')];
    return {
      expanded: document.querySelector('.ml-info').getAttribute('aria-expanded'), visible: !document.querySelector('#ml-panel').hidden,
      keys: items.map((li) => li.dataset.src),
      links: [...document.querySelectorAll('#ml-panel .ml-credit a')].map((a) => ({ href: a.getAttribute('href'), target: a.target, rel: a.rel })),
      terms: items.every((li) => /Terms:/.test(li.textContent) && /Credit:/.test(li.textContent)),
      osmAlways: /always on/.test(document.querySelector('#ml-panel .ml-src[data-src="osm"]')?.textContent || ''),
      osmTerms: document.querySelector('#ml-panel .ml-src[data-src="osm"] .ml-terms')?.textContent.replace(/\s+/g, ' ').trim(),
      osmCredit: document.querySelector('#ml-panel .ml-src[data-src="osm"] .ml-credit')?.textContent.replace(/\s+/g, ' ').trim(),
      bandsInReports: document.querySelectorAll('#ml-panel .ml-src[data-src="reports"] .band-dot').length,
      clearOfZoom: lg.top > z.bottom, noHScroll: document.scrollingElement.scrollWidth <= innerWidth,
    };
  });
  if (SHOTS) await p.screenshot({ path: `${SHOTS}/layers-panel-${scheme}.png` });
  await p.locator('.ml-src[data-src="osm"] .ml-credit a').focus(); await p.keyboard.press('Escape'); await p.waitForTimeout(150);
  r.panelClosed = await p.locator('#ml-panel').isHidden() && await p.evaluate(() => document.activeElement?.classList.contains('ml-info'));
  r.names = await p.locator('.ml-chip').evaluateAll((els) => els.map((e) => e.textContent.replace(/\s+/g, ' ').trim()));
  if (scheme === 'light') {
    // 5. Gauge + CDEC popups.
    await p.locator('.leaflet-marker-icon.src-usgs').first().dispatchEvent('click'); await p.waitForTimeout(400);
    r.gaugePop = (await p.locator('.leaflet-popup').innerText()).replace(/\s+/g, ' ');
    await p.locator('.leaflet-popup-close-button').dispatchEvent('click');
    await p.locator('.leaflet-marker-icon.src-cdec').first().dispatchEvent('click'); await p.waitForTimeout(400);
    r.cdecPop = (await p.locator('.leaflet-popup').innerText()).replace(/\s+/g, ' ');
    await p.locator('.leaflet-popup-close-button').dispatchEvent('click');
    // 6. A report deep link re-enables Reports.
    await p.locator('.ml-chip[data-src="reports"]').click(); await p.waitForTimeout(150);
    const id = REPORTS.find((x) => x.lat != null).id;
    await p.evaluate((id) => { location.hash = `#map?report=${id}`; }, id); await p.waitForTimeout(800);
    r.deepLink = { pressed: await p.locator('.ml-chip[data-src="reports"]').getAttribute('aria-pressed'), popup: await p.locator('.leaflet-popup .rep-card').count(), pins: (await counts(p)).reports };
  }
  r.errs = errs; R[scheme] = r;
  await ctx.close();
}
// Edge: hostile config values (mutated before the map mounts) must be escaped, links https-only.
{
  const { ctx, p, errs } = await page('light', async () => {
    const m = await import('./js/sources.js');
    const s = m.SOURCE_LAYERS.find((x) => x.key === 'wq');
    s.label = '<img src=x onerror="window.__xss=1">Hostile'; s.shortLabel = '<b>bold</b>'; s.description = '<script>window.__xss=2</script>';
    s.attribution = '<img src=x onerror="window.__xss=3">'; s.attributionUrl = 'javascript:window.__xss=4';
    m.SOURCE_LAYERS.find((x) => x.key === 'swim').attributionUrl = 'http://riverdb.org/insecure';
  });
  await p.locator('.ml-info').click(); await p.waitForTimeout(200);
  R.edge = {
    xss: await p.evaluate(() => window.__xss || 0), injected: await p.locator('.map-legend img, .map-legend script, .map-legend b').count(),
    literal: (await p.locator('.ml-chip[data-src="wq"]').innerText()).includes('<b>bold</b>'),
    badLinks: await p.locator('#ml-panel a[href^="javascript:"], #ml-panel a[href^="http:"]').count(),
    wqCreditText: await p.locator('#ml-panel .ml-src[data-src="wq"] .ml-credit').innerText(),
    errs,
  };
  await ctx.close();
}
await b.close(); close();

const L = R.light, D = R.dark;
const checks = {
  everyMarkerInOneLayer: L.membership.bad.length === 0 && D.membership.bad.length === 0 && L.membership.markers > 20,
  allSevenLayersPresent: KEYS.every((k) => L.base[k] > 0),
  chipsMatchConfigAllOn: L.chips.map((c) => c[0]).join() === KEYS.join() && L.chips.every((c) => c[1] === 'true')
    && /Swim hole test/.test(L.chips.map((c) => c[2]).join()) && /Past study site/.test(L.chips.map((c) => c[2]).join()),
  toggleHidesOnlyItsLayer: KEYS.every((k) => L.toggles[k].hid && L.toggles[k].othersKept && L.toggles[k].pressedOff && L.toggles[k].restored)
    && KEYS.every((k) => D.toggles[k].hid && D.toggles[k].restored),
  layoutMobile: [L, D].every((x) => x.layout.noHScroll && x.layout.clearOfZoom && x.layout.insideW && x.layout.legendH <= 110),
  panelListsEverySource: L.panel.visible && L.panel.expanded === 'true' && L.panel.keys.join() === [...KEYS, 'osm'].join() && L.panel.terms && L.panel.osmAlways && L.panel.bandsInReports === 4,
  osmTermsTilesVsData: L.panel.osmTerms === 'Terms: Data: ODbL; map tiles: CC BY-SA 2.0.' && L.panel.osmCredit === 'Credit: © OpenStreetMap contributors',
  panelLinksHttpsNewTab: L.panel.links.length === 8 && L.panel.links.every((a) => a.href.startsWith('https://') && a.target === '_blank' && /noopener/.test(a.rel)),
  panelClearOfZoomAndCloses: L.panel.clearOfZoom && L.panel.noHScroll && D.panel.clearOfZoom && L.panelClosed,
  chipNameContainsVisibleText: L.names.length === 7 && L.names.every((n, i) => n.startsWith(L.chips[i][2].split(' (')[0])) && L.names.some((n) => n.includes('(2024 Regional Board bacteria study)')),
  gaugeAndCdecPopups: /USGS stream gauge · live/i.test(L.gaugePop) && /U\.S\. Geological Survey/.test(L.gaugePop) && /CDEC river station · regional context/i.test(L.cdecPop),
  deepLinkReenablesReports: L.deepLink.pressed === 'true' && L.deepLink.popup === 1 && L.deepLink.pins === L.base.reports,
  edgeEscapedHttpsOnly: !R.edge.xss && !R.edge.injected && R.edge.literal && R.edge.badLinks === 0 && R.edge.wqCreditText.includes('<img'),
  noPageErrors: !L.errs.length && !D.errs.length && !R.edge.errs.length,
};
console.log(JSON.stringify({ base: L.base, membershipBad: L.membership.bad, layout: L.layout, legendH: [L.layout.legendH, D.layout.legendH], panelKeys: L.panel.keys, links: L.panel.links.map((l) => l.href), gauge: L.gaugePop, cdec: L.cdecPop, deep: L.deepLink, edge: R.edge, checks }, null, 1));
const ok = Object.values(checks).every(Boolean);
console.log(ok ? 'PASS source-layers' : `FAIL source-layers: ${Object.entries(checks).filter(([, v]) => !v).map(([k]) => k).join(', ')}`);
process.exit(ok ? 0 : 1);
