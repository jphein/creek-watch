# Creek Watch Alerts: spec (shared contract, 2026-10-03)

JP: "full on alerting for everything so this could be the go-to app for any water-related alerts."

**Goal:** one place for every water-related alert affecting Nevada County creeks, rivers, reservoirs and swimming spots. It merges official feeds (weather, flood, sewage spills, algal blooms, bacteria) with Creek Watch's own early warnings from citizen reports. Alerts are delivered in-app, as open feeds, and as opt-in push notifications. No accounts, and no personal data.

**Region:** Nevada County, CA (bbox roughly 38.95–39.55 N, 121.30–120.00 W). Focus on Wolf Creek and Deer Creek; also cover the Yuba and Bear rivers, Little Deer Creek, and the reservoirs (Scotts Flat, Rollins, Lake Wildwood, Englebright).

## Alert model (data → api → web; every source normalises to this)
```
Alert {
  id: str            # stable: "<source>:<source_id>"; same id = same alert (dedupe/update)
  source: str        # "nws" | "nwps" | "usgs" | "sso" | "hab" | "riverdb" | "creekwatch" | …
  source_name: str   # human, e.g. "National Weather Service"
  category: str      # "flood" | "flash_flood" | "storm" | "heat" | "sewage_spill" | "algal_bloom" | "bacteria" | "low_flow" | "high_flow" | "contamination" | "runoff" | "other"
  severity: str      # "alert" | "watch" | "advisory" | "info"  (maps CAP Extreme/Severe→alert, Moderate→watch, Minor→advisory)
  title: str; summary: str (plain language, ≤280 chars); instruction: str|null
  area: {creek_ids: [str], site_ids: [str], lat: float|null, lon: float|null, polygon_geojson: obj|null, area_desc: str}
  effective: iso8601; expires: iso8601|null; updated: iso8601
  status: "active" | "expired" | "cancelled"
  url: str           # authoritative source page (always link the official source)
  attribution: str   # licence/credit line
}
```
Rules:
- Official alerts are passed through, never reworded so they change meaning; `summary` may simplify, but `url` links the original.
- Creek Watch's own warnings (from data/score.py) become alerts with `source="creekwatch"`.
- Every source adapter is keyless or uses a server-side secret from env. Each needs timeouts, caching and graceful failure (one bad source never blocks the others), and tests against captured fixtures.

## Sources (data lane verifies each one is real, live and free before building it)
1. **NWS active alerts** (api.weather.gov/alerts/active?point= / ?zone=): flood, flash flood, flood watch, hydrologic outlook, heavy rain, heat. Water-related events only.
2. **NOAA NWPS river gauges/forecasts** (api.water.noaa.gov/nwps): flood categories for nearby forecast points (Yuba/Bear), if any are in range.
3. **USGS flow** (already ingested): high-flow and low-flow advisories from percentiles.
4. **CA sewage spills (SSO)**, CIWQS/data.ca.gov: recent spills near our creeks.
5. **CA freshwater harmful algal blooms**, CA HABs portal / data.ca.gov incident reports, plus EPA CyAN for the reservoirs if it covers them: Caution/Warning/Danger advisories.
6. **Bacteria**: RiverDB volunteer E. coli above 320 MPN/100 mL (recent), plus a link to SSI's Pioneer Park status page (no values scraped).
7. **Creek Watch**: the existing 5 warning rules, plus a new E. coli rule.
8. Stretch, research only: boil-water notices (SWRCB DDW), Cal OES spill reports, OEHHA fish advisories. Use them if a real feed exists; otherwise link them.

## Delivery (api + web)
- `GET /api/alerts?creek_id=&severity=&category=&status=active` returns JSON.
- `GET /alerts.atom` and `GET /alerts.cap.xml` (CAP 1.2 alert or feed, valid against the OASIS schema). Per-creek variants are `?creek_id=`.
- In-app **Alerts** page, plus banners on creek cards, plus a map layer.
- **Web Push** (VAPID; opt-in, filtered per creek and per severity; unsubscribe anytime). The subscription stores only the push endpoint and keys plus the filters. The push endpoint host must be on an allowlist of known push services (FCM, Mozilla, Apple, Windows) to prevent SSRF. VAPID private key from env/vault only.
- Poller: refreshes sources on a schedule (5–15 min per source), diffs, and sends pushes only for NEW or ESCALATED alerts (deduped). Includes a rate limit and quiet-hours option.

## Owners
| Lane | Owns |
|---|---|
| nebula-creekwatch-data | `data/alerts/` source adapters + Alert normaliser + fixtures/tests; new E. coli rule in score.py |
| morpheus-creekwatch-api | `backend/` alert store, poller, `/api/alerts`, Atom + CAP feeds, Web Push backend |
| luna-creekwatch-web | `web/` Alerts page, banners, map layer, subscribe UI, service-worker push handler |
| morpheus-creekwatch-deploy | VAPID secret via vault → ubox0 env (never in repo), poller ops, egress checks |
| nebula-creekwatch-story | README/SUBMISSION/About updates (Track 6 resilience + Track 7 standards: CAP 1.2) |
| oracle-creekwatch-gate | read-only gates: push SSRF/keys, feed injection, poller DoS |

Every PR: new branch off main, a board line, and Changed / Checked / Evidence / Not verified. Security code (push, secrets, outbound fetches) gets an Oracle gate before merge.
