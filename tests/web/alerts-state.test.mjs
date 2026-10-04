// No false "all clear" (Oracle, #41): an empty alert list is only ✓ when the alert sources were checked recently.
import { serveWeb, launch, mock } from './harness.mjs';

const { base, close } = await serveWeb();
const b = await launch();
const iso = (msAgo) => new Date(Date.now() - msAgo).toISOString();
const json = (body, status = 200) => ({ status, contentType: 'application/json', body: JSON.stringify(body) });
const src = (list, schedule = {}) => json({ sources: list.map(([source, agoMin]) => ({ source, last_ok: agoMin == null ? null : iso(agoMin * 60e3) })), schedule });
const cases = [
  ['nws fresh (+creekwatch), no alerts → ✓', [], src([['nws', 5], ['creekwatch', 1]], { nws: { interval_s: 600 } }), 'clear'],
  ['nws fresh, others stale → ✓ allowed', [], src([['nws', 5], ['sso', 600], ['hab', 600]]), 'clear'],
  ['nws stale, no alerts → couldn’t check', [], src([['nws', 180]], { nws: { interval_s: 600 } }), 'unchecked'],
  ['creekwatch fresh + all others stale → couldn’t check', [], src([['creekwatch', 1], ['nws', 180], ['sso', 180], ['hab', 180]]), 'unchecked'],
  ['nws stale + others fresh → couldn’t check', [], src([['nws', 180], ['sso', 2], ['hab', 2], ['creekwatch', 1]]), 'unchecked'],
  ['nws missing, others fresh → couldn’t check', [], src([['sso', 2], ['creekwatch', 1]]), 'unchecked'],
  ['no source ever ok → couldn’t check', [], src([['nws', null]]), 'unchecked'],
  ['sources endpoint missing → couldn’t check', [], json({ detail: 'Not Found' }, 404), 'unchecked'],
  ['nws stale, alerts present → list + incomplete note', JSON.parse(mock('alerts')), src([['nws', 180], ['sso', 2]]), 'stale-list'],
];
const out = [];
for (const [label, alerts, sources, want] of cases) {
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
  await ctx.route('**/api/alerts/sources', (r) => r.fulfill(sources));
  await ctx.route('**/api/alerts?**', (r) => r.fulfill(json(alerts)));
  await ctx.route('**/api/alerts', (r) => r.fulfill(json(alerts)));
  await ctx.route('**/api/creeks', (r) => r.fulfill(json(JSON.parse(mock('creeks')))));
  const p = await ctx.newPage();
  await p.goto(base + '#alerts'); await p.waitForSelector('.alerts-list > *:not(.muted)');
  const got = (await p.locator('.all-clear').count()) ? 'clear'
    : (await p.locator('.alerts-list .banner.error').count()) ? 'unchecked'
    : (await p.locator('.stale-note').count()) && (await p.locator('.alerts-list .alert-item').count()) ? 'stale-list' : 'other';
  out.push({ label, want, got, ok: got === want });
  await ctx.close();
}
// Re-visit refreshes source health: fresh on first visit (✓), then nws goes stale → after leaving and
// coming back to the tab the ✓ must be gone.
{
  let stale = false;
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
  await ctx.route('**/api/alerts/sources', (r) => r.fulfill(src([['nws', stale ? 180 : 5]])));
  await ctx.route('**/api/alerts?**', (r) => r.fulfill(json([])));
  await ctx.route('**/api/alerts', (r) => r.fulfill(json([])));
  await ctx.route('**/api/creeks', (r) => r.fulfill(json(JSON.parse(mock('creeks')))));
  const p = await ctx.newPage();
  await p.goto(base + '#alerts'); await p.waitForSelector('.all-clear');
  stale = true;
  await p.evaluate(() => (location.hash = '#about')); await p.waitForTimeout(200);
  await p.evaluate(() => (location.hash = '#alerts')); await p.waitForTimeout(1200);
  const got = (await p.locator('.all-clear').count()) ? 'clear' : (await p.locator('.alerts-list .banner.error').count()) ? 'unchecked' : 'other';
  out.push({ label: 're-visit after nws goes stale → couldn’t check', want: 'unchecked', got, ok: got === 'unchecked' });
  await ctx.close();
}
await b.close(); close();
console.log(JSON.stringify(out, null, 1));
const ok = out.every((x) => x.ok);
console.log(ok ? 'PASS alerts-state' : 'FAIL alerts-state');
process.exit(ok ? 0 : 1);
