// Swim-hole layer (data #100): dated SYRCL tests, neutral markers, 320 wording, never "unsafe".
// SHOTS=<dir> saves 390x844 screenshots (light + dark).
import { serveWeb, launch, mock } from './harness.mjs';

const SHOTS = process.env.SHOTS || '';
const { base, close } = await serveWeb();
const b = await launch();
const json = (body, status = 200) => ({ status, contentType: 'application/json', body: typeof body === 'string' ? body : JSON.stringify(body) });
const COND = JSON.parse(mock('conditions'));
const R = {};
const openPopup = async (p, name) => {
  // Markers may sit outside the initial view (the map frames the creeks); open like a keyboard user would.
  await p.locator(`.leaflet-marker-icon[title="Swim hole: ${name}"]`).first().dispatchEvent('click');
  await p.waitForSelector('.leaflet-popup .swim-pop'); await p.waitForTimeout(300);
  return (await p.locator('.leaflet-popup .swim-pop').innerText()).replace(/\s+/g, ' ');
};

for (const scheme of ['light', 'dark']) {
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, colorScheme: scheme, serviceWorkers: 'block' });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
  await p.goto(base + 'index.html?mock=1#map'); await p.waitForSelector('.leaflet-marker-icon .swim-marker', { timeout: 20000 }); await p.waitForTimeout(800);
  const r = { markers: await p.locator('.leaflet-marker-icon .swim-marker').count(), legend: (await p.locator('.map-legend').innerText()).includes('Swim hole test') };
  r.purdon = await openPopup(p, 'Purdon Crossing');
  r.purdonLink = await p.locator('.leaflet-popup .swim-pop a').getAttribute('href');
  if (SHOTS) await p.screenshot({ path: `${SHOTS}/swim-popup-${scheme}.png` });
  await p.locator('.leaflet-popup-close-button').dispatchEvent('click'); await p.waitForTimeout(200);
  r.oregon = await openPopup(p, 'Oregon Creek swimming hole');
  r.errs = errs; R[scheme] = r;
  if (scheme === 'light') { await p.goto(base + 'index.html?mock=1#about'); await p.waitForSelector('#about-h'); R.about = (await p.locator('#page-about').innerText()).includes('Swim-hole bacteria tests'); }
  await ctx.close();
}
// Edge path: >320, hostile name, http link, duplicates across creeks, stale, bad coords; then empty.
{
  const sw = structuredClone(COND.wolf.swim_holes);
  sw.stations[0].ecoli_mpn_100ml = 410; sw.stations[0].stale = true;
  sw.stations[1].name = '<img src=x onerror="window.__xss=1">Edwards'; sw.stations[1].source_url = 'http://riverdb.org/insecure';
  sw.stations.push({ ...sw.stations[2], station_id: 'nocoords', lat: null, lon: 'x', name: 'No coords' });
  const wolf = { ...COND.wolf, swim_holes: sw }, deer = { ...COND.deer, swim_holes: sw }; // same regional list on both creeks
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
  await ctx.route('**/api/creeks', (r) => r.fulfill(json(mock('creeks'))));
  await ctx.route('**/api/conditions**', (r) => r.fulfill(json(new URL(r.request().url()).searchParams.get('creek_id') === 'wolf' ? wolf : deer)));
  await ctx.route('**/api/{health,alerts,reports,stats}**', (r) => r.fulfill(json('[]')));
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
  await p.goto(base + '#map'); await p.waitForSelector('.leaflet-marker-icon .swim-marker', { timeout: 20000 }); await p.waitForTimeout(800);
  R.edge = { markers: await p.locator('.leaflet-marker-icon .swim-marker').count() };
  R.edge.over = await openPopup(p, 'Purdon Crossing');
  R.edge.overNeutral = await p.locator('.leaflet-marker-icon[title="Swim hole: Purdon Crossing"] .swim-marker').getAttribute('class');
  await p.locator('.leaflet-popup-close-button').dispatchEvent('click'); await p.waitForTimeout(200);
  await p.locator('.leaflet-marker-icon[title^="Swim hole: <img"]').first().dispatchEvent('click'); await p.waitForTimeout(400);
  R.edge.xss = await p.evaluate(() => window.__xss || 0); R.edge.injected = await p.locator('img[src="x"]').count();
  R.edge.httpLinks = await p.locator('.leaflet-popup a[href^="http:"]').count();
  R.edge.errs = errs; await ctx.close();
}
{
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
  await ctx.route('**/api/creeks', (r) => r.fulfill(json(mock('creeks'))));
  await ctx.route('**/api/conditions**', (r) => r.fulfill(json({ ...COND.wolf, swim_holes: { stations: [] } })));
  await ctx.route('**/api/{health,alerts,reports,stats}**', (r) => r.fulfill(json('[]')));
  const p = await ctx.newPage();
  await p.goto(base + '#map'); await p.waitForSelector('.leaflet-marker-icon', { timeout: 20000 }); await p.waitForTimeout(800);
  R.empty = await p.locator('.leaflet-marker-icon .swim-marker').count();
  await ctx.close();
}
await b.close(); close();

const L = R.light;
const checks = {
  fiveNeutralMarkers: L.markers === 5 && R.dark.markers === 5 && L.legend,
  dateProminent: /Tested Aug 8, 2026 \(\d+ days ago\): a summer sample, not a live reading\./.test(L.purdon),
  belowWording: /E\. coli 5\.2 per 100 mL: below California’s recreational threshold of 320\./.test(L.purdon),
  creditAndHttpsLink: /South Yuba River Citizens League volunteer bacteria monitoring, via RiverDB/.test(L.purdon) && L.purdonLink === 'https://riverdb.org/org/SYRCL',
  jonesBarOnlySouthYuba: /South Yuba at Jones Bar now: \d+(\.\d+)? cfs/.test(L.purdon) && !/Jones Bar/.test(L.oregon),
  neverUnsafe: ![L.purdon, L.oregon, R.dark.purdon, R.edge.over].some((t) => /unsafe|toxic/i.test(t)),
  aboveWordingNeutral: /above the 320 recreational threshold \(a statistical threshold, not a single-sample limit\)/.test(R.edge.over) && R.edge.overNeutral === 'swim-marker' && /older sample/.test(R.edge.over),
  dedupeAndBadCoords: R.edge.markers === 5,
  escapedAndHttpsOnly: !R.edge.xss && !R.edge.injected && R.edge.httpLinks === 0,
  emptyRendersNothing: R.empty === 0,
  aboutLine: R.about,
  noPageErrors: !L.errs.length && !R.dark.errs.length && !R.edge.errs.length,
};
console.log(JSON.stringify({ R, checks }, null, 1));
const ok = Object.values(checks).every(Boolean);
console.log(ok ? 'PASS swim-holes' : `FAIL swim-holes: ${Object.entries(checks).filter(([, v]) => !v).map(([k]) => k).join(', ')}`);
process.exit(ok ? 0 : 1);
