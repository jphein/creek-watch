// Map — creek lines, site markers, recent-report pins coloured by band.
import { getCreeks, getReports, reportBand } from './api.js';
import { esc, bandLabel, reportCardHTML } from './ui.js';

const LEAFLET_CSS = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css';
const LEAFLET_JS = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js';
const LEAFLET_JS_SRI = 'sha512-puJW3E/qXDqYp9IfhAI54BJEaWIfloJ7JWs7OeD5i6ruC9JZL1gERT1wjtwXFlh7CjE7ZJ+/vcRZRkIYIb6p4g==';
const LEAFLET_CSS_SRI = 'sha512-h9FcoyWjHcOcmEVkxOfTLnmZFWIH0iZhZT1H2TbOq55xssQGEJHEaIm+PgoUaZbRvQTNTluNOEfb1ZRy6D3BOw==';
const BAND_GLYPH = { good: '✓', fair: '~', watch: '!', alert: '✕' };

let map, L, pinsById = new Map(), creeksCache = [];

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
    <div class="map-legend" aria-label="Legend">${['good', 'fair', 'watch', 'alert']
      .map((b) => `<span><span class="band-dot band-${b}"></span>${BAND_GLYPH[b]} ${bandLabel(b)}</span>`)
      .join('')}</div></div>`;
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
            ? { color: water, weight: 4, opacity: 0.65, dashArray: '2 8', lineCap: 'round' }
            : { color: water, weight: 6, opacity: 0.8, lineCap: 'round' },
        onEachFeature: (f, l) => l.bindTooltip(esc(f?.properties?.name || c.name), { sticky: true }),
      })
        .addTo(map);
      bounds.push(layer.getBounds());
    }
    for (const s of c.sites || []) {
      L.marker([s.lat, s.lon], {
        icon: L.divIcon({ className: '', html: '<div class="site-marker"></div>', iconSize: [14, 14], iconAnchor: [7, 7] }),
        title: `${s.name} (${c.name})`,
        alt: `${s.name}, ${c.name}`,
        keyboard: true,
      })
        .bindPopup(`<strong>${esc(s.name)}</strong><br>${esc(c.name)}<br><a href="#report">Report from here</a>`)
        .addTo(map);
      bounds.push(L.latLngBounds([[s.lat, s.lon], [s.lat, s.lon]]));
    }
  }

  for (const r of reports) {
    if (r.lat == null || r.lon == null) continue;
    const band = reportBand(r);
    const c = creeks.find((x) => x.id === r.creek_id);
    const site = c?.sites?.find((s) => s.id === r.site_id);
    const m = L.marker([r.lat, r.lon], {
      icon: L.divIcon({
        className: '',
        html: `<div class="pin band-${band}"><span class="pin-glyph">${BAND_GLYPH[band]}</span></div>`,
        iconSize: [26, 26],
        iconAnchor: [13, 30],
        popupAnchor: [0, -28],
      }),
      title: `${bandLabel(band)} report${site ? ' at ' + site.name : ''}`,
      alt: `${bandLabel(band)} report`,
      keyboard: true,
      riseOnHover: true,
    })
      .bindPopup(reportCardHTML(r, c?.name || '', site?.name || '', { band }), { maxWidth: 300 })
      .addTo(map);
    pinsById.set(String(r.id), m);
  }

  if (bounds.length) {
    const b = bounds.reduce((a, x) => a.extend(x), L.latLngBounds(bounds[0].getSouthWest(), bounds[0].getNorthEast()));
    map.fitBounds(b, { padding: [24, 24] });
  }
  showMap(qs);
}

export function showMap(qs) {
  if (!map) return;
  setTimeout(() => map.invalidateSize(), 50);
  const id = qs?.get('report');
  const m = id && pinsById.get(String(id));
  if (m) {
    map.setView(m.getLatLng(), 16);
    m.openPopup();
  }
}
