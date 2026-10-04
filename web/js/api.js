// API client. Codes against docs/SPEC.md "API contract".
// `?mock=1` serves web/mock/*.json instead; `?mock=fail` also makes POST fail
// (to exercise the network-error path).

const params = new URLSearchParams(location.search);
export const MOCK = params.has('mock');
const MOCK_FAIL = params.get('mock') === 'fail';

export class ApiError extends Error {
  constructor(message, { status = 0, offline = false } = {}) {
    super(message);
    this.status = status;
    this.offline = offline;
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const mockPosted = () => { try { return JSON.parse(sessionStorage.getItem('cw-mock-posted') || '[]'); } catch { return []; } };
const mockCache = new Map();
async function mockJson(name) {
  if (!mockCache.has(name)) {
    mockCache.set(name, fetch(`mock/${name}.json`).then((r) => r.json()));
  }
  await sleep(120);
  return structuredClone(await mockCache.get(name));
}

// Turn FastAPI's {detail} (string or validation list) into plain words.
function plainDetail(body, status) {
  const d = body && body.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d) && d.length) {
    return d
      .map((e) => {
        const field = Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : '';
        return field ? `${String(field).replace(/_/g, ' ')}: ${e.msg}` : e.msg;
      })
      .join('; ');
  }
  if (status === 413) return 'That photo is too big. Try a smaller one.';
  if (status === 429) return 'Too many reports from this spot just now. Wait a minute and try again.';
  if (status >= 500) return 'The Creek Watch server had a problem. Your report is saved here; try again in a moment.';
  return `Something went wrong (error ${status}).`;
}

async function request(path, opts = {}) {
  let res;
  try {
    res = await fetch(path, { ...opts, headers: { Accept: 'application/json', ...(opts.headers || {}) } });
  } catch {
    throw new ApiError('No connection to Creek Watch right now.', { offline: true });
  }
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON */
  }
  if (!res.ok) throw new ApiError(plainDetail(body, res.status), { status: res.status });
  return body;
}

export async function getCreeks() {
  if (MOCK) return mockJson('creeks');
  return request('/api/creeks');
}

export async function getReports({ creek_id, since, limit } = {}) {
  if (MOCK) {
    let list = await mockJson('reports');
    list = [...mockPosted(), ...list];
    if (creek_id) list = list.filter((r) => r.creek_id === creek_id);
    if (since) list = list.filter((r) => r.observed_at >= since);
    return limit ? list.slice(0, limit) : list;
  }
  const q = new URLSearchParams();
  if (creek_id) q.set('creek_id', creek_id);
  if (since) q.set('since', since);
  if (limit) q.set('limit', limit);
  return request(`/api/reports?${q}`);
}

export async function getReport(id) {
  if (MOCK) return (await getReports()).find((r) => String(r.id) === String(id)) || null;
  return request(`/api/reports/${encodeURIComponent(id)}`);
}

/** Volunteer cleanups for a creek: {cleanups, bags, since}. */
export async function getCleanupStats(creek_id) {
  if (MOCK) return (await mockJson('cleanups'))[creek_id] || { cleanups: 0, bags: 0, since: null };
  return request(`/api/stats/cleanups?creek_id=${encodeURIComponent(creek_id)}`);
}

export async function getConditions(creek_id) {
  if (MOCK) return (await mockJson('conditions'))[creek_id] || null;
  return request(`/api/conditions?creek_id=${encodeURIComponent(creek_id)}`);
}

export async function getHealth(creek_id) {
  if (MOCK) return (await mockJson('health'))[creek_id] || null;
  return request(`/api/health?creek_id=${encodeURIComponent(creek_id)}`);
}

/** @param {FormData} form */
export async function postReport(form) {
  if (MOCK) {
    await sleep(900);
    if (MOCK_FAIL) throw new ApiError('No connection to Creek Watch right now.', { offline: true });
    const rep = Object.fromEntries([...form.entries()].filter(([k]) => k !== 'photo'));
    rep.id = Math.floor(Math.random() * 1e6);
    rep.dead_fish = rep.dead_fish === 'true';
    rep.lat = Number(rep.lat);
    rep.lon = Number(rep.lon);
    rep.photo_url = form.get('photo') ? 'mock/photo-1.svg' : null;
    rep.trash_removed = rep.trash_removed === 'true';
    rep.trash_bags = rep.trash_bags != null ? Number(rep.trash_bags) : null;
    rep.flags = deriveFlags(rep);
    try { sessionStorage.setItem('cw-mock-posted', JSON.stringify([rep, ...mockPosted()])); } catch { /* storage blocked: mock just forgets */ }
    return rep;
  }
  return request('/api/reports', { method: 'POST', body: form });
}

// Client-side mirror of the backend's compute_flags() — used in mock mode.
export function deriveFlags(r) {
  const f = [];
  if (r.dead_fish === true || r.dead_fish === 'true') f.push('dead_fish');
  if (['sewage', 'chemical'].includes(r.odor)) f.push(`${r.odor}_odor`);
  if (r.algae === 'lots') f.push('heavy_algae');
  if (r.water_color === 'brown') f.push('brown_water');
  if (r.flow === 'flood') f.push('flood');
  if (r.trash === 'lots') f.push('heavy_trash');
  return f;
}

// Matched by substring: the API (dead_fish, sewage_odor) and data lane
// (dead_fish_alert, chemical_odor_alert) name flags slightly differently.
const ALERT_HINTS = ['dead_fish', 'sewage', 'chemical', 'alert'];

// Per-report band for map pins (the API gives bands per creek, not per report).
export function reportBand(r) {
  if (r.band) return r.band;
  const flags = (r.flags && r.flags.length ? r.flags : deriveFlags(r)).map(String);
  if (flags.some((x) => ALERT_HINTS.some((h) => x.includes(h)))) return 'alert';
  if (flags.length) return 'watch';
  if (r.algae === 'some' || r.trash === 'some' || ['cloudy', 'green', 'other'].includes(r.water_color) || ['rotten', 'other'].includes(r.odor))
    return 'fair';
  return 'good';
}

/* ---------- alerts + push (docs/ALERTS-SPEC.md) ---------- */

export const SEVERITIES = ['alert', 'watch', 'advisory', 'info'];
const SEV_RANK = { alert: 0, watch: 1, advisory: 2, info: 3 };
export const bySeverity = (a, b) =>
  (SEV_RANK[a.severity] ?? 9) - (SEV_RANK[b.severity] ?? 9) || String(b.updated || '').localeCompare(String(a.updated || ''));

/** @returns {Promise<Array>} active alerts, most severe first */
export async function getAlerts({ creek_id, severity, category, status = 'active' } = {}) {
  let list;
  if (MOCK) {
    list = await mockJson('alerts');
    if (creek_id) list = list.filter((a) => a.area?.creek_ids?.includes(creek_id));
    if (severity) list = list.filter((a) => (SEV_RANK[a.severity] ?? 9) <= (SEV_RANK[severity] ?? 9)); // severity = minimum
    if (category) list = list.filter((a) => a.category === category);
    if (status) list = list.filter((a) => (a.status || 'active') === status);
  } else {
    const q = new URLSearchParams();
    if (creek_id) q.set('creek_id', creek_id);
    if (severity) q.set('severity', severity);
    if (category) q.set('category', category);
    if (status) q.set('status', status);
    list = await request(`/api/alerts?${q}`);
  }
  return (Array.isArray(list) ? list : []).sort(bySeverity);
}

/** One alert by id (deep links to alerts no longer in the active list). null if 404. */
export async function getAlertItem(id) {
  if (MOCK) return (await mockJson('alerts')).find((a) => a.id === id) || null;
  try { return await request(`/api/alerts/item?id=${encodeURIComponent(id)}`); }
  catch (e) { if (e.status === 404) return null; throw e; }
}

/** Source health: {sources:[{source,last_ok,last_error,failures,…}], schedule:{src:{interval_s}}}. */
export async function getAlertSources() {
  if (MOCK) {
    const now = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
    return { adapters_loaded: 6, load_error: null, sources: ['nws', 'sso', 'hab', 'riverdb', 'usgs', 'creekwatch'].map((source) => ({ source, last_ok: now, last_error: null, failures: 0 })), schedule: {} };
  }
  return request('/api/alerts/sources');
}

// Freshness for the "no alerts" ✓ (Oracle, #41). Rules (all must hold):
//  0. The server's poller has adapters loaded (adapters_loaded > 0) and no load_error (a broken
//     deploy polls nothing). Missing fields fail safe (= not loaded).
//  1. `creekwatch` never counts: it is computed from our own DB and succeeds even when every
//     upstream fetch is failing (network out), so it says nothing about official warnings.
//  2. `nws` (the life-safety source) must itself be fresh. Missing or stale nws = couldn't check.
// A source is fresh if last_ok is within 2x its poll interval (15 min when unknown).
export const LIFE_SAFETY_SOURCE = 'nws';
export const LOCAL_SOURCES = new Set(['creekwatch']);
export function sourcesFresh(info, now = Date.now()) {
  const list = (info?.sources || []).filter((s) => !LOCAL_SOURCES.has(s.source));
  const isFresh = (s) => {
    const t = Date.parse(s?.last_ok || '');
    const interval = Number(info?.schedule?.[s?.source]?.interval_s) || 900;
    return !!t && now - t <= 2 * interval * 1000;
  };
  const nws = list.find((s) => s.source === LIFE_SAFETY_SOURCE);
  const nwsT = Date.parse(nws?.last_ok || '');
  const adaptersOk = Number(info?.adapters_loaded) > 0 && !info?.load_error;
  const fresh = adaptersOk && !!nws && isFresh(nws);
  return { fresh, adaptersOk, nwsLatest: nwsT ? new Date(nwsT).toISOString() : null };
}

export async function getVapidKey() {
  if (MOCK) return (await mockJson('vapid')).key;
  return (await request('/api/push/vapid-public-key')).key;
}

/** filters: {creek_ids: [] = all, min_severity, quiet_hours: {start,end,tz}|null}. 201 created / 200 updated. */
export async function pushSubscribe(subscription, { creek_ids = [], min_severity = 'watch', quiet_hours = null } = {}) {
  const body = { subscription, creek_ids, min_severity, quiet_hours };
  if (MOCK) {
    await sleep(300);
    let created = true;
    try { created = !sessionStorage.getItem('cw-mock-push'); sessionStorage.setItem('cw-mock-push', JSON.stringify(body)); } catch { /* soft */ }
    return { status: created ? 'created' : 'updated', creek_ids, min_severity, quiet_hours }; // backend response shape
  }
  return request('/api/push/subscriptions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
}

export async function pushUnsubscribe(endpoint) {
  if (MOCK) { try { sessionStorage.removeItem('cw-mock-push'); } catch { /* soft */ } return; }
  const res = await fetch('/api/push/subscriptions', { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ endpoint }) }).catch(() => null);
  if (!res) throw new ApiError('Couldn’t reach Creek Watch to stop alerts. Check your connection and try again.', { offline: true });
  if (!res.ok) throw new ApiError(`Creek Watch couldn’t stop alerts just now (error ${res.status}). Your alerts are still on; try again.`, { status: res.status });
}

export function feedUrls(creek_id) {
  const q = creek_id ? `?creek_id=${encodeURIComponent(creek_id)}` : '';
  return { atom: `/alerts.atom${q}`, cap: `/alerts.cap.xml${q}` };
}
