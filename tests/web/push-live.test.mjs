// Real round trip against a running backend (alerts + Web Push configured):
//   BASE=http://127.0.0.1:8099/ [DB=path/to/creekwatch.db] node push-live.test.mjs
// Only PushManager is stubbed (headless Chrome can't reach FCM); the subscription carries real-format
// keys (P-256 point + 16-byte auth) so the server's validation applies. Never point this at production.
import { execFileSync } from 'node:child_process';
import { launch } from './harness.mjs';

const BASE = process.env.BASE;
if (!BASE || !/^http:\/\/(127\.0\.0\.1|localhost)[:/]/.test(BASE)) { console.error('Set BASE to a LOCAL backend, e.g. http://127.0.0.1:8099/'); process.exit(2); }
const rows = () => (process.env.DB ? execFileSync('python3', ['-c', `import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute("select creek_ids,min_severity,quiet_start,quiet_end,tz from push_subscriptions").fetchall())`, process.env.DB]).toString().trim() : '(DB not given)');
const b = await launch();
const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, permissions: ['notifications'] });
await ctx.addInitScript(() => {
  let current = null;
  const b64u = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  if (!window.PushManager) return;
  PushManager.prototype.subscribe = async function () {
    const kp = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
    const keys = { p256dh: b64u(await crypto.subtle.exportKey('raw', kp.publicKey)), auth: b64u(crypto.getRandomValues(new Uint8Array(16))) };
    const endpoint = 'https://fcm.googleapis.com/fcm/send/livetest-' + Math.random().toString(36).slice(2);
    current = { endpoint, expirationTime: null, toJSON: () => ({ endpoint, expirationTime: null, keys }), unsubscribe: async () => { current = null; return true; } };
    return current;
  };
  PushManager.prototype.getSubscription = async function () { return current; };
});
const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
const net = []; p.on('response', (r) => { if (r.url().includes('/api/push/subscriptions')) net.push(`${r.request().method()} ${r.status()}`); });
await p.goto(BASE + '#alerts'); await p.waitForSelector('.alerts-list'); await p.evaluate(() => navigator.serviceWorker.ready);
await p.click('[data-act="get-alerts"]'); await p.waitForSelector('.ga-form');
await p.uncheck('input[name="creek"][value="wolf"]'); await p.check('input[name="minsev"][value="alert"]');
await p.check('input[name="quiet"]'); await p.fill('input[name="qstart"]', '21:30');
await p.click('.ga-form button[type="submit"]'); await p.waitForSelector('.ga-on', { timeout: 10000 });
const afterCreate = rows();
await p.click('[data-ga="edit"]'); await p.waitForSelector('.ga-form');
await p.check('input[name="creek"][value="wolf"]'); await p.check('input[name="minsev"][value="watch"]');
await p.click('.ga-form button[type="submit"]'); await p.waitForSelector('.ga-on');
const afterUpdate = rows();
await p.click('[data-ga="stop"]'); await p.waitForSelector('.ga-form');
const afterStop = rows();
await b.close();
console.log(JSON.stringify({ net, afterCreate, afterUpdate, afterStop, pageErrors: errs }, null, 1));
const ok = net.join(',') === 'POST 201,POST 200,DELETE 204' && !errs.length;
console.log(ok ? 'PASS push-live' : 'FAIL push-live');
process.exit(ok ? 0 : 1);
