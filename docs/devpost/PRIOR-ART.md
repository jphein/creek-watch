# Prior art and landscape: is there anything like Creek Watch already?

**Short answer: yes, a lot.** Photo-based citizen creek reporting has existed since 2010, including an IBM app called *Creek Watch*. The contest sponsor already runs its own guided citizen-science app, and several other entries in this hackathon also turn citizen checks into an explained stream-health score. What's genuinely new in ours is narrower than "a citizen creek app". It's in the [Differentiation](#4-differentiation-honest) section below.

**Method:**
- Researched Sat 2026-10-03, about 17:30–17:40 PDT (clock-checked), using web search plus direct fetches.
- "Status" means checked live with `curl` (HTTP code) or the GitHub API at that time. **403** means the site blocks scripted requests (bot protection); it is not dead.
- Claims come from the linked pages. "Inferred" marks anything we didn't read directly.

---

## 1. The name: IBM's "Creek Watch" (2010)

**What it was:**
- An iPhone app and website from IBM Research (Almaden), launched in November 2010 with California's State Water Resources Control Board as the first partner.
- Users took a photo and answered three questions:
  - water level (dry, some, full);
  - flow (still, slow, fast);
  - trash (none, some, a lot).
- The phone's GPS recorded the location.

Sources: [Grist, 2010-11-11](https://grist.org/article/2010-11-11-iphone-app-lets-agencies-crowdsource-environmental-monitoring/); [Forbes, 2010-11-04](https://www.forbes.com/sites/kerryadolan/2010/11/04/ibm-launches-iphone-app-for-crowdsourcing-water-quality/); [SciStarter](https://scistarter.org/creek-watch).

**Paper:** Kim, Robson, Zimmerman, Pierce and Haber, *"Creek Watch: Pairing usefulness and usability for successful citizen science"*, CHI 2011 ([ACM](https://dl.acm.org/doi/10.1145/1978942.1979251), [IBM Research](https://research.ibm.com/publications/creek-watch-pairing-usefulness-and-usability-for-successful-citizen-science)).

**Status: defunct** (checked 2026-10-03):
- `creekwatch.researchlabs.ibm.com` returns HTTP 502.
- An iTunes Search API query for "creek watch" returns no such app. The same query returns 8 other apps, so the search itself works.
- `creekwatch.org` and `creekwatch.com` are parked domains (Afternic nameservers; the page script redirects to `/lander`).

**Trademark:**
- [Trademarkia](https://www.trademarkia.com/search/trademarks?query=creek+watch) shows **no live "CREEK WATCH" mark**. The only combined hit is "CHERRY CREEK WATCH COMPANY", for retail watch stores (class 35).
- *Not verified:* we couldn't query USPTO directly, and we didn't check other countries.

**Other uses of the name** (volunteer programs, not software):
- [CreekWatch, RiverWatch Institute of Alberta](https://creekwatch.ca/), running since 2014;
- [CreekWatchers, Cape Fear River Watch](https://capefearriverwatch.org/creekwatchers/), in North Carolina.

**Recommendation: keep the name, and cite IBM openly.**
- There's no legal blocker that we found.
- Renaming would cost the live URL, the repo, the docs and the script under a hard deadline.
- IBM's app is the closest ancestor of our report flow, in the same state and under the same name. A judge who remembers it would find hiding it worse than crediting it.

The Devpost text should say: *"Named in the spirit of IBM Research's 2010 Creek Watch app (CHI 2011), which first showed that a photo plus a few plain questions gives water managers useful data. That app is no longer available. We extend the idea with live gauge and weather fusion, an explained score and early warning, and an open-source web app."*

Fallback names, if JP prefers a rename. Each was searched, and no app or product was found:
- **Creek Signal:** names the early-warning output. `creeksignal.org` has no NS records; `.com` is registered.
- **CreekCheck:** a verb people use ("do a creek check"). Neither `.org` nor `.com` has NS records.
- **Creek Pulse:** suggests a live health reading. Neither `.org` nor `.com` has NS records.

---

## 2. Similar tools

| Tool | Who | Status | What it does | vs Creek Watch |
|---|---|---|---|---|
| [OneAquaHealth Citizen Science App](https://www.oneaquahealth.eu/citizen-science-project/) | OneAquaHealth (EU), the **contest sponsor**; app at app.enora-oah.eu | Live (the project page says so) | PWA. Guided steps to record water quality, vegetation, wildlife, pollution, photos and video, with "a structured scoring system". Used at research sites in Benevento, Coimbra, Ghent, Oslo and Toulouse | **The closest match, and the judges know it well.** Same idea: a guided PWA with photos. Ours differs by fusing live gauge and weather data, giving a rule-based warning with reasons, and being set in a US region outside its case-study cities |
| [IBM Creek Watch](https://scistarter.org/creek-watch) | IBM Research and the CA Water Board | Defunct (see §1) | Photo plus level, flow and trash | Ancestor of our report flow. No score, no data fusion, no warnings |
| [CrowdWater](https://crowdwater.ch/en/start/) | University of Zurich (SNSF) | 200 | App for water level (virtual staff gauge), temporary streams, soil moisture and plastic, aimed at "modelling of floods and droughts" in data-poor areas | Same "fill the gauge gap" motive, but for hydrology. It doesn't score water quality and has no One Health framing |
| [FreshWater Watch](https://www.freshwaterwatch.org) | Earthwatch Europe | 200 | Kit-based nitrate, phosphate and turbidity tests with an app, and a global open map ([about](https://earthwatch.org.uk/program/freshwater-watch-in-the-uk/)) | Lab-style chemistry with kits. We use no kits, so our data is coarser but anyone can report |
| [Monitor My Watershed](https://monitormywatershed.org/) / [WikiWatershed](https://wikiwatershed.org/) / [Leaf Pack Network](https://leafpacknetwork.org/) | Stroud Water Research Center | 200 / 403 / 403 | Data portal for DIY sensors (EnviroDIY) and macroinvertebrate data. A paid ($4.99) Water Quality app for educators logs chemical, physical and biological parameters ([help](https://wikiwatershed.org/help/wq-app-help/)) | Serious-science tooling. Ours is no-kit and two minutes long |
| [Water Rangers](https://waterrangers.com/) | Canadian non-profit, founded 2015 | 403 | Test kits (pH, hardness, alkalinity, clarity, oxygen, conductivity) plus web and app reporting of algae and pollution ([WWF Tech Hub](https://techhub.wwf.ca/innovator/citizen-science-tools-for-water-quality-monitoring/)) | Kit-based again. Its pollution reporting overlaps ours |
| [mWater](https://www.mwater.co) | mWater (open source) | 200 | WASH platform for mapping water sources and sanitation with test kits, used by thousands of NGOs ([E4C](https://www.engineeringforchange.org/solutions/product/mwater-explorer-mobile-app/)) | Focused on drinking water and sanitation, not urban creek ecology |
| [bloomWatch](https://cyanos.org/bloomwatch/) | Cyanobacteria Monitoring Collaborative | 200 | Photo reports of possible cyanobacteria blooms ([NALMS](https://www.nalms.org/monitoring-habs-with-the-bloomwatch-app/)) | Covers only one of our signals (algae) |
| [EPA CyAN app](https://epa.gov/water-research/cyanobacteria-assessment-network-mobile-application-cyan-app) | US EPA | 200 | Weekly satellite cyanobacteria data for water bodies of about 1 km² or more | Too coarse for small creeks like ours. It's for lakes and reservoirs |
| [CA HABs Portal](https://mywaterquality.ca.gov/habs/) | CA Water Boards | 200 | Online form to report a harmful algal bloom, with a [reports map](https://mywaterquality.ca.gov/habs/resources/reports-map/) | Official channel for blooms. A future Creek Watch could link "lots of algae" reports to it |
| [EyeOnWater](https://www.eyeonwater.org/) | EyeOnWater consortium | 200 | Photo plus a water-colour scale | Colour only |
| [Stream Tracker](https://www.streamtracker.org) | CSU, NASA, USFS; uses the CitSci.org app | 200 | Flowing, standing, dry or frozen observations for intermittent streams ([CitSci blog](https://blog.citsci.org/2018/04/09/stream-tracker/)) | Flow only. Same gap-filling motive |
| [Creek Critters](https://natureforward.org/creek-critters/) | Nature Forward and the Izaak Walton League | 200 | Guided macroinvertebrate ID that produces a "Stream Health Score" | A health score from bugs, with a guided flow. Ours uses no-touch observations plus public data |
| [Georgia Adopt-A-Stream](https://adoptastream.georgia.gov/how-do-i-get-started-adopt-stream) | Georgia EPD | 200 | State volunteer program: chemical, bacterial, macroinvertebrate and visual monitoring, with an online database | A trained, regular program. We're the casual-observer layer |
| [CA SWAMP Clean Water Team](https://www.waterboards.ca.gov/water_issues/programs/swamp/clean_water_team/) and [CEDEN](https://ceden.org) | CA Water Boards | 200 | The state's citizen-monitoring program and its data exchange. Its [apps list](https://waterboards.ca.gov/water_issues/programs/swamp/clean_water_team/apps.html) still lists IBM Creek Watch | The destination for formal data. Exporting to CEDEN formats is a possible next step (not built) |
| [How's My Waterway](https://mywaterway.epa.gov) | US EPA | 200 | Official assessment and impairment status of waterways | Official status, updated slowly. Ours is live and casual |
| [iNaturalist](https://www.inaturalist.org/) | iNaturalist | 403 to scripts | Species observations, including freshwater projects | We record "wildlife seen" as free text only. A future version could link to iNat |
| [L.A. Creek Freak](https://lacreekfreak.wordpress.com/about/) | Blog (2008–) | n/a | Advocacy and mapping of LA's lost creeks | A story and advocacy precedent. Not a tool |
| IOOS / NOAA | NOAA | n/a | Ocean and coastal observing | Not comparable. We do use NOAA's **NWS** API as a data source |

### Other entries in this same hackathon (public GitHub repos, checked via the GitHub API)

The pattern of turning citizen checks into an explained score is crowded here.

| Repo | Created | What it says it does |
|---|---|---|
| [saqlainzahoor/streampulse](https://github.com/saqlainzahoor/streampulse) | 2026-09-21 | Dashboard, health gauges, guided wizard and gamification. **Simulated data** for fictional sites (per its README) |
| [HyunsikParker/streamcheck](https://github.com/HyunsikParker/streamcheck) | 2026-09-23 | OneAquaHealth questions plus explained consistency and weather (Open-Meteo) checks, and a FHIR export. Uses the 5 EU research cities |
| [codeswithroh/streamreach](https://github.com/codeswithroh/streamreach) | 2026-09-28 | Citizen checks plus forecasts become FHIR risk assessments for clinicians. Explained factors, an LLM-drafted advisory, and human approval. Simulated citizen data in EU demo cities |
| [BabayoAP/aquaplot](https://github.com/BabayoAP/aquaplot) | 2026-09-23 | A photo becomes a stream-health reading banded by the EU Water Framework Directive (WFD), plus a One Health signal |
| [Ryugi62/streamfhir](https://github.com/Ryugi62/streamfhir) | 2026-09-29 | Citizen checks become HL7 FHIR R4 records with corroborated warnings |
| [kinnuworks/brook](https://github.com/kinnuworks/brook) | 2026-10-02 | A spoken, 7-language guide to the OneAquaHealth stream check |

*We read the READMEs of streampulse, streamcheck and streamreach (via WebFetch). For the others, we read only the repo description. We didn't run any of them.*

---

## 3. Local: is anyone already watching Wolf Creek and Deer Creek?

**Yes, with serious, long-running volunteer science. We should cite it, not compete with it.**

- **Wolf Creek Community Alliance (WCCA), Grass Valley.** Volunteers "have visited monitoring sites ranging from the Wolf Creek headwaters down also to its confluence with the Bear, testing for pH, dissolved oxygen, turbidity and other essential metrics", for about two decades. WCCA also does watershed-impact advocacy, such as comments on the proposed Idaho-Maryland Mine reopening. Source: [programs](https://wolfcreekalliance.org/programs/). *Earlier drafts said "Friends of Wolf Creek". We found no group by that name; WCCA appears to be the one meant.*
- **Sierra Streams Institute (SSI), Nevada City.** Founded in 1995 as **Friends of Deer Creek** and later reorganized under the new name ([history](https://sierrastreamsinstitute.org/introductionhistory/), [GovTribe](https://govtribe.com/vendors/sierra-streams-institute-friends-of-deer-creek-4xxy7)). Its volunteer program has run for more than 20 years. It measures dissolved oxygen, turbidity, pH, conductivity, temperature, nitrate, phosphate and bacteria quarterly at 9 sentinel sites on Deer Creek and its tributaries, with extra storm and summer sampling ([Deer Creek watershed](https://sierrastreamsinstitute.org/monitoring/deer-creek-watershed/)).
- **SYRCL (South Yuba River Citizens League).** 25 years of [River Monitoring](https://yubariver.org/river-monitoring/) across the Yuba watershed. The 2025 season had 37 sites and 48 volunteers ([25th-year post](https://yubariver.org/posts/a-quarter-century-of-community-science-volunteers-complete-the-25th-year-of-river-monitoring)). Mostly the Yuba; we found no statement that it covers Wolf Creek.
- **[RiverDB.org](https://riverdb.org).** The shared public water-quality database for the region. Its web-app bundle lists organization records for **SYRCL, Sierra Streams Institute and Wolf Creek Community Alliance** ("river: Wolf Creek"). It exposes a public GraphQL endpoint (`gql.riverdb.org/graphql`; a schema introspection query returned field names). We verified this by fetching the bundle and introspecting; we pulled no data.
- **Central Valley Regional Water Board: Wolf Creek Bacteria Study (2024).** A 12-week dry-season study (June 19 – September 4, 2024) covering 14 miles, from the North Star Mining Museum to Wolf Road. Draft results showed *E. coli* exceedances at eight sites; ruminants were the largest source, dogs a source in some areas ([report PDF](https://www.waterboards.ca.gov/centralvalley/water_issues/swamp/rbua/wolf-creek-mst-rpt.pdf), [press release via Maven's Notebook](https://mavensnotebook.com/2024/12/06/press-release-central-valley-water-board-announces-initial-results-from-e-coli-tracking-study-at-nevada-countys-wolf-creek/)). Our Glen Jones Park / North Star site sits at the upstream end of that study reach. (Bacteria figures come from the search summary of those pages; we didn't read the PDF.)
- **Nevada County RCD:** we found no RCD monitoring program or app for these creeks in the time available. *Not verified either way.*
- **Apps:** we found **no app** used by these groups for casual public reports. Their work is trained, kit- and lab-based, monthly or quarterly sampling. *(Inferred from their pages; we didn't ask them.)*

**Partner and cite opportunities** (no outreach; contacting anyone is JP's call):
- **Credit** WCCA's and SSI's decades of monitoring in the Devpost text and the About page, as the scientific baseline Creek Watch is *not* replacing.
- **Next step:** read their public RiverDB data through its GraphQL API and show their latest lab results next to citizen reports. Our sites already overlap theirs geographically: Glen Jones / North Star, and the Tribute Trail.
- **Hand-off:** a report of "lots of algae", or of dead fish, could link to the [CA HABs report form](https://mywaterquality.ca.gov/habs/) and to the groups' contact pages.

---

## 4. Differentiation (honest)

**Where we are *not* novel. Say so plainly:**
- Photo reports plus simple questions: IBM Creek Watch did this in 2010, and the sponsor's own app does it now.
- A guided, plain-language flow: the sponsor's app, Creek Critters, and Brook in this hackathon.
- A stream "health score": Creek Critters, StreamPulse and AquaPlot.
- Weather-aware, explained checks and early warnings: StreamCheck and StreamReach in this hackathon. Theirs are more sophisticated (logistic models, FHIR, CDS Hooks).
- Filling gauge gaps with citizens: CrowdWater and Stream Tracker.

**What's genuinely ours:**
1. **Real, live, local data, not a simulation.** Two specific US creeks, 12 site-checked public access points (from OSM, snapped to the channel, with private banks marked), real USGS and NWS feeds, and real field reports (Alec's creek visit is planned for Sun 2026-10-04 morning). The rival entries we inspected use simulated citizen data or the EU research cities.
2. **Honesty about the gauge gap, as a feature.** We measured it: Wolf Creek has no live gauge, and Deer Creek's only one is about 22 km downstream and regulated. The score says so in its explanations instead of passing off a distant gauge as local truth. Citizen reports are the only near-real-time signal in town.
3. **Explanations in plain words with fixed rules, and no AI in the score.** Every point comes with a reason and a source. Others explain with models; ours is simple enough for a resident to check by hand.
4. **No kit, about 2 minutes, and no login.** Built for the walker who's already there, not the trained monitor. It sits *below* WCCA's and SSI's science and could feed into it.
5. **Name continuity, credited.** It revives a proven 2010 idea that is no longer available, adds fusion and warnings, and is open source.

**Suggested Devpost paragraph** (for "What makes it different"):
> Citizen creek reporting isn't new: IBM Research's 2010 *Creek Watch* app, whose name we honour, showed that a photo plus a few plain questions helps water managers, and OneAquaHealth's own app does guided assessments today. Creek Watch adds three things for two real creeks in California's Sierra foothills. It fuses each report with live USGS stream-gauge and National Weather Service data into a 0–100 score that explains every point it gives or takes. It runs simple, transparent early-warning rules. And it's honest about a real monitoring gap: Wolf Creek has no live stream gauge, and Deer Creek's only one is 22 km downstream, below a reservoir. Local groups (Wolf Creek Community Alliance and Sierra Streams Institute) have run trained, lab-grade monitoring here for about 20 years; Creek Watch is the everyday layer between their samples, not a replacement.
