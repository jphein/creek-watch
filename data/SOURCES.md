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
