"""National Weather Service active alerts (api.weather.gov), water-related events only."""
from __future__ import annotations

from datetime import datetime

from . import http
from .model import Source, make_alert, parse_time

# Per-creek query points (same as data/ingest.py).
POINTS = {"wolf": (39.2081, -121.0696), "deer": (39.2603, -121.0335)}

# Event name (lower-case substring) -> category. Anything else (air quality, wind, fire…) is dropped.
EVENT_CATEGORY = [
    ("flash flood", "flash_flood"),
    ("flood", "flood"),
    ("hydrologic outlook", "flood"),
    ("heavy rain", "storm"),
    ("excessive heat", "heat"),
    ("extreme heat", "heat"),
    ("heat", "heat"),
]
CAP_SEVERITY = {"extreme": "alert", "severe": "alert", "moderate": "watch", "minor": "advisory"}


def category_for(event: str) -> str | None:
    e = (event or "").lower()
    for needle, cat in EVENT_CATEGORY:
        if needle in e:
            return cat
    return None


def stable_id(props: dict) -> str:
    """Updates/cancels carry a new id plus `references` to earlier messages; the earliest
    referenced identifier is the stable thread id, so an update replaces its alert."""
    refs = props.get("references") or []
    if refs:
        first = min(refs, key=lambda r: (r.get("sent") or "", r.get("identifier") or ""))
        return first.get("identifier") or props["id"]
    return props["id"]


class NWS(Source):
    id = "nws"
    name = "National Weather Service"
    attribution = "National Weather Service (NOAA), public domain"
    poll_interval_s = 300

    def _fetch(self, now: datetime) -> list[dict]:
        seen: dict[str, dict] = {}
        creeks_for: dict[str, set] = {}
        errors = []
        for creek_id, (lat, lon) in POINTS.items():
            try:
                d = http.get_json(f"https://api.weather.gov/alerts/active?point={lat},{lon}",
                                  accept="application/geo+json")
            except Exception as e:  # noqa: BLE001 - one point failing shouldn't drop the other
                errors.append(f"{creek_id}: {e}")
                continue
            for f in d.get("features") or []:
                p = f.get("properties") or {}
                if p.get("status") != "Actual" or category_for(p.get("event")) is None:
                    continue
                sid = stable_id(p)
                creeks_for.setdefault(sid, set()).add(creek_id)
                # keep the newest message of the thread
                if sid not in seen or (p.get("sent") or "") > (seen[sid]["properties"].get("sent") or ""):
                    seen[sid] = f
        if errors and not seen and len(errors) == len(POINTS):
            raise RuntimeError("; ".join(errors))
        out = []
        for sid, f in seen.items():
            p = f["properties"]
            ends = parse_time(p.get("ends")) or parse_time(p.get("expires"))
            if p.get("messageType") == "Cancel":
                status = "cancelled"
            elif ends and ends < now:
                status = "expired"
            else:
                status = "active"
            lat, lon = POINTS[sorted(creeks_for[sid])[0]]
            out.append(make_alert(
                source="nws", source_id=sid, source_name=p.get("senderName") or self.name,
                category=category_for(p["event"]),
                severity=CAP_SEVERITY.get((p.get("severity") or "").lower(), "info"),
                title=p["event"],
                summary=p.get("headline") or p.get("description") or p["event"],
                instruction=p.get("instruction"),
                effective=p.get("onset") or p.get("effective") or p.get("sent"),
                updated=p.get("sent"), expires=ends, status=status,
                lat=None, lon=None, polygon_geojson=f.get("geometry"),
                area_desc=p.get("areaDesc") or "",
                creek_ids=sorted(creeks_for[sid]), site_ids=[],
                url=f"https://forecast.weather.gov/MapClick.php?lat={lat}&lon={lon}",
                attribution=self.attribution,
            ))
        return out
