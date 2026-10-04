// Shared helpers.

export const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

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
  report_coverage: 'Reports this week', early_warning_cap: 'Early warning',
  dead_fish: 'Dead fish seen', odor_sewage_chemical: 'Sewage or chemical smell', odor_rotten: 'Rotten-egg smell',
  water_brown: 'Muddy brown water', water_green: 'Green water', water_cloudy: 'Cloudy water',
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
  water_color: { clear: 'Clear', cloudy: 'Cloudy', brown: 'Brown / muddy', green: 'Green', other: 'Other color' },
  flow: { dry: 'Dry', low: 'Low', normal: 'Normal', high: 'High', flood: 'Flooding' },
  algae: { none: 'No algae', some: 'Some algae', lots: 'Lots of algae' },
  trash: { none: 'No trash', some: 'Some trash', lots: 'Lots of trash' },
  odor: { none: 'No smell', earthy: 'Earthy smell', sewage: 'Sewage smell', chemical: 'Chemical smell', rotten: 'Rotten smell', other: 'Unusual smell' },
};

export function reportCardHTML(r, creekName = '', siteName = '', { band } = {}) {
  const v = (k) => VALUE_LABELS[k]?.[r[k]] || r[k] || '';
  return `
  <article class="rep-card">
    ${r.photo_url ? `<img src="${esc(r.photo_url)}" alt="Creek photo from this report" loading="lazy">` : ''}
    <div class="rep-body">
      <header>
        ${band ? `<span class="band-dot band-${band}" title="${esc(bandLabel(band))}"></span>` : ''}
        <strong>${esc(siteName || creekName || 'Creek report')}</strong>
        <time datetime="${esc(r.observed_at)}">${esc(timeAgo(r.observed_at))}</time>
      </header>
      <p class="rep-tags">${[v('water_color'), `${v('flow')} flow`, v('algae'), v('trash'), v('odor')]
        .filter(Boolean)
        .map((t) => `<span>${esc(t)}</span>`)
        .join('')}${r.dead_fish ? '<span class="tag-alert">Dead fish</span>' : ''}</p>
      ${r.wildlife_seen ? `<p class="rep-note">Saw: ${esc(r.wildlife_seen)}</p>` : ''}
      ${r.notes ? `<p class="rep-note">“${esc(r.notes)}”</p>` : ''}
      ${r.reporter_name ? `<p class="rep-by">— ${esc(r.reporter_name)}</p>` : ''}
    </div>
  </article>`;
}
