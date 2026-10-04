# Creek Watch: build spec (shared contract for every lane)

**Contest:** IEEE OneAquaHealth Global Hackathon (Devpost). **HARD deadline: Sun 2026-10-04 21:00 PDT.**
Internal targets:
- **Sun 08:00:** a live, phone-usable report flow at https://creekwatch.realm.watch, so Alec can file real field reports with photos from Wolf Creek and Deer Creek.
- **Sun 15:00:** feature freeze.
- **Sun 18:00:** submission staged for JP's one-click submit.

**Tracks:** primary **Track 2, Data-to-Insight**; secondary Track 1 (Citizen Science UX: guided, plain-language report flow) and Track 6 (Resilience: early-warning signal).
**Team:** JP (owner, Sierra College) and Alec (student, field reports, writing, narration, testing).
**License:** MIT. The repo goes public, so NEVER commit secrets, keys, real reporter emails or EXIF GPS beyond what the user chose to submit.

## Architecture: keep it boring
- **backend/**: Python 3.12+ FastAPI app, run with uv. Storage: SQLite (`data/creekwatch.db`, gitignored) plus photos on disk (`uploads/`, gitignored). One process. It serves the API at `/api/*` and the static web build at `/`.
- **web/**: a no-build static PWA (HTML, CSS, vanilla JS ES modules). Leaflet plus OpenStreetMap tiles from CDN (cdnjs/unpkg). Mobile first. Favicon (SVG). Dark and light themes via `prefers-color-scheme` and CSS custom properties. Installable manifest and a simple service worker; offline queueing of reports is a stretch goal.
- **data/**: public-data ingest plus the creek-health score. Modules are imported by the backend and cached in SQLite.
- **Deploy:** a Docker container on **ubox0**, behind its Caddy at `creekwatch.realm.watch`. It must be always on (familiar sleeps). Version endpoint via realm-sigil (`~/Projects/realm-sigil`, Python `version_dict()`) at `/api/version`; register it in status.realm.watch `checks.json`.

## Creeks and sites (seed data; the data lane refines it)
- **Wolf Creek**, Grass Valley (flows through downtown GV toward Bear River).
- **Deer Creek**, Nevada City (through downtown NC toward Lake Wildwood/Yuba).
- Seed 4–6 named spots per creek with lat/lon (public access points such as Memorial Park, Pioneer Park, the Wolf Creek trail, Nevada City's Deer Creek Tribute Trail). The data lane provides `data/sites.json`.

## API contract (backend implements it; web and data code against it)
All JSON. Times are ISO-8601 UTC.
- `GET /api/creeks` returns `[{id, name, town, geojson_line?, sites:[{id,name,lat,lon}]}]`
- `POST /api/reports` (multipart/form-data): fields `creek_id, site_id?, lat, lon, observed_at, water_color(enum: clear|cloudy|brown|green|other), algae(none|some|lots), trash(none|some|lots), flow(dry|low|normal|high|flood), odor(none|earthy|sewage|chemical|rotten|other), dead_fish(bool), wildlife_seen(text?), notes(text ≤1000), reporter_name?(text ≤60), photo(file ≤10MB, jpeg/png/heic)`. Returns `{id, ...report, photo_url, flags:[...]}`. The server strips EXIF from photos and caps the image size (e.g. 1600 px JPEG). It validates the enums, rate-limits per IP, and rejects lat/lon more than ~25 km from the creeks.
- `GET /api/reports?creek_id=&since=&limit=` returns a list, newest first.
- `GET /api/reports/{id}`
- `GET /api/conditions?creek_id=` returns current public data: `{gauge:{site_no,name,discharge_cfs,gage_height_ft,observed_at,source_url}|null, weather:{temp_f,precip_24h_in,forecast_short,observed_at,source_url}, fetched_at}`
- `GET /api/health?creek_id=` returns the **creek-health score and early warning**: `{score:0-100, band:"good|fair|watch|alert", signals:[{name, value, weight, explanation, source}], recent_report_count, last_updated}`. The score must be **explainable**: each signal says in plain language why it moved the score. Early-warning rules, for example: heavy rain in the last 24 h plus reports of brown water means a runoff/sediment watch; algae "lots" plus warm temperatures means an algal-bloom watch; any dead fish or a chemical/sewage odor means an alert.
- `GET /api/version` (realm-sigil)
- `GET /healthz` returns 200.

## Pages (web)
1. **Report** (default on phones): a guided 6-step flow with big tap targets and picture icons, written in plain words rather than jargon (Track 1). Take or choose a photo, with GPS from the browser and the nearest site auto-picked. Ends with a confirmation and what happens next.
2. **Map**: Leaflet with creek lines, site markers and recent-report pins coloured by health band. Tapping a pin shows the report with its photo.
3. **Dashboard**: one card per creek with the score gauge, band, signals and explanations, latest gauge and weather, recent reports, and a 7-day report sparkline.
4. **About the data**: sources and links (USGS, NWS, citizen reports), how the score works, limitations, privacy (photos have EXIF stripped, names optional), and the One Health framing (creek health, wildlife health and human health).

## Lanes (each lane has its own git worktree and branch; files are owned per lane)
| Lane | Agent | Owns |
|---|---|---|
| core API | morpheus-creekwatch-api | `backend/`, `pyproject.toml`, `Dockerfile`, `compose.yaml` |
| web UI | luna-creekwatch-web | `web/` |
| data and score | nebula-creekwatch-data | `data/` (ingest modules, `sites.json`, `score.py` + tests) |
| deploy | morpheus-creekwatch-deploy | ubox0 container, Caddy block, DNS, sigil and status registration, `deploy/` |
| story | nebula-creekwatch-story | `docs/` (README content, Devpost text, Alec's description outline, 3–5 min demo script, screenshots list) |
| gate | oracle (spawned by the lead) | read-only verification |

Integration: each lane opens a PR against `main` on GitHub (`jphein/creek-watch`, private until the lead does the first-push secret scan). The lead merges. Rebase only when the lead says so.

## Definition of done (per JP's rules)
Every report ends with **Changed / Checked / Evidence / Not verified**. "It compiles" is not a check: test against the running server, and for the UI, use a real phone-sized viewport (Playwright or headless Chromium screenshot at 390×844).
