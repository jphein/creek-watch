# Devpost submission: Creek Watch

> Staging copy for JP's one-click submit. Each `##` section maps to a Devpost field.
> Lines marked **⟨fill⟩** need a real value on Sunday. Nothing here is a guess presented as fact.
> Before pasting, check every **⟨fill⟩** and the [links](#links).

---

## Project name
Creek Watch

## Tagline (Devpost "elevator pitch", ≤200 chars)
Anyone at the creek files a 2-minute photo report; Creek Watch fuses it with live USGS, NWS and Open-Meteo data into an explainable creek-health score and early warning.

## Links
- **Live prototype:** https://creekwatch.realm.watch
- **Code (public, MIT):** https://github.com/jphein/creek-watch
- **Demo video (3–5 min):** ⟨fill: YouTube/Vimeo URL⟩

---

## Track alignment
**Primary: Track 2, Data-to-Insight.** Creek Watch turns citizen-collected stream observations into actionable insight. It plots reports on a map, gives each creek a dashboard card, and computes a 0–100 **creek-health score whose every input is explained in plain language** (which signal moved the score, by how much, and where the data came from). It gets fresher every time someone reports and every time the public gauge and weather feeds update.

**Also addresses:**
- **Track 1, Citizen Science UX:** a guided six-step report flow with big tap targets, picture icons and everyday words ("cloudy", "smells like sewage") instead of lab terminology. Location is filled from the phone, and the nearest monitoring spot is picked automatically.
- **Track 6, Resilience Informatics:** rule-based early-warning signals that combine citizen reports with environmental data. Heavy rain in the last 24 h plus brown-water reports raises a *runoff/sediment watch*. Heavy algae plus warm temperatures raises an *algal-bloom watch*. Any dead fish, or a chemical or sewage odour, raises an *alert*.

## Inspiration
Wolf Creek runs through downtown Grass Valley, and Deer Creek runs through downtown Nevada City, in California's Sierra foothills. Both pass parks, trails, streets and homes, and people walk beside them every day. Yet neither is monitored live where people are. **Wolf Creek has no real-time USGS stream gauge at all.** **Deer Creek's only real-time gauge (USGS 11418500, near Smartsville) is about 22 km downstream of Nevada City, below Lake Wildwood, whose regulation damps and delays what happens in town.** Those walkers see things an instrument can't: trash, algae, foam, an odd smell, a dead fish. But there's no simple way to record what they saw or to connect it with the stream-gauge and weather data that already exist. We wanted the people who notice first to become part of the early-warning system.

## What it does
- **Report (phone-first):** take or choose a photo, then answer six quick questions: water colour, algae, trash, flow, odour, and dead fish. An optional note and wildlife sighting can be added. GPS fills the location and the app picks the nearest named spot. Photos have their EXIF metadata stripped on the server, and the reporter's name is optional.
- **Map:** creek lines, named monitoring spots and recent-report pins coloured by health band. Tap a pin to see the photo and the report.
- **Dashboard:** one card per creek with the health score (0–100) and band (good, fair, watch or alert). Each signal comes with its explanation and source. The card also shows the latest USGS stream-gauge reading, current weather and 24-hour rainfall, recent reports, and a 7-day report sparkline.
- **Early warning:** the rules above raise a *watch* or an *alert*, each with a plain-language reason.
- **About the data:** every source with a link, how the score works, its limitations, privacy, and the One Health framing.

## What makes it different (and what doesn't)
Citizen creek reporting isn't new: IBM Research's 2010 *Creek Watch* app, whose name we honour, showed that a photo plus a few plain questions helps water managers ([CHI 2011](https://dl.acm.org/doi/10.1145/1978942.1979251)). OneAquaHealth's own app does guided assessments today. Creek Watch adds three things for two real creeks in California's Sierra foothills. It fuses each report with live USGS stream-gauge, National Weather Service and Open-Meteo rainfall data into a 0–100 score that explains every point it gives or takes. It runs simple, transparent early-warning rules. And it's honest about a real monitoring gap: Wolf Creek has no live stream gauge, and Deer Creek's only one is 22 km downstream, below a reservoir. Local groups (Wolf Creek Community Alliance and Sierra Streams Institute) have run trained, lab-grade monitoring here for about 20 years; Creek Watch is the everyday layer between their samples, not a replacement. Full landscape: [docs/devpost/PRIOR-ART.md](https://github.com/jphein/creek-watch/blob/main/docs/devpost/PRIOR-ART.md).

## Target users
- **Residents, walkers, students and volunteer creek groups:** the people already at the water, with no training needed.
- **Teachers:** a ready-made field activity that produces real data.
- **City and county staff, watershed groups and researchers:** an early, low-cost signal between scheduled samples, with photos for context. It doesn't replace lab monitoring.

## Impact on ecosystem and human health (One Health)
Creek health, wildlife health and human health are linked. Storm runoff carries sediment and street pollutants into the same water where fish and birds live and where children and dogs play. Algal blooms can harm wildlife, pets and people. Sewage or chemical odours point to contamination that matters to everyone downstream. Creek Watch makes these links visible at the neighbourhood scale:
- **Fills a real monitoring gap:** in town, these creeks have no live instrument (see Inspiration). Many casual observers can report between official samples, and each report carries a photo.
- **Explainable, not black-box:** every score change says why, so residents and officials can trust it and act on it.
- **Awareness and stewardship:** filing a report teaches people what a healthy creek looks like.

## How we built it
All code was written new for this hackathon on October 3–4, 2026, during the extended submission window (before the October 4, 9:00 pm PDT deadline).

- **Backend:** Python 3.12, FastAPI and SQLite, run with uv. One process serves the JSON API (`/api/*`) and the static web app. Photo uploads are re-encoded with Pillow (with HEIC support), which strips EXIF and caps the size. Enum validation, per-IP rate limiting and a geofence reject reports far from the creeks.
- **Frontend:** a no-build progressive web app in plain HTML, CSS and ES modules, with Leaflet and OpenStreetMap tiles. It is mobile-first and installable, with light and dark themes.
- **Data and score:** creek lines and 12 public access sites were built from OpenStreetMap (Overpass API). Each site was snapped to the open channel and checked for public access; road bridges with private banks are marked "view from the bridge only". Ingest modules pull USGS Water Services instantaneous values (discharge, gage height), National Weather Service observations and forecasts, and Open-Meteo hourly precipitation (rain in the past and next 24 h), all cached. A transparent, weighted, rule-based score combines them with recent citizen reports. Each signal records its name, value, weight, explanation and source. The score and ingest have 28 unit tests (20 for the score, 8 for ingest), and the API has 16 more. All 45 pass (`uv run pytest`, 2026-10-03).
- **Honest gauge mapping:** a USGS site-inventory query over the area returns only 4 active real-time stream gauges. Deer Creek uses 11418500, which is on Deer Creek but 22 km downstream and regulated. Wolf Creek has no live gauge (former station 11423150 holds only 3 water-quality samples), so Bear River near Wheatland (11424000) is shown as low-weight regional context only. The score says so in its explanations rather than pretending a distant gauge describes the creek in town.
- **Deploy:** a Docker container on a small always-on home server, behind Caddy with TLS and a Cloudflare tunnel, at https://creekwatch.realm.watch.
- **AI assistance:** the code and docs were written with AI coding assistants (Anthropic's Claude, via Claude Code) under human direction and review. The app itself uses **no AI** in the scoring: the score is deterministic rules, so every result can be explained.

## Data sources
| Source | What we use | Terms |
|---|---|---|
| **Citizen reports** (Creek Watch users) | Photos and observations | Submitted by users. EXIF stripped, names optional |
| **USGS Water Services** ([waterservices.usgs.gov](https://waterservices.usgs.gov/)) | Discharge (cfs) and gage height (ft), provisional. Deer Creek: [11418500](https://waterdata.usgs.gov/monitoring-location/11418500/) near Smartsville, about 22 km downstream and regulated by Lake Wildwood. Wolf Creek: no live gauge; Bear River near Wheatland [11424000](https://waterdata.usgs.gov/monitoring-location/11424000/) as low-weight regional context only | U.S. public domain ([USGS policy](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits)) |
| **National Weather Service API** ([api.weather.gov](https://www.weather.gov/documentation/services-web-api)) | Temperature, short forecast, chance of precipitation | Public domain ([NWS disclaimer](https://www.weather.gov/disclaimer)) |
| **Open-Meteo** ([open-meteo.com](https://open-meteo.com/)) | Rain in the past and next 24 h: gridded model estimates, not a rain gauge | [CC BY 4.0](https://open-meteo.com/en/terms); free API for non-commercial use, and this project is non-commercial |
| **OpenStreetMap** ([openstreetmap.org](https://www.openstreetmap.org/copyright)) | Base map tiles; creek lines and access sites (via Overpass API) | © OpenStreetMap contributors, ODbL. Attribution shown on the map |

Details and retrieval URLs: [`data/SOURCES.md`](https://github.com/jphein/creek-watch/blob/main/data/SOURCES.md).

## Challenges we ran into
- ⟨fill on Sunday from the real build log. Candidates: finding public stream gauges on or near two small creeks; making the score explainable instead of a black box; HEIC photos from iPhones; GPS accuracy beside a creek; keeping the report flow to about 2 minutes.⟩

## Accomplishments we're proud of
- Real field reports with photos from Wolf Creek and Deer Creek, filed on a phone at the creek on ⟨fill: date⟩ (⟨fill: N⟩ reports).
- A health score that explains every point it gives or takes away.
- A live, public, phone-usable prototype, not a mockup.

## What we learned
- ⟨fill: Alec, one or two lines in your own words; JP, one or two lines.⟩

## What's next for Creek Watch
- Partner with local creek volunteer groups to calibrate the score against their monitoring.
- Add more creeks, offline report queueing for spots with no signal, and SMS or email alerts.
- Spanish and other languages.
- Export reports in open, standard formats so other platforms (such as the OneAquaHealth hub tools) can use them.

## Team
- **Jeffrey "JP" Hein:** Sierra College student, full-stack developer, and founder of TechEMPOWER. Design and development.
- **Alec:** student. Field reports, project description, demo narration, and testing.

## Built with
`python` · `fastapi` · `sqlite` · `uv` · `pillow` · `javascript` · `html5` · `css3` · `leaflet` · `openstreetmap` · `usgs-water-services` · `national-weather-service-api` · `open-meteo` · `pwa` · `docker` · `caddy` · `cloudflare` · `claude-code`

---

**Pre-submit check for the person staging this:** every ⟨fill⟩ is resolved; the video link is public and 3:00–5:00 long; the repo is public; the live URL loads on a phone; and the RULES-CHECK.md open items are closed or accepted.
