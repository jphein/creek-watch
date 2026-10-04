// Push subscribe flow vs leftover/stale subscriptions (prod 20:35 incident: FCM 410 on the welcome push,
// one second after a 201). The fake PushManager follows Chrome's rules: subscribe() returns the EXISTING
// subscription when the key matches, throws InvalidStateError when the key differs; unsubscribe() clears it.
import { serveWeb, launch, mock } from './harness.mjs';

const { base, close } = await serveWeb();
const b = await launch();
const json = (body, status = 200) => ({ status, contentType: 'application/json', body: typeof body === 'string' ? body : JSON.stringify(body) });
const SERVER_KEY = JSON.parse(mock('vapid')).key;
const OLD_KEY = 'BOLDOLDOLDkeyFromAnEarlierDeployAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'.slice(0, 87);

async function run({ leftover = null, savedFilters = null, failSubscribe = false, actions }) {
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, permissions: ['notifications'] });
  const calls = [];
  await ctx.route('**/api/**', async (r) => {
    const u = new URL(r.request().url()); const m = r.request().method();
    if (u.pathname === '/api/push/vapid-public-key') return r.fulfill(json({ key: SERVER_KEY }));
    if (u.pathname === '/api/push/subscriptions') { calls.push({ m, body: r.request().postDataJSON() }); return m === 'DELETE' ? r.fulfill({ status: 204, body: '' }) : r.fulfill(json({ status: 'created' }, 201)); }
    if (u.pathname === '/api/alerts/sources') return r.fulfill(json({ adapters_loaded: 1, load_error: null, sources: [{ source: 'nws', last_ok: new Date().toISOString() }], schedule: {} }));
    if (u.pathname === '/api/creeks') return r.fulfill(json(mock('creeks')));
    return r.fulfill(json('[]'));
  });
  await ctx.addInitScript(({ leftover, savedFilters, failSubscribe }) => {
    const dec = (s) => Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (s.length % 4)) % 4)), (c) => c.charCodeAt(0));
    const same = (a, bb) => a.byteLength === bb.byteLength && new Uint8Array(a).every((v, i) => v === new Uint8Array(bb)[i]);
    const P = (window.__push = { log: [], n: 0, current: null });
    const make = (endpoint, keyBytes) => ({
      endpoint, expirationTime: null, options: { userVisibleOnly: true, applicationServerKey: keyBytes.buffer },
      toJSON() { return { endpoint, expirationTime: null, keys: { p256dh: 'BP' + endpoint, auth: 'A' } }; },
      async unsubscribe() { P.log.push(['unsubscribe', endpoint]); if (P.current && P.current.endpoint === endpoint) P.current = null; return true; },
    });
    if (leftover) P.current = make(leftover.endpoint, dec(leftover.key));
    if (savedFilters) localStorage.setItem('cw-push-filters', JSON.stringify(savedFilters));
    if (!window.PushManager) return;
    PushManager.prototype.getSubscription = async () => P.current;
    PushManager.prototype.subscribe = async (opts) => {
      const k = new Uint8Array(opts.applicationServerKey);
      if (P.current) {
        if (same(P.current.options.applicationServerKey, k)) { P.log.push(['subscribe→existing', P.current.endpoint]); return P.current; }
        P.log.push(['subscribe→InvalidStateError']); throw new DOMException('different applicationServerKey', 'InvalidStateError');
      }
      if (failSubscribe) { P.log.push(['subscribe→AbortError']); throw new DOMException('Registration failed - push service error', 'AbortError'); }
      P.current = make(`https://fcm.googleapis.com/fcm/send/fresh-${++P.n}`, k);
      P.log.push(['subscribe→new', P.current.endpoint]);
      return P.current;
    };
  }, { leftover, savedFilters, failSubscribe });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
  await p.goto(base + '#alerts'); await p.waitForSelector('.alerts-list'); await p.evaluate(() => navigator.serviceWorker.register('sw.js').then(() => navigator.serviceWorker.ready));
  const out = await actions(p);
  const push = await p.evaluate(() => ({ log: window.__push.log, current: window.__push.current?.endpoint || null }));
  await ctx.close();
  const posts = calls.filter((c) => c.m === 'POST'), dels = calls.filter((c) => c.m === 'DELETE');
  return { ...out, push, posted: posts.map((c) => c.body.subscription.endpoint), deleted: dels.map((c) => c.body.endpoint), errs };
}
const openPanel = async (p) => { await p.click('[data-act="get-alerts"]'); await p.waitForSelector('#get-alerts h3'); await p.waitForTimeout(300); };
const turnOn = async (p) => { await p.waitForSelector('.ga-form'); await p.click('.ga-form button[type="submit"]'); await p.waitForSelector('.ga-on', { timeout: 10000 }); };

const STALE = 'https://fcm.googleapis.com/fcm/send/STALE-left-over';
const R = {};
// T1: leftover subscription (same key), no saved filters: must NOT post the leftover; fresh endpoint posted.
R.T1 = await run({ leftover: { endpoint: STALE, key: SERVER_KEY }, actions: async (p) => { await openPanel(p); await turnOn(p); return {}; } });
// T2: "on" already (saved filters) but the leftover was made with an OLD key: resubscribe with the server key.
R.T2 = await run({ leftover: { endpoint: STALE, key: OLD_KEY }, savedFilters: { creek_ids: [], min_severity: 'watch', quiet_hours: null },
  actions: async (p) => { await openPanel(p); await p.click('[data-ga="edit"]'); await p.waitForSelector('.ga-form'); await p.click('.ga-form button[type="submit"]'); await p.waitForSelector('.ga-on', { timeout: 10000 }); return {}; } });
// T3: "on" already with the SAME key, Save changes: reuse it (no churn), no DELETE.
R.T3 = await run({ leftover: { endpoint: STALE.replace('STALE', 'GOOD'), key: SERVER_KEY }, savedFilters: { creek_ids: [], min_severity: 'watch', quiet_hours: null },
  actions: async (p) => { await openPanel(p); await p.click('[data-ga="edit"]'); await p.waitForSelector('.ga-form'); await p.click('.ga-form button[type="submit"]'); await p.waitForSelector('.ga-on', { timeout: 10000 }); return {}; } });
// T4: init twice (panel toggled) + double-tap submit: exactly one subscribe and one POST.
R.T4 = await run({ actions: async (p) => {
  await openPanel(p); await p.click('[data-act="get-alerts"]'); await openPanel(p); await p.waitForSelector('.ga-form');
  await p.locator('.ga-form button[type="submit"]').dblclick(); await p.waitForSelector('.ga-on', { timeout: 10000 }); await p.waitForTimeout(500); return {}; } });
// T6: leftover replaced, then the fresh subscribe() fails → plain "alerts are OFF" message, state cleared.
R.T6 = await run({ leftover: { endpoint: STALE, key: SERVER_KEY }, savedFilters: { creek_ids: ['wolf'], min_severity: 'alert', quiet_hours: null }, failSubscribe: true,
  actions: async (p) => {
    await openPanel(p); await p.click('[data-ga="edit"]'); await p.waitForSelector('.ga-form');
    // force a replace on "Save": make the saved state look like it came from an older flow (no saved filters)
    await p.evaluate(() => localStorage.removeItem('cw-push-filters'));
    await p.click('.ga-form button[type="submit"]'); await p.waitForTimeout(1200);
    return { hint: await p.locator('.ga-form .need-hint').textContent(), filtersAfter: await p.evaluate(() => localStorage.getItem('cw-push-filters')), onShown: await p.locator('.ga-on').count() };
  } });
// T7: no leftover, subscribe() fails → the generic message (nothing was removed, so don't claim it was).
R.T7 = await run({ failSubscribe: true, actions: async (p) => {
  await openPanel(p); await p.waitForSelector('.ga-form'); await p.click('.ga-form button[type="submit"]'); await p.waitForTimeout(1200);
  return { hint: await p.locator('.ga-form .need-hint').textContent() }; } });
await b.close(); close();

const fresh = (r) => r.posted.length === 1 && !r.posted[0].includes('STALE') && r.push.current === r.posted[0];
const checks = {
  T1_postsFreshNotLeftover: fresh(R.T1),
  T1_leftoverUnsubscribed: R.T1.push.log.some(([k, e]) => k === 'unsubscribe' && e === STALE),
  T2_rotatedKeyResubscribed: fresh(R.T2) && R.T2.deleted.includes(STALE),
  T3_sameKeyReused: R.T3.posted.length === 1 && R.T3.posted[0].includes('GOOD') && R.T3.deleted.length === 0 && !R.T3.push.log.some(([k]) => k === 'unsubscribe'),
  T4_onceOnly: R.T4.posted.length === 1 && R.T4.push.log.filter(([k]) => k.startsWith('subscribe')).length === 1,
  T5_nothingAfterPost: [R.T1, R.T2, R.T3, R.T4].every((r) => r.push.current === r.posted.at(-1)),
  noPageErrors: [R.T1, R.T2, R.T3, R.T4, R.T6, R.T7].every((r) => !r.errs.length),
  T6_offMessageAfterReplace: R.T6.hint === 'Your previous alert subscription was removed and a new one couldn’t be created, so alerts are OFF on this phone. Tap Turn on alerts to try again.'
    && R.T6.filtersAfter === null && R.T6.onShown === 0 && R.T6.deleted.includes(STALE) && R.T6.posted.length === 0,
  T7_genericWhenNothingRemoved: /Couldn’t turn on alerts on this phone/.test(R.T7.hint || '') && !/OFF/.test(R.T7.hint || ''),
};
console.log(JSON.stringify({ R, checks }, null, 1));
const ok = Object.values(checks).every(Boolean);
console.log(ok ? 'PASS push-subscribe' : `FAIL push-subscribe: ${Object.entries(checks).filter(([, v]) => !v).map(([k]) => k).join(', ')}`);
process.exit(ok ? 0 : 1);
