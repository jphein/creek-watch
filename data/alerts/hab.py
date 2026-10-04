"""California freshwater harmful algal bloom reports (State Water Board FHABs, data.ca.gov)."""
from __future__ import annotations

import urllib.parse
from datetime import datetime, timedelta

from . import http
from .model import REGION_BBOX, SEVERITY_ORDER, Source, make_alert, parse_time

RESOURCE = "c6a36b91-ad38-4611-8750-87ee99e497dd"   # FHABS BLOOM REPORTS
PORTAL = "https://mywaterquality.ca.gov/habs/where/freshwater_events.html"
HISTORY_DAYS = 365
# Advisory sign type -> severity (spec: Danger alert, Warning watch, Caution advisory)
ADVISORY = [("danger", "alert"), ("warning", "watch"), ("caution", "advisory"),
            ("algal mat", "advisory"), ("general awareness", "info")]


def advisory_severity(types) -> tuple[str, str | None]:
    t = (types or "").lower()
    for needle, sev in ADVISORY:
        if needle in t:
            return sev, needle
    return "info", None


class HAB(Source):
    id = "hab"
    name = "California Freshwater Harmful Algal Blooms (State Water Board)"
    attribution = "California State Water Resources Control Board, FHABs bloom reports (public domain)"
    poll_interval_s = 3600

    def _fetch(self, now: datetime) -> list[dict]:
        s, w, n, e = REGION_BBOX
        since = (now - timedelta(days=HISTORY_DAYS)).date().isoformat()
        sql = (f'SELECT "Bloom_Report_ID","Observation_Date","Water_Body_Name","Landmark",'
               f'"Bloom_Latitude","Bloom_Longitude","Advisory_Recommended","Reported_Advisory_Types","Case_Status",'
               f'"AdvisoryEndDate" FROM "{RESOURCE}" '
               f'WHERE "Bloom_Latitude" BETWEEN {s} AND {n} AND "Bloom_Longitude" BETWEEN {w} AND {e} '
               f'AND "Observation_Date" >= \'{since}\' ORDER BY "Observation_Date" DESC LIMIT 500')
        d = http.get_json("https://data.ca.gov/api/3/action/datastore_search_sql?sql=" + urllib.parse.quote(sql),
                          timeout=60)
        return self.from_records(d["result"]["records"], now)

    def from_records(self, records, now: datetime) -> list[dict]:
        # One bloom report can appear on several rows (one per advisory): keep the most severe.
        best: dict[str, dict] = {}
        for r in records:
            rid = str(r.get("Bloom_Report_ID") or "").strip()
            if not rid:
                continue
            # The posted sign level lives in Advisory_Recommended (e.g. "Caution"); the older
            # Reported_Advisory_Types column is usually empty. Take the more severe of the two.
            sev, kind = max((advisory_severity(r.get("Advisory_Recommended")),
                             advisory_severity(r.get("Reported_Advisory_Types"))),
                            key=lambda t: SEVERITY_ORDER[t[0]])
            if rid not in best or SEVERITY_ORDER[sev] > SEVERITY_ORDER[best[rid]["_sev"]]:
                best[rid] = dict(r, _sev=sev, _kind=kind)
        out = []
        for rid, r in best.items():
            obs = parse_time(r.get("Observation_Date"))
            if obs is None:
                continue
            lat, lon = r.get("Bloom_Latitude"), r.get("Bloom_Longitude")
            lat = float(lat) if lat is not None else None
            lon = float(lon) if lon is not None else None
            open_ = (r.get("Case_Status") or "").lower() in ("open", "ongoing")
            name = (r.get("Water_Body_Name") or "a water body").strip()
            sign = (r.get("Advisory_Recommended") or r.get("Reported_Advisory_Types") or "").strip()
            sign_txt = f' The posted advisory is "{sign}".' if r["_kind"] else ""
            out.append(make_alert(
                source="hab", source_id=rid, source_name=self.name,
                category="algal_bloom", severity=r["_sev"],
                title=f"Algal bloom reported: {name}",
                summary=(f"A harmful algal bloom was reported at {name} on {obs:%b %-d, %Y}."
                         f"{sign_txt} Case is {(r.get('Case_Status') or 'unknown').lower()}."),
                instruction=("Keep pets and children out of discolored or scummy water, don't let dogs "
                             "drink it, and check the state HABs portal before swimming.") if open_ else None,
                effective=obs, updated=obs, expires=parse_time(r.get("AdvisoryEndDate")),
                status="active" if open_ else "expired",
                lat=lat, lon=lon, area_desc=f"{name}{' - ' + r['Landmark'] if r.get('Landmark') else ''}",
                url=PORTAL, attribution=self.attribution,
            ))
        return out
