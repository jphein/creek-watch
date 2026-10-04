// "Get alerts": opt-in Web Push with per-creek / per-severity filters and quiet hours.
// No account. The server stores only the browser's push endpoint + keys and these filters.
import { getCreeks, getVapidKey, pushSubscribe, pushUnsubscribe, feedUrls, SEVERITIES, ApiError } from './api.js';
import { esc, SEV, toast, officialLine } from './ui.js';
import { kvSet, kvDel } from './store.js';

const LS = 'cw-push-filters';
const DEFAULT = { creek_ids: [], min_severity: 'watch', quiet_hours: null }; // creek_ids [] = all creeks
const LEVELS = { alert: 'Only Alerts', watch: 'Watch and Alert', advisory: 'Advisory and up', info: 'Everything, including info' };
let box, creeks = [], editing = false;

const loadFilters = () => { try { return JSON.parse(localStorage.getItem(LS)) || null; } catch { return null; } };
const saveFilters = (f) => { try { localStorage.setItem(LS, JSON.stringify(f)); } catch { /* soft */ } kvSet('push-filters', f); };

export function isIOS() {
  const ua = navigator.userAgent || '';
  return /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
}
export const isStandalone = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
const pushCapable = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

async function registration() {
  // The app registers sw.js on load; register here too so the flow also works in mock/dev mode.
  return (await navigator.serviceWorker.getRegistration()) || navigator.serviceWorker.register('sw.js');
}

function sameKey(buf, bytes) {
  if (!buf) return false; // unknown key: treat as different (a fresh subscription is cheap; a dead one is silent)
  const a = new Uint8Array(buf);
  return a.length === bytes.length && a.every((v, i) => v === bytes[i]);
}

function b64urlToBytes(s) {
  const pad = '='.repeat((4 - (s.length % 4)) % 4);
  const raw = atob((s + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

export async function mountSubscribe(el) {
  box = el;
  box.innerHTML = '<p class="muted">Checking this phone…</p>';
  creeks = await getCreeks().catch(() => []);
  render();
}

async function currentSub() {
  if (!pushCapable()) return null;
  const reg = await navigator.serviceWorker.getRegistration();
  return reg ? reg.pushManager.getSubscription() : null;
}

const honesty = `
  <details class="ga-honest"><summary>What we store and how to stop</summary>
    <ul>
      <li><strong>No account, no email, no name, no location.</strong></li>
      <li>We store only your browser’s push address (a random URL from your phone’s push service, plus its encryption keys) and the creeks, severities and quiet hours you pick.</li>
      <li>Tap <strong>Stop alerts</strong> here at any time and we delete them. Blocking notifications for this site in your browser settings also stops them.</li>
      <li>Alerts link to the official source (National Weather Service, State Water Board and others). Creek Watch is <strong>not</strong> an emergency warning service and doesn’t replace one: for emergencies and evacuations use Nevada County Alerts and AwareCA, and call 911.</li>
    </ul>
  </details>`;

function feedsHTML() {
  const f = feedUrls();
  return `<p class="small ga-feeds">No push? Use a feed: <a href="${f.atom}">Atom</a> for news readers, or <a href="${f.cap}">CAP 1.2</a> for emergency systems.</p>`;
}

async function render() {
  const head = `<h3 id="ga-h">Get alerts on this phone</h3>${officialLine({ compact: true })}`;
  if (!pushCapable() && isIOS() && !isStandalone()) {
    box.innerHTML = `${head}
      <div class="ga-ios">
        <p><strong>On iPhone and iPad, add Creek Watch to your Home Screen first.</strong> Apple only allows alerts from web apps that live on the Home Screen (iOS 16.4 or newer).</p>
        <ol class="ga-steps">
          <li>Tap the <strong>Share</strong> button <span class="ios-share" aria-label="Share icon">⬆︎</span> in Safari.</li>
          <li>Choose <strong>Add to Home Screen</strong>, then <strong>Add</strong>.</li>
          <li>Open <strong>Creek Watch</strong> from your Home Screen, go to <strong>Alerts</strong> and tap <strong>Get alerts</strong> again.</li>
        </ol>
      </div>${feedsHTML()}${honesty}`;
    return;
  }
  if (!pushCapable()) {
    box.innerHTML = `${head}<p>This browser can’t show push alerts. You can still follow every alert with a feed.</p>${feedsHTML()}`;
    return;
  }
  let key = null;
  try { key = await getVapidKey(); } catch (e) {
    box.innerHTML = `${head}<p>Push alerts aren’t switched on for Creek Watch yet. The Alerts page and feeds work now.</p>${feedsHTML()}`;
    return;
  }
  if (Notification.permission === 'denied') {
    box.innerHTML = `${head}<div class="banner error" role="alert"><div><strong>Notifications are blocked for this site</strong>
      <span>To turn them back on, open your browser’s site settings for creekwatch.realm.watch and allow notifications, then come back here.</span></div></div>${feedsHTML()}${honesty}`;
    return;
  }
  const sub = await currentSub();
  const saved = loadFilters();
  if (sub && saved && !editing) {
    const names = saved.creek_ids?.length ? saved.creek_ids.map((id) => creeks.find((c) => c.id === id)?.name || id) : ['All creeks'];
    box.innerHTML = `${head}
      <div class="ga-on" role="status"><span class="ga-check" aria-hidden="true">✓</span><div>
        <strong>Alerts are on for this phone</strong>
        <p>${esc(names.join(', '))} · ${esc(LEVELS[saved.min_severity] || saved.min_severity)}${
          saved.quiet_hours ? ` · quiet ${esc(saved.quiet_hours.start)}–${esc(saved.quiet_hours.end)}` : ''
        }</p></div></div>
      <div class="ga-actions"><button type="button" class="btn secondary" data-ga="edit">Change</button>
      <button type="button" class="btn ghost" data-ga="stop">Stop alerts</button></div>${feedsHTML()}${honesty}`;
    bind(key, sub);
    return;
  }
  const f = saved || DEFAULT;
  const checkedCreek = (id) => !f.creek_ids?.length || f.creek_ids.includes(id);
  box.innerHTML = `${head}
    <form class="ga-form" novalidate>
      <fieldset><legend>Which waters?</legend>
        ${creeks.map((c) => `<label class="ga-check-row"><input type="checkbox" name="creek" value="${esc(c.id)}" ${checkedCreek(c.id) ? 'checked' : ''}> ${esc(c.name)} <span class="muted">· ${esc(c.town || '')}</span></label>`).join('')}
        <p class="small muted">Area-wide alerts (like a flood watch for the county) come with any creek you pick.</p>
      </fieldset>
      <fieldset><legend>How serious?</legend>
        ${SEVERITIES.map((s) => `<label class="ga-check-row sev-${s}"><input type="radio" name="minsev" value="${s}" ${f.min_severity === s ? 'checked' : ''}>
          <span class="ga-glyph" aria-hidden="true">${SEV[s].glyph}</span> ${esc(LEVELS[s])}</label>`).join('')}
      </fieldset>
      <fieldset><legend>Quiet hours</legend>
        <label class="ga-check-row"><input type="checkbox" name="quiet" ${f.quiet_hours ? 'checked' : ''}> Don’t buzz me at night</label>
        <div class="ga-times" ${f.quiet_hours ? '' : 'hidden'}>
          <label>From <input type="time" name="qstart" value="${esc(f.quiet_hours?.start || '22:00')}"></label>
          <label>to <input type="time" name="qend" value="${esc(f.quiet_hours?.end || '07:00')}"></label>
        </div>
        <p class="small muted">Only Alerts (✕) come through during quiet hours.</p>
      </fieldset>
      <p class="need-hint" aria-live="polite"></p>
      <button type="submit" class="btn primary big"><span aria-hidden="true">🔔</span><span>${sub ? 'Save changes' : 'Turn on alerts'}</span></button>
      ${sub ? '<button type="button" class="link-btn" data-ga="cancel">Cancel</button>' : ''}
    </form>${feedsHTML()}${honesty}`;
  bind(key, sub);
}

function readForm(form) {
  const boxes = [...form.querySelectorAll('input[name="creek"]')];
  const picked = boxes.filter((i) => i.checked).map((i) => i.value);
  const creek_ids = picked.length === boxes.length ? [] : picked; // [] = all creeks (incl. new ones later)
  const min_severity = form.querySelector('input[name="minsev"]:checked')?.value || 'watch';
  const quiet = form.querySelector('input[name="quiet"]').checked;
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'America/Los_Angeles';
  return {
    creek_ids, min_severity, _none: !picked.length,
    quiet_hours: quiet ? { start: form.qstart.value || '22:00', end: form.qend.value || '07:00', tz } : null,
  };
}

function bind(key, existing) {
  box.onchange = (e) => {
    if (e.target.name === 'quiet') box.querySelector('.ga-times').hidden = !e.target.checked;
  };
  box.onclick = async (e) => {
    const b = e.target.closest('[data-ga]');
    if (!b) return;
    if (b.dataset.ga === 'edit') { editing = true; return render(); }
    if (b.dataset.ga === 'cancel') { editing = false; return render(); }
    if (b.dataset.ga === 'stop') {
      b.disabled = true;
      try {
        const sub = await currentSub();
        if (sub) { await pushUnsubscribe(sub.endpoint); await sub.unsubscribe(); }
        try { localStorage.removeItem(LS); } catch { /* soft */ }
        kvDel('push-filters');
        toast('Alerts are off. We deleted your push address.');
      } catch (err) {
        toast(err instanceof ApiError ? err.message : 'Couldn’t stop alerts. Try again.');
      }
      editing = false;
      return render();
    }
  };
  const form = box.querySelector('.ga-form');
  if (!form) return;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const hint = form.querySelector('.need-hint');
    const filters = readForm(form);
    if (filters._none) { hint.textContent = 'Pick at least one creek.'; return; }
    if (filters.quiet_hours && filters.quiet_hours.start === filters.quiet_hours.end) {
      hint.textContent = 'Quiet hours need different start and end times.';
      return;
    }
    delete filters._none;
    const btn = form.querySelector('button[type="submit"]');
    btn.disabled = true;
    hint.textContent = '';
    let replaced = null; // endpoint of a leftover subscription we already unsubscribed
    try {
      const perm = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission();
      if (perm !== 'granted') {
        hint.textContent = perm === 'denied' ? 'Notifications were blocked, so we can’t send alerts.' : 'Allow notifications when your phone asks, to get alerts.';
        btn.disabled = false;
        return render();
      }
      const reg = await registration();
      await navigator.serviceWorker.ready;
      const keyBytes = b64urlToBytes(key);
      // Re-read NOW (not the render-time snapshot). Reuse a subscription only when alerts are already on
      // from this flow AND it was made with the current server key. Anything else is a leftover (an earlier
      // session, a reset permission, a rotated VAPID key) whose push token may already be dead: posting it
      // got FCM 410 on the welcome push (prod, 2026-10-03 20:35). Replace it with a fresh one.
      let sub = await reg.pushManager.getSubscription();
      const wasOn = !!loadFilters();
      if (sub && !(wasOn && sameKey(sub.options && sub.options.applicationServerKey, keyBytes))) {
        replaced = sub.endpoint;
        await sub.unsubscribe().catch(() => {});
        sub = null;
      }
      if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes });
      await pushSubscribe(sub.toJSON ? sub.toJSON() : sub, filters);
      if (replaced && replaced !== sub.endpoint) pushUnsubscribe(replaced).catch(() => {}); // server forgets the old one
      saveFilters(filters);
      editing = false;
      toast(wasOn && !replaced ? 'Alert settings saved.' : 'Alerts are on. We’ll only buzz you for what you picked.');
      render();
    } catch (err) {
      if (replaced) {
        // The old subscription is already gone and the new one didn't make it (subscribe() or the POST failed):
        // alerts are OFF on this phone. Say so plainly, and make local state match.
        try { localStorage.removeItem(LS); } catch { /* soft */ }
        kvDel('push-filters');
        pushUnsubscribe(replaced).catch(() => {}); // best effort: the server forgets the old endpoint too
        hint.textContent = 'Your previous alert subscription was removed and a new one couldn’t be created, so alerts are OFF on this phone. Tap Turn on alerts to try again.';
      } else {
        hint.textContent = err instanceof ApiError ? err.message : 'Couldn’t turn on alerts on this phone. Check your connection and try again.';
      }
      btn.disabled = false;
    }
  };
}
