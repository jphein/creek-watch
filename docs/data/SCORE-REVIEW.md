# Creek Watch score: weights for a biologist's review

Creek Watch gives Wolf Creek (Grass Valley) and Deer Creek (Nevada City) a health score from 0 to 100. It's built from what people report at the creek plus free public data. Every number below was picked by a software engineer, not a biologist. We'd be grateful for a red pen. Short answers in the margin are perfect.

**How it works in one line:** start at 100, subtract the points below, keep the result between 0 and 100. Bands: 80+ **good**, 60–79 **fair**, 40–59 **watch**, under 40 **alert**. Live now at https://creekwatch.realm.watch.

## 1. What people report at the creek (last 7 days)

A report's weight halves every 3 days. Each condition subtracts *up to* its maximum, in proportion to the share of recent reports that show it.

| Reported | Max pts | Our reasoning | Question for you |
|---|---|---|---|
| Dead fish | −40 | Stress or poisoning: low oxygen, heat, a spill | One dead fish versus many: should a count matter? Are there seasons when a few are normal? |
| Sewage or chemical smell | −30 | A leak, spill or illegal discharge | Can a layperson tell these apart from natural smells? |
| Rotten-egg smell | −10 | Natural decay, but often comes with low oxygen | Too high, too low, or should we drop it? |
| Brown water | −15 | Sediment smothers spawning gravel and carries pollutants | Is turbidity worse for these creeks in some months than others? |
| Lots of algae | −15 | Uses up oxygen at night; some blooms are toxic to dogs | Can volunteers tell harmless filamentous algae from cyanobacteria? Should we ask? |
| Green water | −10 | Algae feeding on extra nutrients | |
| Cloudy water | −6 | A mild sediment or algae signal | |
| Some algae | −5 | Normal in summer | Should this be 0 from June to October? |
| Lots / some trash | −10 / −4 | Harms wildlife; signals street runoff | Does trash belong in a *health* score at all? |
| Flood flow | −10 | Scours the banks and flushes runoff | |
| Dry or nearly dry bed | −8 | Strands fish and insects | On Wolf and Deer Creek in late summer, is "dry" normal (should it be 0) or a real warning? |

**Missing items?** Our report form asks only about color, algae, trash, flow, smell, dead fish and "wildlife seen". What 1–3 things should a non-expert check that we left out? Foam, oily sheen, macroinvertebrates under rocks, crayfish, frogs?

## 2. Public data (always counted)

| Signal | Rule | Pts | Question for you |
|---|---|---|---|
| Rain in the last 24 h (Open-Meteo estimate) | ≥ 1.0 / ≥ 0.5 / ≥ 0.1 in | −15 / −10 / −4 | Is the first fall storm (first flush) worse than later ones? Should we weight it more? |
| Air temperature (no water thermometer; a stand-in) | ≥ 90 °F / ≥ 80 °F | −8 / −4 | How well does air temperature track water temperature in shaded reaches here? |
| Flow vs the USGS median for this date | ≥ 300 % / ≥ 150 % / < 50 % / < 25 % | −10 / −3 / −3 / −6 | Deer Creek's gauge is 22 km downstream below Lake Wildwood, and Wolf Creek has none, so it counts ¼. Is that worth anything? |
| No reports this week / only 1–2 | Holds back points | −10 / −5 | Is "nobody looked, so not a perfect score" reasonable? |

## 3. Volunteer water tests (SYRCL, Sierra Streams Institute, WCCA, via RiverDB)

We use the most recent test on each creek. A test up to 60 days old counts fully, 60–180 days counts half, and anything older is shown but not counted. Today Deer Creek uses SYRCL's 8 Aug 2026 test. Wolf Creek's newest published test is from Dec 2019, so it doesn't count.

| Reading | Threshold | Pts | Source | Question for you |
|---|---|---|---|---|
| Dissolved oxygen | < 5 / < 7 mg/L | −15 / −6 | Basin Plan, cold-water habitat (7 mg/L) | Are these the right cut-offs for these reaches? |
| pH | outside 6.5–8.5 | −5 | Basin Plan objective | |
| E. coli | > 320 per 100 mL | −12 | State bacteria objective (swimming) | WCCA reports bacteria impairment on Wolf Creek. Should this weigh more? |
| Water temperature | > 20 °C | −5 | Our rule of thumb for trout stress | A better number for these creeks? |
| Turbidity | > 10 / > 25 NTU | −4 / −8 | Our rule of thumb | A better local baseline? |

## 4. Early warnings (these override the band)

| Warning | Trigger | Effect | Question for you |
|---|---|---|---|
| Possible contamination | Dead fish **or** a sewage/chemical smell reported in the last 3 days | **alert**, score capped at 39 | Is one report enough, or should it take two people? |
| Recent contamination | The same, 3–7 days ago | at least **watch** | |
| Runoff / sediment | ≥ 0.5 in of rain in 24 h **and** brown or cloudy water reported within 48 h | at least **watch** | Right rain threshold for these watersheds? |
| Algal bloom | Lots of algae or green water this week **and** ≥ 80 °F | at least **watch** | Should this also need low flow? |
| Heavy rain forecast | ≥ 0.5 in forecast in the next 24 h | advisory only | |

## The three questions that matter most

1. **Which observations would you drop, and which would you add?** Keep it to what a layperson can see, safely, in two minutes.
2. **Are dead fish (−40) and a sewage/chemical smell (−30) the right "alarm" signals**, or is something else a better early sign on these creeks?
3. **Would WCCA's or SSI's own long-term data give better local baselines** (normal turbidity, temperature or DO by month) than the statewide numbers? Could we use them, with credit?

---
*Built from `data/score.py` on main (609f108). The full method, sources and limitations are in `data/README.md` and on the app's About page. Thank you!*
