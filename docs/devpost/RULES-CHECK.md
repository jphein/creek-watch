# Rules compliance check: OneAquaHealth IEEE Global Hackathon

**Sources checked:**
- (R) the Devpost **Rules** page, live at https://oneaquahealth-ieee-hackathon.devpost.com/rules, plus the saved copy;
- (O) the **Overview** page (saved copy);
- (U) the **Updates** page, live.

All three were read on Sat 2026-10-03, about 17:20 PDT.
**Status key:** ✅ met · 🟡 open, someone owns it · 🔴 risk needing a decision · ℹ️ informational.

| # | Requirement (source, quote) | How we meet it | Status |
|---|---|---|---|
| 1 | **Deadline:** "Oct 4, 2026 @ 9:00pm PDT" (O). Extended per (U): "submission deadline has been extended … October 4, 2026 at 9:00 PM" | Staged by Sun 18:00 for JP's one-click submit; three hours of buffer | 🟡 submit |
| 2 | **Development period:** "Projects must be original and developed during the hackathon period" (R). Period listed as "September 16 – September 30, 2026" (R/O) and "September 14–30" (U); then (U) extended the deadline to Oct 4 and "encouraged continued development work during the extended period" | All code is new; the repo's first commit is 2026-10-03, inside the extended submission window (Oct 3–4, before the Oct 4 21:00 PDT deadline). SUBMISSION.md says so in "How we built it". A clarifying question for the hackathon manager is drafted in [MANAGER-QUESTION.md](MANAGER-QUESTION.md); sending it is JP's call, since it goes out as him | 🟡 open: JP decides whether to send the question |
| 3 | **Age:** "Participants must meet the legal age requirement in their country of residence" (R) | JP is an adult. Alec: ⟨confirm he's of legal age⟩ | 🟡 JP confirms |
| 4 | **Students only:** the overview badge says "Students only" (O); the rules text doesn't say it | JP is a Sierra College student. Alec is a student ⟨school to confirm⟩ | 🟡 school name |
| 5 | **Team:** the overview badge says "Team required" (O). The rules say "Open to individuals or teams (each participant can join only one team)" (R), and (U) says "You can participate individually or as part of a team" | Team of two: JP and Alec. That satisfies both readings. Neither of them may be on another team | 🟡 Devpost team created, Alec joined (JP's local agent owns this) |
| 6 | **Register on Devpost:** "All participants must register on Devpost before the deadline" (R). The rules list "Registration Closes: August 31, 2026", but (U) says "Yes, you can still register and participate" | JP is registered. Alec has to register and join the team | 🟡 Alec registered (not this lane) |
| 7 | **Excluded:** "Organizers and judges are not eligible" (R); "Companies/professional organizations excluded" (O) | We are two individual students. No organisation is named as the entrant, a sponsor or an affiliation: JP's bio was trimmed to "Sierra College student and full-stack developer" (JP, 2026-10-03) | ✅ |
| 8 | **Public code repository:** "All projects must include a public code repository (e.g., GitHub) with source code and documentation" (R) | github.com/jphein/creek-watch is **PUBLIC**, and GitHub detects the licence as **MIT** (lead, after a full-history secret scan). README and docs are present | ✅ |
| 9 | **License / third-party IP:** "Submissions must not violate any copyright, licensing, or third-party IP rights" (R) | MIT `LICENSE` at the repo root ("Copyright (c) 2026 Jeffrey Hein and Creek Watch contributors"). GitHub REST `repos/jphein/creek-watch` reports `spdx_id: MIT` (checked 2026-10-03, about 18:20). Third-party items: rows 9a–9c3 | ✅ |
| 9a | OpenStreetMap: ODbL, and you must "Provide credit to OpenStreetMap" ([copyright](https://www.openstreetmap.org/copyright)). The [tile policy](https://operations.osmfoundation.org/policies/tiles/) applies | Leaflet's attribution control must show "© OpenStreetMap contributors" with a link. The About page credits OSM. Traffic is tiny, within the tile policy | ✅ verified in code: web/js/map.js sets the attribution "© OpenStreetMap contributors" with the copyright link (main, 2026-10-03). Still check it is visible on a phone screenshot |
| 9b | USGS: "USGS-authored or produced data and information are considered to be in the U.S. Public Domain" ([USGS](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits)) | Credited on the About page and in the README | ✅ (once the About page ships) |
| 9c | NWS: "in the public domain … may be used without charge for any lawful purpose", but you must not imply endorsement ([NWS](https://www.weather.gov/disclaimer)) | Credited as a data source; no NWS logo; no claim of affiliation | ✅ |
| 9c2 | Open-Meteo (rainfall, used by data/ingest.py): data is "CC-BY 4.0", and the free API is "only … for non-commercial purposes" ([terms](https://open-meteo.com/en/terms)) | Non-commercial student project with no ads or subscriptions; a few calls per 15-minute cache, far under the 10,000/day limit. **Fixed in PR #20 (794d0af, merged):** the About page and the dashboard weather box credit Open-Meteo, link CC BY 4.0, and limit the NWS credit to temperature and forecast. Confirmed in main's web/index.html:43 and the 390 px screenshot (scratch/web/shots/wq-390-light-about.png). Credited in the README and SUBMISSION too | ✅ in code; recheck on the live site after the next deploy |
| 9c3 | RiverDB volunteer data (SYRCL, SSI, WCCA): their publicly published monitoring data, read through RiverDB's public GraphQL API (data/wq.py) | Credited by group name on every reading, and in data/README.md, SUBMISSION and README. No explicit licence was found on RiverDB. *Not verified:* RiverDB's terms of use. Attribution is our good-faith basis | 🟡 low risk: attributed; terms not found |
| 9c4 | State Water Board sewage-spill data (Cat 1–3 file) | Public data, self-reported by agencies; each alert links the data source. We don't characterise causes | ✅ |
| 9c5 | CA freshwater HABs (data.ca.gov) | Licence listed as "Other (Public Domain)" (per data/alerts/SOURCES.md); linked to the HABs portal | ✅ |
| 9c6 | OEHHA fish-consumption advisories (data.ca.gov) | Public domain; advisory text not reproduced, only linked; no reasons stated by us | ✅ |
| 9c7 | NWS alerts and NOAA NWPS | U.S. Government, public domain; official alerts passed through and linked, not reworded in meaning; no endorsement implied | ✅ |
| 9c8 | CEDEN fecal-indicator-bacteria results (data.ca.gov) | The portal lists **no licence** for this dataset; it's State Water Board public data, credited "Central Valley Regional Water Quality Control Board via CEDEN" and linked. Shown as dated history only. Single samples above 320 are framed as "not by itself a violation" | 🟡 low risk: attributed, no licence stated |
| 9c9 | CDEC (California Department of Water Resources) | State public data, credited to DWR CDEC with station links. We found no licence text. Regional context only, with observation times shown | 🟡 low risk: attributed, terms not found |
| 9d | Leaflet (BSD-2-Clause) and Python dependencies (FastAPI MIT, Pillow MIT-CMU, and others) | Permissive licences, compatible with MIT. Not vendored into the repo (loaded from a CDN or installed by uv) | ✅ (inferred from the known licences, not audited per package) |
| 9e | Photos | Only photos the team took, or citizen reports submitted through the app. No stock or web images | 🟡 keep it that way in the video and screenshots |
| 10 | **Track alignment:** "Clearly state the track you've chosen" (O) | Primary Track 2, plus 1 and 6, stated first in SUBMISSION.md | ✅ |
| 11 | **Project description:** "problem, your solution, target users, and expected impact on ecosystem and human health" (O) | SUBMISSION.md covers all four; Alec's one-page version follows DESCRIPTION-OUTLINE.md | 🟡 Alec writes his page |
| 12 | **Demo video, 3–5 mins:** "Demo Video (3–5 mins): Showcase your project in action" (O) | DEMO-SCRIPT.md is timed at about 4:20–4:40 (566 words). The final video is **narrated with text-to-speech from that script**, disclosed in SUBMISSION. Check the final file is between 3:00 and 5:00 with `ffprobe` before uploading | 🟡 render and upload the video, then confirm its length |
| 13 | **Prototype / demo:** "Share a working prototype, mockup, or proof-of-concept" (O) | Live at https://creekwatch.realm.watch. **Not reachable yet** (HTTP 000 at 17:19); the deploy lane is in progress | 🟡 deploy lane |
| 14 | **Original work** | All new code. AI coding assistance is disclosed in SUBMISSION.md ("How we built it"). **Neither the rules nor the overview has an AI-use clause**: we checked R, O and U and found none. Disclosing it is a voluntary good-faith step | ✅ |
| 15 | **Showcase:** "results … will be showcased on the OneAquaHealth Open Information Hub" (O) | Fine with the MIT licence. Nothing private is in the repo or the video | ℹ️ |
| 16 | **Prize amount mismatch:** the rules say "5000$ Cash/InKind Prize TBD" (R), but the overview lists "$3,500 in cash": Winner $1,500, Runner Up $1,000, Second Runner Up $500, and Special Mention $250 × 2 winners, plus certificates (O). (U) says "Prize Pool: $3,500+" | We follow the overview's figures. No change to what we build or submit. Public materials quote no prize figure | ℹ️ |
| 17 | **Judging weights** (R): Impact 30%, Innovation 20%, Technical 20%, UX 15%, Feasibility 15% | The script and submission lead with impact (One Health), then the explainable score (innovation and technical), then the plain-words flow (UX), then next steps and open data (feasibility) | ℹ️ |

| 18 | **Alerts / Track 7 claim:** CAP 1.2 | Live `/alerts.cap.xml` (Atom wrapping CAP alerts). On 2026-10-03 at about 20:15 PDT, 26/26 `cap:alert` elements validated with `xmllint --schema` against the OASIS [CAP-v1.2.xsd](https://docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2.xsd); a minimal invalid alert failed (negative control). SUBMISSION claims a "CAP 1.2" format with schema-checked alerts, not FHIR | ✅ |
| 19 | **Push privacy and safety** | Opt-in, no accounts. The table stores the endpoint, p256dh/auth keys, filters, timestamps and a failure counter, and nothing else (backend/creekwatch/alerts/push.py schema). Endpoint hosts are allowlisted (FCM, Mozilla, Apple, Windows push). The VAPID key is server-side only. Oracle-gated per the alerts spec | ✅ in code, and tested end to end on a real phone on 2026-10-03: JP received the welcome notification on subscribing, and again after unsubscribing and resubscribing (prod log 22:19:21 PDT: `welcome push sub=df880f31 age_s=1 status=201`, relayed by the lead). The story lane made no subscribe or POST itself |
| 20 | **Life-safety framing** | The Alerts and subscribe pages say Creek Watch is not an emergency service and point to Nevada County Alerts, AwareCA and 911 (web/js/subscribe.js) | ✅ |

## Privacy and data-safety checks (our own rules, for a public repo)
- [ ] No secrets, `.env`, API tokens or Cloudflare token in the repo or its history. The deploy snippet references `{env.CLOUDFLARE_API_TOKEN}` by name only.
- [ ] No database or uploads committed (`*.db` and `uploads/` are in `.gitignore`).
- [ ] Photos are EXIF-stripped server-side (spec). Verify on a live upload with `exiftool` or `identify -verbose`.
- [ ] Video and screenshots show no faces, licence plates or reporter surnames.

## Still open (owner)
1. ~~Make the repo public after the secret scan~~ ✅ done (**lead**).
2. Alec's surname and school (use "Alec" only until JP answers), and legal-age confirmation; his Devpost registration and team join (**JP / JP's local agent**).
3. Live URL up and phone-usable (**deploy lane**, target Sun 08:00).
4. OSM attribution visible on the map (in code ✅; confirm on a screenshot), and the About page's rain credit corrected to Open-Meteo (✅ PR #20; confirm live after deploy) (**web lane**).
5. Video recorded, 3:00–5:00 confirmed with `ffprobe`, and uploaded publicly (**JP + Alec**).
6. Whether to send MANAGER-QUESTION.md (**JP**; sent as him, so not drafted to send automatically).
7. Every ⟨fill⟩ in SUBMISSION.md resolved (**story lane**, Sunday afternoon).
