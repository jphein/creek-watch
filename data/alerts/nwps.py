"""NOAA National Water Prediction Service: flood categories at river forecast points in the region."""
from __future__ import annotations

from datetime import datetime, timedelta

from . import http
from .model import Source, make_alert

# Wider than the county bbox: the only points with flood stages near us are downstream,
# Bear R nr Wheatland (BRWC1, -121.41) and Yuba R abv Marysville (MRYC1, -121.52).
NWPS_BBOX = (38.90, -121.60, 39.60, -120.00)  # S, W, N, E

FLOOD_SEVERITY = {"action": "advisory", "minor": "watch", "moderate": "alert", "major": "alert"}
WORDS = {"action": "near flood stage (action stage)", "minor": "minor flooding",
         "moderate": "moderate flooding", "major": "major flooding"}


class NWPS(Source):
    id = "nwps"
    name = "NOAA National Water Prediction Service"
    attribution = "NOAA National Water Prediction Service, public domain"
    poll_interval_s = 900

    def _fetch(self, now: datetime) -> list[dict]:
        s, w, n, e = NWPS_BBOX
        d = http.get_json("https://api.water.noaa.gov/nwps/v1/gauges"
                          f"?bbox.xmin={w}&bbox.ymin={s}&bbox.xmax={e}&bbox.ymax={n}&srid=EPSG_4326")
        out = []
        for g in d.get("gauges") or []:
            st = g.get("status") or {}
            for kind in ("observed", "forecast"):
                cat = ((st.get(kind) or {}).get("floodCategory") or "").lower()
                if cat not in FLOOD_SEVERITY:
                    continue  # no_flooding / not_defined / obs_not_current ...
                v = st[kind]
                when = "is at" if kind == "observed" else "is forecast to reach"
                out.append(make_alert(
                    source="nwps", source_id=f"{g['lid']}:{kind}", source_name=self.name,
                    category="flood", severity=FLOOD_SEVERITY[cat],
                    title=f"{g['name']}: {WORDS[cat]}",
                    summary=f"{g['name']} {when} {WORDS[cat]} "
                            f"({v.get('primary')} {v.get('primaryUnit', '')}).",
                    effective=v.get("validTime") or now, updated=v.get("validTime") or now,
                    expires=now + timedelta(hours=6),
                    lat=g.get("latitude"), lon=g.get("longitude"),
                    area_desc=g["name"],
                    url=f"https://water.noaa.gov/gauges/{g['lid']}",
                    attribution=self.attribution,
                ))
        return out
