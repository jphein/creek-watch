# Creek Watch

**Citizen creek reports plus public data, turned into an explainable creek-health score and early warning.**
Built for Wolf Creek (Grass Valley, CA) and Deer Creek (Nevada City, CA) for the [IEEE OneAquaHealth Global Hackathon 2026](https://oneaquahealth-ieee-hackathon.devpost.com/).

**Live:** https://creekwatch.realm.watch
**Tracks:** primary Track 2 (Data-to-Insight); also Track 1 (Citizen Science UX) and Track 6 (Resilience Informatics).

<!-- SCREENSHOT PLACEHOLDER: once docs/screenshots/01-hero-dashboard.png exists (shot list: docs/devpost/SCREENSHOTS.md), replace this comment with:
![Creek Watch dashboard](docs/screenshots/01-hero-dashboard.png) -->

## What it does

- **Report:** anyone at the creek takes a photo and answers six quick, plain-language questions on their phone: water colour, algae, trash, flow, odour and dead fish. Location fills in from GPS, and the nearest spot is picked automatically.
- **Cleanups:** when trash is reported, an optional "I picked it up" toggle (with a bag count) records a cleanup, shown beside a safety line. Badges (Creek Helper, Creek Steward, Trash Hero) live only in the browser's local storage: no account, nothing sent. Creek cards show "N reported cleanups · B bags" (honour system, not verified). The score thanks people who removed trash, but reported trash still counts.
- **Map:** creek lines, named monitoring spots and recent reports, coloured by health band.
- **Dashboard:** a 0–100 health score per creek. **Every signal explains why it moved the score**, and the card shows the latest USGS gauge, NWS weather and Open-Meteo rainfall.
- **Early warning:** rule-based *watch* and *alert* signals. Examples: heavy rain plus brown water means a runoff watch; lots of algae plus warm weather means an algal-bloom watch; dead fish or a chemical or sewage odour means an alert.
- **Privacy:** photos are re-encoded from raw pixels (at most 1600 px), which removes all EXIF metadata including GPS. Public report locations are rounded to 3 decimal places (about 110 m). Reporter names are optional.

## Run it locally

You need Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/jphein/creek-watch.git
cd creek-watch
uv sync
uv run uvicorn creekwatch.asgi:app --app-dir backend --reload --port 8000
# open http://localhost:8000 (interactive API docs at /api/docs)
```

Run the tests:

```bash
uv run pytest                                    # Python tests (backend + data)
cd tests/web && npm install && CHROME_PATH=/usr/bin/google-chrome npm test   # headless-browser suites
```

With Docker:

```bash
docker compose up --build
# open http://localhost:8080
```

No environment variables are required. The SQLite database (`data/creekwatch.db`) and photos (`data/uploads/`) are created locally and are git-ignored. `CREEKWATCH_DATA_DIR` moves both.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/creeks` | Creeks and their named sites |
| `POST /api/reports` | File a report (multipart, with photo) |
| `GET /api/reports?creek_id=&since=&limit=` | Recent reports, newest first |
| `GET /api/reports/{id}` | One report |
| `GET /api/conditions?creek_id=` | Latest USGS gauge, NWS weather and Open-Meteo rainfall |
| `GET /api/health?creek_id=` | Health score, band and explained signals |
| `GET /api/alerts?creek_id=&severity=&category=&status=` | Water-related alerts (official sources plus Creek Watch rules) |
| `GET /api/alerts/sources` | Each alert source's status and polling schedule |
| `GET /alerts.atom` · `GET /alerts.cap.xml` (`?creek_id=`) | Open feeds: Atom, and CAP 1.2 alerts inside Atom |
| `GET /api/push/vapid-public-key` · `POST`/`DELETE /api/push/subscriptions` | Opt-in Web Push (filters by creek, severity and quiet hours) |
| `GET /api/version` | Build info |
| `GET /healthz` | Liveness |

Full contract: [docs/SPEC.md](docs/SPEC.md).

## Alerts

Creek Watch gathers water-related alerts for Wolf Creek, Deer Creek and nearby waters in one place: the **Alerts** page, open feeds, and opt-in push notifications.

| Source | Checked every | What becomes an alert |
|---|---|---|
| National Weather Service alerts | 5 min | Flood, flash-flood, hydrologic-outlook, heavy-rain and heat alerts at our sites |
| Creek Watch rules (citizen reports plus data) | 5 min | Runoff watch, algal-bloom watch, and alerts for dead fish or chemical/sewage odour |
| USGS stream gauges | 15 min | High- and low-flow signals |
| NOAA National Water Prediction Service | 15 min | River flood categories at forecast points in range |
| CA freshwater harmful algal blooms | 1 h | State Caution/Warning/Danger advisories |
| State Water Board sewage spills | 12 h | Reported spills near our creeks |
| RiverDB volunteer tests | daily | E. coli above California's recreational threshold of 320 per 100 mL (a statistical threshold, not a single-sample limit) |
| OEHHA fish-consumption advisories | daily | Standing advisories, linked to OEHHA |

Not live sources: EPA CyAN (too coarse for these waters), boil-water notices (no public feed; see [waterboards.ca.gov/drinking_water](https://www.waterboards.ca.gov/drinking_water/)) and Cal OES spill reports (no machine-readable feed). The app links to these instead.

- **Feeds:** `/alerts.atom` and `/alerts.cap.xml` (CAP 1.2 inside Atom), both filterable with `?creek_id=`.
- **Push:** opt-in Web Push with per-creek, per-severity and quiet-hours filters. No account is needed. The server stores only the push endpoint, its keys and your filters, plus timestamps and a delivery-failure counter. Push hosts are restricted to the known push services.
- **Not an emergency service.** Official alerts are linked to their source. For emergencies and evacuations, use Nevada County Alerts, AwareCA and 911.

Source details: [data/alerts/SOURCES.md](data/alerts/SOURCES.md).

## Layout

```
backend/   FastAPI app (serves /api/* and the web app)
web/       no-build PWA: HTML, CSS, ES modules, Leaflet
data/      public-data ingest, sites.json, creek-health score (+ tests)
deploy/    container + reverse-proxy config for creekwatch.realm.watch
docs/      spec, submission text, demo script, field guide
```

## Data sources

| Source | Used for | Terms |
|---|---|---|
| Citizen reports (Creek Watch users) | Observations and photos | Submitted by users; EXIF stripped; names optional |
| [USGS Water Services](https://waterservices.usgs.gov/) | Discharge and gage height. Deer Creek: gauge 11418500 near Smartsville (about 22 km downstream, regulated by Lake Wildwood). Wolf Creek: **no live gauge**; Bear River near Wheatland (11424000) is shown as low-weight regional context only | [U.S. public domain](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits) |
| [National Weather Service API](https://www.weather.gov/documentation/services-web-api) | Temperature, short forecast | [Public domain](https://www.weather.gov/disclaimer); no endorsement implied |
| [Open-Meteo](https://open-meteo.com/) | Rain in the past and next 24 h (model estimates, not a gauge) | [CC BY 4.0](https://open-meteo.com/en/terms); free API for non-commercial use |
| [RiverDB](https://riverdb.org) | Volunteer water tests: South Yuba River Citizens League (Deer Creek, monthly, 2022 to now), Sierra Streams Institute (Deer Creek, 2000–2023), Wolf Creek Community Alliance (Wolf Creek, 2017–2019) | The groups' public data, credited on every reading; periodic samples, not live |
| [CEDEN via data.ca.gov](https://data.ca.gov/dataset/surface-water-fecal-indicator-bacteria-results) | The 2024 Regional Board *E. coli* study on Wolf Creek, shown as dated history ("Past study · 2024") | State Water Board public data; no licence listed; credited |
| [CDEC (California DWR)](https://cdec.water.ca.gov/) | South Yuba River flow (JBR) and Englebright Lake storage (ENG), as regional context only | State public data; credited; readings can lag by hours, and each shows its observation time |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) | Base map; creek lines and the 12 access sites (via Overpass) | © OpenStreetMap contributors, [ODbL](https://opendatacommons.org/licenses/odbl/) |

Details, retrieval URLs and the right-creek checks: [data/SOURCES.md](data/SOURCES.md).

**Why citizen reports matter here:** neither creek has a live instrument in town, so a real-time gauge can't tell you what Wolf Creek or Deer Creek looks like downtown. People at the water can.

**Photos:** the South Yuba River and Sierra newt photos in the app (and in the demo video) come from Wikimedia Commons. Five are U.S. Bureau of Land Management works in the public domain. Three are CC BY-SA: Frank Schulenburg (Bridgeport Covered Bridge, 4.0) and Larry Miller (old Highway 49 bridge and Sierra newt, 2.0). Our edited versions of those three keep the same licence. Full table with links and edits: [web/assets/photos/CREDITS.md](web/assets/photos/CREDITS.md).

Creek Watch is not affiliated with or endorsed by USGS, NOAA/NWS, Open-Meteo or OpenStreetMap.

**Limitations:** the score is a screening signal built from casual observations and nearby public data. It is not a lab water-quality test and does not tell you whether the water is safe to drink or swim in.

## Team

- **Jeffrey "JP" Hein:** Sierra College student, full-stack developer, founder of TechEMPOWER. Design and development.
- **Alec:** student. Field reports, writing, demo narration and testing.

Built with AI coding assistance (Claude Code) under human direction and review. The health score itself uses deterministic, explainable rules, not AI.

## License

[MIT](LICENSE) © 2026 Jeffrey Hein and Creek Watch contributors.
