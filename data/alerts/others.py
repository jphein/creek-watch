"""Smaller sources: USGS flow advisories, RiverDB bacteria, OEHHA fish advisories, Creek Watch rules."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .. import ingest, wq
from ..score import ECOLI_LIMIT, ECOLI_WATCH_DAYS, ecoli_text
from . import http
from .model import Source, in_region, make_alert

ECOLI_RECENT_DAYS = 60     # E. coli alerts drop after 60 days (limit + watch window: data.score)
SSI_PIONEER = "https://sierrastreamsinstitute.org/pioneer-park-monitoring-status/"
# Standing items (fish advisories, the SSI link) have no issue date in their source; this is the
# date Creek Watch verified the listing, so "effective" never pretends to be the source's date.
LISTED_ON = "2026-10-03T00:00:00Z"


class USGSFlow(Source):
    """High/low flow vs the long-term median for the date (from data.ingest)."""
    id = "usgs"
    name = "USGS stream gauges"
    attribution = "U.S. Geological Survey, provisional data, public domain"
    poll_interval_s = 900

    def _fetch(self, now: datetime) -> list[dict]:
        return self.from_conditions(now, ingest.get_conditions)

    def from_conditions(self, now: datetime, get_conditions) -> list[dict]:
        out = []
        for creek_id in ingest.SOURCES:
            g = (get_conditions(creek_id) or {}).get("gauge")
            if not g or g.get("pct_of_median") is None:
                # Unknown is not "normal": raise so a full-set store doesn't resolve live alerts.
                raise RuntimeError(f"no usable gauge reading for {creek_id}")
            pct = g["pct_of_median"]
            if pct >= 300:
                cat, sev, words = "high_flow", "watch", "far above normal (storm runoff likely)"
            elif pct < 25:
                cat, sev, words = "low_flow", "advisory", "far below normal (warm, low water stresses fish)"
            else:
                continue
            out.append(make_alert(
                source="usgs", source_id=f"{g['site_no']}:{cat}", source_name=self.name,
                category=cat, severity=sev if g.get("on_creek") else "info",
                title=f"{g.get('name') or g['site_no']}: flow {words.split(' (')[0]}",
                summary=(f"USGS gauge {g['site_no']} reads {g.get('discharge_cfs')} cfs, {pct}% of the "
                         f"long-term median for this date: {words}." +
                         ("" if g.get("on_creek") else " This gauge is not on the creek; regional context only.")),
                effective=g.get("observed_at") or now, updated=g.get("observed_at") or now,
                expires=now + timedelta(hours=2),
                creek_ids=[creek_id] if g.get("on_creek") else [], site_ids=[],
                area_desc=g.get("name") or "", url=g.get("source_url") or "https://waterdata.usgs.gov/",
                attribution=self.attribution,
            ))
        return out


class RiverDBBacteria(Source):
    """Volunteer E. coli above the state threshold (recent only), plus SSI's Pioneer Park page link."""
    id = "riverdb"
    name = "Volunteer water monitoring (RiverDB)"
    attribution = "Volunteer monitoring by SYRCL, Sierra Streams Institute and WCCA, via RiverDB"
    poll_interval_s = 86400

    def _fetch(self, now: datetime) -> list[dict]:
        out = []
        for creek_id in ("deer", "wolf"):
            for st in wq.get_water_quality(creek_id, now=now)["stations"]:
                self._seen += 1
                try:
                    a = ecoli_alert(creek_id, st, now)
                except Exception as e:  # noqa: BLE001 - one bad station record never drops the rest
                    self.skip(f"station {st.get('station_id') if isinstance(st, dict) else '?'}", e)
                    continue
                if a:
                    out.append(a)
        # SYRCL swim holes (South/Middle Yuba): region-wide, not tied to Wolf or Deer Creek.
        for sh in wq.get_swim_holes(now=now)["stations"]:
            self._seen += 1
            try:
                a = ecoli_alert(None, dict(sh, readings={"ecoli_mpn_100ml": sh["ecoli_mpn_100ml"]},
                                           site_id=None), now)
            except Exception as e:  # noqa: BLE001
                self.skip(f"swim hole {sh.get('station_id', '?')}", e)
                continue
            if a:
                out.append(a)
        out.append(make_alert(
            source="riverdb", source_id="ssi-pioneer-park-status", source_name="Sierra Streams Institute",
            category="bacteria", severity="info",
            title="Pioneer Park (Little Deer Creek) bacteria monitoring",
            summary=("Sierra Streams Institute posts its current E. coli results for Little Deer Creek at "
                     "Pioneer Park on its own page. Check it before swimming or wading there."),
            effective=LISTED_ON, expires=None,
            lat=39.25914, lon=-121.00983, creek_ids=["deer"], site_ids=["deer-pioneer-park"],
            area_desc="Little Deer Creek at Pioneer Park, Nevada City",
            url=SSI_PIONEER, attribution="Sierra Streams Institute",
        ))
        return out


def ecoli_alert(creek_id: str | None, st: dict, now: datetime) -> dict | None:
    ec = (st.get("readings") or {}).get("ecoli_mpn_100ml")
    age = st.get("age_days")
    if ec is None or ec <= ECOLI_LIMIT or age is None or age > ECOLI_RECENT_DAYS:
        return None
    d = datetime.fromisoformat(st["date"]).replace(tzinfo=timezone.utc)
    return make_alert(
        source="riverdb", source_id=f"{st['station_id']}:{st['date']}", source_name=st["credit"],
        category="bacteria", severity="watch" if age <= ECOLI_WATCH_DAYS else "advisory",
        title=f"E. coli above the recreational threshold at {st['name']}",
        summary=ecoli_text(ec, st["name"], st["date"]) + (" It also lowers this creek's Creek Watch score."
                                                       if creek_id else ""),
        instruction=("Consider skipping swimming or putting your face in the water here until a newer "
                     "test comes back lower, and wash hands after contact."),
        effective=d, expires=d + timedelta(days=ECOLI_RECENT_DAYS),
        lat=st.get("lat"), lon=st.get("lon"), creek_ids=[creek_id] if creek_id else [],
        site_ids=[st["site_id"]] if st.get("site_id") else [],
        area_desc=st["name"], url=st.get("source_url") or "https://riverdb.org/",
        attribution=st["credit"],
    )


class OEHHA(Source):
    """Standing state fish-consumption advisories (OEHHA) for water bodies in the region."""
    id = "oehha"
    name = "OEHHA fish consumption advisories"
    attribution = "California Office of Environmental Health Hazard Assessment (public domain)"
    poll_interval_s = 86400
    RESOURCE = "7805faef-ed21-43e9-a13e-4920a9440bb8"

    def _fetch(self, now: datetime) -> list[dict]:
        d = http.get_json("https://data.ca.gov/api/3/action/datastore_search"
                          f"?resource_id={self.RESOURCE}&q=Nevada&limit=200", timeout=10)
        out = []
        for r in d["result"]["records"]:
            self._seen += 1
            try:
                a = self._advisory(r)
            except Exception as e:  # noqa: BLE001 - one bad advisory record never drops the rest
                self.skip(f"advisory {r.get('_id') if isinstance(r, dict) else '?'}", e)
                continue
            if a:
                out.append(a)
        return out

    def _advisory(self, r):
        lat, lon = float(r["Latitude"]), float(r["Longitude"])   # unparseable = bad record (counted)
        if "nevada" not in (r.get("County") or "").lower() or not in_region(lat, lon):
            return None
        link = (r.get("Link") or "").strip()
        slug = re.sub(r"[^a-z0-9-]", "", link.rstrip("/").rsplit("/", 1)[-1].lower()) or str(r.get("_id"))
        return make_alert(
            source="oehha", source_id=slug, source_name=self.name,
            category="contamination", severity="info",
            title=f"Fish consumption advisory: {r['Advisory']}",
            summary=(f"The state has a fish-eating advisory for {r['Advisory']}. Check OEHHA's guidance "
                     "for which fish are safe to eat and how often."),
            effective=LISTED_ON, expires=None,
            # Standing advisories attach to a creek by NAME, not distance (a lake can sit
            # within 2 km of a creek line without being that creek).
            lat=lat, lon=lon, creek_ids=[c for c, nm in (("deer", "deer creek"), ("wolf", "wolf creek"))
                                         if nm in r["Advisory"].lower()],
            area_desc=f"{r['Advisory']} ({r.get('County')} County)",
            url=link or "https://oehha.ca.gov/fish/advisories", attribution=self.attribution,
        )


# Creek Watch's own early-warning rules (data/score.py warnings) -> alerts
WARNING_CATEGORY = {
    "contamination_alert": "contamination", "contamination_followup": "contamination",
    "orange_water_watch": "contamination",
    "runoff_sediment_watch": "runoff", "runoff_ahead": "runoff",
    "algal_bloom_watch": "algal_bloom", "bacteria_watch": "bacteria",
}


def creekwatch_alerts(creek_id: str, health: dict, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    out = []
    for w in (health or {}).get("warnings") or []:
        if w["id"] == "bacteria_watch":
            continue  # same sample is already published as the riverdb:<station>:<date> alert
        out.append(make_alert(
            source="creekwatch", source_id=f"{creek_id}:{w['id']}", source_name="Creek Watch",
            category=WARNING_CATEGORY.get(w["id"], "other"),
            severity=w["level"] if w["level"] in ("alert", "watch", "advisory") else "info",
            title=w["title"], summary=w["explanation"],
            effective=health.get("last_updated") or now, updated=health.get("last_updated") or now,
            expires=None, creek_ids=[creek_id], site_ids=[], area_desc="",
            url=f"https://creekwatch.realm.watch/#dashboard/{creek_id}",
            attribution="Creek Watch early-warning rules (citizen reports + public data)",
        ))
    return out
