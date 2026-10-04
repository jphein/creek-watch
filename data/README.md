# About the data

Creek Watch combines two kinds of information: **what people see at the creek** and **free public data** about water and weather. It turns them into a creek-health score from 0 to 100 that you can check by hand. There's no black box: every point the score loses is listed with the reason.

## Where the data comes from

| What | Source | How fresh | Notes |
|---|---|---|---|
| Citizen reports (water color, algae, trash, flow, smell, dead fish, photo) | People using Creek Watch at the creek | Live | Names are optional. The server strips GPS and other EXIF metadata from photos. |
| Stream flow and water level | [USGS Water Data](https://waterdata.usgs.gov/) gauges (the new Water Data API, falling back to legacy WaterServices) | Every 15 to 60 min (USGS updates hourly); we cache for 15 min | Values are *provisional* until USGS reviews them. |
| "Normal" flow for today's date | USGS daily statistics (25th, 50th and 75th percentile of all years on record) | Fixed snapshot (`flow_stats.json`) | 90 years for Deer Creek and 60 for the Bear River, so it changes very little year to year. |
| Air temperature and current conditions | [National Weather Service](https://www.weather.gov/) station KGOO, Nevada County Air Park | About hourly; cached 15 min | The station sits between the two towns, about 4 to 6 km from each creek. |
| Short forecast | NWS gridpoint forecast for each creek | A few times a day | |
| Rain in the last 24 h and the next 24 h | [Open-Meteo](https://open-meteo.com/) hourly precipitation | Hourly; cached 15 min | Open-Meteo is a gridded weather model, not a rain gauge. Thunderstorms can be missed or misplaced. |
| Volunteer water tests (dissolved oxygen, pH, temperature, turbidity, conductivity, E. coli) | Local monitoring groups via [RiverDB](https://riverdb.org): **South Yuba River Citizens League** (Deer Creek above and below Nevada City, monthly, 2022 to now), **Sierra Streams Institute** (Deer Creek, 2000–2023), **Wolf Creek Community Alliance** (Wolf Creek, 2017–2019) | SYRCL: fetched live, cached 24 h. SSI/WCCA: committed snapshot (`wq_snapshot.json`) | The groups' own data, credited on every reading. Volunteers sample monthly or quarterly, so this is the newest *test*, not a live sensor. |
| Creek lines and sites | [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors (ODbL) | Built once (`tools/build_sites.py`) | See `SOURCES.md` for the right-creek check and how each site was chosen. |

### Which gauge belongs to which creek (honestly)

- **Deer Creek** has a real USGS gauge on the creek, **11418500 "Deer Creek near Smartsville"**. It is about 22 km downstream of Nevada City, below Lake Wildwood, so a muddy pulse in town reaches it late and diluted.
- **Wolf Creek has no live stream gauge.** The closest one is the **Bear River near Wheatland (11424000)**, about 38 km away, downstream of where Wolf Creek joins the Bear River and below a reservoir. We show it as *regional context*, and it counts for only a quarter of a normal flow signal in the Wolf Creek score. This is one of the reasons citizen reports matter so much here: on Wolf Creek, people are the only real-time sensor.

## How the score works

Start at **100**. Each signal below can subtract points. The score is `100 + the sum of the signal weights`, kept between 0 and 100. Every signal the API returns carries its `value`, its `weight` (the points it moved the score), a plain-language `explanation` and its `source`.

### Public-data signals (always present)

| Signal | Rule | Points |
|---|---|---|
| Rain in the last 24 h | ≥ 1.0 in / ≥ 0.5 in / ≥ 0.1 in | −15 / −10 / −4 |
| Air temperature (a stand-in for water temperature) | ≥ 90 °F / ≥ 80 °F | −8 / −4 |
| Stream flow compared with the long-term median for today's date | ≥ 300 % / ≥ 150 % / < 50 % / < 25 % | −10 / −3 / −3 / −6 |
| | A gauge that isn't on the creek (Wolf Creek's case) counts ¼ | |
| Report coverage | 0 reports this week / 1–2 reports | −10 / −5 |
| Latest volunteer water test on the creek | DO < 5 mg/L / < 7 mg/L (the cold-water standard) | −15 / −6 |
| | pH outside 6.5–8.5 (Basin Plan objective) | −5 |
| | E. coli > 320 MPN/100 mL (California's recreational threshold) | −12 |
| | water > 20 °C (stress for trout) / turbidity > 10 NTU / > 25 NTU | −5 / −4 / −8 |
| | A test 2–6 months old counts half; anything older is shown but not counted | |

**About the volunteer water tests:** these are real measurements of the water, the closest thing to a lab result the app has. But they're taken monthly at best. Today the newest Deer Creek test is SYRCL's from 8 August 2026. The newest *published* Wolf Creek test is from December 2019, so it's shown as background only and doesn't count. The thresholds come from the Central Valley Water Board's Basin Plan (dissolved oxygen of at least 7 mg/L for cold-water habitat, and pH 6.5–8.5) and from California's statewide bacteria objective (E. coli 320 per 100 mL). The temperature and turbidity limits are rules of thumb, labelled as such.

**Why report coverage costs points:** public data can't see trash, algae, dead fish or a sewage smell. A creek nobody has looked at this week shouldn't score a perfect 100, so we hold back 10 points until someone reports.

### Citizen-report signals (last 7 days)

Newer reports count more: a report's weight halves every 3 days. Each condition subtracts *up to* its maximum, in proportion to the weighted share of recent reports that show it. If every recent report shows it, the full amount comes off. If one report in four shows it, about a quarter comes off.

| Condition reported | Max points | Why it matters |
|---|---|---|
| Dead fish | −40 | Something stressed or poisoned them: low oxygen, heat, or a spill. |
| Sewage or chemical smell | −30 | A leak, spill or illegal discharge, which is a risk to people and pets too. |
| Brown water | −15 | Soil and the pollutants that ride on it. Sediment smothers spawning gravel. |
| Lots of algae | −15 | Uses up oxygen at night. Some blooms are toxic to dogs. |
| Green water | −10 | A sign of algae feeding on extra nutrients. |
| Lots of trash | −10 | Harms wildlife and signals runoff from streets or camps. |
| Flood flow | −10 | Scours the banks and flushes runoff into the creek. |
| Rotten-egg smell | −10 | Can be natural decay, but it often comes with low oxygen. |
| Dry or nearly dry bed | −8 | Strands fish and insects. Common in late summer, but still stressful. |
| Cloudy water | −6 | A mild sediment or algae signal. |
| Some algae | −5 | Normal in summer, so a small deduction. |
| Some trash | −4 | |

If a reporter picked up the trash they saw, the trash still counts (it shows litter and runoff are reaching the creek), but the explanation credits the cleanup and how many bags were filled.

### Bands

| Score | Band |
|---|---|
| 80–100 | **good** |
| 60–79 | **fair** |
| 40–59 | **watch** |
| 0–39 | **alert** |

### Early warnings (these can override the band)

| Warning | Trigger | Effect |
|---|---|---|
| **Possible contamination** | Any report of dead fish or a sewage/chemical smell in the last 3 days | Band forced to **alert**, score capped at 39 |
| Recent contamination report | Dead fish or a sewage/chemical smell reported 3 to 7 days ago | At least **watch** |
| **Runoff / sediment watch** | ≥ 0.5 in of rain in the last 24 h **and** a report of brown or cloudy water in the last 48 h | At least **watch** |
| **Algal bloom watch** | A report of lots of algae or green water this week **and** air temperature ≥ 80 °F | At least **watch** |
| Heavy rain forecast | ≥ 0.5 in of rain forecast in the next 24 h | Advisory only; the score is unchanged |
| **E. coli above the recreational threshold** | Any volunteer test on the creek in the last 60 days with E. coli > 320 MPN/100 mL (California's recreational statistical threshold value, not a single-sample limit) | **watch** for 14 days after the test, then **advisory** to day 60; names the group and the test date |

When a warning forces a band, the score is capped at the top of that band. A creek can't show "alert" next to a score of 85. The cap is listed as its own signal, `early_warning_cap`.

### Confidence

- **low**: no reports this week (public data only).
- **medium**: 1 to 5 reports.
- **high**: 6 or more reports with weather data available.

## Limitations: read these before trusting a number

- **This is a screening tool, not a lab test.** The only measured chemistry comes from volunteer tests taken monthly at best (weeks old on Deer Creek, years old on Wolf Creek). Nothing measures toxins. A "good" score does **not** mean the water is safe to drink or swim in.
- **The weights are expert-informed judgment calls, not fitted to data.** They are written down above so anyone can argue with them. We would love a local biologist to tune them.
- **Air temperature stands in for water temperature.** Shaded pools stay much cooler than the air.
- **The gauges are far from town** (22 km for Deer Creek; none at all on Wolf Creek). A storm pulse in Grass Valley or Nevada City won't show up in the flow signal for hours, if at all.
- **The rain figures are model estimates** (Open-Meteo), not a rain gauge in town.
- **Citizen observations are subjective.** "Cloudy" and "brown" mean different things to different people, and one mistaken report can swing a creek with few reports. That's why the score holds back points when there are few reports and weights recent reports more.
- **Late summer and fall are naturally low-flow** on these foothill creeks. A low or dry reading in September or October can be normal. The flow signal compares against the median *for that date*, which helps but doesn't fully remove this.
- **Upstream reservoirs** (Scotts Flat and Lake Wildwood on Deer Creek, Camp Far West on the Bear River) regulate flow, so the gauges partly reflect dam operations rather than nature.

## Other data we found

- **Wolf Creek Community Alliance (WCCA)** ([wolfcreekalliance.org](https://wolfcreekalliance.org/programs/)) has run volunteer monitoring on Wolf Creek and its tributaries for almost twenty years. WCCA reports that Wolf Creek and its tributary French Ravine are listed as Clean Water Act "impaired waters" for fecal bacteria. Its 2017–2019 results are in RiverDB, and Creek Watch shows them as background. In April 2026 WCCA registered about 40 of its sites on the Stroud Water Research Center's [Monitor My Watershed](https://monitormywatershed.org/browse/), but no readings have been posted there yet. When they are, Wolf Creek gets current water-test data.
- **Sierra Streams Institute** (founded in 1995 as *Friends of Deer Creek*) sampled 19 Deer Creek sites from 2000 to 2023 for nutrients, E. coli, dissolved oxygen, pH and more. The latest sample per site is in the snapshot.
- **USGS historical water-quality samples** from studies of mercury and Gold Rush mining legacy exist on both creeks. They are not real-time, so they are not used.
- **CEDEN / California Water Boards** host statewide data. We haven't queried it yet.

## Update cadence

| Data | How often it updates |
|---|---|
| Weather, rain and gauge readings | Fetched on demand, cached for 15 minutes |
| A served stale value | Flagged `"stale": true` (we serve the last good value when a source is down) |
| The score | Recomputed on every `/api/health` request |
| Volunteer water tests | SYRCL live (cached 24 h). SSI and WCCA from a snapshot (`python3 -m data.tools.build_wq_snapshot`) |
| Flow medians and creek lines | Static files, rebuilt by hand with the scripts in `tools/` |
