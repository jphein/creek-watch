// Alerts page: every active water alert (official feeds + Creek Watch early
// warnings), filterable, deep-linkable (#alerts?id=… / #alerts?creek=…).
import { getAlerts, getCreeks, SEVERITIES, feedUrls } from './api.js';
import { esc, SEV, CATEGORY_LABEL, alertHTML } from './ui.js';
import { mountSubscribe } from './subscribe.js';

let root, all = [], creeks = [];
const f = { creek: '', sev: new Set(SEVERITIES), cat: '' };

export async function mountAlerts(el, qs) {
  root = el;
  if (qs?.get('creek')) f.creek = qs.get('creek');
  el.innerHTML = `
    <header class="alerts-head">
      <h2 id="alerts-h">Water alerts</h2>
      <p class="lead">Official alerts and Creek Watch early warnings for Nevada County creeks, rivers and reservoirs, in one place.</p>
      <button type="button" class="btn primary big" data-act="get-alerts" aria-expanded="false" aria-controls="get-alerts">
        <span aria-hidden="true">🔔</span><span>Get alerts on this phone</span></button>
    </header>
    <section id="get-alerts" class="get-alerts" hidden aria-labelledby="ga-h"></section>
    <form class="alert-filters" aria-label="Filter alerts">
      <label class="af-field"><span>Where</span><select name="creek"><option value="">All waters</option></select></label>
      <label class="af-field"><span>Type</span><select name="cat"><option value="">All types</option></select></label>
      <fieldset class="af-sev"><legend class="sr-only">Severity</legend>
        ${SEVERITIES.map((s) => `<button type="button" class="chip sev-${s}" data-sev="${s}" aria-pressed="true"><span aria-hidden="true">${SEV[s].glyph}</span> ${SEV[s].label}</button>`).join('')}
      </fieldset>
    </form>
    <p class="alerts-count" role="status" aria-live="polite"></p>
    <div class="alerts-list"><p class="muted">Loading alerts…</p></div>
    <p class="feeds small">Subscribe via feed: <span class="feed-links"></span></p>`;
  bind();
  try {
    [all, creeks] = await Promise.all([getAlerts(), getCreeks().catch(() => [])]);
  } catch (e) {
    // Never imply "all clear" when we simply couldn't check. Point to the official source instead.
    root.querySelector('.alerts-list').innerHTML = `<div class="banner error" role="alert"><div><strong>Alerts aren’t available right now</strong>
      <span>We couldn’t check the alert sources${e.offline ? ' (no connection)' : ''}. This does <em>not</em> mean all is clear. For official warnings, see the
      <a href="https://alerts.weather.gov/search?area=CA" target="_blank" rel="noopener noreferrer">National Weather Service alerts for California</a>.</span></div></div>`;
    root.querySelector('.alerts-count').textContent = '';
    return;
  }
  const sel = root.querySelector('select[name="creek"]');
  sel.insertAdjacentHTML('beforeend', creeks.map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join(''));
  sel.value = f.creek;
  const cats = [...new Set(all.map((a) => a.category))].filter(Boolean);
  root.querySelector('select[name="cat"]').insertAdjacentHTML('beforeend', cats.map((c) => `<option value="${esc(c)}">${esc(CATEGORY_LABEL[c] || c)}</option>`).join(''));
  render();
  focusAlert(qs?.get('id'));
}

export function showAlerts(qs) {
  if (!root) return;
  if (qs?.get('creek') != null) { f.creek = qs.get('creek'); const s = root.querySelector('select[name="creek"]'); if (s) s.value = f.creek; render(); }
  focusAlert(qs?.get('id'));
  getAlerts().then((a) => { all = a; render(); focusAlert(qs?.get('id')); }).catch(() => {});
}

function focusAlert(id) {
  if (!id) return;
  const el = root.querySelector(`[data-id="${CSS.escape(id)}"]`);
  if (!el) return;
  el.querySelector('details')?.setAttribute('open', '');
  el.classList.add('focus-flash');
  el.scrollIntoView({ block: 'center' });
  el.focus({ preventScroll: true });
}

function render() {
  const list = all.filter((a) => (!f.creek || a.area?.creek_ids?.includes(f.creek)) && f.sev.has(a.severity) && (!f.cat || a.category === f.cat));
  const box = root.querySelector('.alerts-list');
  const n = list.length;
  root.querySelector('.alerts-count').textContent = all.length
    ? `${n} active alert${n === 1 ? '' : 's'}${n !== all.length ? ` (of ${all.length})` : ''}`
    : '';
  box.innerHTML = n
    ? list.map((a) => alertHTML(a)).join('')
    : `<div class="all-clear"><span aria-hidden="true">✓</span><div><strong>${all.length ? 'No alerts match these filters' : 'No active water alerts from the sources we check'}</strong>
       <p>${all.length ? 'Try “All waters” or turn more severities back on.' : 'We check official sources and Creek Watch reports every few minutes. Always use your own judgement near water.'}</p></div></div>`;
  const feeds = feedUrls(f.creek);
  root.querySelector('.feed-links').innerHTML =
    `<a href="${feeds.atom}">Atom</a> (news readers) · <a href="${feeds.cap}">CAP 1.2</a> (emergency systems)${f.creek ? ' for this creek' : ''}`;
}

function bind() {
  root.addEventListener('change', (e) => {
    if (e.target.name === 'creek') f.creek = e.target.value;
    if (e.target.name === 'cat') f.cat = e.target.value;
    if (['creek', 'cat'].includes(e.target.name)) render();
  });
  root.addEventListener('click', (e) => {
    const chip = e.target.closest('[data-sev]');
    if (chip) {
      const s = chip.dataset.sev;
      f.sev.has(s) ? f.sev.delete(s) : f.sev.add(s);
      chip.setAttribute('aria-pressed', String(f.sev.has(s)));
      return render();
    }
    const ga = e.target.closest('[data-act="get-alerts"]');
    if (ga) {
      const panel = root.querySelector('#get-alerts');
      const open = panel.hidden;
      panel.hidden = !open;
      ga.setAttribute('aria-expanded', String(open));
      if (open) { mountSubscribe(panel); panel.scrollIntoView({ block: 'start', behavior: 'smooth' }); }
    }
  });
}
