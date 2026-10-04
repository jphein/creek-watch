// Field bug (found in the final prod pass, 2026-10-03): with a slow /api/creeks (weak signal at the creek), the
// Report page re-rendered the photo step while the phone's camera was open. The tapped <input> was replaced,
// its `change` fired on a detached element, and the photo was silently lost.
// Camera model: tap at t=1 s (camera opens), creeks arrive at t=3 s, camera returns at t=4 s on the TAPPED input.
import fs from 'node:fs';
import { serveWeb, launch, mock, WEB } from './harness.mjs';

const { base, close } = await serveWeb();
const b = await launch();
const b64 = fs.readFileSync(`${WEB}/icons/apple-touch-icon.png`).toString('base64'); // any real image
const out = [];
for (const delay of [0, 3000]) {
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, serviceWorkers: 'block' });
  await ctx.route('**/api/creeks', async (r) => { await new Promise((s) => setTimeout(s, delay)); r.fulfill({ status: 200, contentType: 'application/json', body: mock('creeks') }); });
  await ctx.route('**/api/**', (r) => (r.request().url().includes('/api/creeks') ? r.fallback() : r.fulfill({ status: 200, contentType: 'application/json', body: '[]' })));
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
  const t0 = Date.now();
  await p.goto(base + '#report'); await p.evaluate(() => localStorage.clear()); await p.reload();
  await p.waitForSelector('.step-title');
  const formShownMs = Date.now() - t0;
  await p.waitForTimeout(1000);
  await p.locator('label.file-btn').first().click({ trial: true }).catch(() => {});
  await p.evaluate(() => { const el = document.querySelector('input[data-photo][capture]'); window.__tapped = el; el.closest('label').dispatchEvent(new MouseEvent('click', { bubbles: true })); });
  await p.waitForTimeout(delay + 1000);
  const r = await p.evaluate(async (b64) => {
    const el = window.__tapped, bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const dt = new DataTransfer(); dt.items.add(new File([bytes], 'photo.png', { type: 'image/png' }));
    el.files = dt.files; el.dispatchEvent(new Event('change', { bubbles: true }));
    return { stillInDom: document.contains(el) };
  }, b64);
  await p.waitForTimeout(1500);
  const kept = (await p.locator('.photo-zone.has img').count()) === 1;
  // Next must still work and show the creeks (the photo step skipped the late re-render, the "where" step renders them)
  let whereShowsCreeks = false;
  if (kept) { await p.click('[data-act="next"]', { timeout: 5000 }).catch(() => {}); await p.waitForTimeout(500); whereShowsCreeks = (await p.locator('input[name="creek_id"]').count()) >= 2; }
  out.push({ creeksDelayMs: delay, formShownMs, tappedInputStillInDom: r.stillInDom, photoKept: kept, whereShowsCreeks, errs });
  await ctx.close();
}
await b.close(); close();
const ok = out.every((x) => x.photoKept && x.tappedInputStillInDom && x.whereShowsCreeks && !x.errs.length);
console.log(JSON.stringify(out, null, 1));
console.log(ok ? 'PASS photo-race' : 'FAIL photo-race');
process.exit(ok ? 0 : 1);
