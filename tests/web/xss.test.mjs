// Untrusted upstream alert fields must never execute or produce javascript:/data: links (Oracle gate, #41).
// Hostile values in every field, rendered on the Alerts page, a deep link, creek banners and a map popup.
import { serveWeb, launch, mock } from './harness.mjs';

const evil = {
  id: 'evil:"><img src=x onerror="window.__xss=(window.__xss||0)+1">', source: 'nws', source_name: '<b onmouseover="window.__xss=1">NWS</b>',
  category: 'flood', severity: 'alert',
  title: '<img src=x onerror=alert(1)>', summary: '<script>window.__xss=1</script><img src=x onerror="window.__xss=1">',
  instruction: '<a href="javascript:alert(1)">click</a>', url: 'javascript:alert(1)',
  attribution: '<iframe src="javascript:alert(1)"></iframe>',
  area: { creek_ids: ['wolf'], site_ids: [], lat: 39.2186, lon: -121.0612, area_desc: '"><svg onload="window.__xss=1">',
          polygon_geojson: { type: 'Polygon', coordinates: [[[-121.1, 39.2], [-121.0, 39.2], [-121.0, 39.25], [-121.1, 39.2]]], properties: { name: '<img src=x onerror="window.__xss=1">' } } },
  effective: '2026-10-04T01:00:00Z', expires: '<img src=x onerror=alert(1)>', updated: '2026-10-04T01:00:00Z', status: 'active',
};
const alerts = [evil,
  { ...evil, id: 'evil:2', severity: 'watch', url: 'data:text/html,<script>alert(1)</script>', title: 'Second "evil" & <u>bold</u>' },
  { ...evil, id: 'evil:3', severity: 'advisory', url: 'http://insecure.example/', title: 'Plain http link must not be linked' }];

const { base, close } = await serveWeb();
const b = await launch();
const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, serviceWorkers: 'block' });
const json = (body) => ({ status: 200, contentType: 'application/json', body: typeof body === 'string' ? body : JSON.stringify(body) });
await ctx.route('**/api/alerts/sources', (r) => r.fulfill(json({ sources: [{ source: 'nws', last_ok: new Date().toISOString() }], schedule: {} })));
await ctx.route('**/api/alerts?**', (r) => r.fulfill(json(alerts)));
await ctx.route('**/api/alerts', (r) => r.fulfill(json(alerts)));
await ctx.route('**/api/alerts/item**', (r) => r.fulfill(json(evil)));
await ctx.route('**/api/creeks', (r) => r.fulfill(json(mock('creeks'))));
await ctx.route('**/api/{health,conditions,reports}**', (r) => r.fulfill(json('[]')));
const p = await ctx.newPage();
const dialogs = []; p.on('dialog', (d) => { dialogs.push(d.message()); d.dismiss(); });
const check = async (where) => ({
  where,
  xssFlag: await p.evaluate(() => window.__xss || 0),
  badLinks: await p.locator('a[href^="javascript:" i], a[href^="data:" i], iframe').count(),
  injectedNodes: await p.locator('img[src="x"], svg[onload], [onerror], [onmouseover]').count(),
  httpLinked: await p.locator('a[href^="http://insecure.example"]').count(),
  literalTitle: await p.getByText('<img src=x onerror=alert(1)>', { exact: true }).count(),
});
const R = [];
await p.goto(base + '#alerts'); await p.waitForSelector('.alert-item');
await p.locator('.alert-item details').evaluateAll((ds) => ds.forEach((d) => (d.open = true))); await p.waitForTimeout(400); R.push(await check('alerts page'));
await p.goto(base + '#alerts?id=' + encodeURIComponent(evil.id)); await p.waitForTimeout(800); R.push(await check('deep link'));
await p.goto(base + '#dashboard'); await p.waitForSelector('.creek-alerts', { timeout: 20000 }).catch(() => {}); await p.waitForTimeout(600); R.push(await check('creek banners'));
await p.goto(base + '#map'); await p.waitForSelector('.alert-marker:not(.sm)', { timeout: 20000 }).catch(() => {}); await p.waitForTimeout(1200);
await p.locator('.leaflet-marker-icon:has(.alert-marker.sev-alert)').first().click({ force: true }).catch(() => {}); await p.waitForTimeout(600); R.push(await check('map popup'));
await b.close(); close();
const fail = dialogs.length || R.some((r) => r.xssFlag || r.badLinks || r.injectedNodes || r.httpLinked || !r.literalTitle);
console.log(JSON.stringify({ results: R, dialogs }, null, 1));
console.log(fail ? 'FAIL xss' : 'PASS xss');
process.exit(fail ? 1 : 0);
