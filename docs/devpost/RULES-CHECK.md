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
| 2 | **Development period:** "Projects must be original and developed during the hackathon period" (R). Period listed as "September 16 – September 30, 2026" (R/O), "September 14–30" in (U), then the deadline was extended to Oct 4 and (U) "encouraged continued development work during the extended period" | All code is new; the repo's first commit is 2026-10-03, inside the extended window. The idea came from JP's pre-weekend notes; no prior code is reused. Low risk. To be safe, the Devpost text says the project was built during the submission window | ✅ (low risk) |
| 3 | **Age:** "Participants must meet the legal age requirement in their country of residence" (R) | JP is an adult. Alec: ⟨confirm he's of legal age⟩ | 🟡 JP confirms |
| 4 | **Students only:** the overview badge says "Students only" (O); the rules text doesn't say it | JP is a Sierra College student. Alec is a student ⟨school to confirm⟩ | 🟡 school name |
| 5 | **Team:** the overview badge says "Team required" (O). The rules say "Open to individuals or teams (each participant can join only one team)" (R), and (U) says "You can participate individually or as part of a team" | Team of two: JP and Alec. That satisfies both readings. Neither of them may be on another team | 🟡 Devpost team created, Alec joined (JP's local agent owns this) |
| 6 | **Register on Devpost:** "All participants must register on Devpost before the deadline" (R). The rules list "Registration Closes: August 31, 2026", but (U) says "Yes, you can still register and participate" | JP is registered. Alec has to register and join the team | 🟡 Alec registered (not this lane) |
| 7 | **Excluded:** "Organizers and judges are not eligible" (R); "Companies/professional organizations excluded" (O) | We are two individual students. TechEMPOWER (JP's nonprofit) is **not** the entrant. It's mentioned only as part of JP's bio, never as the team or a sponsor | ✅ keep it that way in the submission text |
| 8 | **Public code repository:** "All projects must include a public code repository (e.g., GitHub) with source code and documentation" (R) | github.com/jphein/creek-watch. **Currently PRIVATE** (checked 17:19 via `gh repo view`), pending the lead's first-push secret scan. README and docs are in this PR | 🔴 lead must make it public before submitting |
| 9 | **License / third-party IP:** "Submissions must not violate any copyright, licensing, or third-party IP rights" (R) | MIT `LICENSE` at the repo root ("Copyright (c) 2026 Jeffrey Hein and Creek Watch contributors"). GitHub's licence detection showed `none` at 17:19, probably not yet indexed; re-check once it's public. Third-party items: rows 9a–9e | 🟡 re-check detection |
| 9a | OpenStreetMap: ODbL, and you must "Provide credit to OpenStreetMap" ([copyright](https://www.openstreetmap.org/copyright)). The [tile policy](https://operations.osmfoundation.org/policies/tiles/) applies | Leaflet's attribution control must show "© OpenStreetMap contributors" with a link. The About page credits OSM. Traffic is tiny, within the tile policy | 🟡 web lane: confirm the attribution is visible on the map |
| 9b | USGS: "USGS-authored or produced data and information are considered to be in the U.S. Public Domain" ([USGS](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits)) | Credited on the About page and in the README | ✅ (once the About page ships) |
| 9c | NWS: "in the public domain … may be used without charge for any lawful purpose", but you must not imply endorsement ([NWS](https://www.weather.gov/disclaimer)) | Credited as a data source; no NWS logo; no claim of affiliation | ✅ |
| 9d | Leaflet (BSD-2-Clause) and Python dependencies (FastAPI MIT, Pillow MIT-CMU, and others) | Permissive licences, compatible with MIT. Not vendored into the repo (loaded from a CDN or installed by uv) | ✅ (inferred from the known licences, not audited per package) |
| 9e | Photos | Only photos the team took, or citizen reports submitted through the app. No stock or web images | 🟡 keep it that way in the video and screenshots |
| 10 | **Track alignment:** "Clearly state the track you've chosen" (O) | Primary Track 2, plus 1 and 6, stated first in SUBMISSION.md | ✅ |
| 11 | **Project description:** "problem, your solution, target users, and expected impact on ecosystem and human health" (O) | SUBMISSION.md covers all four; Alec's one-page version follows DESCRIPTION-OUTLINE.md | 🟡 Alec writes his page |
| 12 | **Demo video, 3–5 mins:** "Demo Video (3–5 mins): Showcase your project in action" (O) | DEMO-SCRIPT.md is timed at about 4:00–4:20 (520 words). The video must be **3:00–5:00**: check the final file's length with `ffprobe` before uploading | 🟡 record, edit and upload |
| 13 | **Prototype / demo:** "Share a working prototype, mockup, or proof-of-concept" (O) | Live at https://creekwatch.realm.watch. **Not reachable yet** (HTTP 000 at 17:19); the deploy lane is in progress | 🟡 deploy lane |
| 14 | **Original work** | All new code. AI coding assistance is disclosed in SUBMISSION.md ("How we built it"). **Neither the rules nor the overview has an AI-use clause**: we checked R, O and U and found none. Disclosing it is a voluntary good-faith step | ✅ |
| 15 | **Showcase:** "results … will be showcased on the OneAquaHealth Open Information Hub" (O) | Fine with the MIT licence. Nothing private is in the repo or the video | ℹ️ |
| 16 | **Prize amount:** the rules say "5000$ Cash/InKind Prize TBD" (R); the overview and updates say "$3,500 in cash" / "$3,500+" (O/U) | Don't quote any prize figure in public materials | ℹ️ |
| 17 | **Judging weights** (R): Impact 30%, Innovation 20%, Technical 20%, UX 15%, Feasibility 15% | The script and submission lead with impact (One Health), then the explainable score (innovation and technical), then the plain-words flow (UX), then next steps and open data (feasibility) | ℹ️ |

## Privacy and data-safety checks (our own rules, for a public repo)
- [ ] No secrets, `.env`, API tokens or Cloudflare token in the repo or its history. The deploy snippet references `{env.CLOUDFLARE_API_TOKEN}` by name only.
- [ ] No database or uploads committed (`*.db` and `uploads/` are in `.gitignore`).
- [ ] Photos are EXIF-stripped server-side (spec). Verify on a live upload with `exiftool` or `identify -verbose`.
- [ ] Video and screenshots show no faces, licence plates or reporter surnames.

## Still open (owner)
1. Make the repo public after the secret scan (**lead**).
2. Alec's surname, school and legal-age confirmation; his Devpost registration and team join (**JP / JP's local agent**).
3. Live URL up and phone-usable (**deploy lane**, target Sun 08:00).
4. OSM attribution visible on the map (**web lane**).
5. Video recorded, 3:00–5:00 confirmed with `ffprobe`, and uploaded publicly (**JP + Alec**).
6. Every ⟨fill⟩ in SUBMISSION.md resolved (**story lane**, Sunday afternoon).
