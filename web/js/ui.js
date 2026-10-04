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
  alert: 'Alert: dead fish or a sewage/chemical smell. This is flagged for follow-up.',
  runoff_watch: 'Runoff watch: muddy water can mean soil or street runoff is washing in.',
  sediment_watch: 'Runoff watch: muddy water can mean soil or street runoff is washing in.',
  algal_bloom_watch: 'Algae watch: thick algae can turn into a harmful bloom in warm weather.',
  algae_watch: 'Algae watch: thick algae can turn into a harmful bloom in warm weather.',
  trash: 'Lots of trash noted. It can harm wildlife and block the flow.',
};
export function flagText(f) {
  if (typeof f === 'object' && f) return f.explanation || f.message || f.name || '';
  return FLAG_TEXT[f] || String(f).replace(/_/g, ' ');
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
