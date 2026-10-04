// Source layers: every data source on the map, one toggleable layer each (modelled on Forage for All's
// src/config/sourceLayers.ts). Order here = order in the layer control. Terms and credits follow the
// README "Data sources" table and data/SOURCES.md; don't add a licence claim that isn't written there.
// `toggle: false` = credit only (always on). `glyph` is static HTML from this file, never from data.

export const SOURCE_LAYERS = [
  {
    key: 'reports',
    label: 'Creek Watch community reports',
    shortLabel: 'Reports',
    glyph: '<span class="pin-chip" aria-hidden="true"></span>',
    description: 'What volunteers saw at the creek: water colour, flow, algae, trash and smell. Pins are coloured by each report’s band; small dots are the named report spots.',
    license: 'Submitted by users; photo EXIF stripped; names optional. App code: MIT.',
    attribution: 'Creek Watch volunteers',
    attributionUrl: 'https://creekwatch.realm.watch/#about',
  },
  {
    key: 'wq',
    label: 'Volunteer water tests',
    shortLabel: 'Water test',
    glyph: '<span class="flask-marker sm" aria-hidden="true">⚗</span>',
    description: 'Periodic tests (oxygen, pH, temperature, cloudiness) by Wolf Creek Community Alliance, Sierra Streams Institute and SYRCL. Periodic samples, not live. Most WCCA sites are on private land: view the data here only.',
    license: 'The groups’ public data on RiverDB (no licence stated); credited on every reading.',
    attribution: 'WCCA, Sierra Streams Institute and SYRCL via RiverDB',
    attributionUrl: 'https://riverdb.org/',
  },
  {
    key: 'swim',
    label: 'Swim-hole bacteria tests',
    shortLabel: 'Swim hole test',
    glyph: '<span class="swim-marker sm" aria-hidden="true">≈</span>',
    description: 'Summer E. coli tests at South and Middle Yuba swim holes. Dated samples, not live readings; 320 is the state’s statistical threshold, not a single-sample limit.',
    license: 'SYRCL’s public data on RiverDB (no licence stated); credited on every reading.',
    attribution: 'South Yuba River Citizens League via RiverDB',
    attributionUrl: 'https://yubariver.org/',
  },
  {
    key: 'study',
    label: '2024 Regional Board bacteria study',
    shortLabel: 'Past study site',
    glyph: '<span class="study-marker sm" aria-hidden="true">’24</span>',
    description: 'Weekly E. coli samples from May to September 2024 on Wolf Creek and its tributaries. History, not current conditions; never part of a score.',
    license: 'State Water Board public data; no licence listed; credited.',
    attribution: 'Central Valley Regional Water Quality Control Board via CEDEN',
    attributionUrl: 'https://data.ca.gov/dataset/surface-water-fecal-indicator-bacteria-results',
  },
  {
    key: 'usgs',
    label: 'USGS stream gauges',
    shortLabel: 'USGS gauge',
    glyph: '<span class="gauge-marker sm" aria-hidden="true">cfs</span>',
    description: 'Live stream flow (provisional). Deer Creek near Smartsville is on Deer Creek, about 22 km downstream of Nevada City. Wolf Creek has no live gauge; the Bear River near Wheatland is regional context only.',
    license: 'U.S. public domain.',
    attribution: 'U.S. Geological Survey',
    attributionUrl: 'https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits',
  },
  {
    key: 'cdec',
    label: 'CDEC river stations',
    shortLabel: 'CDEC station',
    glyph: '<span class="cdec-marker sm" aria-hidden="true">≋</span>',
    description: 'Yuba River system context: South Yuba flow at Jones Bar and Englebright Lake storage. Hourly, but often hours behind; each reading shows its time. Not part of any creek score.',
    license: 'State public data; credited.',
    attribution: 'California Department of Water Resources, CDEC',
    attributionUrl: 'https://cdec.water.ca.gov/',
  },
  {
    key: 'alerts',
    label: 'Alert areas',
    shortLabel: 'Alert area',
    glyph: '<span class="alert-marker sm sev-watch" aria-hidden="true"><span>!</span></span>',
    description: 'Areas covered by active alerts: National Weather Service warnings and other official feeds, plus Creek Watch’s own early warnings. Each alert names its source. Not an emergency service: for emergencies call 911.',
    license: 'NWS: U.S. public domain. Other feeds: credited on each alert.',
    attribution: 'National Weather Service and the feeds named on each alert',
    attributionUrl: 'https://www.weather.gov/disclaimer',
  },
  {
    key: 'osm',
    label: 'Base map and creek lines',
    shortLabel: 'OpenStreetMap',
    toggle: false,
    glyph: '',
    description: 'Map tiles, creek lines and the named report spots’ locations.',
    license: 'ODbL.',
    attribution: '© OpenStreetMap contributors',
    attributionUrl: 'https://www.openstreetmap.org/copyright',
  },
];

export const TOGGLE_KEYS = SOURCE_LAYERS.filter((s) => s.toggle !== false).map((s) => s.key);

// Station coordinates the API doesn't carry. USGS: data/SOURCES.md. CDEC: cdec.water.ca.gov staMeta
// (JBR 39.292, -121.104; ENG 39.239, -121.267), retrieved 2026-10-04.
export const STATION_COORDS = {
  '11418500': [39.2243, -121.2685], // USGS DEER C NR SMARTSVILLE CA
  '11424000': [39.0002, -121.4066], // USGS BEAR R NR WHEATLAND CA
  JBR: [39.292, -121.104], // CDEC South Yuba River at Jones Bar
  ENG: [39.239, -121.267], // CDEC Englebright Lake
};
