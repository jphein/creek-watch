// Planned-move write freeze: the server answers POST with 503 + Retry-After. The report must be queued (not lost)
// and retried automatically. Also: permanent 4xx is not queued; the photo-budget 503 still offers "send without photo".
import fs from 'node:fs';
import { serveWeb, launch, mock, WEB } from './harness.mjs';

const MOVE = "Creek Watch is moving to a new home for a few minutes; please try again shortly. Your report was not saved.";
const { base, close } = await serveWeb();
const b = await launch();
const PHOTO = `${WEB}/icons/apple-touch-icon.png`;

async function run(respond, { photo = true } = {}) {
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, serviceWorkers: 'block',
    geolocation: { latitude: 39.2127, longitude: -121.0648, accuracy: 8 }, permissions: ['geolocation'] });
  let posts = 0;
  await ctx.route('**/api/creeks', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: mock('creeks') }));
  await ctx.route('**/api/reports', (r) => (r.request().method() === 'POST' ? respond(r, ++posts) : r.fulfill({ status: 200, contentType: 'application/json', body: '[]' })));
  await ctx.route('**/api/{alerts,health,conditions,stats}**', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
  await p.goto(base + '#report'); await p.evaluate(() => { localStorage.clear(); indexedDB.deleteDatabase('creekwatch'); }); await p.reload();
  await p.waitForSelector('.step-title'); await p.waitForLoadState('networkidle');
  if (photo) { await p.setInputFiles('input[data-photo][capture]', PHOTO); await p.waitForSelector('.photo-zone.has img'); } else await p.click('[data-act="no-photo"]');
  if (photo) await p.click('[data-act="next"]');
  await p.waitForSelector('.gps-card.ok'); await p.click('[data-act="next"]');
  for (const [n, v] of [['water_color', 'clear'], ['flow', 'normal']]) await p.click(`label.choice:has(input[name="${n}"][value="${v}"]) .choice-face`);
  await p.click('[data-act="next"]');
  for (const [n, v] of [['algae', 'none'], ['trash', 'none'], ['dead_fish', 'false']]) await p.click(`label.choice:has(input[name="${n}"][value="${v}"]) .choice-face`);
  await p.click('[data-act="next"]'); await p.click('label.choice:has(input[name="odor"][value="none"]) .choice-face'); await p.click('[data-act="next"]');
  await p.click('button[type="submit"]'); await p.waitForSelector('.banner.error, section.done');
  const out = {
    bannerText: (await p.locator('.banner.error').innerText().catch(() => '')).replace(/\s+/g, ' '),
    queueBtn: await p.locator('[data-act="queue"]').count(), noPhotoBtn: await p.locator('[data-act="send-nophoto"]').count(),
  };
  const outbox = () => p.evaluate(() => new Promise((ok) => { const q = indexedDB.open('creekwatch'); q.onsuccess = () => { try { const g = q.result.transaction('outbox').objectStore('outbox').getAll(); g.onsuccess = () => ok(g.result.length); } catch { ok(-1); } }; }));
  return { p, ctx, out, outbox, posts: () => posts, errs };
}

const R = {};
// A. Planned move: 503 + Retry-After 2 on the first POST, 201 afterwards.
{
  const t = await run((r, n) => (n === 1
    ? r.fulfill({ status: 503, headers: { 'Retry-After': '2', 'content-type': 'application/json' }, body: JSON.stringify({ detail: MOVE }) })
    : r.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ id: 7, creek_id: 'wolf', flags: [], photo_url: null }) })));
  const a = { ...t.out };
  await t.p.click('[data-act="queue"]'); await t.p.waitForSelector('section.done');
  a.queuedTitle = await t.p.locator('section.done h2').textContent(); a.queuedLead = await t.p.locator('section.done .lead').textContent();
  a.outboxAfterQueue = await t.outbox();
  await t.p.waitForTimeout(7500); // Retry-After 2 → clamped to 5 s
  a.outboxAfterRetry = await t.outbox(); a.posts = t.posts(); a.toast = await t.p.locator('#toast').textContent(); a.errs = t.errs;
  R.A = a; await t.ctx.close();
}
// B. Permanent 4xx (validation): don't offer the outbox.
{
  const t = await run((r) => r.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: 'That location is 40 km from Wolf Creek.' }) }), { photo: false });
  R.B = { ...t.out, errs: t.errs }; await t.ctx.close();
}
// C. Photo-budget 503 still offers "Send without the photo".
{
  const t = await run((r) => r.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: "We're receiving a lot of photos right now. Please send your report without the photo, or try again in a few minutes." }) }));
  R.C = { ...t.out, errs: t.errs }; await t.ctx.close();
}
await b.close(); close();

const checks = {
  A_showsServerText: R.A.bannerText.includes('moving to a new home'),
  A_offersQueue: R.A.queueBtn === 1,
  A_noBogusNoPhoto: R.A.noPhotoBtn === 0,
  A_queuedServerCopy: /it will send itself/.test(R.A.queuedTitle) && /busy for a few minutes/.test(R.A.queuedLead),
  A_queued: R.A.outboxAfterQueue === 1,
  A_autoRetried: R.A.posts === 2 && R.A.outboxAfterRetry === 0 && /saved report was sent/.test(R.A.toast),
  B_noQueueFor4xx: R.B.queueBtn === 0,
  C_photoBudgetStillOffersNoPhoto: R.C.noPhotoBtn === 1 && R.C.queueBtn === 1,
  noPageErrors: ![R.A, R.B, R.C].some((x) => x.errs.length),
};
console.log(JSON.stringify({ R, checks }, null, 1));
const ok = Object.values(checks).every(Boolean);
console.log(ok ? 'PASS outbox-retry' : `FAIL outbox-retry: ${Object.entries(checks).filter(([, v]) => !v).map(([k]) => k).join(', ')}`);
process.exit(ok ? 0 : 1);
