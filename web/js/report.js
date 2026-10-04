// Report page — the guided 6-step flow (SPEC "Pages" #1, Track 1).
import { getCreeks, postReport, ApiError, reportBand, warningFlags } from './api.js';
import { icon } from './icons.js';
import { kvGet, kvSet, kvDel, outboxAdd, outboxAll, outboxDel, draftLoad, draftSave, draftClear } from './store.js';
import { esc, haversineKm, fmtDistance, bandLabel, flagText, toast } from './ui.js';
import { recordCleanup, badgeSVG, badgesStripHTML } from './badges.js';

const STEPS = [
  { key: 'photo', title: 'Take a picture of the creek', hint: 'Stand back so we can see the water and the bank.' },
  { key: 'where', title: 'Where are you?', hint: 'We use your phone’s location to find the closest spot.' },
  { key: 'water', title: 'How does the water look?', hint: 'Pick what is closest. There are no wrong answers.' },
  { key: 'see', title: 'What do you see?', hint: 'Look along the water and the bank.' },
  { key: 'smell', title: 'How does it smell?', hint: 'Take a sniff near the water, not too close.' },
  { key: 'send', title: 'Anything else?', hint: 'Optional. Then check your answers and send.' },
];

const CHOICES = {
  water_color: [
    ['clear', 'Clear', 'You can see the bottom', icon.clear],
    ['cloudy', 'Cloudy', 'Milky or hazy', icon.cloudy],
    ['brown', 'Brown', 'Muddy', icon.brown],
    ['orange', 'Orange', 'Rusty; can mean mine drainage', icon.orange],
    ['green', 'Green', 'Tinted green', icon.green],
    ['other', 'Other', 'Another color', icon.other],
  ],
  flow: [
    ['dry', 'Dry', 'No water moving', icon.dry],
    ['low', 'Low', 'A trickle', icon.low],
    ['normal', 'Normal', 'Steady flow', icon.normal],
    ['high', 'High', 'Fast and full', icon.high],
    ['flood', 'Flooding', 'Over the banks', icon.flood],
  ],
  algae: [
    ['none', 'None', '', icon.none],
    ['some', 'Some', 'A little green slime', icon.algaeSome],
    ['lots', 'Lots', 'Thick mats or scum', icon.algaeLots],
  ],
  trash: [
    ['none', 'None', '', icon.none],
    ['some', 'Some', 'A few pieces', icon.trashSome],
    ['lots', 'Lots', 'Piles or big items', icon.trashLots],
  ],
  odor: [
    ['none', 'No smell', '', icon.noSmell],
    ['earthy', 'Earthy', 'Like soil or leaves', icon.earthy],
    ['sewage', 'Sewage', 'Like a toilet', icon.sewage],
    ['chemical', 'Chemical', 'Like gas or bleach', icon.chemical],
    ['rotten', 'Rotten', 'Like rotten eggs', icon.rotten],
    ['other', 'Something else', '', icon.otherSmell],
  ],
  dead_fish: [
    ['false', 'No', 'No dead fish', icon.fish],
    ['true', 'Yes', 'I saw dead fish', icon.deadFish],
  ],
};

const NEAR_SITE_KM = 0.5;

const REQUIRED = {
  photo: [],
  where: ['creek_id'],
  water: ['water_color', 'flow'],
  see: ['algae', 'trash', 'dead_fish'],
  smell: ['odor'],
  send: [],
};

const blank = () => ({
  step: 0,
  creek_id: '', site_id: '', lat: null, lon: null, accuracy: null, gpsAt: null,
  water_color: '', flow: '', algae: '', trash: '', dead_fish: '', odor: '',
  wildlife_seen: '', notes: '', reporter_name: localStorageGet('cw-name'),
  noPhoto: false,
  trash_removed: false, trash_bags: 0,
});
let lastCleanup = null; // {bags, newly, saved, stats} for the confirmation card

// Site access notes come from OSM research; drop "(OSM way 123…)" style refs for field users.
const plainAccess = (t) => String(t).replace(/\s*\((?:[^()]*\bOSM\b[^()]*)\)/gi, '').replace(/\s+([.,])/g, '$1');

function localStorageGet(k) {
  try { return localStorage.getItem(k) || ''; } catch { return ''; }
}

let creeks = [];
let st = blank();
let photo = null; // Blob (already resized)
let photoUrl = null;
let root;
let gpsState = 'idle'; // idle | asking | ok | denied | unavailable
let sending = false;
let lastError = null;
let done = null; // server response after success

let photoTouched = false; // the user tapped "Open camera" / "Choose from my photos"

// Late async loads (draft photo from IndexedDB, /api/creeks on a weak signal) must not re-render the photo
// step once the picker was tapped: on a phone the camera app is open, and replacing the <input> detaches it,
// so its `change` never reaches us and the photo is silently lost (reproduced: creeks 3 s late).
function renderUnlessPicking() {
  if (STEPS[st.step]?.key === 'photo' && photoTouched) return;
  render();
}

export async function mountReport(el) {
  root = el;
  st = { ...blank(), ...(draftLoad() || {}) };
  render(); // show the form right away; IndexedDB and the network can be slow
  const saved = await kvGet('draft-photo');
  if (saved instanceof Blob && !photo && !photoTouched) { setPhoto(saved, false); renderUnlessPicking(); }
  try {
    creeks = await getCreeks();
  } catch (e) {
    creeks = [];
    lastError = e;
  }
  renderUnlessPicking(); // the photo step doesn't need creeks; Next renders the "where" step with them
  flushOutbox();
}

function persist() {
  draftSave(st);
}

function setPhoto(blob, save = true) {
  if (photoUrl) URL.revokeObjectURL(photoUrl);
  photo = blob;
  photoUrl = blob ? URL.createObjectURL(blob) : null;
  if (save) blob ? kvSet('draft-photo', blob) : kvDel('draft-photo');
}

// Downscale to ≤1600px JPEG on the phone: faster upload on a weak signal, and
// re-encoding drops EXIF (incl. GPS) before the photo ever leaves the device.
async function shrink(file) {
  try {
    const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' });
    const scale = Math.min(1, 1600 / Math.max(bmp.width, bmp.height));
    const w = Math.round(bmp.width * scale), h = Math.round(bmp.height * scale);
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    c.getContext('2d').drawImage(bmp, 0, 0, w, h);
    bmp.close?.();
    const out = await new Promise((r) => c.toBlob(r, 'image/jpeg', 0.84));
    return out || file;
  } catch {
    return file; // e.g. HEIC on a browser that can't decode it — server handles it
  }
}

function nearestSite(lat, lon) {
  let best = null;
  for (const c of creeks) {
    for (const s of c.sites || []) {
      const d = haversineKm(lat, lon, s.lat, s.lon);
      if (!best || d < best.d) best = { d, creek: c, site: s };
    }
  }
  return best;
}

function locate() {
  if (!('geolocation' in navigator)) {
    gpsState = 'unavailable';
    return render();
  }
  gpsState = 'asking';
  render();
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      st.lat = +pos.coords.latitude.toFixed(6);
      st.lon = +pos.coords.longitude.toFixed(6);
      st.accuracy = Math.round(pos.coords.accuracy);
      st.gpsAt = Date.now();
      gpsState = 'ok';
      const n = nearestSite(st.lat, st.lon);
      if (n && !st.site_id_manual) {
        st.creek_id = n.creek.id;
        // Only auto-pick a named spot when you're actually at it; otherwise it's "somewhere else" (e.g. a side
        // stream) and the report keeps your exact GPS point.
        st.site_id = n.d <= NEAR_SITE_KM ? n.site.id : '';
      }
      persist();
      render();
    },
    (err) => {
      gpsState = err.code === 1 ? 'denied' : 'unavailable';
      render();
    },
    { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 }
  );
}

function stepValid(i) {
  const k = STEPS[i].key;
  if (k === 'photo') return !!photo || st.noPhoto;
  return REQUIRED[k].every((f) => st[f] !== '' && st[f] != null);
}

function go(i) {
  st.step = Math.max(0, Math.min(STEPS.length - 1, i));
  persist();
  render();
  root.querySelector('.step-title')?.focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: 'smooth' });
  if (STEPS[st.step].key === 'where' && gpsState === 'idle' && !st.gpsAt) locate();
}

/* ---------- rendering ---------- */

function choiceGrid(field, legend, { cols = 'auto' } = {}) {
  const opts = CHOICES[field];
  return `<fieldset class="choices" data-cols="${cols}">
    <legend>${esc(legend)}</legend>
    <div class="choice-grid">
      ${opts
        .map(
          ([v, label, sub, ic]) => `
        <label class="choice">
          <input type="radio" name="${field}" value="${v}" ${String(st[field]) === v ? 'checked' : ''}>
          <span class="choice-face">
            ${ic}
            <span class="choice-label">${esc(label)}</span>
            ${sub ? `<span class="choice-sub">${esc(sub)}</span>` : ''}
          </span>
        </label>`
        )
        .join('')}
    </div>
  </fieldset>`;
}

function progress() {
  return `<ol class="progress" aria-label="Progress">
    ${STEPS.map(
      (s, i) =>
        `<li class="${i < st.step ? 'done' : i === st.step ? 'now' : ''}"><span class="sr-only">${esc(s.title)}${
          i === st.step ? ' (current step)' : i < st.step ? ' (done)' : ''
        }</span></li>`
    ).join('')}
  </ol>`;
}

function stepPhoto() {
  return `
    <div class="photo-zone ${photo ? 'has' : ''}">
      ${
        photo
          ? `<img src="${photoUrl}" alt="Your creek photo">
             <button type="button" class="btn ghost small" data-act="photo-clear">Retake</button>`
          : `<div class="photo-empty">${icon.camera}<p>No photo yet</p></div>`
      }
    </div>
    <div class="stack">
      <label class="btn primary big file-btn">
        ${icon.camera}<span>${photo ? 'Take another' : 'Open camera'}</span>
        <input type="file" accept="image/*" capture="environment" data-photo>
      </label>
      <label class="btn secondary big file-btn">
        ${icon.gallery}<span>Choose from my photos</span>
        <input type="file" accept="image/*" data-photo>
      </label>
      ${
        photo
          ? ''
          : `<button type="button" class="link-btn" data-act="no-photo">I can’t take a photo right now</button>`
      }
    </div>`;
}

function stepWhere() {
  const creek = creeks.find((c) => c.id === st.creek_id);
  const n = st.lat != null ? nearestSite(st.lat, st.lon) : null;
  let gps = '';
  if (gpsState === 'asking') gps = `<div class="gps-card busy" role="status"><span class="spinner" aria-hidden="true"></span>Finding you… (allow location if your phone asks)</div>`;
  else if (st.lat != null) {
    const far = n && n.d > 2;
    gps = `<div class="gps-card ${far ? 'warn' : 'ok'}" role="status">
      ${icon.pin}
      <div><strong>${far ? 'You seem far from the creek' : 'Got your location'}</strong>
      <span>${
        n ? `Closest named spot: ${esc(n.site.name)} on ${esc(n.creek.name)}, ${fmtDistance(n.d)} away.` : ''
      } ${n && n.d > NEAR_SITE_KM ? 'You’re not right at it, so we’ll use your exact GPS point. ' : ''}${st.accuracy ? `Accurate to about ${fmtDistance(st.accuracy / 1000)}.` : ''}</span></div>
      <button type="button" class="btn ghost small" data-act="gps">Again</button></div>`;
  } else if (gpsState === 'denied')
    gps = `<div class="gps-card warn" role="status">${icon.pin}<div><strong>Location is turned off</strong><span>That’s OK. Pick your spot below.</span></div><button type="button" class="btn ghost small" data-act="gps">Try again</button></div>`;
  else if (gpsState === 'unavailable')
    gps = `<div class="gps-card warn" role="status">${icon.pin}<div><strong>Couldn’t get a location</strong><span>Pick your spot below, or try again in the open.</span></div><button type="button" class="btn ghost small" data-act="gps">Try again</button></div>`;
  else gps = `<button type="button" class="btn primary big" data-act="gps">${icon.pin}<span>Find my spot</span></button>`;

  if (!creeks.length)
    return `${gps}<p class="muted">Loading creeks…</p>`;

  return `${gps}
    <fieldset class="choices">
      <legend>Which creek?</legend>
      <div class="choice-grid one">
        ${creeks
          .map(
            (c) => `<label class="choice">
              <input type="radio" name="creek_id" value="${esc(c.id)}" ${st.creek_id === c.id ? 'checked' : ''}>
              <span class="choice-face row"><span class="creek-glyph" aria-hidden="true"></span>
              <span><span class="choice-label">${esc(c.name)}</span><span class="choice-sub">${esc(c.town)}</span></span></span>
            </label>`
          )
          .join('')}
      </div>
    </fieldset>
    ${
      creek
        ? `<fieldset class="choices">
      <legend>Which spot?</legend>
      <div class="site-list">
        ${(creek.sites || [])
          .map((s) => {
            const d = st.lat != null ? haversineKm(st.lat, st.lon, s.lat, s.lon) : null;
            return `<label class="site">
              <input type="radio" name="site_id" value="${esc(s.id)}" ${st.site_id === s.id ? 'checked' : ''}>
              <span class="site-face"><span class="site-dot" aria-hidden="true"></span><span class="site-name">${esc(s.name)}</span>${
                d != null ? `<span class="site-dist">${fmtDistance(d)}</span>` : ''
              }</span>${
                st.site_id === s.id && s.access ? `<span class="site-access">${esc(plainAccess(s.access))}</span>` : ''
              }</label>`;
          })
          .join('')}
        <label class="site">
          <input type="radio" name="site_id" value="" ${st.site_id === '' ? 'checked' : ''}>
          <span class="site-face"><span class="site-dot other" aria-hidden="true"></span><span class="site-name">Somewhere else (between spots, or a side stream)</span></span>${
            st.site_id === '' ? `<span class="site-access">${st.lat != null ? 'We’ll use your exact GPS point.' : 'Turn on location so we can use your exact spot.'} If it’s a side stream, name it in Notes on the last step, for example “small stream off ${esc(creek.name)} by the trail.”</span>` : ''
          }
        </label>
      </div>
    </fieldset>`
        : ''
    }`;
}

function stepWater() {
  return choiceGrid('water_color', 'Water color') + choiceGrid('flow', 'How much water is moving?');
}

function stepSee() {
  return (
    choiceGrid('algae', 'Green slime or algae?', { cols: 3 }) +
    choiceGrid('trash', 'Trash in or near the water?', { cols: 3 }) +
    cleanupBlock() +
    choiceGrid('dead_fish', 'Any dead fish?', { cols: 2 }) +
    `<label class="field">
      <span class="field-label">${icon.heron} Animals you saw <em>(optional)</em></span>
      <input type="text" name="wildlife_seen" maxlength="200" autocomplete="off" placeholder="Ducks, a heron, crawdads…" value="${esc(st.wildlife_seen)}">
    </label>`
  );
}

// Shown only when there's trash: optional "I picked it up" + bag count + a safety line.
function cleanupBlock() {
  if (st.trash !== 'some' && st.trash !== 'lots') return '';
  const on = !!st.trash_removed;
  const bags = st.trash_bags | 0;
  return `<div class="cleanup">
    <p class="safety" role="note"><span aria-hidden="true">⚠️</span> Only pick up what’s safe. Leave needles, chemicals and big items, and report them.</p>
    <button type="button" class="cleanup-toggle" data-act="cleanup" aria-pressed="${on}">
      <span class="ct-icon" aria-hidden="true">🧤</span>
      <span><span class="ct-label">I picked it up</span><span class="ct-sub">${on ? 'Thank you! Tap again to undo.' : 'Optional. Tap if you removed some.'}</span></span>
      <span class="ct-check" aria-hidden="true">${on ? '✓' : ''}</span>
    </button>
    ${on ? `<div class="bags" role="group" aria-labelledby="bags-l">
      <span id="bags-l" class="bags-label">About how many bags? <em>(optional)</em></span>
      <div class="stepper">
        <button type="button" class="step-btn" data-act="bags-dec" aria-label="One fewer bag" ${bags <= 0 ? 'disabled' : ''}>−</button>
        <output class="bags-n" aria-live="polite" aria-label="${bags} bag${bags === 1 ? '' : 's'}">${bags}</output>
        <button type="button" class="step-btn" data-act="bags-inc" aria-label="One more bag" ${bags >= 20 ? 'disabled' : ''}>+</button>
      </div>
    </div>` : ''}
  </div>`;
}

function stepSmell() {
  return choiceGrid('odor', 'Pick one');
}

function summaryRow(label, value) {
  return `<div class="sum-row"><dt>${esc(label)}</dt><dd>${value}</dd></div>`;
}

function labelOf(field, v) {
  const o = (CHOICES[field] || []).find(([x]) => x === String(v));
  return o ? o[1] : '—';
}

function stepSend() {
  const creek = creeks.find((c) => c.id === st.creek_id);
  const site = creek?.sites?.find((s) => s.id === st.site_id);
  const editBtn = (i) => `<button type="button" class="link-btn" data-go="${i}">Change</button>`;
  return `
    <label class="field">
      <span class="field-label">Notes <em>(optional)</em></span>
      <textarea name="notes" maxlength="1000" rows="3" placeholder="${st.site_id === '' ? 'If it’s a side stream, which one? Anything unusual?' : 'Anything that seemed unusual?'}">${esc(st.notes)}</textarea>
    </label>
    <label class="field">
      <span class="field-label">Your first name <em>(optional, shown with your report)</em></span>
      <input type="text" name="reporter_name" maxlength="60" autocomplete="given-name" value="${esc(st.reporter_name)}">
    </label>
    <section class="summary" aria-labelledby="sum-h">
      <h3 id="sum-h">Your report</h3>
      ${photo ? `<img class="sum-photo" src="${photoUrl}" alt="Your creek photo">` : ''}
      <dl>
        ${summaryRow('Photo', (photo ? 'Added' : 'None') + editBtn(0))}
        ${summaryRow('Place', esc(site ? `${site.name}, ${creek ? creek.name : ''}` : `Away from named spots near ${creek ? creek.name : 'the creek'} (your GPS point)`) + editBtn(1))}
        ${summaryRow('Water', `${labelOf('water_color', st.water_color)}, ${labelOf('flow', st.flow).toLowerCase()} flow` + editBtn(2))}
        ${summaryRow('Algae', labelOf('algae', st.algae) + editBtn(3))}
        ${summaryRow('Trash', labelOf('trash', st.trash) + editBtn(3))}
        ${st.trash === 'some' || st.trash === 'lots'
          ? summaryRow('Cleanup', esc(st.trash_removed ? `Picked up${st.trash_bags > 0 ? `, about ${st.trash_bags} bag${st.trash_bags === 1 ? '' : 's'}` : ''} 🧤` : 'Not picked up') + editBtn(3))
          : ''}
        ${summaryRow('Dead fish', labelOf('dead_fish', st.dead_fish) + editBtn(3))}
        ${summaryRow('Smell', labelOf('odor', st.odor) + editBtn(4))}
      </dl>
    </section>`;
}

function errorBanner() {
  if (!lastError) return '';
  const offline = lastError.offline;
  return `<div class="banner error" role="alert">
    ${offline ? icon.wifiOff : ''}
    <div><strong>${offline ? 'Weak or no signal' : 'Not sent yet'}</strong>
    <span>${esc(lastError.message)} Your answers are saved on this phone.</span></div>
    <div class="banner-actions">
      <button type="button" class="btn primary" data-act="send">Try again</button>
      ${offline ? `<button type="button" class="btn secondary" data-act="queue">Send later automatically</button>` : ''}
      ${photo && [413, 415, 503].includes(lastError.status) ? `<button type="button" class="btn secondary" data-act="send-nophoto">Send without the photo</button>` : ''}
    </div>
  </div>`;
}

function renderDone() {
  const r = done;
  const creek = creeks.find((c) => c.id === r.creek_id);
  const band = reportBand(r);
  const flags = warningFlags(r.flags)
    .map((f) => ({ text: flagText(f), alert: /dead_fish|sewage|chemical|alert/.test(String(f)) }))
    .filter((f) => f.text);
  root.innerHTML = `
  <section class="done" aria-labelledby="done-h">
    <div class="done-mark" aria-hidden="true">${icon.check}</div>
    <h2 id="done-h" class="step-title" tabindex="-1">${r.queued ? 'Saved — it will send itself' : 'Report sent. Thank you!'}</h2>
    <p class="lead">${
      r.queued
        ? 'No signal right now. Your report is safe on this phone and will send as soon as you have a connection. You can close this page.'
        : `Your eyes on ${esc(creek ? creek.name : 'the creek')} help everyone downstream.`
    }</p>
    ${!r.queued && r.photo_url ? `<img class="done-photo" src="${esc(r.photo_url)}" alt="Your creek photo">` : ''}
    ${
      !r.queued
        ? `<div class="band-chip band-${band}"><span class="dot"></span>This report reads as <strong>${bandLabel(band)}</strong></div>`
        : ''
    }
    ${flags.length ? `<ul class="flag-list">${flags.map((f) => `<li class="${f.alert ? 'alert' : ''}">${esc(f.text)}</li>`).join('')}</ul>` : ''}
    ${cleanupCardHTML()}
    <h3>What happens next</h3>
    <ol class="next-steps">
      <li><strong>It shows on the map</strong> for anyone to see, with your photo.</li>
      <li><strong>It updates the creek score</strong> along with rain and stream-gauge data.</li>
      <li><strong>Warning signs get flagged.</strong> Things like dead fish or a sewage smell raise an alert on the dashboard.</li>
    </ol>
    <div class="stack">
      <button type="button" class="btn primary big" data-act="again">${icon.navReport}<span>Report another spot</span></button>
      <a class="btn secondary big" href="#map${r.id && !r.queued ? `?report=${encodeURIComponent(r.id)}` : ''}">${icon.navMap}<span>See it on the map</span></a>
    </div>
  </section>`;
  root.querySelector('.step-title')?.focus({ preventScroll: true });
}

function cleanupCardHTML() {
  const c = lastCleanup;
  if (!c) return '';
  const newly = c.newly || [];
  return `<section class="celebrate" aria-labelledby="cel-h">
    <div class="cel-burst" aria-hidden="true">🧤</div>
    <h3 id="cel-h">Thank you for cleaning up!</h3>
    <p>${c.bags > 0 ? `About ${c.bags} bag${c.bags === 1 ? '' : 's'} of trash out of the creek. ` : ''}Every piece you take out is one less for fish, birds and the river downstream.</p>
    ${newly.map((b) => `<div class="new-badge" role="status">${badgeSVG(b.id, { size: 88 })}<div><span class="nb-kicker">New badge</span><strong>${esc(b.name)}</strong><span class="nb-rule">For ${esc(b.rule)}</span></div></div>`).join('')}
    ${c.saved ? badgesStripHTML(c.stats) : '<p class="b-note">This phone isn’t letting us save badges (private browsing or storage turned off), but your cleanup is in the report. Thank you!</p>'}
  </section>`;
}

function render() {
  if (!root) return;
  if (done) return renderDone();
  const i = st.step;
  const s = STEPS[i];
  const body = { photo: stepPhoto, where: stepWhere, water: stepWater, see: stepSee, smell: stepSmell, send: stepSend }[s.key]();
  const last = i === STEPS.length - 1;
  root.innerHTML = `
  <form class="report" novalidate>
    <header class="step-head">
      ${progress()}
      <p class="step-count">Step ${i + 1} of ${STEPS.length}</p>
      <h2 class="step-title" tabindex="-1">${esc(s.title)}</h2>
      <p class="step-hint">${esc(s.hint)}</p>
    </header>
    ${last ? errorBanner() : ''}
    <div class="step-body">${body}</div>
    <div class="step-nav">
      ${i > 0 ? `<button type="button" class="btn secondary" data-act="back" aria-label="Back">${icon.back}<span>Back</span></button>` : '<span></span>'}
      ${
        last
          ? `<button type="submit" class="btn primary go" ${sending ? 'disabled aria-busy="true"' : ''}>${
              sending ? '<span class="spinner" aria-hidden="true"></span><span>Sending…</span>' : `${icon.check}<span>Send report</span>`
            }</button>`
          : `<button type="button" class="btn primary go" data-act="next" ${stepValid(i) ? '' : 'aria-disabled="true"'}><span>Next</span>${icon.next}</button>`
      }
    </div>
    <p class="need-hint" aria-live="polite"></p>
  </form>`;
}

/* ---------- events (delegated once) ---------- */

export function bindReport(el) {
  el.addEventListener('change', async (e) => {
    const t = e.target;
    if (t.matches('[data-photo]') && t.files && t.files[0]) {
      const file = t.files[0];
      if (file.size > 25 * 1024 * 1024) return toast('That file is very large. Try another photo.');
      const small = await shrink(file);
      setPhoto(small);
      st.noPhoto = false;
      persist();
      render();
      return;
    }
    if (t.name && t.type === 'radio') {
      st[t.name] = t.value;
      if (t.name === 'creek_id') {
        const c = creeks.find((x) => x.id === t.value);
        if (!c?.sites?.some((s) => s.id === st.site_id)) st.site_id = '';
        st.site_id_manual = true;
        persist();
        return render();
      }
      if (t.name === 'trash') {
        if (t.value === 'none') { st.trash_removed = false; st.trash_bags = 0; }
        persist();
        render();
        el.querySelector(`input[name="trash"][value="${CSS.escape(t.value)}"]`)?.focus();
        return;
      }
      if (t.name === 'site_id') {
        st.site_id_manual = true;
        persist();
        render();
        el.querySelector(`input[name="site_id"][value="${CSS.escape(t.value)}"]`)?.focus();
        return;
      }
      persist();
      // enable Next without a full re-render (keeps focus on the radio)
      const nb = el.querySelector('[data-act="next"]');
      if (nb) stepValid(st.step) ? nb.removeAttribute('aria-disabled') : nb.setAttribute('aria-disabled', 'true');
      el.querySelector('.need-hint').textContent = '';
    }
  });
  el.addEventListener('input', (e) => {
    const t = e.target;
    if (['wildlife_seen', 'notes', 'reporter_name'].includes(t.name)) {
      st[t.name] = t.value;
      persist();
    }
  });
  el.addEventListener('click', (e) => {
    if (e.target.closest('[data-photo], .file-btn')) photoTouched = true;
    const b = e.target.closest('[data-act],[data-go]');
    if (!b) return;
    if (b.dataset.go) return go(+b.dataset.go);
    const act = b.dataset.act;
    if (act === 'next') {
      if (!stepValid(st.step)) {
        el.querySelector('.need-hint').textContent =
          st.step === 0 ? 'Add a photo, or tap “I can’t take a photo right now”.' : 'Please answer each question above.';
        return;
      }
      return go(st.step + 1);
    }
    if (act === 'back') return go(st.step - 1);
    if (act === 'gps') return locate();
    if (act === 'photo-clear') { setPhoto(null); persist(); return render(); }
    if (act === 'no-photo') { st.noPhoto = true; persist(); return go(1); }
    if (act === 'cleanup' || act === 'bags-inc' || act === 'bags-dec') {
      if (act === 'cleanup') { st.trash_removed = !st.trash_removed; if (!st.trash_removed) st.trash_bags = 0; }
      else st.trash_bags = Math.max(0, Math.min(20, (st.trash_bags | 0) + (act === 'bags-inc' ? 1 : -1)));
      persist();
      render();
      (el.querySelector(`[data-act="${act}"]:not([disabled])`) || el.querySelector('[data-act="cleanup"]'))?.focus();
      return;
    }
    if (act === 'send') return send();
    if (act === 'send-nophoto') { setPhoto(null); st.noPhoto = true; persist(); return send(); }
    if (act === 'queue') return queue();
    if (act === 'again') return reset();
  });
  el.addEventListener('submit', (e) => {
    e.preventDefault();
    send();
  });
}

function buildForm() {
  const creek = creeks.find((c) => c.id === st.creek_id);
  const site = creek?.sites?.find((s) => s.id === st.site_id);
  // No GPS → use the picked spot (or the creek's first spot) as the location.
  const ref = site || creek?.sites?.[0];
  const lat = st.lat ?? ref?.lat;
  const lon = st.lon ?? ref?.lon;
  const f = {
    creek_id: st.creek_id,
    lat: String(lat),
    lon: String(lon),
    observed_at: new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'),
    water_color: st.water_color,
    algae: st.algae,
    trash: st.trash,
    flow: st.flow,
    odor: st.odor,
    dead_fish: st.dead_fish === 'true' ? 'true' : 'false',
    notes: st.notes.trim(),
    trash_removed: st.trash !== 'none' && st.trash_removed ? 'true' : 'false',
  };
  if (f.trash_removed === 'true' && (st.trash_bags | 0) > 0) f.trash_bags = String(Math.min(20, st.trash_bags | 0));
  if (st.site_id) f.site_id = st.site_id;
  else f.location_kind = 'side_stream'; // tells the server not to snap this report to the nearest named spot
  if (st.wildlife_seen.trim()) f.wildlife_seen = st.wildlife_seen.trim();
  if (st.reporter_name.trim()) f.reporter_name = st.reporter_name.trim().slice(0, 60);
  return f;
}

function toFormData(fields, blob) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.append(k, v);
  if (blob) fd.append('photo', blob, 'creek.jpg');
  return fd;
}

async function send() {
  if (sending) return;
  for (let i = 0; i < STEPS.length - 1; i++) {
    if (!stepValid(i)) {
      toast('One step still needs an answer.');
      return go(i);
    }
  }
  sending = true;
  lastError = null;
  render();
  const fields = buildForm();
  try {
    done = await postReport(toFormData(fields, photo));
    finish(fields);
  } catch (e) {
    lastError = e instanceof ApiError ? e : new ApiError('Something went wrong sending your report.');
    if (!navigator.onLine) lastError.offline = true;
  } finally {
    sending = false;
    render();
  }
}

async function queue() {
  const fields = buildForm();
  const ok = await outboxAdd({ fields, photo, created: Date.now() });
  if (!ok) return toast('Couldn’t save on this phone. Please try sending again.');
  done = { ...fields, queued: true };
  finish(fields);
  render();
  updateOutboxBadge();
}

function finish(fields) {
  try { if (fields.reporter_name) localStorage.setItem('cw-name', fields.reporter_name); } catch { /* soft */ }
  lastCleanup = fields.trash_removed === 'true' ? { bags: Number(fields.trash_bags || 0), ...recordCleanup(Number(fields.trash_bags || 0)) } : null;
  draftClear();
  kvDel('draft-photo');
  lastError = null;
}

function reset() {
  lastCleanup = null;
  photoTouched = false;
  const keep = { creek_id: st.creek_id, site_id: st.site_id, lat: st.lat, lon: st.lon, accuracy: st.accuracy, gpsAt: st.gpsAt };
  st = { ...blank(), ...keep };
  setPhoto(null);
  done = null;
  persist();
  render();
  window.scrollTo({ top: 0 });
}

/* ---------- offline outbox ---------- */

let flushing = false;
export async function flushOutbox() {
  if (flushing || !navigator.onLine) return updateOutboxBadge();
  flushing = true;
  try {
    for (const item of await outboxAll()) {
      try {
        await postReport(toFormData(item.fields, item.photo));
        await outboxDel(item.key);
        toast('A saved report was sent. Thank you!');
      } catch (e) {
        if (e.offline) break;
        if (e.status && e.status < 500 && e.status !== 429) await outboxDel(item.key); // rejected for good
        break;
      }
    }
  } finally {
    flushing = false;
    updateOutboxBadge();
  }
}

async function updateOutboxBadge() {
  const n = (await outboxAll()).length;
  const b = document.getElementById('outbox');
  if (!b) return;
  b.hidden = n === 0;
  b.textContent = n === 1 ? '1 report waiting for signal' : `${n} reports waiting for signal`;
}

addEventListener('online', flushOutbox);
document.addEventListener('visibilitychange', () => document.visibilityState === 'visible' && flushOutbox());
