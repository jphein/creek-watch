// Dashboard — one card per creek: score gauge, band, explained signals,
// gauge + weather, 7-day report sparkline, recent reports.
import { getCreeks, getHealth, getConditions, getReports, reportBand } from './api.js';
import { esc, BANDS, bandLabel, timeAgo, reportCardHTML, signalLabel, signalValue } from './ui.js';

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
    ${s.source ? `<span class="s-src">Source: ${esc(s.source)}</span>` : ''}
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
           ${g.source_url ? `<a href="${esc(g.source_url)}" target="_blank" rel="noopener">USGS ${esc(g.site_no || '')}</a>` : ''}`
        : `<p>No live USGS gauge on this creek. Reports and weather fill the gap.</p>`
    }</div>
    <div class="cond"><h4>Weather</h4>${
      w
        ? `<div class="big">${w.temp_f != null ? `${esc(Math.round(w.temp_f))}°F` : '—'}</div>
           <p>Rain last 24 h: ${w.precip_24h_in != null ? `${esc(w.precip_24h_in)} in` : '—'}</p>
           ${w.forecast_short ? `<p>${esc(w.forecast_short)}</p>` : ''}
           ${w.source_url ? `<a href="${esc(w.source_url)}" target="_blank" rel="noopener">NWS forecast</a>` : ''}`
        : '<p>Not available right now.</p>'
    }</div>
  </div>
  ${g?.note ? `<p class="cond-note">${esc(g.note)}</p>` : ''}`;
}

async function creekCard(c) {
  const since = new Date(Date.now() - 7 * 864e5).toISOString().replace(/\.\d{3}Z$/, 'Z');
  const [health, cond, reports] = await Promise.all([
    getHealth(c.id).catch(() => null),
    getConditions(c.id).catch(() => null),
    getReports({ creek_id: c.id, since, limit: 200 }).catch(() => []),
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
    ${
      health
        ? `<div class="band-line"><span class="band-dot band-${esc(band)}" aria-hidden="true"></span>
             <span><strong>${BAND_GLYPH[band] || ''} ${esc(bandLabel(band))}</strong> — ${esc(BANDS[band]?.blurb || '')}</span></div>
           <h3 class="sr-only">Why this score</h3>
           <ul class="signals">${(health.signals || []).map(signalHTML).join('') || '<li class="signal">No warning signs right now.</li>'}</ul>`
        : `<p class="muted">Score not available right now.</p>`
    }
    ${condHTML(cond)}
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
    ${health?.last_updated ? `<p class="updated">Score updated ${esc(timeAgo(health.last_updated))}.</p>` : ''}
  </article>`;
}

export async function mountDashboard(el) {
  el.innerHTML = `<h2 class="sr-only">Creek health</h2><p class="dash-intro">How the creeks are doing right now, and why.</p><div id="dash-cards"><p class="muted">Loading…</p></div>`;
  const box = el.querySelector('#dash-cards');
  try {
    const creeks = await getCreeks();
    box.innerHTML = (await Promise.all(creeks.map(creekCard))).join('');
  } catch (e) {
    box.innerHTML = `<div class="banner error" role="alert"><div><strong>Couldn’t load the creeks</strong><span>${esc(e.message)}</span></div></div>`;
  }
}
