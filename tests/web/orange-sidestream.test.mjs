// "Orange" water colour + side-stream reporting (local watershed feedback).
// SHOTS=<dir> saves 390x844 screenshots (light + dark).
import { serveWeb, launch, mock } from './harness.mjs';

const SHOTS = process.env.SHOTS || '';
const { base, close } = await serveWeb();
const b = await launch();
const json = (body, status = 200) => ({ status, contentType: 'application/json', body: typeof body === 'string' ? body : JSON.stringify(body) });
const TRIB = { latitude: 39.235, longitude: -121.04, accuracy: 8 };      // > 0.5 km from every named spot
const AT_SITE = { latitude: 39.2127, longitude: -121.0648, accuracy: 8 }; // Memorial Park (mock)
const field = (post, n) => (post.match(new RegExp(`name="${n}"\\r\\n\\r\\n([^\\r]*)`)) || [])[1];

async function flow({ geo, scheme = 'light', color = 'orange', chooseElsewhere = false, shots = '' }) {
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, colorScheme: scheme,
    serviceWorkers: 'block', geolocation: geo, permissions: ['geolocation'] });
  let post = '';
  await ctx.route('**/api/creeks', (r) => r.fulfill(json(mock('creeks'))));
  await ctx.route('**/api/reports', (r) => {
    if (r.request().method() !== 'POST') return r.fulfill(json('[]'));
    post = r.request().postData() || '';
    return r.fulfill(json({ id: 1, creek_id: field(post, 'creek_id'), water_color: field(post, 'water_color'), location_kind: field(post, 'location_kind') || null, flags: [], photo_url: null }, 201));
  });
  await ctx.route('**/api/{alerts,health,conditions,stats}**', (r) => r.fulfill(json('[]')));
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
  await p.goto(base + '#report'); await p.evaluate(() => localStorage.clear()); await p.reload(); await p.waitForSelector('.step-title');
  await p.click('[data-act="no-photo"]'); await p.waitForSelector('.gps-card.ok');
  const out = {
    autoPicked: await p.evaluate(() => document.querySelector('input[name="site_id"]:checked')?.value ?? null),
    gpsText: (await p.locator('.gps-card').innerText()).replace(/\s+/g, ' '),
  };
  if (chooseElsewhere) {
    const el = p.locator('label.site:has(input[name="site_id"][value=""]) .site-face');
    await el.scrollIntoViewIfNeeded(); await p.waitForTimeout(300); await el.click({ force: true }); await p.waitForTimeout(300);
  }
  out.elsewhereLabel = await p.locator('label.site:has(input[name="site_id"][value=""]) .site-name').textContent();
  out.hint = await p.locator('label.site:has(input[name="site_id"][value=""]) .site-access').textContent().catch(() => '');
  if (shots) {
    await p.locator('label.site:has(input[name="site_id"][value=""])').evaluate((e) => e.scrollIntoView({ block: 'center' })); await p.waitForTimeout(250);
    await p.screenshot({ path: `${shots}/where-sidestream-${scheme}.png` });
  }
  await p.click('[data-act="next"]');
  const tile = p.locator('label.choice:has(input[name="water_color"][value="orange"])');
  out.orangeTile = { count: await tile.count(), label: await tile.locator('.choice-label').textContent().catch(() => ''), sub: await tile.locator('.choice-sub').textContent().catch(() => ''), icon: await tile.locator('svg').count() };
  await p.click(`label.choice:has(input[name="water_color"][value="${color}"]) .choice-face`);
  await p.click('label.choice:has(input[name="flow"][value="low"]) .choice-face');
  if (shots) { await tile.scrollIntoViewIfNeeded(); await p.screenshot({ path: `${shots}/water-orange-${scheme}.png` }); }
  await p.click('[data-act="next"]');
  for (const [n, v] of [['algae', 'none'], ['trash', 'none'], ['dead_fish', 'false']]) await p.click(`label.choice:has(input[name="${n}"][value="${v}"]) .choice-face`);
  await p.click('[data-act="next"]'); await p.click('label.choice:has(input[name="odor"][value="none"]) .choice-face'); await p.click('[data-act="next"]');
  out.notesPlaceholder = await p.getAttribute('textarea[name="notes"]', 'placeholder');
  out.summaryWater = await p.locator('.sum-row', { hasText: 'Water' }).innerText();
  out.summaryPlace = (await p.locator('.sum-row', { hasText: 'Place' }).innerText()).replace(/\s+/g, ' ');
  await p.click('button[type="submit"]'); await p.waitForSelector('section.done');
  out.post = { water_color: field(post, 'water_color'), site_id: field(post, 'site_id') ?? null, location_kind: field(post, 'location_kind') ?? null, lat: field(post, 'lat'), lon: field(post, 'lon') };
  out.errs = errs; await ctx.close(); return out;
}

const R = {};
R.B = await flow({ geo: TRIB, shots: SHOTS });                         // side stream: nothing near
R.C = await flow({ geo: AT_SITE, chooseElsewhere: true });             // at a named spot, but chooses "somewhere else"
R.N = await flow({ geo: AT_SITE, color: 'clear' });                    // normal named-spot report: unchanged
if (SHOTS) await flow({ geo: TRIB, scheme: 'dark', shots: SHOTS });
// D. Cards/popups label orange + side stream (mock data).
for (const scheme of ['light', 'dark']) {
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, colorScheme: scheme, serviceWorkers: 'block' });
  const p = await ctx.newPage();
  await p.goto(base + 'index.html?mock=1#dashboard'); await p.waitForSelector('.creek-card .rep-card');
  const c = p.locator('.rep-card', { hasText: 'rusty orange water' }).first();
  R[`D_${scheme}`] = { tags: await c.locator('.rep-tags span').allTextContents(), dot: await c.locator('.band-dot').getAttribute('class') };
  if (scheme === 'light') R.bands = await p.evaluate(async () => {
    const { reportBand, POSITIVE_FLAGS, deriveFlags } = await import('/js/api.js');
    const { flagText } = await import('/js/ui.js');
    const base = { algae: 'none', trash: 'none', odor: 'none', dead_fish: false };
    return { serverFlag: reportBand({ ...base, water_color: 'orange', flags: ['orange_water'] }), noFlags: reportBand({ ...base, water_color: 'orange', flags: [] }),
      derived: deriveFlags({ ...base, water_color: 'orange' }), positive: POSITIVE_FLAGS.has('orange_water'), text: flagText('orange_water') };
  });
  if (SHOTS) { await c.scrollIntoViewIfNeeded(); await p.screenshot({ path: `${SHOTS}/card-orange-sidestream-${scheme}.png` }); }
  await p.goto(base + 'index.html?mock=1#map'); await p.waitForSelector('.leaflet-marker-icon .pin', { timeout: 20000 }); await p.waitForTimeout(1000);
  R[`D_${scheme}`].sidePin = await p.locator('.leaflet-marker-icon:has(.pin)').evaluateAll((els) => els.map((e) => e.title).find((t) => /away from named spots/.test(t)) || '');
  await ctx.close();
}
await b.close(); close();

const checks = {
  orangeOption: R.B.orangeTile.count === 1 && R.B.orangeTile.label === 'Orange' && /mine drainage/.test(R.B.orangeTile.sub) && R.B.orangeTile.icon === 1,
  orangePosted: R.B.post.water_color === 'orange' && /Orange/.test(R.B.summaryWater),
  sideStreamNotAutoPicked: R.B.autoPicked === '' && /not right at it, so we’ll use your exact GPS point/.test(R.B.gpsText),
  sideStreamLabelAndHint: R.B.elsewhereLabel === 'Somewhere else (between spots, or a side stream)' && /exact GPS point/.test(R.B.hint) && /If it’s a side stream, name it in Notes/.test(R.B.hint),
  sideStreamPost: R.B.post.site_id === null && R.B.post.location_kind === 'side_stream' && R.B.post.lat === '39.235' && R.B.post.lon === '-121.04',
  sideStreamSummaryAndNotes: /Away from named spots near Wolf Creek \(your GPS point\)/.test(R.B.summaryPlace) && /If it’s a side stream, which one\?/.test(R.B.notesPlaceholder),
  atSiteAutoPicks: R.N.autoPicked === 'wolf-memorial-park' && R.N.post.site_id === 'wolf-memorial-park' && R.N.post.location_kind === null,
  chooseElsewhereWorks: R.C.autoPicked === 'wolf-memorial-park' && R.C.post.site_id === null && R.C.post.location_kind === 'side_stream' && R.C.post.lat === '39.2127',
  cardsLabelOrange: R.D_light.tags.includes('Orange / rusty') && R.D_dark.tags.includes('Orange / rusty'),
  cardsLabelNeutral: R.D_light.tags.includes('Not at a named spot') && !R.D_light.tags.some((t) => /side stream/i.test(t)),
  orangeIsWatch: R.bands.serverFlag === 'watch' && R.bands.noFlags === 'watch' && R.bands.derived.includes('orange_water') && !R.bands.positive && /band-watch/.test(R.D_light.dot),
  pinTitleNeutral: R.D_light.sidePin === 'Watch report · away from named spots near Wolf Creek',
  orangeWordingPlain: /orange or rusty-looking water/.test(R.bands.text) && !/toxic|unsafe/i.test(R.bands.text),
  noPageErrors: [R.B, R.C, R.N].every((r) => !r.errs.length),
};
console.log(JSON.stringify({ R, checks }, null, 1));
const ok = Object.values(checks).every(Boolean);
console.log(ok ? 'PASS orange-sidestream' : `FAIL orange-sidestream: ${Object.entries(checks).filter(([, v]) => !v).map(([k]) => k).join(', ')}`);
process.exit(ok ? 0 : 1);
