# Creek Watch

**Citizen creek reports plus public data, turned into an explainable creek-health score and early warning.**
Built for Wolf Creek (Grass Valley, CA) and Deer Creek (Nevada City, CA) for the [IEEE OneAquaHealth Global Hackathon 2026](https://oneaquahealth-ieee-hackathon.devpost.com/).

**Live:** https://creekwatch.realm.watch
**Tracks:** primary Track 2 (Data-to-Insight); also Track 1 (Citizen Science UX) and Track 6 (Resilience Informatics).

<!-- SCREENSHOT PLACEHOLDER: once docs/screenshots/01-hero-dashboard.png exists (shot list: docs/devpost/SCREENSHOTS.md), replace this comment with:
![Creek Watch dashboard](docs/screenshots/01-hero-dashboard.png) -->

## What it does

- **Report:** anyone at the creek takes a photo and answers six quick, plain-language questions on their phone: water colour, algae, trash, flow, odour and dead fish. Location fills in from GPS, and the nearest spot is picked automatically.
- **Map:** creek lines, named monitoring spots and recent reports, coloured by health band.
- **Dashboard:** a 0–100 health score per creek. **Every signal explains why it moved the score**, and the card shows the latest USGS gauge and NWS weather.
- **Early warning:** rule-based *watch* and *alert* signals. Examples: heavy rain plus brown water means a runoff watch; lots of algae plus warm weather means an algal-bloom watch; dead fish or a chemical or sewage odour means an alert.
- **Privacy:** photos have EXIF metadata (including GPS) stripped on upload; reporter names are optional.

## Run it locally

You need Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/jphein/creek-watch.git
cd creek-watch
uv sync
uv run uvicorn creekwatch.asgi:app --app-dir backend --reload --port 8000
# open http://localhost:8000
```

Run the tests:

```bash
uv run pytest
```

With Docker:

```bash
docker compose up --build
```

The SQLite database (`data/creekwatch.db`) and photo uploads (`uploads/`) are created locally and are git-ignored.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/creeks` | Creeks and their named sites |
| `POST /api/reports` | File a report (multipart, with photo) |
| `GET /api/reports?creek_id=&since=&limit=` | Recent reports, newest first |
| `GET /api/reports/{id}` | One report |
| `GET /api/conditions?creek_id=` | Latest USGS gauge and NWS weather |
| `GET /api/health?creek_id=` | Health score, band and explained signals |
| `GET /api/version` | Build info |
| `GET /healthz` | Liveness |

Full contract: [docs/SPEC.md](docs/SPEC.md).

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
| [USGS Water Services](https://waterservices.usgs.gov/) | Stream discharge and gage height | [U.S. public domain](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits) |
| [National Weather Service API](https://www.weather.gov/documentation/services-web-api) | Temperature, rainfall, forecast | [Public domain](https://www.weather.gov/disclaimer); no endorsement implied |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) | Base map | © OpenStreetMap contributors, [ODbL](https://opendatacommons.org/licenses/odbl/) |

Creek Watch is not affiliated with or endorsed by USGS, NOAA/NWS or OpenStreetMap.

**Limitations:** the score is a screening signal built from casual observations and nearby public data. It is not a lab water-quality test and does not tell you whether the water is safe to drink or swim in.

## Team

- **Jeffrey "JP" Hein:** Sierra College student, full-stack developer, founder of TechEMPOWER. Design and development.
- **Alec:** student. Field reports, writing, demo narration and testing.

Built with AI coding assistance (Claude Code) under human direction and review. The health score itself uses deterministic, explainable rules, not AI.

## License

[MIT](LICENSE) © 2026 Jeffrey Hein and Creek Watch contributors.
