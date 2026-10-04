// No false "all clear" (Oracle, #41): an empty alert list is only ✓ when the alert sources were checked recently.
import { serveWeb, launch, mock } from './harness.mjs';

const { base, close } = await serveWeb();
const b = await launch();
const iso = (msAgo) => new Date(Date.now() - msAgo).toISOString();
const json = (body, status = 200) => ({ status, contentType: 'application/json', body: JSON.stringify(body) });
const cases = [
  ['fresh sources, no alerts → ✓', [], json({ sources: [{ source: 'nws', last_ok: iso(5 * 60e3) }], schedule: { nws: { interval_s: 600 } } }), 'clear'],
  ['stale sources, no alerts → couldn’t check', [], json({ sources: [{ source: 'nws', last_ok: iso(3 * 3600e3) }], schedule: { nws: { interval_s: 600 } } }), 'unchecked'],
  ['no source ever ok → couldn’t check', [], json({ sources: [{ source: 'nws', last_ok: null, last_error: 'timeout' }], schedule: {} }), 'unchecked'],
  ['sources endpoint missing → couldn’t check', [], json({ detail: 'Not Found' }, 404), 'unchecked'],
  ['stale sources, alerts present → list + out-of-date note', JSON.parse(mock('alerts')), json({ sources: [{ source: 'nws', last_ok: iso(3 * 3600e3) }], schedule: {} }), 'stale-list'],
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
await b.close(); close();
console.log(JSON.stringify(out, null, 1));
const ok = out.every((x) => x.ok);
console.log(ok ? 'PASS alerts-state' : 'FAIL alerts-state');
process.exit(ok ? 0 : 1);
