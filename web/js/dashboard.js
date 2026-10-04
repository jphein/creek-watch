// Dashboard — one card per creek: score gauge, band, explained signals,
// gauge + weather, 7-day report sparkline, recent reports.
import { getCreeks, getHealth, getConditions, getReports, getAlerts, getCleanupStats, reportBand } from './api.js';
import { esc, BANDS, bandLabel, timeAgo, reportCardHTML, signalLabel, signalValue, safeUrl, httpsUrl, alertHTML } from './ui.js';

const BAND_GLYPH = { good: '✓', fair: '~', watch: '!', alert: '✕' };

function gaugeSVG(score, band) {
  // 180° arc gauge. Score is the hero number; band is spelled out beside it.
  const s = Math.max(0, Math.min(100, Number(score) || 0));
  const r = 52, cx = 66, cy = 66;
  const len = Math.PI * r;
  return `<svg class="gauge" viewBox="0 0 132 92" role="img" aria-label="Creek score ${s} out of 100, ${esc(bandLabel(band))}">
    <path class="g-track" d="M${cx - r} ${cy}a${r} ${r} 0 0 1 ${2 * r} 0" fill="none" stroke-width="12" stroke-linecap="round"/>
    <path class="g-val" d="M${cx - r} ${cy}a${r} ${r} 0 0 1 ${2 * r} 0" fill="none" stroke-width="12" stroke-linecap="round"
      stroke-dasharray="${((len * s) / 100).toFixed(1)} ${len.toFixed(1)}"/>
    <text x="${cx}" y="${cy - 4}" text-anchor="middle" font-size="34" font-weight="800">${s}</text>
    <text x="${cx}" y="${cy + 18}" text-anchor="middle" font-size="11" opacity=".75">out of 100</text>
  </svg>`;
}

function sparkSVG(reports) {
  // Reports per day, last 7 days (today on the right).
  const days = [];
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  for (let i = 6; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    days.push({ d, n: 0 });
  }
  for (const r of reports) {
    const t = new Date(r.observed_at);
    t.setHours(0, 0, 0, 0);
    const slot = days.find((x) => x.d.getTime() === t.getTime());
    if (slot) slot.n++;
  }
  const max = Math.max(1, ...days.map((x) => x.n));
  const W = 280, H = 48, gap = 6, bw = (W - gap * 6) / 7, plot = 34;
  const bars = days
    .map((x, i) => {
      const h = x.n ? Math.max(4, (x.n / max) * plot) : 3;
      const label = x.d.toLocaleDateString(undefined, { weekday: 'short' });
      const xx = i * (bw + gap);
      return `<g><title>${esc(label)}: ${x.n} report${x.n === 1 ? '' : 's'}</title>
        <rect x="${xx}" y="0" width="${bw}" height="${H}" fill="transparent"/>
        <rect class="bar ${x.n ? '' : 'zero'}" x="${xx}" y="${plot - h}" width="${bw}" height="${h}" rx="4"/>
        <text x="${xx + bw / 2}" y="${H - 2}" text-anchor="middle">${esc(label.slice(0, 2))}</text></g>`;
    })
    .join('');
  const total = days.reduce((a, x) => a + x.n, 0);
  return {
    total,
    svg: `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Reports per day, last 7 days: ${days
      .map((x) => x.n)
      .join(', ')}">${bars}</svg>`,
  };
}

// "USGS NWIS 11418500" / "USGS 11418500" → source-neutral, linked to the site page.
function sourceHTML(src) {
  const m = String(src).match(/^USGS(?:\s+NWIS)?\s+(\d{8,15})$/);
  if (m) return `<a href="https://waterdata.usgs.gov/monitoring-location/${m[1]}/" target="_blank" rel="noopener">USGS ${m[1]}</a>`;
  return esc(String(src).replace(/^USGS NWIS$/, 'USGS'));
}

function signalHTML(s) {
  const w = Number(s.weight);
  const wr = Math.round(Math.abs(w) * 10) / 10;
  const wTxt = Number.isFinite(w) && wr !== 0
    ? `<span class="s-w ${w < 0 ? 'neg' : 'pos'}" title="${w < 0 ? 'Points taken off the score' : 'Points added'}">${w > 0 ? '+' : '−'}${wr}</span>`
    : '';
  return `<li class="signal">
    <span class="s-name">${esc(signalLabel(s.name))}</span>
    <span class="s-val">${esc(signalValue(s.name, s.value))} ${wTxt}</span>
    ${s.explanation ? `<span class="s-exp">${esc(s.explanation)}</span>` : ''}
    ${s.source ? `<span class="s-src">Source: ${sourceHTML(s.source)}</span>` : ''}
  </li>`;
}

function condHTML(c) {
  if (!c) return '';
  const g = c.gauge, w = c.weather;
  return `<div class="cond-grid">
    <div class="cond"><h4>Stream gauge</h4>${
      g
        ? `<div class="big">${g.discharge_cfs != null ? `${esc(g.discharge_cfs)} <small>cfs</small>` : '—'}</div>
           <p>${g.gage_height_ft != null ? `Water height ${esc(g.gage_height_ft)} ft · ` : ''}${esc(timeAgo(g.observed_at))}</p>
           ${g.pct_of_median != null ? `<p>${esc(Math.round(g.pct_of_median))}% of normal for today</p>` : ''}
           ${g.source_url ? `<a href="${esc(safeUrl(g.source_url))}" target="_blank" rel="noopener">USGS ${esc(g.site_no || '')}</a>` : ''}`
        : `<p>No live USGS gauge on this creek. Reports and weather fill the gap.</p>`
    }</div>
    <div class="cond"><h4>Weather</h4>${
      w
        ? `<div class="big">${w.temp_f != null ? `${esc(Math.round(w.temp_f))}°F` : '—'}</div>
           <p>Rain last 24 h: ${w.precip_24h_in != null ? `${esc(w.precip_24h_in)} in` : '—'}${
             w.precip_next_24h_in != null ? ` · next 24 h: ${esc(w.precip_next_24h_in)} in` : ''
           }</p>
           ${w.forecast_short ? `<p>${esc(w.forecast_short)}</p>` : ''}
           <p class="credit">Temperature &amp; forecast: ${
             w.forecast_url || w.source_url
               ? `<a href="${esc(safeUrl(w.forecast_url || w.source_url))}" target="_blank" rel="noopener">NWS</a>`
               : 'NWS'
           }. Rain: <a href="${esc(safeUrl(w.precip_source_url || 'https://open-meteo.com/'))}" target="_blank" rel="noopener">Open-Meteo</a> model estimate (<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener">CC BY 4.0</a>).</p>`
        : '<p>Not available right now.</p>'
    }</div>
  </div>
  ${g?.note ? `<p class="cond-note">${esc(g.note)}</p>` : ''}`;
}

/* ---------- dated history: past bacteria studies (data #70) ----------
   Rules: always dated ("2024 Regional Board study"), never beside today's readings, credit + state-objective
   link, the data lane's ready-made text verbatim, never the word "unsafe". Values may be null or "<1"-style:
   only finite numbers are plotted. */
const num = (v) => (typeof v === 'number' ? v : typeof v === 'string' && /^\s*-?\d+(\.\d+)?\s*$/.test(v) ? Number(v) : NaN);

// Objective lines carry the objective's own units (cfu), since the samples were measured as MPN (data lane).
const unitTag = (obj) => (/cfu/i.test(String(obj?.units || '')) ? ' (cfu)' : '');

function historyChart(st, obj, minN) {
  // qual (CEDEN ResultQualCode): '=' exact; '<'/'>' means the number is the lab's limit, so never draw it as exact.
  const pts = (st.samples || []).map((x) => ({ d: String(x.date || ''), v: num(x.ecoli), g: num(x.gm6w), n: Number(x.gm6w_n) || 0,
    q: x.qual == null || x.qual === '' ? '=' : String(x.qual) }))
    .filter((x) => /^\d{4}-\d{2}-\d{2}$/.test(x.d));
  const exact = (x) => Number.isFinite(x.v) && x.q === '=';
  const plotted = pts.filter(exact);
  const limits = pts.filter((x) => Number.isFinite(x.v) && x.q !== '=').map((x) => `${x.q}${x.v}`);
  if (plotted.length < 2) return '';
  const stv = Number(obj?.stv) || 320, gm = Number(obj?.gm_six_week) || 100;
  const W = 300, H = 120, padL = 30, padB = 16, top = 6, plotH = H - padB - top, plotW = W - padL - 4;
  const yMax = Math.max(stv * 1.15, ...plotted.map((x) => x.v)) || 1;
  const y = (v) => top + plotH - (Math.min(v, yMax) / yMax) * plotH;
  const bw = Math.max(3, plotW / pts.length - 3);
  const x = (i) => padL + i * (plotW / pts.length) + 1.5;
  const bars = pts.map((p, i) => (exact(p)
    ? `<rect class="hb" x="${x(i).toFixed(1)}" y="${Math.min(y(p.v), top + plotH - 2).toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(2, top + plotH - y(p.v)).toFixed(1)}" rx="2"><title>${esc(p.d)}: ${esc(p.v)}</title></rect>`
    : '')).join('');
  const gpts = pts.map((p, i) => (Number.isFinite(p.g) && p.n >= (minN || 5) ? `${(x(i) + bw / 2).toFixed(1)},${y(p.g).toFixed(1)}` : null)).filter(Boolean);
  const ref = (v, cls, label) => `<line class="${cls}" x1="${padL}" x2="${W - 4}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"/><text class="hl" x="${W - 6}" y="${(y(v) - 3).toFixed(1)}" text-anchor="end">${label}</text>`;
  const first = pts[0].d, last = pts[pts.length - 1].d;
  return `<figure class="hist-chart">
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(`E. coli samples at ${st.name}, ${first} to ${last}: ${plotted.length} values plotted, highest ${Math.max(...plotted.map((p) => p.v))}`)}">
      <line class="axis" x1="${padL}" x2="${padL}" y1="${top}" y2="${top + plotH}"/>
      <text class="ht" x="${padL - 4}" y="${(y(0)).toFixed(1)}" text-anchor="end">0</text>
      <text class="ht" x="${padL - 4}" y="${(top + 8).toFixed(1)}" text-anchor="end">${Math.round(yMax)}</text>
      ${bars}
      ${gpts.length > 1 ? `<polyline class="hg" points="${gpts.join(' ')}"/>` : ''}
      ${ref(stv, 'ref stv', `${stv} statistical threshold${unitTag(obj)}`)}${ref(gm, 'ref gm', `${gm} six-week geometric mean${unitTag(obj)}`)}
      <text class="ht" x="${padL}" y="${H - 3}">${esc(first)}</text><text class="ht" x="${W - 4}" y="${H - 3}" text-anchor="end">${esc(last)}</text>
    </svg>
    <figcaption class="small muted">Bars: each sample. Line: 6-week geometric mean (only with ${minN || 5}+ samples). Dashed lines: the state objectives; ${stv} is a statistical threshold for a month’s samples, not a single-sample limit. One sample above ${stv} isn’t by itself a violation.${
      limits.length ? ` ${limits.length} result(s) outside the lab’s measuring range (${esc(limits.slice(0, 3).join(', '))}) not drawn as exact values.` : ''}${
      pts.length - plotted.length - limits.length ? ` ${pts.length - plotted.length - limits.length} value(s) not shown (no number reported).` : ''}</figcaption>
  </figure>`;
}

function historyHTML(cond) {
  const studies = (cond?.bacteria_history?.studies || []).filter((s) => s && s.is_current === false);
  if (!studies.length) return '';
  return studies.map((s) => {
    const objUrl = httpsUrl(s.objective?.url), srcUrl = httpsUrl(s.source_url);
    const year = String(s.period || '').slice(0, 4);
    return `<details class="history" data-study="${esc(s.id || '')}">
      <summary><span class="h-kicker">Past study · ${esc(year || 'history')}</span><strong>${esc(s.title || 'Past study')}</strong>
        <span class="h-period">${esc(s.period || '')}</span></summary>
      <p class="h-note">This is <strong>history</strong>, not today’s water. It shows what one study measured during ${esc(s.period || 'that period')}.</p>
      ${(s.stations || []).map((st) => `<section class="h-station" aria-label="${esc(st.name)}">
        <h4>${esc(st.name)}</h4>
        ${st.text ? `<p>${esc(st.text)}</p>` : ''}
        ${historyChart(st, s.objective, s.gm_min_samples)}
      </section>`).join('')}
      ${s.method_note ? `<p class="h-method small">${esc(s.method_note)}</p>` : ''}
      <p class="credit">${esc(s.credit || '')}${srcUrl ? ` · <a href="${esc(srcUrl)}" target="_blank" rel="noopener">data</a>` : ''}${
        objUrl ? ` · compared with the <a href="${esc(objUrl)}" target="_blank" rel="noopener">state objective</a>` : ''}${s.licence ? ` · Licence: ${esc(s.licence)}` : ''}</p>
    </details>`;
  }).join('');
}

/* ---------- regional river context (data #73, CDEC) ----------
   Yuba-system context only; never a score claim. The reading's age is shown prominently because CDEC
   can lag 2–12 hours. */
function fmtAsOf(iso) {
  const t = Date.parse(iso || '');
  if (!t) return '';
  return new Date(t).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}
const n0 = (v, d = 0) => (Number.isFinite(Number(v)) ? Number(v).toLocaleString(undefined, { maximumFractionDigits: d }) : null);

function riverHTML(cond) {
  const sts = cond?.river?.stations || [];
  if (!sts.length) return '';
  return `<section class="river" aria-label="Yuba River and Englebright Lake">
    <h4>Yuba River system <span class="r-sub">regional context, not part of this creek’s score</span></h4>
    ${sts.map((st) => {
      const vals = st.kind === 'reservoir'
        ? [n0(st.storage_af) && `${n0(st.storage_af)} acre-feet stored`, n0(st.elevation_ft, 1) && `water level ${n0(st.elevation_ft, 1)} ft`]
        : [n0(st.flow_cfs, 1) && `${n0(st.flow_cfs, 1)} cfs flow`, n0(st.stage_ft, 2) && `stage ${n0(st.stage_ft, 2)} ft`];
      // Age from observed_at, client-side (the API's age_hours is frozen when its response was cached).
      const obsT = Date.parse(st.observed_at || '');
      const age = obsT ? Math.max(0, (Date.now() - obsT) / 3600e3) : Number(st.age_hours);
      const stale = Number.isFinite(age) && age > 6;
      const href = httpsUrl(st.source_url);
      return `<div class="r-st${stale ? ' stale' : ''}">
        <p class="r-name"><strong>${esc(st.name)}</strong></p>
        <p class="r-vals">${esc(vals.filter(Boolean).join(' · ') || 'No reading')}</p>
        <p class="r-age">As of ${esc(fmtAsOf(st.observed_at))}${Number.isFinite(age) ? ` (${esc(age < 1 ? 'under 1 h' : `${Math.round(age)} h`)} ago)` : ''}${
          stale ? ' · <strong>older reading</strong>: CDEC data can lag several hours' : ''}</p>
        ${st.note ? `<p class="r-note">${esc(st.note)}</p>` : ''}
        <p class="credit">${esc(st.credit || 'CDEC')}${href ? ` · <a href="${esc(href)}" target="_blank" rel="noopener">station data</a>` : ''}</p>
      </div>`;
    }).join('')}
  </section>`;
}

// Volunteer water tests (RiverDB). Thresholds per data/SOURCES.md.
const WQ = [
  ['do_mg_l', 'Oxygen (DO)', (v) => `${v} mg/L`, (v) => (v >= 7 ? 'healthy for trout (7 or more)' : 'low for trout (under 7)'), (v) => v >= 7],
  ['ph', 'pH', (v) => `${v}`, (v) => (v >= 6.5 && v <= 8.5 ? 'in the healthy range (6.5–8.5)' : 'outside 6.5–8.5'), (v) => v >= 6.5 && v <= 8.5],
  ['water_temp_c', 'Water temperature', (v) => `${Math.round(v * 10) / 10} °C (${Math.round(v * 1.8 + 32)} °F)`, (v) => (v <= 20 ? 'cool enough for fish' : 'warm for fish (over 20 °C)'), (v) => v <= 20],
  ['turbidity_ntu', 'Cloudiness (turbidity)', (v) => `${v} NTU`, (v) => (v <= 10 ? 'clear' : v <= 25 ? 'a bit cloudy' : 'cloudy'), (v) => v <= 10],
  // 320 is California's REC-1 statistical threshold value (for a month's samples), not a single-sample swim limit:
  // one volunteer reading above it is shown neutrally (no "!"/alert colour), never as a violation.
  ['ecoli_mpn_100ml', 'E. coli bacteria', (v) => `${v} per 100 mL`,
    (v) => (v <= 320 ? 'under the 320 recreational threshold' : 'above 320 (a statistical threshold, not a single-sample limit)'),
    (v) => (v <= 320 ? true : null)],
  ['conductivity_us_cm', 'Conductivity', (v) => `${Math.round(v)} µS/cm`, () => 'dissolved minerals', null],
];

function fmtDate(iso) {
  const d = new Date(`${iso}T12:00:00`);
  return Number.isNaN(+d) ? iso : d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}
function ageText(days) {
  if (days == null) return '';
  if (days < 45) return `${days} days ago`;
  if (days < 730) return `about ${Math.round(days / 30)} months ago`;
  return `about ${Math.floor(days / 365)} years ago`;
}

function stationHTML(st, { compact = false } = {}) {
  const r = st.readings || {};
  const rows = WQ.filter(([k]) => r[k] != null)
    .map(([k, label, fmt, say, ok]) => {
      const good = ok ? ok(r[k]) : null;
      return `<li><span class="wq-k">${esc(label)}</span><span class="wq-v">${esc(fmt(r[k]))}</span>
        <span class="wq-say ${good === false ? 'off' : good === null ? 'neutral' : ''}">${good === null ? '' : good ? '✓ ' : '! '}${esc(say(r[k]))}</span></li>`;
    })
    .join('');
  const old = (st.age_days ?? 0) > 365;
  return `<div class="wq-station">
    <p class="wq-where"><strong>${esc(st.name)}</strong><br>
      <span class="${old ? 'wq-old' : ''}">Tested ${esc(fmtDate(st.date))} (${esc(ageText(st.age_days))})${
        old ? ' — the latest published test here, shown as background only' : ''
      }</span></p>
    ${compact ? '' : `<ul class="wq-list">${rows}</ul>`}
    <p class="credit">${esc(st.credit || st.agency || 'Volunteer monitoring')}${
      st.source_url ? ` · <a href="${esc(safeUrl(st.source_url))}" target="_blank" rel="noopener">data</a>` : ''
    }${st.agency_url ? ` · <a href="${esc(safeUrl(st.agency_url))}" target="_blank" rel="noopener">${esc(st.agency || 'group')}</a>` : ''}</p>
  </div>`;
}

function wqHTML(cond) {
  const stations = cond?.water_quality?.stations || [];
  if (!stations.length) return '';
  const [first, ...rest] = stations;
  return `<section class="wq" aria-label="Volunteer water tests">
    <h4>Volunteer water tests</h4>
    ${stationHTML(first)}
    ${
      rest.length
        ? `<details class="more"><summary>${rest.length} more test site${rest.length === 1 ? '' : 's'}</summary>${rest
            .map((x) => stationHTML(x))
            .join('')}</details>`
        : ''
    }
  </section>`;
}

// Creek banners: this creek's active alerts (official + Creek Watch). Until /api/alerts lists
// Creek Watch's own warnings, fall back to health.warnings so nothing disappears.
function bannersHTML(c, alerts, h) {
  const own = alerts.some((a) => a.source === 'creekwatch');
  const items = [...alerts];
  if (!own) for (const w of h?.warnings || []) items.push({ id: `creekwatch:${c.id}:${w.id}`, source: 'creekwatch', source_name: 'Creek Watch early warning',
    category: 'other', severity: w.level, title: w.title, summary: w.explanation, url: null });
  if (!items.length) return '';
  const top = items.slice(0, 3);
  return `<div class="creek-alerts" aria-label="Active alerts for ${esc(c.name)}">${top.map((a) => alertHTML(a, { compact: true })).join('')}${
    items.length > top.length || alerts.length
      ? `<a class="see-alerts" href="#alerts?creek=${encodeURIComponent(c.id)}">See ${items.length > top.length ? `all ${items.length} alerts` : 'alert details'} for ${esc(c.name)} →</a>`
      : ''
  }</div>`;
}

const CONFIDENCE = {
  low: 'Low confidence: no reports this week, so this uses public data only.',
  medium: 'Medium confidence: based on a few reports this week.',
  high: 'High confidence: plenty of reports this week plus weather data.',
};

// "N cleanups · B bags removed by volunteers": hidden when zero or unavailable.
function cleanupCountHTML(cs) {
  const n = Number(cs?.cleanups) | 0, bags = Number(cs?.bags) | 0;
  if (!(n > 0)) return '';
  // Honour system (Oracle): always "reported", never presented as verified.
  // Visible on the card, not only in a tooltip (phones don't show title tooltips).
  const since = Date.parse(cs?.since || '') ? ` since ${new Date(cs.since).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}` : '';
  return `<p class="cleanup-count"><span aria-hidden="true">🧤</span> <span><strong>${n} reported cleanup${n === 1 ? '' : 's'}</strong>${
    bags > 0 ? ` · <strong>${bags} bag${bags === 1 ? '' : 's'}</strong>` : ''}${esc(since)} <span class="cc-note">(self-reported by volunteers)</span></span></p>`;
}

async function creekCard(c) {
  const since = new Date(Date.now() - 7 * 864e5).toISOString().replace(/\.\d{3}Z$/, 'Z');
  const [health, cond, reports, alerts, cleanups] = await Promise.all([
    getHealth(c.id).catch(() => null),
    getConditions(c.id).catch(() => null),
    getReports({ creek_id: c.id, since, limit: 200 }).catch(() => []),
    getAlerts({ creek_id: c.id }).catch(() => []),
    getCleanupStats(c.id).catch(() => null),
  ]);
  const band = health?.band || 'fair';
  const spark = sparkSVG(reports);
  const siteName = (id) => c.sites?.find((s) => s.id === id)?.name || '';
  const recent = reports.slice(0, 3);
  const more = reports.slice(3, 10);
  return `<article class="creek-card" data-band="${esc(band)}" aria-labelledby="h-${esc(c.id)}">
    <div class="creek-head">
      <div>
        <h2 id="h-${esc(c.id)}">${esc(c.name)}</h2>
        <p class="town">${esc(c.town || '')}</p>
      </div>
      ${health ? gaugeSVG(health.score, band) : ''}
    </div>
    ${bannersHTML(c, alerts, health)}
    ${
      health
        ? `<div class="band-line"><span class="band-dot band-${esc(band)}" aria-hidden="true"></span>
             <span><strong>${BAND_GLYPH[band] || ''} ${esc(bandLabel(band))}</strong> — ${esc(BANDS[band]?.blurb || '')}</span></div>
           ${health.confidence ? `<p class="confidence">${esc(CONFIDENCE[health.confidence] || `Confidence: ${health.confidence}`)}</p>` : ''}
           <h3 class="sr-only">Why this score</h3>
           <ul class="signals">${(health.signals || []).map(signalHTML).join('') || '<li class="signal">No warning signs right now.</li>'}</ul>`
        : `<p class="muted">Score not available right now.</p>`
    }
    ${condHTML(cond)}
    ${wqHTML(cond)}
    ${c.id === 'deer' ? riverHTML(cond) : ''}
    ${cleanupCountHTML(cleanups)}
    <div class="spark-wrap"><h4>Reports, last 7 days</h4>${spark.svg}<span class="spark-total">${spark.total}</span></div>
    <h3>Latest reports</h3>
    <div class="recent">${
      recent.map((r) => reportCardHTML(r, c.name, siteName(r.site_id), { band: reportBand(r) })).join('') ||
      `<p class="muted">No reports yet this week. <a href="#report">Be the first.</a></p>`
    }</div>
    ${
      more.length
        ? `<details class="more"><summary>${more.length} more</summary><div class="recent">${more
            .map((r) => reportCardHTML(r, c.name, siteName(r.site_id), { band: reportBand(r) }))
            .join('')}</div></details>`
        : ''
    }
    ${historyHTML(cond)}
    ${health?.last_updated ? `<p class="updated">Score updated ${esc(timeAgo(health.last_updated))}.</p>` : ''}
  </article>`;
}

export async function mountDashboard(el, { refresh = false } = {}) {
  // On a refresh keep the current cards on screen until the new ones are ready.
  if (!refresh || !el.querySelector('#dash-cards')) {
    el.innerHTML = `<h2 class="sr-only">Creek health</h2><p class="dash-intro">How the creeks are doing right now, and why.</p><div id="dash-cards"><p class="muted">Loading…</p></div>`;
  }
  const box = el.querySelector('#dash-cards');
  try {
    const creeks = await getCreeks();
    box.innerHTML = (await Promise.all(creeks.map(creekCard))).join('');
  } catch (e) {
    box.innerHTML = `<div class="banner error" role="alert"><div><strong>Couldn’t load the creeks</strong><span>${esc(e.message)}</span></div></div>`;
  }
}
