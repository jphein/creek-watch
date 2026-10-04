// Service-worker push handler: delivers pushes over CDP and reads back the notifications.
// Desktop context on purpose: mobile emulation hides notifications from getNotifications().
// The first CDP push after ServiceWorker.enable is dropped by the instrument, so a warm-up is sent first.
import { serveWeb, launch } from './harness.mjs';

const { base, close } = await serveWeb();
const b = await launch();
const ctx = await b.newContext({ permissions: ['notifications'] });
await ctx.route('**/api/**', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
const p = await ctx.newPage();
await p.goto(base + '#about'); await p.evaluate(() => navigator.serviceWorker.register('sw.js').then(() => navigator.serviceWorker.ready));
const cdp = await ctx.newCDPSession(p);
const regs = []; cdp.on('ServiceWorker.workerRegistrationUpdated', (e) => regs.push(...e.registrations));
await cdp.send('ServiceWorker.enable'); await p.waitForTimeout(600);
const reg = regs.find((r) => !r.isDeleted);
const origin = base.replace(/\/$/, '');
let last = [];
// Read back after every push (reading only once at the end came back empty in headless Chrome).
const send = async (data) => { for (let i = 0; i < 3; i++) { try { await cdp.send('ServiceWorker.deliverPushMessage', { origin, registrationId: reg.registrationId, data }); break; } catch { await p.waitForTimeout(400); } } await p.waitForTimeout(1300); last = await read(); };
const read = () => p.evaluate(async () => (await (await navigator.serviceWorker.ready).getNotifications()).map((n) => ({ title: n.title, body: n.body, tag: n.tag, ri: n.requireInteraction, url: n.data?.url })));
await send(JSON.stringify({ id: 'warmup', severity: 'info', title: 'w', summary: 'w' }));
await send(JSON.stringify({ id: 'sso:1182', tag: 'sso:1182', kind: 'new', severity: 'alert', title: 'Sewage spill near Deer Creek', summary: 'Avoid contact.', url: '/#alerts?id=sso%3A1182', source_url: 'https://evil.example/', notice: 'Emergencies: 911. Official: Nevada County Alerts, AwareCA.' }));
await send(JSON.stringify({ id: 'hab:7', kind: 'new', severity: 'watch', title: 'Algae caution', summary: 'Caution.' }));
await send(JSON.stringify({ id: 'hab:7', kind: 'escalated', severity: 'alert', title: 'Algae danger', summary: 'Danger.' }));
await send(JSON.stringify({ id: 'evil:1', severity: 'watch', title: '<b>x</b>', summary: 'y', url: 'https://evil.example/phish' }));
await send('not json at all');
await send(JSON.stringify({ id: 'cw-welcome', tag: 'cw-welcome', kind: 'welcome', severity: 'info', title: 'Creek Watch alerts are on',
  body: "You'll get watch-level and higher alerts for Deer Creek. For emergencies: Nevada County Alerts, AwareCA, 911.",
  summary: "You'll get watch-level and higher alerts for Deer Creek. For emergencies: Nevada County Alerts, AwareCA, 911.",
  url: '/#alerts', official: false, notice: 'Emergencies: 911. Official: Nevada County Alerts, AwareCA.', creek_ids: ['deer'] }));
const n = last;
await b.close(); close();
const by = (tag) => n.filter((x) => x.tag === tag);
const checks = {
  alertHasNotice: by('sso:1182')[0]?.body.includes('Nevada County Alerts') && by('sso:1182')[0]?.ri === true,
  alertDeepLinkSameOrigin: by('sso:1182')[0]?.url === `${base}#alerts?id=sso%3A1182`,
  escalationReplaced: by('hab:7').length === 1 && by('hab:7')[0].title.startsWith('ALERT:'),
  offsiteUrlIgnored: by('evil:1')[0]?.url.startsWith(base),
  htmlTitleLiteral: by('evil:1')[0]?.title === 'WATCH: <b>x</b>',
  malformedGeneric: by('creekwatch').length === 1,
  welcomeShownAsIs: by('cw-welcome')[0]?.title === 'Creek Watch alerts are on' && by('cw-welcome')[0]?.ri === false,
  welcomeDeferralOnce: (by('cw-welcome')[0]?.body.match(/Nevada County Alerts/g) || []).length === 1,
  welcomeOpensAlerts: by('cw-welcome')[0]?.url === `${base}#alerts`,
};
console.log(JSON.stringify({ notifications: n, checks }, null, 1));
const ok = Object.values(checks).every(Boolean);
console.log(ok ? 'PASS push-sw' : 'FAIL push-sw');
process.exit(ok ? 0 : 1);
