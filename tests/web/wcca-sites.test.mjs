// WCCA feedback (2026-10-04): a monitoring-site popup shows only that site (its test, reports within
// 500 m labelled with their own spot), private-land wording by default for WCCA, and the upstream
// caveat wherever site data or reports appear. SHOTS=<dir> saves 390x844 screenshots (light + dark).
import { serveWeb, launch, mock } from './harness.mjs';

const SHOTS = process.env.SHOTS || '';
const { base, close } = await serveWeb();
const b = await launch();
const json = (body, status = 200) => ({ status, contentType: 'application/json', body: typeof body === 'string' ? body : JSON.stringify(body) });
const COND = JSON.parse(mock('conditions'));
const CREEKS = JSON.parse(mock('creeks'));
CREEKS.find((c) => c.id === 'wolf').sites.push({ id: 'wolf-loma-rica-trail', name: 'Loma Rica Trail', lat: 39.2245, lon: -121.0263 });

// Station shapes as prod serves them (2026-10-04), plus edge cases.
const wq = (o) => ({ agency: 'WCCA', site_id: null, source_url: `https://riverdb.org/station/${o.station_id}`, date: '2019-12-19', age_days: 2481, readings: { do_mg_l: 9.5, water_temp_c: 7.5, ph: 7.2, turbidity_ntu: 1.2 },
  visit_count: 25, live: false, stale: false, credit: 'Wolf Creek Community Alliance volunteer monitoring, via RiverDB', ...o });
const STATIONS = [
  wq({ station_id: '285873023374516', name: 'WCCA Site 2 (Idaho Maryland Rd at Brunswick Rd)', lat: 39.224505, lon: -121.02629, site_id: 'wolf-loma-rica-trail' }),
  wq({ station_id: '285873023374546', name: 'WCCA Site 15 (above the Bear River)', lat: 39.045784, lon: -121.115951, site_id: 'wolf-wolf-rd', readings: { do_mg_l: 11.22, water_temp_c: 7.6, ph: 7.83, turbidity_ntu: null } }),
  wq({ station_id: 'pub1', name: 'WCCA Site 8 (Glenn Jones Park)', lat: 39.2078806, lon: -121.0695512, access: 'public' }),
  wq({ station_id: 'syrcl1', agency: 'SYRCL', name: 'Other group site', lat: 39.19, lon: -121.05 }),
  wq({ station_id: 'xss', name: '<img src=x onerror="window.__xss=1">Hostile', lat: 39.18, lon: -121.04 }),
  wq({ station_id: 'nullc', name: 'Null coords', lat: null, lon: null }),
];
const ago = (h) => new Date(Date.now() - h * 36e5).toISOString();
// Report 14's real shape (Loma Rica, flood + some trash), and an old report AT Site 15 (outside 30 days).
const REPORTS = [
  { id: 14, creek_id: 'wolf', site_id: 'wolf-loma-rica-trail', location_kind: 'site', lat: 39.224, lon: -121.027, observed_at: ago(3), water_color: 'clear', flow: 'flood', algae: 'none', trash: 'some', odor: 'none', flags: [] },
  { id: 3, creek_id: 'wolf', site_id: 'wolf-wolf-rd', location_kind: 'site', lat: 39.0458, lon: -121.1159, observed_at: ago(24 * 60), water_color: 'brown', flow: 'flood', algae: 'none', trash: 'lots', odor: 'none', flags: [] },
];
const wolf = { ...COND.wolf, water_quality: { stations: STATIONS } };

const R = {};
const text = (l) => l.innerText().then((t) => t.replace(/\s+/g, ' '));
async function popup(p, sel) {
  await p.locator(sel).first().dispatchEvent('click');
  await p.waitForSelector('.leaflet-popup'); await p.waitForTimeout(300);
  const t = await text(p.locator('.leaflet-popup'));
  const links = await p.locator('.leaflet-popup a').evaluateAll((as) => as.map((a) => a.getAttribute('href')));
  return { t, links };
}
const closePop = (p) => p.locator('.leaflet-popup-close-button').dispatchEvent('click').then(() => p.waitForTimeout(200));

for (const scheme of ['light', 'dark']) {
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, colorScheme: scheme, serviceWorkers: 'block' });
  await ctx.route('**/api/creeks', (r) => r.fulfill(json(CREEKS)));
  await ctx.route('**/api/conditions**', (r) => r.fulfill(json(new URL(r.request().url()).searchParams.get('creek_id') === 'wolf' ? wolf : COND.deer)));
  await ctx.route('**/api/reports**', (r) => r.fulfill(json(new URL(r.request().url()).searchParams.get('creek_id') === 'deer' ? [] : REPORTS)));
  await ctx.route('**/api/{health,alerts,stats}**', (r) => r.fulfill(json(r.request().url().includes('/health') ? mock('health') : '[]')));
  await ctx.route('**/api/**', (r) => (r.request().method() === 'GET' ? r.fallback() : r.abort()));
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
  await p.goto(base + '#map'); await p.waitForSelector('.flask-marker', { timeout: 20000 }); await p.waitForTimeout(800);
  const r = { flasks: await p.locator('.leaflet-marker-icon:has(.flask-marker)').evaluateAll((els) => els.map((e) => e.title)) };
  r.s15 = await popup(p, '.leaflet-marker-icon[title="Volunteer water test: WCCA Site 15 (above the Bear River)"]');
  if (SHOTS) await p.screenshot({ path: `${SHOTS}/wcca-site15-${scheme}.png` });
  await closePop(p);
  r.s2 = await popup(p, '.leaflet-marker-icon[title^="Volunteer water test: WCCA Site 2"]');
  if (SHOTS) await p.screenshot({ path: `${SHOTS}/wcca-site2-${scheme}.png` });
  await closePop(p);
  if (scheme === 'light') {
    r.pub = await popup(p, '.leaflet-marker-icon[title="Volunteer water test: WCCA Site 8 (Glenn Jones Park)"]'); await closePop(p);
    r.syrcl = await popup(p, '.leaflet-marker-icon[title="Volunteer water test: Other group site"]'); await closePop(p);
    await p.locator('.leaflet-marker-icon[title^="Volunteer water test: <img"]').first().dispatchEvent('click'); await p.waitForTimeout(400);
    r.xss = await p.evaluate(() => window.__xss || 0); r.injected = await p.locator('img[src="x"]').count(); await closePop(p);
    r.pin = await popup(p, '.leaflet-marker-icon:has(.pin)'); await closePop(p);
    await p.goto(base + '#dashboard'); await p.waitForSelector('.creek-card', { timeout: 20000 }); await p.waitForTimeout(800);
    const card = p.locator('.creek-card').first();
    r.card = await text(card);
    r.cardPrivate = await card.locator('.wq .access-note').count();
    r.cardStationLinks = await card.locator('.wq a[href*="riverdb.org/station/"]').evaluateAll((as) => as.map((a) => a.getAttribute('href')));
    if (SHOTS) { await card.locator('.wq').scrollIntoViewIfNeeded(); await card.locator('.wq details').evaluate((d) => { d.open = true; }); await p.screenshot({ path: `${SHOTS}/wcca-card-${scheme}.png` }); }
    await p.goto(base + '#about'); await p.waitForSelector('#about-h');
    r.about = await text(p.locator('#page-about'));
  }
  r.errs = errs; R[scheme] = r;
  await ctx.close();
}
await b.close(); close();

const L = R.light;
const PRIVATE = 'Private land: monitored by WCCA with the landowner’s permission. Not open to visitors; please view the data here only.';
const UP = 'Conditions at any spot can come from anywhere upstream. They don’t reflect on the landowner, and may be outside the landowner’s power to fix.';
const offsite = (links) => links.filter((h) => !h.startsWith('#'));
const checks = {
  flaskMarkersSkipNullCoords: STATIONS.filter((s) => s.lat != null).every((s) => L.flasks.includes(`Volunteer water test: ${s.name}`)) && !L.flasks.some((t) => /Null coords/.test(t)) && R.dark.flasks.length === L.flasks.length,
  site15ShowsOnlyItsOwnData: /Last tested Dec 19, 2019/.test(L.s15.t) && /DO 11\.2 mg\/L · water 7\.6 °C · pH 7\.8/.test(L.s15.t) && !/turbidity/.test(L.s15.t)
    && /No Creek Watch reports within .* of this site in the last 30 days\./.test(L.s15.t) && !/Flooding|trash|Loma Rica/i.test(L.s15.t),
  site2NamesReporterSpotAndDistance: /report at Loma Rica Trail, \d+ ft from this site · 3 hr ago \(Flooding, Some trash\)/.test(L.s2.t),
  wholeCreekLinkLabelled: L.s15.links.includes('#dashboard') && /Whole-creek overview \(all of Wolf Creek\)/.test(L.s15.t) && !/See results/.test(L.s15.t),
  privateDefaultForWcca: L.s15.t.includes(PRIVATE) && L.s2.t.includes(PRIVATE) && R.dark.s15.t.includes(PRIVATE),
  noDirectionsOnPrivate: offsite(L.s15.links).length === 0 && offsite(L.s2.links).length === 0,
  publicOverrideAndOtherAgency: !L.pub.t.includes('Private land') && !L.syrcl.t.includes('Private land'),
  upstreamEverywhere: [L.s15.t, L.s2.t, L.pin.t, L.card, L.about].every((t) => t.includes(UP)),
  cardScopedAndPrivate: /From anywhere on Wolf Creek; each card names its own spot\./.test(L.card) && L.cardPrivate >= 1,
  noStationLinkOnPrivate: L.cardStationLinks.map((h) => h.split('/').pop()).sort().join() === 'pub1,syrcl1', // private WCCA sites lose the RiverDB link; public + non-WCCA keep it
  aboutPrivateLand: /private land.*not open to visitors/i.test(L.about),
  escaped: !L.xss && !L.injected,
  noPageErrors: !L.errs.length && !R.dark.errs.length,
};
console.log(JSON.stringify({ R: { s15: L.s15.t, s2: L.s2.t, pin: L.pin.t }, checks }, null, 1));
const ok = Object.values(checks).every(Boolean);
console.log(ok ? 'PASS wcca-sites' : `FAIL wcca-sites: ${Object.entries(checks).filter(([, v]) => !v).map(([k]) => k).join(', ')}`);
process.exit(ok ? 0 : 1);
