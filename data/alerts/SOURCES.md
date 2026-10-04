# Alert sources: verification (Phase 1, Sat 2026-10-03, ~19:00 PDT)

Every source below was probed live from katana on 2026-10-03. "Fixture" is a real captured response in `data/alerts/fixtures/`. Region = Nevada County bbox 38.95–39.55 N, 121.30–120.00 W.

## Go / no-go

| # | Source | Verdict | Live data for our area today |
|---|---|---|---|
| 1 | NWS active alerts | **GO** | **Heat Advisory active now** at Deer Creek (zone CAZ131, county CAC057) |
| 2 | NOAA NWPS gauges | **GO (thin)** | 30 points in region; flood categories only at BRWC1 Bear R nr Wheatland and MRYC1 Yuba R abv Marysville (both `no_flooding`); DCSC1 Deer Ck nr Smartsville has none defined |
| 3 | USGS flow percentiles | **GO** (already ingested) | Deer 93 %, Bear 153 % of median |
| 4 | CA sewage spills (CIWQS SSS) | **GO** | 42 spills in region since 2023, incl. **Wolf Creek 2026-05-05 (850 gal to creek)**, **Deer Creek 2025-09-03 (50 gal)**, Peabody Ck 2025-06-18 (1,000 gal), Scotts Flat 2026-06-02 (392 gal), **Lake Wildwood 2025-11-20 (71,355 gal)** |
| 5a | CA freshwater HABs (FHABS bloom reports) | **GO** | Open **Caution** at Lake of the Pines (obs 2026-09-18) and Lake Zyac (2026-09-04); South Yuba River Caution 2026-08-30 (closed) |
| 5b | EPA CyAN (satellite) | **NO-GO for alerts** (context only) | Covers Scotts Flat (newest image 2026-01-17) and Englebright (2024-12-14); "not a lake / not available" at Rollins, Lake Wildwood, Lake of the Pines; no summer imagery |
| 6 | RiverDB E. coli (volunteer) | **GO (historical)** | No 2026 E. coli on our creeks in RiverDB. SSI Pioneer Park Site 13 last 2022-09-07; Site 12 hit 1,299.7 / 1,413.6 MPN (Jun/Jul 2021). SSI's 2026 DC 22/24/26 program is only a PNG → **link, don't scrape** |
| 7 | Creek Watch own rules | **GO** | 5 rules in `data/score.py` + new E. coli rule |
| 8a | Boil-water notices (SWRCB DDW) | **NO-GO (no feed)** | No notices dataset on data.ca.gov (searched "boil water", "drinking water notice", "do not drink") → link DDW page |
| 8b | Cal OES / OSPR spill reports | **NO-GO** | data.ca.gov OSPR "Oil Spill Incident Tracking" covers **2008 only** (3,237 rows, min/max date both 2008); no live Cal OES feed → link |
| 8c | OEHHA fish advisories | **GO (static)** | 10 advisories touching Nevada County, **incl. Deer Creek itself**, Rollins, Englebright, Lake Combie, Bear River, South Yuba |

## Details per source

### 1. NWS active alerts: GO
- **Endpoint:** `https://api.weather.gov/alerts/active?point={lat},{lon}` (per creek), or `?zone=CAZ131` / `?area=CA` and then a geo-filter. Zones from `/points/39.2603,-121.0335`: forecast zone **CAZ131**, county **CAC057**.
- **Auth:** none. Send a `User-Agent` with contact details (NWS asks for one).
- **Licence:** US Government work, public domain. Attribution: "National Weather Service".
- **Cadence:** real time. Poll every 5 minutes and respect `Cache-Control`.
- **Format:** GeoJSON features whose properties are CAP fields (`event`, `severity`, `urgency`, `certainty`, `onset`, `expires`, `headline`, `description`, `instruction`, `messageType` = Alert/Update/Cancel, `references`). The id is a stable `urn:oid`.
- **Geo-filter:** query per creek point (Wolf: 39.2081,−121.0696; Deer: 39.2603,−121.0335), or by zone.
- **Water-related events to keep:** Flood Warning/Watch/Advisory/Statement, Flash Flood *, Hydrologic Outlook, Heat Advisory, Excessive/Extreme Heat *, Red Flag Warning (fire runoff later), Winter Storm (snowmelt). Air Quality is dropped (not water).
- **Severity map:** CAP Extreme/Severe → alert, Moderate → watch, Minor → advisory, Unknown → info.
- **Today:** one active **Heat Advisory** at the Deer Creek point. CA-wide right now: 8 Extreme Heat Warnings, 6 Heat Advisories, 1 Air Quality Alert.
- **Fixture:** `nws_active_point.json`.

### 2. NOAA NWPS: GO (thin)
- **Endpoints:** `https://api.water.noaa.gov/nwps/v1/gauges?bbox.xmin=-121.6&bbox.ymin=38.9&bbox.xmax=-120.0&bbox.ymax=39.6&srid=EPSG_4326` and `/gauges/{lid}` (flood stages, observed and forecast category).
- **Auth:** none. **Licence:** NOAA, public domain. **Cadence:** observed data every 15–60 minutes; forecasts several times a day.
- **Useful points:**
  - **BRWC1** Bear R nr Wheatland. Flood stages: action 16 ft, minor 24, moderate 32.1, major 33.1. Now −0.28 ft, `no_flooding`.
  - **MRYC1** Yuba R abv Marysville.
  - Every other point near our creeks reports `not_defined`: DCSC1 Deer Ck, JNSC1 S Yuba at Jones Bar.
- **Alert rule:** emit when `status.observed.floodCategory` or `status.forecast.floodCategory` ∈ {action, minor, moderate, major}.
- **Fixtures:** `nwps_gauges_region.json`, `nwps_gauge_BRWC1.json`.

### 4. CA sanitary sewer system spills (CIWQS): GO
- **Endpoint:** `https://www.waterboards.ca.gov/water_issues/programs/sso/docs/data_files/Cat1-2-3-Spills.txt`. Tab-separated, UTF-8, about 10.8 MB, 3,631 rows statewide, spills reported since 2023-06-05 under the new General Order. **Last-Modified: Sat, 03 Oct 2026 13:01:40 GMT**, i.e. regenerated daily.
- **Auth:** none. **Licence:** California State Water Resources Control Board public data. Enrollees self-report the spills, and the data is not independently verified. Attribution: "State Water Resources Control Board, CIWQS Sanitary Sewer System spills".
- **Cadence:** daily file. Poll once or twice a day with `If-Modified-Since`, never more often.
- **Geo-filter:** there's no county column, so filter by `LATITUDE`/`LONGITUDE` in the bbox, then match to a creek by distance to its line or by `NAME_OF_RECEIVING_WATER_BODY(S)`.
- **Alert rule:**
  - Category 1 (reached surface water), started within the last 30 days: **alert** if within 2 km of our creeks; otherwise **watch** if in the region.
  - Category 2/3: advisory.
  - "Monthly Category 4" rows are summary counts, not single events, so they're ignored.
- **Caveat:** reports are certified after the fact, so this source lags. It is good for "recent spill" alerts, not real-time ones.
- **Fixture:** `sso_spills_region.tsv`, trimmed to 16 non-personal columns (`CERTIFIED_BY` and the narratives are dropped).

### 5a. CA freshwater harmful algal blooms (FHABS): GO
- **Endpoint:** the data.ca.gov CKAN datastore. Resource **FHABS BLOOM REPORTS** `c6a36b91-ad38-4611-8750-87ee99e497dd`; SQL via `https://data.ca.gov/api/3/action/datastore_search_sql?sql=…`.
- **Auth:** none. **Licence:** "Other (Public Domain)", State Water Board. **Cadence:** dataset modified 2026-10-02, about daily.
- **Fields used:** `Bloom_Report_ID`, `Observation_Date`, `Water_Body_Name`, `Bloom_Latitude`, `Bloom_Longitude`, `Reported_Advisory_Types` (Caution / Warning / Danger / Algal mat alert sign / General awareness), `Case_Status` (Open/Closed), `AdvisoryStartDate`/`AdvisoryEndDate`.
- **Geo-filter:** use the bbox on lat/lon. **Don't** filter on `County ILIKE 'Nevada'`: that also matched Lake Havasu, whose `County` field holds the *state* of Nevada.
- **Severity map:** Danger → alert, Warning → watch, Caution or algal mat → advisory, General awareness → info. Only `Case_Status = Open` counts as active.
- **Portal link for every alert:** https://mywaterquality.ca.gov/habs/where/freshwater_events.html
- **Fixture:** `fhabs_nevada.json`.

### 5b. EPA CyAN: NO-GO for alerts
- **Endpoint:** `https://cyan.epa.gov/cyan/cyano/location/data/{lat}/{lon}/all`. No auth; US EPA, public domain.
- Satellite pixels are 300 m, so only Scotts Flat (12 images, newest 2026-01-17) and Englebright (6 images, newest 2024-12-14) resolve. Imagery is sparse and has no 2026 summer coverage. It could appear as a "satellite context" line, but never as an alert.
- **Fixtures:** `cyan_scotts_flat.json`, `cyan_not_covered.json`.

### 6. RiverDB volunteer E. coli: GO (historical), link SSI
- Already ingested (`data/wq.py`; GraphQL `gql.riverdb.org/graphql`). Its E. coli comes from SSI Sites 11/12/13 (to 2021–2023). SYRCL stations don't measure E. coli.
- **Rule:** a recent sample (≤ 60 days) above **320 MPN/100 mL** → a "bacteria" alert citing the group and the date. On today's data it fires on **nothing**, which is correct; nothing is invented.
- SSI's 2026 Pioneer Park monitoring (DC 22/24/26) exists only as an image on https://sierrastreamsinstitute.org/pioneer-park-monitoring-status/. The deer-pioneer-park site gets a static **info** link to that page; no values are copied.

### 8a. Boil-water / do-not-drink notices: NO-GO
- No statewide notices dataset or API exists. Link https://www.waterboards.ca.gov/drinking_water/ and the local water suppliers (Nevada Irrigation District, Grass Valley, Nevada City) as static resources.

### 8b. Cal OES spill reports / OSPR: NO-GO
- data.ca.gov `oil-spill-incident-tracking-ds3941` holds **2008 only**. Cal OES's hazardous-materials spill reports have no public machine feed. Link https://www.caloes.ca.gov/ (spill reporting: 1-800-852-7550).

### 8c. OEHHA fish consumption advisories: GO (static)
- **Endpoint:** data.ca.gov resource `7805faef-ed21-43e9-a13e-4920a9440bb8` (Fish Consumption Advisories). Fields: `Advisory`, `County`, `Link`, `Latitude`, `Longitude`. **Licence:** public domain (OEHHA). **Cadence:** modified 2026-05-27, a few times a year.
- **Nevada County (10):** Deer Creek, Rollins Reservoir, Englebright Lake, Lake Combie, Bear River, Camp Far West Reservoir, South Yuba River, Yuba/N/M Yuba River, Donner Lake, Lake Spaulding.
- These are standing advisories, not events, so they become **info** alerts with `expires: null`, each linking its OEHHA page. Most are probably mercury advisories from the Gold Rush legacy, but **the page contents weren't read**; the text must come from the OEHHA link, not from us.
- **Fixture:** `oehha_fish_advisories_nevada.json`.

## Not verified
- FHABS licence wording beyond the CKAN "Other (Public Domain)" tag (the disclaimer PDF wasn't read).
- The reasons behind the OEHHA advisories (the pages weren't opened).
- The NWS `User-Agent` policy wasn't re-read; our UA includes a contact URL.
