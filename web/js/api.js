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
    const extra = JSON.parse(sessionStorage.getItem('cw-mock-posted') || '[]');
    list = [...extra, ...list];
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
    rep.flags = deriveFlags(rep);
    const extra = JSON.parse(sessionStorage.getItem('cw-mock-posted') || '[]');
    sessionStorage.setItem('cw-mock-posted', JSON.stringify([rep, ...extra]));
    return rep;
  }
  return request('/api/reports', { method: 'POST', body: form });
}

// Client-side mirror of the SPEC's early-warning rules — used for mock mode
// and to colour a report when the server sends no band.
export function deriveFlags(r) {
  const f = [];
  if (r.dead_fish === true || r.dead_fish === 'true' || ['sewage', 'chemical'].includes(r.odor)) f.push('alert');
  if (r.water_color === 'brown') f.push('runoff_watch');
  if (r.algae === 'lots') f.push('algal_bloom_watch');
  if (r.trash === 'lots') f.push('trash');
  return f;
}

export function reportBand(r) {
  if (r.band) return r.band;
  const flags = r.flags && r.flags.length ? r.flags : deriveFlags(r);
  const has = (s) => flags.some((x) => String(x).includes(s));
  if (has('alert')) return 'alert';
  if (has('watch') || flags.length) return 'watch';
  if (r.algae === 'some' || r.trash === 'some' || ['cloudy', 'green', 'other'].includes(r.water_color) || r.odor === 'rotten')
    return 'fair';
  return 'good';
}
