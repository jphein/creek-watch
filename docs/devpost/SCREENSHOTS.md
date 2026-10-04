# Screenshot shot list (for luna-creekwatch-web)

**Where they go:** the Devpost image gallery (first image = the project thumbnail), the README hero, and B-roll for the demo video.
**Files:** `docs/screenshots/NN-name.png`. Phone shots at **390×844** (device scale 2 or 3), desktop at **1440×900**.
**Data:** use **real** reports from Alec's Sunday visit, never mock data. If a shot needs a state that hasn't happened (such as an alert), see the note on that shot.
**Privacy:** no reporter surnames, no faces and no licence plates visible. Crop or choose another report if needed.
**Theme:** light, unless the shot says otherwise.

| # | File | Viewport | What's on screen | Used in |
|---|---|---|---|---|
| 01 | `01-hero-dashboard.png` | desktop 1440×900 | Dashboard with both creek cards: score gauge, band, signals with explanations, gauge and weather box. **This is the Devpost thumbnail; it must read at a small size.** | Devpost #1, README hero |
| 02 | `02-report-start.png` | phone | Report step 1: the photo picker with the big "take a photo" button | Devpost, video §3 |
| 03 | `03-report-questions.png` | phone | The water-colour or algae step: icon buttons with plain words, one selected | Devpost, video §3 |
| 04 | `04-report-place.png` | phone | Location step: the auto-picked nearest spot on a small map | Devpost, video §3 |
| 05 | `05-report-done.png` | phone | Confirmation screen: "what happens next" | Devpost |
| 06 | `06-map.png` | desktop | Map zoomed to show both towns: creek lines, site markers and coloured report pins | Devpost, video §5 |
| 07 | `07-map-pin-popup.png` | phone | A tapped pin showing a real report photo and its answers | Devpost, video §5 |
| 08 | `08-dashboard-signals.png` | phone | One creek card scrolled to the signals list, showing the explanations clearly | Devpost, video §6 |
| 09 | `09-early-warning.png` | phone or desktop | A card in the **watch** or **alert** band, with its reason. *If no real report triggers one, use a staging or local instance with a clearly test-only report, and caption it "example of the alert view (test data)". Never pass test data off as real.* | Devpost, video §6 |
| 10 | `10-about-data.png` | desktop | About the data page: the source list, how the score works, privacy | Devpost, video §7 |
| 11 | `11-dark-mode.png` | phone | The dashboard in dark mode | Devpost (polish) |
| 12 | `12-field-photo.jpg` | (Alec's camera) | A real creek photo from Sunday: wide shot, no people | Devpost, README, video §1/§8 |

**Devpost captions:** one sentence each, for example: "01: Each creek gets an explainable 0–100 health score built from citizen reports plus live USGS and NWS data."

**Check before handing off:** open each PNG and confirm it isn't blank, the text is legible, and no mock or placeholder data is visible (shot 09's caption excepted).
