// Dated bacteria history (data #70) + CDEC river context (data #73) on the creek cards.
// SHOTS=<dir> saves 390x844 screenshots (light + dark).
import { serveWeb, launch, mock } from './harness.mjs';

const SHOTS = process.env.SHOTS || '';
const { base, close } = await serveWeb();
const b = await launch();
const json = (body, status = 200) => ({ status, contentType: 'application/json', body: typeof body === 'string' ? body : JSON.stringify(body) });
const COND = JSON.parse(mock('conditions'));
const R = {};
const card = (p, name) => p.locator('.creek-card', { has: p.locator('h2', { hasText: name }) });

for (const scheme of ['light', 'dark']) {
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, colorScheme: scheme, serviceWorkers: 'block' });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
  await p.goto(base + 'index.html?mock=1#dashboard'); await p.waitForSelector('.creek-card .signal');
  const wolf = card(p, 'Wolf Creek'), deer = card(p, 'Deer Creek');
  const hist = wolf.locator('details.history');
  await hist.locator('summary').click();
  const r = {
    histCount: await hist.count(),
    kicker: await hist.locator('.h-kicker').textContent(),
    title: await hist.locator('summary strong').textContent(),
    historyNote: (await hist.locator('.h-note').innerText()).includes('history'),
    notInTodayGrid: (await wolf.locator('.cond-grid details.history, .wq details.history').count()) === 0,
    afterLatestReports: await wolf.evaluate((el) => {
      const h = el.querySelector('details.history'), lr = [...el.querySelectorAll('h3')].find((x) => /Latest reports/.test(x.textContent));
      return !!(h && lr && (lr.compareDocumentPosition(h) & Node.DOCUMENT_POSITION_FOLLOWING));
    }),
    stationTexts: await hist.locator('.h-station > p').allTextContents(),
    credit: await hist.locator('.credit').innerText(),
    methodNote: await hist.locator('.h-method').textContent().catch(() => ''),
    refLabels: await hist.locator('.hist-chart text.hl').allTextContents(),
    captions: await hist.locator('.hist-chart figcaption').allTextContents(),
    overBars: await hist.locator('rect.hb.over').count(),
    objectiveLink: await hist.locator('.credit a', { hasText: 'state objective' }).getAttribute('href'),
    unsafeWord: /unsafe/i.test(await wolf.innerText()),
    charts: await hist.locator('.hist-chart svg[role="img"]').count(),
    barsPlotted: await hist.locator('.hist-chart rect.hb').count(),
    deerHistory: await deer.locator('details.history').count(),
    wolfRiver: await wolf.locator('.river').count(),
    deerRiverStations: await deer.locator('.river .r-st').count(),
    deerRiverVals: await deer.locator('.river .r-vals').allTextContents(),
    deerRiverAges: await deer.locator('.river .r-age').allTextContents(),
    deerRiverNotScore: (await deer.locator('.river h4').innerText()).includes('not part of this creek’s score'),
    errors: errs,
  };
  R[scheme] = r;
  if (SHOTS) {
    await hist.scrollIntoViewIfNeeded(); await p.waitForTimeout(200);
    await hist.screenshot({ path: `${SHOTS}/wolf-history-${scheme}.png` });
    await deer.locator('.river').scrollIntoViewIfNeeded(); await p.waitForTimeout(200);
    await p.screenshot({ path: `${SHOTS}/deer-river-${scheme}.png` });
  }
  if (scheme === 'light') {
    await p.goto(base + 'index.html?mock=1#about'); await p.waitForSelector('#about-h');
    const about = await p.locator('#page-about').innerText();
    R.about = { cdec: about.includes('California Department of Water Resources (CDEC)'), ceden: about.includes('CEDEN'), lag: about.includes('2–12 hours') };
  }
  await ctx.close();
}

// Real network path with hostile/edge data: stale river, null/"<1" values, HTML in titles, wrong study shape.
{
  const wolf = structuredClone(COND.wolf), deer = structuredClone(COND.deer);
  const st = wolf.bacteria_history.studies[0];
  st.title = '<img src=x onerror="window.__xss=1">2024 study';
  st.stations[0].samples[1].ecoli = null; st.stations[0].samples[2].ecoli = '<1'; st.stations[0].samples[3].ecoli = '12';
  st.stations[1].samples[4].qual = '<'; st.stations[1].samples[4].ecoli = 10; st.stations[1].samples[5].qual = '>'; st.stations[1].samples[5].ecoli = 2419.6;
  // Volunteer E. coli readings on the card: threshold wording, never "swim limit", never alert-styled.
  wolf.water_quality = { stations: [{ agency: 'WCCA', name: 'Test site A', date: '2026-09-20', age_days: 14, live: true, credit: 'test',
    readings: { ecoli_mpn_100ml: 410 } }, { agency: 'WCCA', name: 'Test site B', date: '2026-09-20', age_days: 14, live: true, credit: 'test', readings: { ecoli_mpn_100ml: 120 } }] };
  deer.river.stations[0].age_hours = 1; deer.river.stations[0].observed_at = new Date(Date.now() - 9 * 3600e3).toISOString(); // cached age is stale on purpose
  deer.river.stations[1].observed_at = new Date(Date.now() - 2 * 3600e3).toISOString();
  deer.river.stations[1].source_url = 'http://cdec.water.ca.gov/insecure';
  st.objective = { ...st.objective, url: 'http://www.waterboards.ca.gov/insecure.pdf' };
  deer.bacteria_history = { studies: [{ ...st, is_current: true, id: 'current-should-not-show' }] }; // only dated history renders
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
  await ctx.route('**/api/creeks', (r) => r.fulfill(json(mock('creeks'))));
  await ctx.route('**/api/conditions**', (r) => r.fulfill(json(new URL(r.request().url()).searchParams.get('creek_id') === 'wolf' ? wolf : deer)));
  await ctx.route('**/api/{health,alerts,reports,stats}**', (r) => r.fulfill(json('[]')));
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
  await p.goto(base + '#dashboard'); await p.waitForSelector('.creek-card details.history');
  const w = card(p, 'Wolf Creek'), d = card(p, 'Deer Creek');
  await w.locator('details.history summary').click();
  R.edge = {
    xss: await p.evaluate(() => window.__xss || 0), injected: await p.locator('img[src="x"]').count(),
    literalTitle: (await w.locator('details.history summary strong').textContent()).includes('<img'),
    firstStationBars: await w.locator('.h-station').first().locator('rect.hb').count(),
    notShownNote: (await w.locator('.h-station').first().locator('figcaption').innerText()).includes('2 value(s) not shown'),
    nanInDom: /NaN|undefined/.test(await w.innerText()),
    qualBars: await w.locator('.h-station').nth(1).locator('rect.hb').count(),
    qualCaption: await w.locator('.h-station').nth(1).locator('figcaption').innerText(),
    ecoliSays: await w.locator('.wq-say').allTextContents(),
    ecoliOffStyled: await w.locator('.wq .wq-say.off').count(),
    swimWord: /swim limit/i.test(await p.locator('#page-dashboard').innerText()),
    staleNote: (await d.locator('.river .r-st').first().innerText()).includes('older reading'),
    computedAge: /\(9 h ago\)/.test(await d.locator('.river .r-age').first().innerText()) && /\(2 h ago\)/.test(await d.locator('.river .r-age').nth(1).innerText()),
    httpLinks: await p.locator('a[href^="http:"]').count(),
    objLinkPresent: await w.locator('details.history .credit a', { hasText: 'state objective' }).count(),
    staleClass: await d.locator('.river .r-st.stale').count(),
    currentStudyHidden: (await d.locator('details.history').count()) === 0,
    errors: errs,
  };
  await ctx.close();
}
// Empty/absent data renders nothing (no empty boxes).
{
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
  await ctx.route('**/api/creeks', (r) => r.fulfill(json(mock('creeks'))));
  await ctx.route('**/api/conditions**', (r) => r.fulfill(json({ gauge: null, weather: null, river: { stations: [] }, bacteria_history: { studies: [] } })));
  await ctx.route('**/api/{health,alerts,reports,stats}**', (r) => r.fulfill(json('[]')));
  const p = await ctx.newPage();
  await p.goto(base + '#dashboard'); await p.waitForSelector('.creek-card'); await p.waitForTimeout(500);
  R.empty = { river: await p.locator('.river').count(), history: await p.locator('details.history').count() };
  await ctx.close();
}
await b.close(); close();

const L = R.light, D = R.dark;
const expectedTexts = COND.wolf.bacteria_history.studies[0].stations.map((s) => s.text);
const checks = {
  wolfHistoryDated: L.histCount === 1 && /Past study · 2024/.test(L.kicker) && L.title === '2024 Regional Board study',
  historyNoteSaysHistory: L.historyNote,
  notBesideToday: L.notInTodayGrid && L.afterLatestReports,
  textVerbatim: JSON.stringify(L.stationTexts) === JSON.stringify(expectedTexts),
  creditAndObjective: L.credit.includes('Central Valley Regional Water Quality Control Board') && L.objectiveLink === COND.wolf.bacteria_history.studies[0].objective.url,
  methodNoteShown: L.methodNote === COND.wolf.bacteria_history.studies[0].method_note,
  objectiveLabelsHonest: L.refLabels.includes('320 statistical threshold (cfu)') && L.refLabels.includes('100 six-week geometric mean (cfu)') && !L.refLabels.some((t) => /single sample/i.test(t)),
  captionNotViolation: L.captions.every((c) => c.includes('One sample above 320 isn’t by itself a violation.')),
  noWatchFillOnBars: L.overBars === 0,
  ecoliThresholdWording: R.edge.ecoliSays.some((t) => t.includes('above 320 (a statistical threshold, not a single-sample limit)'))
    && R.edge.ecoliSays.some((t) => t.includes('under the 320 recreational threshold')) && !R.edge.swimWord,
  ecoliAboveNotAlertStyled: R.edge.ecoliOffStyled === 0 && !R.edge.ecoliSays.some((t) => t.trim().startsWith('!')),
  httpsOnlyLinks: R.edge.httpLinks === 0 && R.edge.objLinkPresent === 0,
  riverAgeFromObservedAt: R.edge.computedAge,
  neverUnsafe: !L.unsafeWord && !D.unsafeWord,
  chartsPlotAllNumbers: L.charts === 2 && L.barsPlotted === 26,
  deerHasNoHistory: L.deerHistory === 0, riverOnlyOnDeer: L.wolfRiver === 0 && L.deerRiverStations === 2,
  riverValues: L.deerRiverVals.join(' | ') === '37 cfs flow · stage 1.74 ft | 69,361 acre-feet stored · water level 526.3 ft',
  riverAgeProminent: L.deerRiverAges.every((t) => /^As of .+\((2|4) h ago\)$/.test(t.trim())),
  riverNotScore: L.deerRiverNotScore,
  aboutLines: R.about.cdec && R.about.ceden && R.about.lag,
  edgeEscaped: !R.edge.xss && !R.edge.injected && R.edge.literalTitle,
  edgeOnlyNumbersPlotted: R.edge.firstStationBars === 11 && R.edge.notShownNote && !R.edge.nanInDom,
  qualNotExact: R.edge.qualBars === 11 && R.edge.qualCaption.includes('2 result(s) outside the lab’s measuring range (<10, >2419.6) not drawn as exact values'),
  edgeStaleRiver: R.edge.staleNote && R.edge.staleClass === 1,
  onlyDatedHistory: R.edge.currentStudyHidden,
  emptyRendersNothing: R.empty.river === 0 && R.empty.history === 0,
  noPageErrors: !L.errors.length && !D.errors.length && !R.edge.errors.length,
};
console.log(JSON.stringify({ R, checks }, null, 1));
const ok = Object.values(checks).every(Boolean);
console.log(ok ? 'PASS history-river' : `FAIL history-river: ${Object.entries(checks).filter(([, v]) => !v).map(([k]) => k).join(', ')}`);
process.exit(ok ? 0 : 1);
