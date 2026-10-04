// Shared helpers.

export const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

// Only http(s) and same-origin paths may become links/images. Blocks javascript:, data:, etc. from external feeds.
export function safeUrl(u) {
  if (!u) return '';
  try {
    const x = new URL(String(u), location.origin);
    return x.protocol === 'https:' || x.protocol === 'http:' ? x.href : '';
  } catch { return ''; }
}

// Upstream alert links: absolute https:// only (re-checked client-side even though the API validates).
export function httpsUrl(u) {
  try { const x = new URL(String(u || '')); return x.protocol === 'https:' ? x.href : ''; } catch { return ''; }
}

// Life-safety warnings have official channels; Creek Watch defers to them (PRIOR-ART §2b).
export const OFFICIAL = {
  nca: 'https://www.nevadacountyca.gov/3780/Emergency-Alerts',
  aware: 'https://aware.ca.gov/',
};
export function officialLine({ compact = false } = {}) {
  return `<p class="official-line${compact ? ' compact' : ''}"><span aria-hidden="true">☎</span> <span>For emergencies and evacuations, sign up for
    <a href="${OFFICIAL.nca}" target="_blank" rel="noopener noreferrer">Nevada County Alerts</a> and
    <a href="${OFFICIAL.aware}" target="_blank" rel="noopener noreferrer">AwareCA</a> · call <a href="tel:911">911</a>.${
      compact ? '' : ' Creek Watch is the everyday water-health layer between those, not a replacement for official warnings.'
    }</span></p>`;
}

export function haversineKm(lat1, lon1, lat2, lon2) {
  const R = 6371, rad = Math.PI / 180;
  const dLat = (lat2 - lat1) * rad, dLon = (lon2 - lon1) * rad;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

// US field users: feet/miles.
export function fmtDistance(km) {
  const ft = km * 3280.84;
  if (ft < 1000) return `${Math.max(10, Math.round(ft / 10) * 10)} ft`;
  const mi = km * 0.621371;
  return `${mi < 10 ? mi.toFixed(1) : Math.round(mi)} mi`;
}

export function timeAgo(iso) {
  const t = Date.parse(iso);
  if (!t) return '';
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 60) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} hr ago`;
  const d = Math.round(h / 24);
  if (d < 14) return `${d} day${d === 1 ? '' : 's'} ago`;
  return new Date(t).toLocaleDateString();
}

export const BANDS = {
  good: { label: 'Good', blurb: 'Looking healthy' },
  fair: { label: 'Fair', blurb: 'Mostly fine, a few things to watch' },
  watch: { label: 'Watch', blurb: 'Something may be wrong — keep an eye on it' },
  alert: { label: 'Alert', blurb: 'Possible problem — avoid contact and report it' },
};
export const bandLabel = (b) => BANDS[b]?.label || 'Unknown';

const FLAG_TEXT = {
  dead_fish: 'Alert: dead fish. This is flagged for follow-up. Please avoid touching the water.',
  sewage_odor: 'Alert: a sewage smell can mean a leak. This is flagged for follow-up.',
  chemical_odor: 'Alert: a chemical smell can mean a spill. This is flagged for follow-up.',
  brown_water: 'Runoff watch: muddy water can mean soil or street runoff is washing in.',
  orange_water: 'Orange water watch: orange or rusty-looking water can mean drainage from old mine sites (iron and other metals). Flagged for follow-up.',
  heavy_algae: 'Algae watch: thick algae can turn into a harmful bloom in warm weather.',
  flood: 'Flood: stay back from the banks. Fast water is dangerous.',
  heavy_trash: 'Lots of trash noted. It can harm wildlife and block the flow.',
};
const FLAG_ALIAS = {
  dead_fish_alert: 'dead_fish', sewage_odor_alert: 'sewage_odor', chemical_odor_alert: 'chemical_odor',
  algae_heavy: 'heavy_algae', trash_heavy: 'heavy_trash', flood_flow: 'flood',
};
FLAG_TEXT.green_water = 'Green water often means algae growing on extra nutrients.';
export function flagText(f) {
  if (typeof f === 'object' && f) return f.explanation || f.message || f.name || '';
  return FLAG_TEXT[f] || FLAG_TEXT[FLAG_ALIAS[f]] || humanize(f);
}

export const humanize = (s) => {
  const t = String(s ?? '').replace(/_/g, ' ').trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
};

// Plain-language names + value formatting for score signals (data/score.py).
const SIGNAL_LABEL = {
  rain_24h: 'Rain, last 24 hours', air_temp: 'Air temperature', stream_flow: 'Stream flow',
  report_coverage: 'Reports this week', early_warning_cap: 'Early warning', volunteer_lab_data: 'Volunteer water test',
  dead_fish: 'Dead fish seen', odor_sewage_chemical: 'Sewage or chemical smell', odor_rotten: 'Rotten-egg smell',
  water_brown: 'Muddy brown water', water_green: 'Green water', water_cloudy: 'Cloudy water', water_orange: 'Orange (rusty) water',
  algae_lots: 'Lots of algae', algae_some: 'Some algae', trash_lots: 'Lots of trash', trash_some: 'Some trash',
  flow_flood: 'Flooding', flow_dry: 'Dry creek bed',
};
const REPORT_SHARE = new Set(['dead_fish', 'odor_sewage_chemical', 'odor_rotten', 'water_brown', 'water_green', 'water_cloudy',
  'algae_lots', 'algae_some', 'trash_lots', 'trash_some', 'flow_flood', 'flow_dry']);

export function signalLabel(name) {
  return SIGNAL_LABEL[name] || (/[A-Z ]/.test(String(name)) ? String(name) : humanize(name));
}
export function signalValue(name, v) {
  if (v == null || v === '') return '';
  if (name === 'volunteer_lab_data' && /^\d{4}-\d{2}-\d{2}/.test(String(v)))
    return `tested ${new Date(`${String(v).slice(0, 10)}T12:00:00`).toLocaleDateString(undefined, { year: 'numeric', month: 'short' })}`;
  if (typeof v !== 'number') return String(v);
  if (name === 'rain_24h') return `${v.toFixed(2)} in`;
  if (name === 'air_temp') return `${Math.round(v)}°F`;
  if (name === 'stream_flow') return `${Math.round(v)}% of normal`;
  if (name === 'report_coverage') return `${v} report${v === 1 ? '' : 's'}`;
  if (REPORT_SHARE.has(name)) return `${Math.round(v * 100)}% of reports`;
  return String(Math.round(v * 10) / 10);
}

let toastTimer;
export function toast(msg) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 4200);
}

export const VALUE_LABELS = {
  water_color: { clear: 'Clear', cloudy: 'Cloudy', brown: 'Brown / muddy', orange: 'Orange / rusty', green: 'Green', other: 'Other color' },
  flow: { dry: 'Dry', low: 'Low', normal: 'Normal', high: 'High', flood: 'Flooding' },
  algae: { none: 'No algae', some: 'Some algae', lots: 'Lots of algae' },
  trash: { none: 'No trash', some: 'Some trash', lots: 'Lots of trash' },
  odor: { none: 'No smell', earthy: 'Earthy smell', sewage: 'Sewage smell', chemical: 'Chemical smell', rotten: 'Rotten smell', other: 'Unusual smell' },
};

export function reportCardHTML(r, creekName = '', siteName = '', { band } = {}) {
  const v = (k) => VALUE_LABELS[k]?.[r[k]] || r[k] || '';
  return `
  <article class="rep-card">
    ${safeUrl(r.photo_url) ? `<img src="${esc(safeUrl(r.photo_url))}" alt="Creek photo from this report" loading="lazy">` : ''}
    <div class="rep-body">
      <header>
        ${band ? `<span class="band-dot band-${band}" title="${esc(bandLabel(band))}"></span>` : ''}
        <strong>${esc(siteName || creekName || 'Creek report')}</strong>
        <time datetime="${esc(r.observed_at)}">${esc(timeAgo(r.observed_at))}</time>
      </header>
      <p class="rep-tags">${r.location_kind === 'side_stream' ? '<span class="tag-side">Not at a named spot</span>' : ''}${[v('water_color'), `${v('flow')} flow`, v('algae'), v('trash'), v('odor')]
        .filter(Boolean)
        .map((t) => `<span>${esc(t)}</span>`)
        .join('')}${r.dead_fish ? '<span class="tag-alert">Dead fish</span>' : ''}${
        r.trash_removed ? `<span class="tag-clean"><span aria-hidden="true">🧤</span> Cleaned up${Number(r.trash_bags) > 0 ? ` · ${Number(r.trash_bags) | 0} bag${Number(r.trash_bags) === 1 ? '' : 's'}` : ''}</span>` : ''
      }</p>
      ${r.wildlife_seen ? `<p class="rep-note">Saw: ${esc(r.wildlife_seen)}</p>` : ''}
      ${r.notes ? `<p class="rep-note">“${esc(r.notes)}”</p>` : ''}
      ${r.reporter_name ? `<p class="rep-by">— ${esc(r.reporter_name)}</p>` : ''}
    </div>
  </article>`;
}

/* ---------- alerts (shared by Alerts page, creek banners, map popups) ---------- */

export const SEV = {
  alert: { label: 'Alert', glyph: '✕', say: 'Take action' },
  watch: { label: 'Watch', glyph: '!', say: 'Be careful' },
  advisory: { label: 'Advisory', glyph: 'i', say: 'Good to know' },
  info: { label: 'Info', glyph: '•', say: 'For your information' },
};
export const CATEGORY_LABEL = {
  flood: 'Flood', flash_flood: 'Flash flood', storm: 'Storm', heat: 'Heat', sewage_spill: 'Sewage spill',
  algal_bloom: 'Algal bloom', bacteria: 'Bacteria', low_flow: 'Low flow', high_flow: 'High flow',
  contamination: 'Contamination', runoff: 'Runoff', other: 'Other',
};

export function fmtWhen(iso) {
  const t = Date.parse(iso);
  if (!t) return '';
  return new Date(t).toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

// NWS zone lists can run to hundreds of characters; keep the kicker to the first area.
export function shortArea(d) {
  const t = String(d || '');
  if (t.length <= 70) return t;
  const parts = t.split(/;\s*/).filter(Boolean);
  if (parts.length > 1 && parts[0].length <= 70) return `${parts[0]} + ${parts.length - 1} more area${parts.length > 2 ? 's' : ''}`;
  return t.slice(0, 67).trimEnd() + '…';
}

// Creek Watch's own warnings arrive without a category ("other"); call them what they are.
const categoryLabel = (a) => (a.category === 'other' || !a.category) && a.source === 'creekwatch' ? 'Early warning' : CATEGORY_LABEL[a.category] || 'Alert';

/** One alert. `compact` = banner/popup form (title + summary + source link). */
export function alertHTML(a, { compact = false, open = false } = {}) {
  const sev = SEV[a.severity] ? a.severity : 'info';
  const s = SEV[sev];
  const href = httpsUrl(a.url);
  const srcName = a.source === 'creekwatch' ? 'Creek Watch early warning (not official)' : a.source_name || a.source || 'Source';
  const src = href ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(srcName)}</a>` : esc(srcName);
  const when = [a.effective ? `From ${esc(fmtWhen(a.effective))}` : '', a.expires ? `until ${esc(fmtWhen(a.expires))}` : 'until further notice']
    .filter(Boolean).join(' ');
  if (compact) {
    return `<div class="alert-item sev-${sev} compact" role="${sev === 'alert' ? 'alert' : 'note'}">
      <span class="a-glyph" aria-hidden="true">${s.glyph}</span>
      <div><p class="a-kicker"><span class="a-sev">${s.label}</span> · ${esc(categoryLabel(a))}</p>
      <strong class="a-title">${esc(a.title)}</strong>
      ${a.summary ? `<p class="a-sum">${esc(a.summary)}</p>` : ''}
      <p class="a-src">Source: ${src}</p>${sev === 'alert' ? officialLine({ compact: true }) : ''}</div></div>`;
  }
  return `<article class="alert-item sev-${sev}" id="alert-${esc(a.id)}" data-id="${esc(a.id)}" tabindex="-1">
    <span class="a-glyph" aria-hidden="true">${s.glyph}</span>
    <div class="a-body">
      <p class="a-kicker"><span class="a-sev">${s.label}</span> · ${esc(categoryLabel(a))}${
        a.area?.area_desc ? ` · <span class="a-area">${esc(shortArea(a.area.area_desc))}</span>` : ''
      }</p>
      <h3 class="a-title">${esc(a.title)}</h3>
      ${a.summary ? `<p class="a-sum">${esc(a.summary)}</p>` : ''}
      ${a.instruction ? `<p class="a-do"><strong>What to do:</strong> ${esc(a.instruction)}</p>` : ''}
      <p class="a-when">${when}</p>
      ${sev === 'alert' ? officialLine({ compact: true }) : ''}
      <details class="a-more" ${open ? 'open' : ''}><summary>Source and details</summary>
        <p class="a-src">Official source: ${src}${href ? ' (opens the original alert)' : ''}</p>
        ${a.area?.area_desc && shortArea(a.area.area_desc) !== a.area.area_desc ? `<p class="a-src">Area: ${esc(a.area.area_desc)}</p>` : ''}
        ${a.updated ? `<p class="a-src">Updated ${esc(fmtWhen(a.updated))}</p>` : ''}
        ${a.attribution ? `<p class="a-src">${esc(a.attribution)}</p>` : ''}
      </details>
    </div>
  </article>`;
}
