// "I picked it up" + device-local badges + community counter (JP request).
// SHOTS=<dir> also saves 390x844 screenshots (light + dark).
import { serveWeb, launch, mock } from './harness.mjs';

const SHOTS = process.env.SHOTS || '';
const { base, close } = await serveWeb();
const b = await launch();
const json = (body, status = 200) => ({ status, contentType: 'application/json', body: typeof body === 'string' ? body : JSON.stringify(body) });
const R = {};
const shot = async (p, name) => { if (SHOTS) await p.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false }); };

async function newCtx({ scheme = 'light', blockStorage = false } = {}) {
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, colorScheme: scheme,
    serviceWorkers: 'block', geolocation: { latitude: 39.2186, longitude: -121.0612, accuracy: 10 }, permissions: ['geolocation'] });
  if (blockStorage) await ctx.addInitScript(() => {
    const boom = () => { throw new DOMException('blocked', 'SecurityError'); };
    Storage.prototype.setItem = boom; Storage.prototype.getItem = boom;
  });
  return ctx;
}
// Walk the report flow to the review step with Some trash, picked up, `bags` bags.
async function fileCleanup(p, { bags = 3, pickUp = true, name = '' } = {}) {
  await p.waitForSelector('.step-title');
  await p.click('[data-act="no-photo"]'); await p.waitForSelector('.gps-card.ok'); await p.click('[data-act="next"]');
  for (const [n, v] of [['water_color', 'clear'], ['flow', 'normal']]) await p.click(`label.choice:has(input[name="${n}"][value="${v}"]) .choice-face`);
  await p.click('[data-act="next"]');
  await p.click('label.choice:has(input[name="algae"][value="none"]) .choice-face');
  R[`${name}blockHiddenBeforeTrash`] = (await p.locator('.cleanup').count()) === 0;
  await p.click('label.choice:has(input[name="trash"][value="some"]) .choice-face');
  R[`${name}safetyShown`] = (await p.locator('.safety').count()) === 1;
  if (pickUp) {
    await p.click('[data-act="cleanup"]');
    R[`${name}togglePressed`] = (await p.getAttribute('[data-act="cleanup"]', 'aria-pressed')) === 'true';
    for (let i = 0; i < bags; i++) await p.click('[data-act="bags-inc"]');
    R[`${name}bagsShown`] = await p.locator('.bags-n').textContent();
  }
  if (name === 'A_') await shot(p, '1-trash-step');
  await p.click('label.choice:has(input[name="dead_fish"][value="false"]) .choice-face');
  await p.click('[data-act="next"]'); await p.click('label.choice:has(input[name="odor"][value="none"]) .choice-face'); await p.click('[data-act="next"]');
  R[`${name}summaryRow`] = (await p.locator('.sum-row', { hasText: 'Cleanup' }).innerText().catch(() => '')).replace(/\s+/g, ' ');
  if (name === 'A_') await shot(p, '2-review');
  await p.click('button[type="submit"]'); await p.waitForSelector('section.done');
}

// A. Real network path: POST multipart carries trash_removed/trash_bags.
{
  const ctx = await newCtx(); let post = '';
  await ctx.route('**/api/creeks', (r) => r.fulfill(json(mock('creeks'))));
  await ctx.route('**/api/reports', (r) => {
    if (r.request().method() !== 'POST') return r.fulfill(json('[]'));
    post = r.request().postData() || '';
    return r.fulfill(json({ id: 1, creek_id: 'wolf', trash: 'some', water_color: 'clear', algae: 'none', odor: 'none', trash_removed: true, trash_bags: 3, flags: ['trash_removed'], photo_url: null }, 201));
  });
  await ctx.route('**/api/{alerts,health,conditions,stats}**', (r) => r.fulfill(json('[]')));
  const p = await ctx.newPage(); p.on('pageerror', (e) => console.error('A pageerror:', e.message));
  await p.goto(base + '#report'); await p.evaluate(() => localStorage.clear()); await p.reload();
  await fileCleanup(p, { bags: 3, name: 'A_' });
  const field = (n) => (post.match(new RegExp(`name="${n}"\\r\\n\\r\\n([^\\r]*)`)) || [])[1];
  R.A_postTrashRemoved = field('trash_removed'); R.A_postTrashBags = field('trash_bags');
  R.A_celebrate = await p.locator('.celebrate').count();
  R.A_noWarningForCleanup = (await p.locator('.flag-list li').count()) === 0;
  R.A_bandNotRaised = (await p.locator('.band-chip').innerText()).includes('Fair');
  R.A_bands = await p.evaluate(async () => {
    const { reportBand } = await import('/js/api.js');
    const base = { water_color: 'clear', algae: 'none', odor: 'none', dead_fish: false };
    return {
      cleanOnly: reportBand({ ...base, trash: 'none', flags: ['trash_removed'] }),
      someTrashCleaned: reportBand({ ...base, trash: 'some', flags: ['trash_removed'] }),
      heavyStillWatch: reportBand({ ...base, trash: 'lots', flags: ['trash_heavy', 'trash_removed'] }),
    };
  });
  R.A_newBadge = await p.locator('.new-badge strong').allTextContents();
  R.A_stored = await p.evaluate(() => JSON.parse(localStorage.getItem('cw-badges') || 'null'));
  R.A_badgeAlt = await p.locator('.new-badge svg[role="img"]').getAttribute('aria-label');
  await p.locator('.celebrate').scrollIntoViewIfNeeded(); await shot(p, '3-celebrate');
  await ctx.close();
}
// B. Thresholds: 4 cleanups / 8 bags + one more with 2 bags → Steward + Hero.
{
  const ctx = await newCtx();
  const p = await ctx.newPage();
  await p.goto(base + 'index.html?mock=1#report');
  await p.evaluate(() => localStorage.setItem('cw-badges', JSON.stringify({ cleanups: 4, bags: 8, earned: { helper: '2026-10-01T00:00:00Z' } })));
  await p.reload(); await fileCleanup(p, { bags: 2, name: 'B_' });
  R.B_newBadges = await p.locator('.new-badge strong').allTextContents();
  R.B_stripEarned = await p.locator('.badge-strip li.got .b-name').allTextContents();
  await ctx.close();
}
// C. Trash "none" hides and resets the cleanup.
{
  const ctx = await newCtx(); const p = await ctx.newPage();
  await p.goto(base + 'index.html?mock=1#report'); await p.evaluate(() => localStorage.clear()); await p.reload();
  await p.waitForSelector('.step-title'); await p.click('[data-act="no-photo"]'); await p.waitForSelector('.gps-card.ok'); await p.click('[data-act="next"]');
  for (const [n, v] of [['water_color', 'clear'], ['flow', 'normal']]) await p.click(`label.choice:has(input[name="${n}"][value="${v}"]) .choice-face`);
  await p.click('[data-act="next"]');
  await p.click('label.choice:has(input[name="trash"][value="lots"]) .choice-face'); await p.click('[data-act="cleanup"]'); await p.click('[data-act="bags-inc"]');
  await p.click('label.choice:has(input[name="trash"][value="none"]) .choice-face');
  R.C_blockGoneOnNone = (await p.locator('.cleanup').count()) === 0;
  await p.click('label.choice:has(input[name="trash"][value="some"]) .choice-face');
  R.C_resetAfterNone = (await p.getAttribute('[data-act="cleanup"]', 'aria-pressed')) === 'false';
  await ctx.close();
}
// D. Storage blocked: the flow still completes; honest copy instead of badges.
{
  // Production path (real network, /api intercepted): every storage access is blocked.
  const ctx = await newCtx({ blockStorage: true }); const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
  await ctx.route('**/api/creeks', (r) => r.fulfill(json(mock('creeks'))));
  await ctx.route('**/api/reports', (r) => (r.request().method() === 'POST'
    ? r.fulfill(json({ id: 2, creek_id: 'wolf', trash_removed: true, trash_bags: 1, flags: [], photo_url: null }, 201)) : r.fulfill(json('[]'))));
  await ctx.route('**/api/{alerts,health,conditions,stats}**', (r) => r.fulfill(json('[]')));
  await p.goto(base + '#report'); await fileCleanup(p, { bags: 1, name: 'D_' });
  R.D_doneShown = await p.locator('section.done').count();
  R.D_honestNote = (await p.locator('.celebrate .b-note').innerText()).includes('isn’t letting us save badges');
  R.D_pageErrors = errs.length;
  await ctx.close();
}
// E/F/G. Counter, chip, pin badge, About strip (light + dark screenshots).
for (const scheme of ['light', 'dark']) {
  const ctx = await newCtx({ scheme }); const p = await ctx.newPage();
  await p.goto(base + 'index.html?mock=1#dashboard'); await p.waitForSelector('.creek-card .signal');
  const wolf = p.locator('.creek-card').first(), deer = p.locator('.creek-card', { has: p.locator('h2', { hasText: 'Deer Creek' }) });
  R[`E_${scheme}_wolfCounter`] = (await wolf.locator('.cleanup-count').innerText().catch(() => '')).replace(/\s+/g, ' ');
  R[`E_${scheme}_deerCounterHidden`] = (await deer.locator('.cleanup-count').count()) === 0;
  R[`F_${scheme}_cleanChips`] = await p.locator('.rep-tags .tag-clean').count();
  await wolf.locator('.cleanup-count').scrollIntoViewIfNeeded(); await shot(p, `4-dashboard-counter-${scheme}`);
  await p.goto(base + 'index.html?mock=1#map'); await p.waitForSelector('.leaflet-marker-icon .pin', { timeout: 20000 }); await p.waitForTimeout(1500);
  R[`F_${scheme}_pinBadges`] = await p.locator('.leaflet-marker-icon .pin-clean').count();
  await p.evaluate(() => localStorage.setItem('cw-badges', JSON.stringify({ cleanups: 2, bags: 3, earned: { helper: '2026-10-03T00:00:00Z' } })));
  await p.goto(base + 'index.html?mock=1#about'); await p.waitForSelector('#about-badges .badge-strip');
  R[`G_${scheme}_aboutStrip`] = (await p.locator('#about-badges .b-note').innerText()).includes('Badges live on this phone only');
  R[`G_${scheme}_lockedTextNotColourOnly`] = (await p.locator('#about-badges li.locked .b-rule').allTextContents()).every((t) => t.startsWith('Locked'));
  await p.locator('#about-badges').scrollIntoViewIfNeeded(); await shot(p, `5-about-badges-${scheme}`);
  await ctx.close();
}
// E. Counter hidden on API error (real network path).
{
  const ctx = await newCtx(); const p = await ctx.newPage();
  await ctx.route('**/api/creeks', (r) => r.fulfill(json(mock('creeks'))));
  await ctx.route('**/api/stats/cleanups**', (r) => r.fulfill(json({ detail: 'boom' }, 500)));
  await ctx.route('**/api/{alerts,health,conditions,reports}**', (r) => r.fulfill(json('[]')));
  await p.goto(base + '#dashboard'); await p.waitForSelector('.creek-card'); await p.waitForTimeout(500);
  R.E_counterHiddenOnError = (await p.locator('.cleanup-count').count()) === 0;
  await ctx.close();
}
await b.close(); close();

const checks = {
  hiddenUntilTrash: R.A_blockHiddenBeforeTrash, safety: R.A_safetyShown, toggle: R.A_togglePressed, bags3: R.A_bagsShown === '3',
  summary: /Picked up, about 3 bags/.test(R.A_summaryRow), postTrashRemoved: R.A_postTrashRemoved === 'true', postTrashBags: R.A_postTrashBags === '3',
  celebrate: R.A_celebrate === 1, noWarningForCleanup: R.A_noWarningForCleanup, bandNotRaised: R.A_bandNotRaised,
  positiveFlagNeverRaisesBand: R.A_bands?.cleanOnly === 'good' && R.A_bands?.someTrashCleaned === 'fair' && R.A_bands?.heavyStillWatch === 'watch', helperEarned: R.A_newBadge?.join() === 'Creek Helper', storedCounts: R.A_stored?.cleanups === 1 && R.A_stored?.bags === 3,
  badgeAlt: R.A_badgeAlt === 'Creek Helper badge',
  stewardAndHero: R.B_newBadges?.join() === 'Creek Steward,Trash Hero', stripAllEarned: R.B_stripEarned?.length === 3,
  noneHides: R.C_blockGoneOnNone, noneResets: R.C_resetAfterNone,
  storageBlockedStillWorks: R.D_doneShown === 1 && R.D_honestNote && R.D_pageErrors === 0,
  counterWolf: /^🧤 7 reported cleanups · 12 bags since [A-Z][a-z]{2} \d+ \(self-reported by volunteers\)$/.test(R.E_light_wolfCounter.trim()), counterNeverVerified: !/verified/i.test(R.E_light_wolfCounter), counterZeroHidden: R.E_light_deerCounterHidden,
  counterErrorHidden: R.E_counterHiddenOnError, cleanedChip: R.F_light_cleanChips >= 1, pinBadge: R.F_light_pinBadges >= 1,
  aboutStrip: R.G_light_aboutStrip && R.G_dark_aboutStrip, lockedHasText: R.G_light_lockedTextNotColourOnly,
};
console.log(JSON.stringify({ R, checks }, null, 1));
const ok = Object.values(checks).every(Boolean);
console.log(ok ? 'PASS cleanup' : `FAIL cleanup: ${Object.entries(checks).filter(([, v]) => !v).map(([k]) => k).join(', ')}`);
process.exit(ok ? 0 : 1);
