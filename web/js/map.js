// Map — creek lines, site markers, recent-report pins coloured by band.
import { getCreeks, getReports, getConditions, getAlerts, reportBand } from './api.js';
import { esc, bandLabel, reportCardHTML, alertHTML, SEV, httpsUrl } from './ui.js';
import { wqPopupHTML, upstreamNoteHTML, isNum, isStudyOnly } from './sites.js';
import { SOURCE_LAYERS, TOGGLE_KEYS, STATION_COORDS } from './sources.js';

const LEAFLET_CSS = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css';
const LEAFLET_JS = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js';
const LEAFLET_JS_SRI = 'sha512-puJW3E/qXDqYp9IfhAI54BJEaWIfloJ7JWs7OeD5i6ruC9JZL1gERT1wjtwXFlh7CjE7ZJ+/vcRZRkIYIb6p4g==';
const LEAFLET_CSS_SRI = 'sha512-h9FcoyWjHcOcmEVkxOfTLnmZFWIH0iZhZT1H2TbOq55xssQGEJHEaIm+PgoUaZbRvQTNTluNOEfb1ZRy6D3BOw==';
const BAND_GLYPH = { good: '✓', fair: '~', watch: '!', alert: '✕' };

let map, L, pinsById = new Map(), creeksCache = [], layers = {};

function loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  return new Promise((resolve, reject) => {
    const css = document.createElement('link');
    css.rel = 'stylesheet';
    css.href = LEAFLET_CSS;
    css.integrity = LEAFLET_CSS_SRI;
    css.crossOrigin = 'anonymous';
    css.referrerPolicy = 'no-referrer';
    document.head.appendChild(css);
    const s = document.createElement('script');
    s.src = LEAFLET_JS;
    s.integrity = LEAFLET_JS_SRI;
    s.crossOrigin = 'anonymous';
    s.referrerPolicy = 'no-referrer';
    s.onload = () => resolve(window.L);
    s.onerror = () => reject(new Error('Map library could not load. Check your connection.'));
    document.head.appendChild(s);
  });
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export async function mountMap(el, qs) {
  el.innerHTML = `<h2 class="sr-only">Map of reports</h2>
    <div class="map-wrap"><div id="map-canvas" role="region" aria-label="Map of Wolf Creek and Deer Creek with recent reports"></div>
    ${layerControlHTML()}</div>`;
  try {
    L = await loadLeaflet();
  } catch (e) {
    el.querySelector('#map-canvas').innerHTML = `<div class="banner error" role="alert"><div><strong>Map unavailable</strong><span>${esc(e.message)}</span></div></div>`;
    return;
  }
  map = L.map('map-canvas', { zoomControl: true, attributionControl: true }).setView([39.237, -121.04], 13);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  // One layer group per source (web/js/sources.js); all on by default.
  layers = Object.fromEntries(TOGGLE_KEYS.map((k) => [k, L.layerGroup().addTo(map)]));
  wireLayerControl(el);

  const [creeks, reports] = await Promise.all([getCreeks().catch(() => []), getReports({ limit: 200 }).catch(() => [])]);
  creeksCache = creeks;
  const bounds = [];
  const water = cssVar('--brand') || '#0d6a80';

  for (const c of creeks) {
    if (c.geojson_line) {
      // Main stem solid; tributaries (properties.main_stem === false) thinner + dashed.
      const layer = L.geoJSON(c.geojson_line, {
        style: (f) =>
          f?.properties?.main_stem === false
            ? { color: water, weight: 4, opacity: 0.65, dashArray: '2 8', lineCap: 'round', className: 'src-osm' }
            : { color: water, weight: 6, opacity: 0.8, lineCap: 'round', className: 'src-osm' },
        onEachFeature: (f, l) => l.bindTooltip(esc(f?.properties?.name || c.name), { sticky: true }),
      })
        .addTo(map);
      bounds.push(layer.getBounds());
    }
    for (const s of c.sites || []) {
      L.marker([s.lat, s.lon], {
        icon: L.divIcon({ className: 'src-reports', html: '<div class="site-marker"></div>', iconSize: [14, 14], iconAnchor: [7, 7] }),
        title: `${s.name} (${c.name})`,
        alt: `${s.name}, ${c.name}`,
        keyboard: true,
      })
        .bindPopup(`<strong>${esc(s.name)}</strong><br>${esc(c.name)}<br><a href="#report">Report from here</a>`)
        .addTo(layers.reports);
      bounds.push(L.latLngBounds([[s.lat, s.lon], [s.lat, s.lon]]));
    }
  }

  // Volunteer water-test stations (RiverDB) as small flask markers. Each popup shows only that site:
  // its own test, its access note, and reports within 500 m labelled with their own spot (WCCA).
  const conds = await Promise.all(creeks.map((c) => getConditions(c.id).catch(() => null)));
  const reportSpot = (r) => creeks.find((x) => x.id === r.creek_id)?.sites?.find((s) => s.id === r.site_id)?.name || '';
  conds.forEach((cond, i) => {
    for (const st of cond?.water_quality?.stations || []) {
      if (!isNum(st.lat) || !isNum(st.lon)) continue;
      L.marker([Number(st.lat), Number(st.lon)], {
        icon: L.divIcon({ className: 'src-wq', html: '<div class="flask-marker" aria-hidden="true">⚗</div>', iconSize: [22, 22], iconAnchor: [11, 11] }),
        title: `Volunteer water test: ${st.name}`,
        alt: `Volunteer water test site ${st.name}`,
        keyboard: true,
      })
        .bindPopup(wqPopupHTML(st, creeks[i].name, reports, { spotName: reportSpot, band: reportBand }),
          // Scroll inside the popup rather than run under the legend on short phones.
          { maxWidth: 300, maxHeight: Math.max(260, innerHeight - 330), autoPanPaddingTopLeft: [52, 12], autoPanPaddingBottomRight: [12, 90] })
        .addTo(layers.wq);
    }
  });

  // Swim holes (SYRCL bacteria tests, data #100): regional, the same for every creek. These are dated summer
  // samples, not live readings: the date leads, the wording follows the 320 rule, and markers are neutral.
  const holes = new Map();
  for (const cond of conds) for (const st of cond?.swim_holes?.stations || []) {
    if (st && st.station_id != null && !holes.has(String(st.station_id))) holes.set(String(st.station_id), st);
  }
  const jbr = conds.flatMap((c) => c?.river?.stations || []).find((x) => x?.station_id === 'JBR');
  for (const st of holes.values()) {
    if (!isNum(st.lat) || !isNum(st.lon)) continue; // a null coordinate must not become 0, 0
    const name = spotName(st);
    L.marker([Number(st.lat), Number(st.lon)], {
      icon: L.divIcon({ className: 'src-swim', html: '<div class="swim-marker" aria-hidden="true">≈</div>', iconSize: [24, 24], iconAnchor: [12, 12] }),
      title: `Swim hole: ${name}`, alt: `Swim hole ${name}`, keyboard: true,
    }).bindPopup(swimPopupHTML(st, jbr), { maxWidth: 300, autoPanPaddingTopLeft: [52, 12], autoPanPaddingBottomRight: [12, 90] }).addTo(layers.swim); // clear the zoom control and legend
  }

  // Past-study sites (data #109): study-only stations (site_id null) as grey, dated pins. History, never
  // current conditions: no colour scale, never red, the period leads the popup.
  const studied = new Set();
  for (const cond of conds) for (const s of cond?.bacteria_history?.studies || []) {
    if (!s || s.is_current !== false) continue;
    for (const st of s.stations || []) {
      const key = String(st?.station_code ?? st?.name ?? '');
      if (!isStudyOnly(st) || !key || studied.has(key) || !isNum(st.lat) || !isNum(st.lon)) continue;
      studied.add(key);
      const yr = String(s.period || '').slice(0, 4);
      const name = String(st.name ?? '').trim() || 'Study site';
      L.marker([Number(st.lat), Number(st.lon)], {
        icon: L.divIcon({ className: 'src-study', html: `<div class="study-marker" aria-hidden="true">${esc(yr.slice(2) ? `’${yr.slice(2)}` : '·')}</div>`, iconSize: [26, 20], iconAnchor: [13, 10] }),
        title: `Past study site${yr ? ` (${yr})` : ''}: ${name}`, alt: `Past study site ${name}`, keyboard: true,
      }).bindPopup(studyPopupHTML(st, s), { maxWidth: 300, maxHeight: Math.max(260, innerHeight - 330), autoPanPaddingTopLeft: [52, 12], autoPanPaddingBottomRight: [12, 90] }).addTo(layers.study);
    }
  }

  // Live gauges (USGS) and Yuba-system stations (CDEC). The API carries no coordinates for these, so they
  // come from STATION_COORDS (sources.js); a station without known coordinates is simply not mapped.
  const POP = { maxWidth: 300, autoPanPaddingTopLeft: [52, 12], autoPanPaddingBottomRight: [12, 90] };
  const seenGauge = new Set();
  for (const cond of conds) {
    const g = cond?.gauge, at = STATION_COORDS[String(g?.site_no ?? '')];
    if (!g || !at || seenGauge.has(String(g.site_no))) continue;
    seenGauge.add(String(g.site_no));
    const name = String(g.name ?? '').trim() || `USGS ${g.site_no}`;
    L.marker(at, {
      icon: L.divIcon({ className: 'src-usgs', html: '<div class="gauge-marker" aria-hidden="true">cfs</div>', iconSize: [32, 20], iconAnchor: [16, 10] }),
      title: `USGS stream gauge: ${name}`, alt: `USGS stream gauge ${name}`, keyboard: true,
    }).bindPopup(gaugePopupHTML(g), POP).addTo(layers.usgs);
  }
  const seenCdec = new Set();
  for (const st of conds.flatMap((c) => c?.river?.stations || [])) {
    const at = STATION_COORDS[String(st?.station_id ?? '')];
    if (!at || seenCdec.has(String(st.station_id))) continue;
    seenCdec.add(String(st.station_id));
    const name = String(st.name ?? '').trim() || `CDEC ${st.station_id}`;
    L.marker(at, {
      icon: L.divIcon({ className: 'src-cdec', html: '<div class="cdec-marker" aria-hidden="true">≋</div>', iconSize: [24, 24], iconAnchor: [12, 12] }),
      title: `CDEC river station: ${name}`, alt: `CDEC river station ${name}`, keyboard: true,
    }).bindPopup(cdecPopupHTML(st), POP).addTo(layers.cdec);
  }

  // Alert areas (docs/ALERTS-SPEC.md): polygons dashed + lightly filled, points as glyph markers.
  const SEV_VAR = { alert: '--alert', watch: '--watch', advisory: '--brand', info: '--muted' };
  for (const a of await getAlerts().catch(() => [])) {
    const sev = SEV[a.severity] ? a.severity : 'info';
    const color = cssVar(SEV_VAR[sev]) || '#888';
    const popup = alertHTML(a, { compact: true }) + `<a class="see-alerts" href="#alerts?id=${encodeURIComponent(a.id)}">Open alert →</a>`;
    if (a.area?.polygon_geojson) {
      try {
        L.geoJSON(a.area.polygon_geojson, { style: { color, weight: 2, dashArray: '6 6', fillColor: color, fillOpacity: 0.08, className: 'src-alerts' } })
          .bindPopup(popup, { maxWidth: 300 }).addTo(layers.alerts);
      } catch { /* malformed polygon from a feed: skip it */ }
    }
    if (a.area?.lat != null && a.area?.lon != null) {
      L.marker([a.area.lat, a.area.lon], {
        icon: L.divIcon({ className: 'src-alerts', html: `<div class="alert-marker sev-${sev}" aria-hidden="true"><span>${SEV[sev].glyph}</span></div>`, iconSize: [26, 26], iconAnchor: [13, 13] }),
        title: `${SEV[sev].label}: ${a.title}`, alt: `${SEV[sev].label}: ${a.title}`, keyboard: true, zIndexOffset: 500,
      }).bindPopup(popup, { maxWidth: 300 }).addTo(layers.alerts);
    }
  }

  for (const r of reports) {
    if (r.lat == null || r.lon == null) continue;
    const band = reportBand(r);
    const c = creeks.find((x) => x.id === r.creek_id);
    const site = c?.sites?.find((s) => s.id === r.site_id);
    const m = L.marker([r.lat, r.lon], {
      icon: L.divIcon({
        className: 'src-reports',
        html: `<div class="pin band-${band}"><span class="pin-glyph">${BAND_GLYPH[band]}</span></div>${r.trash_removed ? '<span class="pin-clean" aria-hidden="true">🧤</span>' : ''}`,
        iconSize: [26, 26],
        iconAnchor: [13, 30],
        popupAnchor: [0, -28],
      }),
      title: `${bandLabel(band)} report${site ? ' at ' + site.name : r.location_kind === 'side_stream' ? ` · away from named spots near ${c?.name || 'the creek'}` : ''}${r.trash_removed ? ' · cleaned up' : ''}`,
      alt: `${bandLabel(band)} report`,
      keyboard: true,
      riseOnHover: true,
    })
      .bindPopup(reportCardHTML(r, c?.name || '', site?.name || '', { band }) + upstreamNoteHTML(), { maxWidth: 300 })
      .addTo(layers.reports);
    pinsById.set(String(r.id), m);
  }

  if (bounds.length) {
    const b = bounds.reduce((a, x) => a.extend(x), L.latLngBounds(bounds[0].getSouthWest(), bounds[0].getNorthEast()));
    map.fitBounds(b, { padding: [24, 24] });
  }
  showMap(qs);
}

// "2024-05-22 to 2024-09-04" -> "May–Sep 2024" (dates read as UTC, so no off-by-one month).
export function studyMonths(period) {
  const m = String(period || '').match(/(\d{4})-(\d{2})-\d{2}\D+(\d{4})-(\d{2})-\d{2}/);
  if (!m) return String(period || '');
  const mon = (y, mo) => new Date(Date.UTC(+y, +mo - 1, 15)).toLocaleDateString(undefined, { month: 'short', timeZone: 'UTC' });
  return m[1] === m[3] ? `${mon(m[1], m[2])}–${mon(m[3], m[4])} ${m[1]}` : `${mon(m[1], m[2])} ${m[1]} – ${mon(m[3], m[4])} ${m[3]}`;
}
export function studyPopupHTML(st, s) {
  const ctx = httpsUrl(s.context_url);
  const n = (st.samples || []).length;
  return `<div class="swim-pop study-pop">
    <p class="sp-kicker">Past study · ${esc(String(s.period || '').slice(0, 4) || 'history')}</p>
    <strong class="sp-name">${esc(String(st.name ?? '').trim() || 'Study site')}</strong>${st.waterbody ? `<span class="sp-river">${esc(st.waterbody)}</span>` : ''}
    <p class="sp-date">Tested ${n ? 'weekly ' : ''}<strong>${esc(studyMonths(s.period))}</strong>: a past study, not current conditions.</p>
    ${st.text ? `<p class="sp-val">${esc(st.text)}</p>` : ''}
    ${upstreamNoteHTML()}
    <p class="credit">${esc(s.credit || s.agency || 'Past study')}${ctx ? ` · <a href="${esc(ctx)}" target="_blank" rel="noopener noreferrer">${esc(s.context_label || 'Study map')}</a>` : ''}</p>
    <a class="see-alerts" href="#dashboard">See the charts on the Creeks page →</a>
  </div>`;
}

/* ---------- source layer control (sources.js) ---------- */
function layerControlHTML() {
  const bands = ['good', 'fair', 'watch', 'alert']
    .map((b) => `<span><span class="band-dot band-${b}"></span>${BAND_GLYPH[b]} ${bandLabel(b)}</span>`).join('');
  const chips = SOURCE_LAYERS.filter((s) => s.toggle !== false).map((s) => `<button type="button" class="ml-chip" data-src="${esc(s.key)}"
    aria-pressed="true">${s.glyph}<span>${esc(s.shortLabel)}</span><span class="sr-only"> (${esc(s.label)})</span></button>`).join('');
  const rows = SOURCE_LAYERS.map((s) => {
    const href = httpsUrl(s.attributionUrl);
    return `<li class="ml-src" data-src="${esc(s.key)}">
      <p class="ml-src-h">${s.glyph}<strong>${esc(s.label)}</strong>${s.toggle === false ? '<span class="ml-always">always on</span>' : ''}</p>
      <p>${esc(s.description)}</p>${s.key === 'reports' ? `<p class="ml-bands-in">${bands}</p>` : ''}
      <p class="ml-terms"><span>Terms:</span> ${esc(s.license)}</p>
      <p class="ml-credit"><span>Credit:</span> ${href ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(s.attribution)}</a>` : esc(s.attribution)}</p>
    </li>`;
  }).join('');
  return `<div class="map-legend" role="region" aria-label="Map layers and legend">
    <div class="ml-bands" aria-label="Report colours">${bands}</div>
    <div class="ml-row"><div class="ml-chips" role="group" aria-label="Show or hide map layers">${chips}</div>
      <button type="button" class="ml-info" aria-expanded="false" aria-controls="ml-panel"><span aria-hidden="true">ⓘ</span> Sources</button></div>
    <div id="ml-panel" class="ml-panel" hidden><h3 class="ml-panel-h">Map layers and where the data comes from</h3><ul>${rows}</ul></div>
  </div>`;
}
function setLayer(key, on) {
  const g = layers[key];
  if (!g || !map) return;
  if (on) g.addTo(map); else map.removeLayer(g);
  document.querySelector(`.ml-chip[data-src="${key}"]`)?.setAttribute('aria-pressed', String(!!on));
}
function wireLayerControl(root) {
  const lg = root.querySelector('.map-legend');
  if (!lg) return;
  lg.addEventListener('keydown', (e) => {
    const info = lg.querySelector('.ml-info');
    if (e.key === 'Escape' && info.getAttribute('aria-expanded') === 'true') { info.click(); info.focus(); }
  });
  lg.addEventListener('click', (e) => {
    const chip = e.target.closest('.ml-chip');
    if (chip) return setLayer(chip.dataset.src, chip.getAttribute('aria-pressed') !== 'true');
    const info = e.target.closest('.ml-info');
    if (info) {
      const open = info.getAttribute('aria-expanded') !== 'true';
      info.setAttribute('aria-expanded', String(open));
      lg.querySelector('#ml-panel').hidden = !open;
    }
  });
}
const fmtNum = (v, d = 1) => Number(v).toLocaleString(undefined, { maximumFractionDigits: d });
const fmtTime = (iso) => { const t = Date.parse(iso || ''); return t ? new Date(t).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : ''; };
export function gaugePopupHTML(g) {
  const vals = [isNum(g.discharge_cfs) && `<strong>${esc(fmtNum(g.discharge_cfs))} cfs</strong> flow`, isNum(g.gage_height_ft) && `gage height ${esc(fmtNum(g.gage_height_ft, 2))} ft`].filter(Boolean);
  const href = httpsUrl(g.source_url), when = fmtTime(g.observed_at);
  return `<div class="swim-pop gauge-pop">
    <p class="sp-kicker">USGS stream gauge · live${g.provisional ? ', provisional' : ''}</p>
    <strong class="sp-name">${esc(String(g.name ?? '').trim() || `USGS ${g.site_no ?? ''}`)}</strong>
    <p class="sp-val">${vals.length ? vals.join(' · ') : 'No reading right now.'}${isNum(g.pct_of_median) ? ` · ${esc(Math.round(Number(g.pct_of_median)))}% of normal for this date` : ''}</p>
    ${when ? `<p class="sp-date">As of <strong>${esc(when)}</strong></p>` : ''}
    ${g.note ? `<p class="sp-note">${esc(g.note)}</p>` : ''}
    <p class="credit">U.S. Geological Survey${href ? ` · <a href="${esc(href)}" target="_blank" rel="noopener noreferrer">data</a>` : ''}</p>
  </div>`;
}
export function cdecPopupHTML(st) {
  const vals = st.kind === 'reservoir'
    ? [isNum(st.storage_af) && `<strong>${esc(fmtNum(st.storage_af, 0))} acre-feet</strong> stored`, isNum(st.elevation_ft) && `water level ${esc(fmtNum(st.elevation_ft))} ft`]
    : [isNum(st.flow_cfs) && `<strong>${esc(fmtNum(st.flow_cfs))} cfs</strong> flow`, isNum(st.stage_ft) && `stage ${esc(fmtNum(st.stage_ft, 2))} ft`];
  const v = vals.filter(Boolean), href = httpsUrl(st.source_url), when = fmtTime(st.observed_at);
  const ageH = Date.parse(st.observed_at || '') ? (Date.now() - Date.parse(st.observed_at)) / 3600e3 : NaN;
  return `<div class="swim-pop cdec-pop">
    <p class="sp-kicker">CDEC river station · regional context</p>
    <strong class="sp-name">${esc(String(st.name ?? '').trim() || `CDEC ${st.station_id ?? ''}`)}</strong>
    <p class="sp-val">${v.length ? v.join(' · ') : 'No reading right now.'}</p>
    ${when ? `<p class="sp-date">As of <strong>${esc(when)}</strong>${ageH > 6 ? ' (an older reading; CDEC can lag by hours)' : ''}</p>` : ''}
    ${st.note ? `<p class="sp-note">${esc(st.note)}</p>` : ''}
    <p class="credit">${esc(st.credit || 'California Department of Water Resources, CDEC')}${href ? ` · <a href="${esc(href)}" target="_blank" rel="noopener noreferrer">data</a>` : ''}</p>
  </div>`;
}

const ECOLI_STV = 320;
const spotName = (st) => String(st.name ?? '').trim() || 'Unnamed spot';
export function swimPopupHTML(st, jbr) {
  const t = Date.parse(`${String(st.date || '').slice(0, 10)}T12:00:00`);
  const when = t ? new Date(t).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '';
  // Calendar days between the sample date and today (local), e.g. Aug 8 → Oct 4 = 57.
  const today = new Date(); today.setHours(12, 0, 0, 0);
  const days = t ? Math.max(0, Math.round((today - t) / 864e5)) : null;
  const v = Number(st.ecoli_mpn_100ml);
  const val = isNum(st.ecoli_mpn_100ml)
    ? `E. coli <strong>${esc(v)}</strong> per 100 mL: ${v <= ECOLI_STV
      ? `below California’s recreational threshold of ${ECOLI_STV}.`
      : `above the ${ECOLI_STV} recreational threshold (a statistical threshold, not a single-sample limit).`}`
    : 'No E. coli number in the latest test.';
  const href = httpsUrl(st.source_url);
  const southYuba = /south yuba/i.test(String(st.river || ''));
  const flowT = Date.parse(jbr?.observed_at || '');
  const flow = southYuba && jbr && isNum(jbr.flow_cfs)
    ? `<p class="sp-flow">South Yuba at Jones Bar now: ${esc(Number(jbr.flow_cfs))} cfs${flowT ? `, as of ${esc(new Date(flowT).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }))}` : ''}.</p>`
    : '';
  return `<div class="swim-pop">
    <p class="sp-kicker">Swim hole · volunteer bacteria test</p>
    <strong class="sp-name">${esc(spotName(st))}</strong>${st.river ? `<span class="sp-river">${esc(st.river)}</span>` : ''}
    <p class="sp-date">Tested <strong>${esc(when || 'date unknown')}</strong>${days != null ? ` (${esc(days)} day${days === 1 ? '' : 's'} ago)` : ''}: a summer sample, not a live reading.</p>
    <p class="sp-val">${val}</p>
    ${st.stale ? '<p class="sp-note">An older sample; newer tests may not be published yet.</p>' : ''}
    ${flow}
    ${upstreamNoteHTML()}
    <p class="credit">${esc(st.credit || 'Volunteer monitoring')}${href ? ` · <a href="${esc(href)}" target="_blank" rel="noopener noreferrer">data</a>` : ''}</p>
  </div>`;
}

export function showMap(qs) {
  if (!map) return;
  setTimeout(() => map.invalidateSize(), 50);
  const id = qs?.get('report');
  const m = id && pinsById.get(String(id));
  if (m) {
    setLayer('reports', true); // a shared report link must show its pin even if Reports was switched off
    map.setView(m.getLatLng(), 16);
    m.openPopup();
  }
}
