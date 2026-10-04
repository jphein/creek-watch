// Past-study sites (data #109): the 2024 Regional Board study's 9 stations. Our 2 spots stay on top of
// the history panel; the 7 study-only ones collapse under "Other sites in this study" and get grey,
// dated map pins (never red, never "unsafe"). The Board's map is a link only.
// Fixture: tests/web/fixtures/wolf-history-109.json = data.history.get_bacteria_history('wolf') on main after #109 (= 228c955).
// SHOTS=<dir> saves 390x844 screenshots (light + dark).
import fs from 'node:fs';
import { serveWeb, launch, mock } from './harness.mjs';

const SHOTS = process.env.SHOTS || '';
const { base, close } = await serveWeb();
const b = await launch();
const json = (body, status = 200) => ({ status, contentType: 'application/json', body: typeof body === 'string' ? body : JSON.stringify(body) });
const COND = JSON.parse(mock('conditions'));
const HIST = JSON.parse(fs.readFileSync(new URL('./fixtures/wolf-history-109.json', import.meta.url), 'utf8'));
const OTHERS = HIST.studies[0].stations.filter((s) => s.site_id == null);
const R = {};

async function run(wolfHist, deerHist, { scheme = 'light', shots = false } = {}) {
  const wolf = { ...COND.wolf, bacteria_history: wolfHist }, deer = { ...COND.deer, bacteria_history: deerHist };
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, colorScheme: scheme, serviceWorkers: 'block' });
  await ctx.route('**/api/creeks', (r) => r.fulfill(json(mock('creeks'))));
  await ctx.route('**/api/conditions**', (r) => r.fulfill(json(new URL(r.request().url()).searchParams.get('creek_id') === 'wolf' ? wolf : deer)));
  await ctx.route('**/api/{health,alerts,reports,stats}**', (r) => r.fulfill(json(r.request().url().includes('/health') ? mock('health') : '[]')));
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
  await p.goto(base + '#map'); await p.waitForSelector('.leaflet-marker-icon', { timeout: 20000 }); await p.waitForTimeout(1000);
  const r = { titles: await p.locator('.leaflet-marker-icon:has(.study-marker)').evaluateAll((e) => e.map((x) => x.title)),
    classes: await p.locator('.leaflet-marker-icon .study-marker').evaluateAll((e) => [...new Set(e.map((x) => x.className))]),
    legend: await p.locator('.map-legend').innerText() };
  if (r.titles.length) {
    await p.locator('.leaflet-marker-icon[title*="French Ravine"], .leaflet-marker-icon:has(.study-marker)').first().dispatchEvent('click');
    await p.waitForSelector('.leaflet-popup .study-pop'); await p.waitForTimeout(300);
    r.popup = (await p.locator('.leaflet-popup').innerText()).replace(/\s+/g, ' ');
    r.popLinks = await p.locator('.leaflet-popup a').evaluateAll((a) => a.map((x) => ({ href: x.getAttribute('href'), target: x.target })));
    if (shots) await p.screenshot({ path: `${SHOTS}/study-popup-${scheme}.png` });
  }
  r.xss = await p.evaluate(() => window.__xss || 0);
  await p.goto(base + '#dashboard'); await p.waitForSelector('.creek-card', { timeout: 20000 }); await p.waitForTimeout(800);
  const h = p.locator('.creek-card').first().locator('details.history');
  if (await h.count()) {
    await h.locator('> summary').click();
    r.top = await h.locator(':scope > .h-station h4').allTextContents();
    r.othersSummary = await h.locator('details.h-others > summary').textContent().catch(() => '');
    r.others = await h.locator('details.h-others .h-station h4').allTextContents();
    r.waters = await h.locator('details.h-others .h-water').allTextContents();
    // French Ravine 2024-07-10 is censored (qual ">", above the 2419.6 upper limit): never an exact bar.
    const fr = h.locator('.h-station[aria-label="French Ravine at Hidden Valley Road"]');
    r.frBars = await fr.locator('rect.hb').count(); r.frCaption = await fr.locator('figcaption').textContent().catch(() => '');
    r.ctxLinks = await h.locator('.credit a').evaluateAll((a) => a.map((x) => ({ href: x.getAttribute('href'), text: x.textContent })));
    if (shots) {
      await h.locator('details.h-others').evaluate((d) => { d.open = true; });
      await h.locator('details.h-others').scrollIntoViewIfNeeded(); await p.screenshot({ path: `${SHOTS}/study-panel-${scheme}.png` });
    }
  }
  r.xss = r.xss || await p.evaluate(() => window.__xss || 0);
  r.injected = await p.locator('img[src="x"]').count();
  r.errs = errs; await ctx.close();
  return r;
}

for (const scheme of ['light', 'dark']) R[scheme] = await run(HIST, HIST, { scheme, shots: !!SHOTS }); // same study on both creeks: deduped pins
// Edge: http context link, hostile name, null coords, and a CURRENT study (no pins, no panel).
{
  const e = structuredClone(HIST); const s = e.studies[0];
  s.context_url = 'http://experience.arcgis.com/insecure';
  const o = s.stations.filter((x) => x.site_id == null);
  o[0].name = '<img src=x onerror="window.__xss=1">Hostile'; o[1].lat = null; o[2].lon = '';
  R.edge = await run(e, { studies: [{ ...structuredClone(HIST).studies[0], is_current: true, id: 'cur' }] });
}
await b.close(); close();

const L = R.light;
const othersN = OTHERS.length;
const checks = {
  sevenStudyPinsDeduped: othersN === 7 && L.titles.length === 7 && R.dark.titles.length === 7 && L.titles.every((t) => /^Past study site \(2024\): /.test(t)),
  ourSitesNoStudyPin: !L.titles.some((t) => /North Star Mining Museum|Wolf Road/.test(t)),
  greyNeverStatus: L.classes.join() === 'study-marker' && /Past study site/.test(L.legend),
  popupDatedPast: /Past study · 2024/i.test(L.popup) && /Tested weekly May–Sep 2024: a past study, not current conditions\./.test(L.popup) && /Rattlesnake|French|Cherry|Auburn|Lime Kiln|Cottage|South Wolf/.test(L.popup),
  censoredWording: /highest above 2419\.6 MPN\/100 mL \(the test’s upper limit\)|highest above 2419\.6 MPN\/100 mL \(the test's upper limit\)/.test(L.popup),
  neverUnsafe: ![L.popup, R.dark.popup].some((t) => /unsafe|toxic|danger/i.test(t)),
  contextLinkOnly: L.popLinks.some((l) => l.href === HIST.studies[0].context_url && l.target === '_blank') && L.ctxLinks.some((l) => l.href === HIST.studies[0].context_url && /Regional Board’s map|Regional Board's map/.test(l.text)),
  panelOursTopOthersCollapsed: L.top.length === 2 && /Other sites in this study \(7\)/.test(L.othersSummary) && L.others.length === 7 && L.waters.includes('French Ravine (tributary)'),
  censoredNotExact: L.frBars === 12 && /1 result\(s\) outside the lab’s measuring range \(>2419\.6\) not drawn as exact values/.test(L.frCaption),
  edgeHttpsOnly: !R.edge.popLinks.some((l) => /^http:/.test(l.href)) && !R.edge.ctxLinks.some((l) => /^http:/.test(l.href)),
  edgeEscapedAndBadCoords: !R.edge.xss && !R.edge.injected && R.edge.titles.length === 5 && R.edge.titles.some((t) => t.includes('<img')),
  noPageErrors: !L.errs.length && !R.dark.errs.length && !R.edge.errs.length,
};
console.log(JSON.stringify({ titles: L.titles, popup: L.popup, top: L.top, others: L.others, edgeTitles: R.edge.titles, checks }, null, 1));
const ok = Object.values(checks).every(Boolean);
console.log(ok ? 'PASS study-sites' : `FAIL study-sites: ${Object.entries(checks).filter(([, v]) => !v).map(([k]) => k).join(', ')}`);
process.exit(ok ? 0 : 1);
