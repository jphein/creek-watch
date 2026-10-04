// Monitoring sites (WCCA / SYRCL water tests): access wording, the upstream caveat, and which
// Creek Watch reports are actually near a site. WCCA feedback, 2026-10-04: a site popup must show
// only that site's data, never the whole creek's reports as if they happened there.
import { esc, bandLabel, haversineKm, fmtDistance, timeAgo, VALUE_LABELS } from './ui.js';

// Number(null) and Number('') are 0; a missing value must never read as a real 0.
export const isNum = (x) => x != null && x !== '' && Number.isFinite(Number(x));

// Some WCCA sites are on private land, visited monthly with the landowner's permission. Until we
// have WCCA's list, every WCCA site gets the private wording (the safer default); station ids
// here are known-public overrides. An `access` field from the API ("private" | "public") wins.
export const PUBLIC_WQ_STATIONS = new Set([]);
export function siteAccess(st) {
  const a = String(st?.access || '').toLowerCase();
  if (a === 'private' || a === 'public') return a;
  if (PUBLIC_WQ_STATIONS.has(String(st?.station_id))) return 'public';
  return /^wcca$/i.test(String(st?.agency || '')) ? 'private' : null;
}
export const PRIVATE_TEXT = 'Private land: monitored by WCCA with the landowner’s permission. Not open to visitors; please view the data here only.';
export const privateNoteHTML = (st) =>
  siteAccess(st) === 'private'
    ? `<p class="access-note"><span aria-hidden="true">⛔</span> <span>${esc(/^wcca$/i.test(String(st?.agency || '')) || !st?.agency
      ? PRIVATE_TEXT : PRIVATE_TEXT.replace('WCCA', st.agency))}</span></p>`
    : '';

export const UPSTREAM_TEXT = 'Conditions at any spot can come from anywhere upstream. They don’t reflect on the landowner, and may be outside the landowner’s power to fix.';
export const upstreamNoteHTML = () => `<p class="upstream-note">${esc(UPSTREAM_TEXT)}</p>`;

// Reports near a site: within `radiusKm`, in the last `days`, nearest first, each with its own spot.
export const NEAR_KM = 0.5, NEAR_DAYS = 30;
export function reportsNear(st, reports, { radiusKm = NEAR_KM, days = NEAR_DAYS, now = Date.now() } = {}) {
  if (!isNum(st?.lat) || !isNum(st?.lon)) return [];
  const since = now - days * 864e5;
  return (reports || [])
    .filter((r) => isNum(r?.lat) && isNum(r?.lon) && (Date.parse(r.observed_at) || 0) >= since)
    .map((r) => ({ r, km: haversineKm(Number(st.lat), Number(st.lon), Number(r.lat), Number(r.lon)) }))
    .filter((x) => x.km <= radiusKm)
    .sort((a, b) => a.km - b.km);
}

const fmtR = (v, d) => Number(v).toLocaleString(undefined, { maximumFractionDigits: d });
const READINGS = [
  ['do_mg_l', (v) => `DO ${fmtR(v, 1)} mg/L`],
  ['water_temp_c', (v) => `water ${fmtR(v, 1)} °C`],
  ['ph', (v) => `pH ${fmtR(v, 1)}`],
  ['turbidity_ntu', (v) => `turbidity ${fmtR(v, 1)} NTU`],
];

/** Map popup for one volunteer water-test site. `spotName(r)` names a report's own spot. */
export function wqPopupHTML(st, creekName, reports, { spotName = () => '', band = () => 'fair', now } = {}) {
  const rd = st.readings || {};
  const vals = READINGS.filter(([k]) => isNum(rd[k])).map(([k, f]) => f(Number(rd[k])));
  const t = Date.parse(String(st.date || ''));
  const when = t ? new Date(t).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }) : 'date unknown';
  const near = reportsNear(st, reports, { now });
  const nearHTML = near.length
    ? `<ul class="wq-near">${near.slice(0, 5).map(({ r, km }) => {
      const spot = spotName(r) || (r.location_kind === 'side_stream' ? 'a spot away from the named spots' : 'an unnamed spot');
      const tags = [r.flow === 'flood' ? 'Flooding' : VALUE_LABELS.flow?.[r.flow] && `${VALUE_LABELS.flow[r.flow]} flow`, VALUE_LABELS.trash?.[r.trash] || '']
        .filter((x) => x && !/^none\b/i.test(x)).join(', ');
      return `<li><strong>${esc(bandLabel(band(r)))}</strong> report at ${esc(spot)}, ${esc(fmtDistance(km))} from this site · ${esc(timeAgo(r.observed_at))}${tags ? ` (${esc(tags)})` : ''}</li>`;
    }).join('')}</ul>`
    : `<p class="wq-none">No Creek Watch reports within ${esc(fmtDistance(NEAR_KM))} of this site in the last ${NEAR_DAYS} days.</p>`;
  return `<div class="wq-pop">
    <p class="sp-kicker">Volunteer water-test site</p>
    <strong class="sp-name">${esc(String(st.name ?? '').trim() || 'Unnamed site')}</strong><span class="sp-river">${esc(creekName || '')}</span>
    ${privateNoteHTML(st)}
    <p class="sp-date">Last tested <strong>${esc(when)}</strong>${isNum(st.age_days) ? ` (${esc(Number(st.age_days).toLocaleString())} days ago)` : ''}</p>
    ${vals.length ? `<p class="wq-vals">${esc(vals.join(' · '))}</p>` : ''}
    <p class="wq-near-h">Creek Watch reports near this site</p>
    ${nearHTML}
    ${upstreamNoteHTML()}
    <p class="credit">${esc(st.credit || st.agency || 'Volunteer monitoring')}</p>
    <a class="see-alerts" href="#dashboard">Whole-creek overview (all of ${esc(creekName || 'the creek')}) →</a>
  </div>`;
}
