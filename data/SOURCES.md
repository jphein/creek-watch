# Data sources

Everything here is public and keyless. Retrieved 2026-10-03 unless noted.

## Creek lines and sites: OpenStreetMap
- Creek geometry in `creeks.geojson` comes from OSM `waterway=stream` ways named "Wolf Creek", "Deer Creek" and "Little Deer Creek", fetched through the Overpass API (`https://overpass-api.de/api/interpreter`). © OpenStreetMap contributors, [ODbL](https://www.openstreetmap.org/copyright).
- **Right-creek check:** California has several Wolf Creeks and Deer Creeks. The build script keeps only the connected set of ways that passes within 0.5 km of the town centre. The actual values are 0.13 km for Wolf Creek in Grass Valley and 0.05 km for Deer Creek in Nevada City. Wolf Creek is about 32 km of mapped line, from Loma Rica to the Bear River near Wolf. Deer Creek is about 43 km, from above Scotts Flat to past Lake Wildwood.
- **Sites** in `sites.json` were hand-picked from named public OSM features (trail bridges, parks and public road bridges) within 120 m of the creek. Each one was then snapped onto the open creek channel, and `snap_moved_m` records how far the snap moved it. Every site has an `osm_ref` link. Culverted stretches are excluded from snapping: Wolf Creek runs underground beneath downtown Grass Valley (OSM way 1085194147), so the downtown site sits at the culvert outlet.
- Two notes on the SPEC's seed list:
  - **Pioneer Park (Nevada City) is on Little Deer Creek**, a tributary that joins Deer Creek about 0.6 km downstream at Calanan Park. It is still included, flagged `on_main_stem: false`.
  - **Memorial Park (Grass Valley) is about 0.56 km from Wolf Creek's channel** (park centroid 39.2141, −121.0553), so it was not used.
- Several sites are public road bridges with private land on both banks (`access` says so). Observe from the bridge only.
- Rebuild: `python3 data/tools/build_sites.py` (standard library only).

## Stream gauges: USGS Water Services (NWIS)
- Instantaneous values: `https://waterservices.usgs.gov/nwis/iv/?format=json&sites=<site>&parameterCd=00060,00065` (discharge in cfs, gage height in ft). Values are provisional ("P").
- Site inventory query: `https://waterservices.usgs.gov/nwis/site/?bBox=-121.60,39.00,-120.70,39.50&siteType=ST&hasDataTypeCd=iv&siteStatus=active`. It returns only 4 active real-time stream gauges in that box: 11418500, 11421000, 11424000 and 11424500.
- **Deer Creek → 11418500 "DEER C NR SMARTSVILLE CA"** (39.2243, −121.2685). This gauge **is on Deer Creek itself**, but it is about 22 km in a straight line west (downstream) of downtown Nevada City and about 4.6 km below the Lake Wildwood site. Lake Wildwood and Scotts Flat regulate the flow, so the reading lags and damps what happens in town.
- **Wolf Creek → no live gauge exists.** The former USGS station 11423150 "WOLF C NR WOLF CA" holds only 3 water-quality samples (2002–2015) and no real-time data. The nearest live gauge downstream is **11424000 "BEAR R NR WHEATLAND CA"** (39.0002, −121.4066). It is on the Bear River, about 24 km (straight line) below Wolf Creek's mouth and 38 km from downtown Grass Valley, below Camp Far West Reservoir. It is a **regional context signal only**: it says nothing reliable about Wolf Creek in Grass Valley, and the score gives it a low weight.
- Historical USGS water-quality sample sites on these creeks (no real-time data; mostly from the USGS mercury/mining-legacy studies). They are useful for the story but not for the live score:
  - Wolf Creek: 391231121041001 "WOLF C A GRASS VALLEY", 390955121034101 "WOLF C NR LA BARR MEADOWS", 11423150.
  - Deer Creek: 391533121021601 "DEER C A NEVADA CITY", 391518121025801 "DEER C A STOCKING FLAT", 391440121080801 "DEER C BL DEER C FALLS", and others.

## Weather: NWS and Open-Meteo
- NWS latest observation: `https://api.weather.gov/stations/KGOO/observations/latest`. KGOO is Nevada County Air Park (39.2240, −121.0031), the first station that `/gridpoints/STO/61,93/stations` (Grass Valley) and `/gridpoints/STO/63,95/stations` (Nevada City) list. Its precipitation fields came back null in testing, so we don't use them for rain.
- NWS forecast: `https://api.weather.gov/gridpoints/STO/61,93/forecast` (Wolf Creek) and `https://api.weather.gov/gridpoints/STO/63,95/forecast` (Deer Creek), resolved through `/points/{lat},{lon}`.
- Rain over the past and next 24 h: Open-Meteo `https://api.open-meteo.com/v1/forecast?hourly=precipitation&past_days=2&forecast_days=2`. This is keyless, gridded model data (not a rain gauge).

## USGS reliability note (2026-10-03)
- Legacy `waterservices.usgs.gov` returned intermittent HTTP 503 errors during testing (the same URL alternated between 200 and 503). It was also slow (0.6–7.6 s per call, against about 0.25 s for the new API). So `ingest.fetch_gauge` now uses the new USGS Water Data OGC API first and falls back to legacy NWIS: `https://api.waterdata.usgs.gov/ogcapi/v0/collections/latest-continuous/items?monitoring_location_id=USGS-<site>&parameter_code=00060,00065`. The new API returned identical values (4.84 cfs and 2.50 ft at 2026-10-04T00:00Z for 11418500).
- The daily flow percentiles come from the stat service and are committed as `flow_stats.json` (all 366 days for both gauges). That way the score doesn't depend on that endpoint's uptime.

## Volunteer water-quality monitoring: RiverDB (ingested)
- RiverDB (riverdb.org) is the public data portal used by SYRCL, Sierra Streams Institute and Wolf Creek Community Alliance. Its site loads data from a keyless GraphQL endpoint, `https://gql.riverdb.org/graphql`. We use the same `stations(agency:)` and `sitevisits(stationRef:)` queries the site's own pages use, and only for projects the groups flagged `Public` (SYRCL_WQ, SSI_1 "Deer Creek"; WCCA_1 "Monthly Water Quality").
- Stations used (ids are RiverDB station refs):
  - SYRCL "Deer Creek Below Nevada City" (17592187179149) and "Deer Creek Above Nevada City" (17592187179145): 41 visits each, 2022-03 → 2026-08.
  - SSI Sites 4, 17, 13, 5 and 7 on Deer Creek: about 250 visits each, 2000 → 2022/23.
  - WCCA Sites 2, 5, 8, 8.5, 9.2 and 15 on Wolf Creek: about 25 visits each, 2017 → 2019-12.
- No license or terms statement was found on RiverDB. We treat the data as the groups' own: we read it, credit it on every reading, cache SYRCL for 24 h, and commit only the latest sample per station (`wq_snapshot.json`), never the history. If a group asks, we remove it.
- Thresholds: DO ≥ 7.0 mg/L and pH 6.5–8.5 (Central Valley RWQCB Basin Plan, COLD beneficial use), and E. coli 320 per 100 mL (State Water Board bacteria objective, REC-1 statistical threshold value). 20 °C water and 10/25 NTU turbidity are rules of thumb.

## Stroud Water Research Center / Monitor My Watershed (checked, not ingested)
- monitormywatershed.org/browse lists 40 sites within 40 km of the creeks, all of them WCCA's Wolf Creek watershed stations, registered 2026-04-14 (e.g. "Glen Jones Park (WCCA Site 8)": pH, temperature and turbidity sensors configured). Every one shows "Last observation: –", so there is no data yet. When readings appear they can be downloaded as CSV per sensor, which makes this the likely future source of current Wolf Creek water tests.
- Model My Watershed / WikiWatershed modelling tools: not used (they model land use and runoff; they don't observe it).

## Community monitoring groups
- Wolf Creek Community Alliance: https://wolfcreekalliance.org/programs/
- Sierra Streams Institute (formerly Friends of Deer Creek): https://sierrastreamsinstitute.org/
- South Yuba River Citizens League: https://yubariver.org

## Official bacteria history: CEDEN (2024 Regional Board study)
- **Source:** CEDEN data published on the California open data portal as *Surface Water – Fecal Indicator Bacteria Monitoring Results, 2020 to present*, resource `15a63495-8d9f-4a49-b43a-3092ef3106b9` (https://data.ca.gov/dataset/surface-water-fecal-indicator-bacteria-results). Queried through keyless CKAN `datastore_search_sql`. The dataset was modified 2026-10-02.
- **Licence:** not specified. The portal lists no licence for this dataset; it's State Water Board public data. **Credit:** "Central Valley Regional Water Quality Control Board via CEDEN".
- **Study:** project "RWB5 Microbial Source Tracking Wolf Cr Study 2024", sampled 2024-05-22 to 2024-09-04 (13 weekly E. coli samples per site). Method SM 9223 B, results in MPN/100 mL.
- **Mapped stations** (distance to our site):
  - `516NEV109` "Wolf Creek at the North Star Mining Museum" (39.207851, −121.06952) → `wolf-glen-jones-park` (13.7 m);
  - `516NEV101` "Wolf Creek at Wolf Road" (39.05216, −121.10846) → `wolf-wolf-rd` (4.8 m).
  The study also sampled 7 other Wolf Creek watershed sites, which aren't mapped to our sites.
- **E. coli only:** the builder keeps rows whose `Analyte` is exactly "E. coli". Total coliform rows (same samples) are dropped.
- **State objective used for comparison:** State Water Resources Control Board, *2019 ISWEBE Bacteria Provisions* (https://www.waterboards.ca.gov/plans_policies/docs/bacteria.pdf). For fresh water: "a six-week rolling geometric mean of E. coli not to exceed 100 cfu/100 mL, calculated weekly, and a statistical threshold value (STV) of 320 cfu/100 mL not to be exceeded by more than 10 percent of the samples collected in a calendar month".
  - The study reports MPN/100 mL while the objective is written in cfu/100 mL. These are commonly treated as comparable, not identical.
  - CEDEN's own `6WeekGeoMean`/`6WeekCount` columns are used, and a 6-week mean is only called "above the objective" when it rests on **at least 5 samples**.
- **Result:**
  - **Wolf Road:** the 6-week geometric mean was above 100 in 4 weekly calculations (2024-07-17 to 2024-08-07; highest qualified 119.3). One sample exceeded 320 (648.8 on 2024-05-22).
  - **North Star Museum:** the qualified 6-week geometric mean stayed ≤ 41. One sample exceeded 320 (770.1 on 2024-07-31).
- **Presentation rule:** this is dated history ("2024 Regional Board study", `is_current: false`). It is **never** shown as current conditions and **never** feeds the health score.
- **Rebuild:** `python3 -m data.tools.build_ceden_history`.
## Regional river flow and reservoir storage: CDEC (DWR)
- **Endpoint:** `https://cdec.water.ca.gov/dynamicapp/req/JSONDataServlet?Stations=JBR,ENG&SensorNums=1,6,15,20&dur_code=H&Start=…&End=…`. Keyless JSON. **Credit:** California Department of Water Resources, CDEC.
- **Stations:**
  - **JBR**, South Yuba River at Jones Bar: flow (sensor 20, cfs) and stage (sensor 1, ft). Below the Hwy 49 / Purdon / Edwards Crossing swim holes.
  - **ENG**, Englebright Lake: storage (sensor 15, acre-feet) and elevation (sensor 6, ft).
  - **DCS** (Deer Creek nr Smartsville) is deliberately not used: it mirrors USGS 11418500, which we read directly.
- **Times:** CDEC's station pages label hourly times "DATE / TIME PDT", i.e. California local time. We convert from America/Los_Angeles to UTC.
- **Freshness:** hourly, but CDEC's own lag varies. At 20:41 PDT on 2026-10-03 the newest JBR value was 09:00 PDT; at 20:51 PDT it was 19:00 PDT. So every value carries `observed_at` and `age_hours`, and the UI must show the observation time.
- **Exposure:** `conditions["river"]` (regional, the same for both creeks). Cached 15 min, with the shared failure backoff. Missing values (−9999) are skipped. The module never raises.
