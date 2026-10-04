"""Alert model (docs/ALERTS-SPEC.md), shared helpers, and the Source base class."""
from __future__ import annotations

import math
import threading
from datetime import datetime, timezone

from .. import sites

SEVERITIES = ("info", "advisory", "watch", "alert")
SEVERITY_ORDER = {s: i for i, s in enumerate(SEVERITIES)}
CATEGORIES = {"flood", "flash_flood", "storm", "heat", "sewage_spill", "algal_bloom", "bacteria",
              "low_flow", "high_flow", "contamination", "runoff", "other"}
STATUSES = {"active", "expired", "cancelled"}

# Nevada County, CA (spec): S, W, N, E
REGION_BBOX = (38.95, -121.30, 39.55, -120.00)
CREEK_NEAR_KM = 2.0     # an item this close to a creek line is "on" that creek
SITE_NEAR_KM = 1.0


def iso(d: datetime | None) -> str | None:
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(v) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def in_region(lat, lon) -> bool:
    s, w, n, e = REGION_BBOX
    return lat is not None and lon is not None and s <= lat <= n and w <= lon <= e


def _km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def creeks_near(lat, lon, km: float = CREEK_NEAR_KM) -> list[str]:
    if lat is None or lon is None:
        return []
    return [cid for cid in sites.creek_ids() if sites.distance_to_creek_km(cid, lat, lon) <= km]


def sites_near(lat, lon, km: float = SITE_NEAR_KM) -> list[str]:
    if lat is None or lon is None:
        return []
    out = []
    for c in sites.load_creeks(with_geojson=False):
        for s in c["sites"]:
            if _km((lat, lon), (s["lat"], s["lon"])) <= km:
                out.append(s["id"])
    return out


def clip(text: str | None, n: int = 280) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def make_alert(*, source: str, source_id: str, source_name: str, category: str, severity: str,
               title: str, summary: str, url: str, attribution: str, effective, updated=None,
               expires=None, status: str = "active", instruction: str | None = None,
               lat=None, lon=None, polygon_geojson=None, area_desc: str = "",
               creek_ids=None, site_ids=None) -> dict:
    """Build a spec-shaped Alert dict; validates the enums so a bad adapter fails its tests."""
    assert category in CATEGORIES, category
    assert severity in SEVERITY_ORDER, severity
    assert status in STATUSES, status
    eff = parse_time(effective)
    return {
        "id": f"{source}:{source_id}",
        "source": source,
        "source_name": source_name,
        "category": category,
        "severity": severity,
        "title": clip(title, 140),
        "summary": clip(summary),
        "instruction": clip(instruction, 600) if instruction else None,
        "area": {
            "creek_ids": sorted(set(creek_ids if creek_ids is not None else creeks_near(lat, lon))),
            "site_ids": sorted(set(site_ids if site_ids is not None else sites_near(lat, lon))),
            "lat": lat, "lon": lon,
            "polygon_geojson": polygon_geojson,
            "area_desc": clip(area_desc, 200),
        },
        "effective": iso(eff),
        "expires": iso(parse_time(expires)),
        "updated": iso(parse_time(updated) or eff),
        "status": status,
        "url": url,
        "attribution": attribution,
    }


class Source:
    """One alert source. Subclasses implement _fetch(now) -> list[Alert]; fetch() never raises."""

    id = "base"
    name = "base"
    attribution = ""
    poll_interval_s = 900

    def __init__(self):
        self.last_error: str | None = None
        self.last_ok: str | None = None
        self._lock = threading.Lock()

    def _fetch(self, now: datetime) -> list[dict]:  # pragma: no cover - abstract
        raise NotImplementedError

    def fetch(self, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(timezone.utc)
        try:
            out = self._fetch(now)
        except Exception as e:  # noqa: BLE001 - one bad source must never break the others
            with self._lock:
                self.last_error = f"{type(e).__name__}: {e}"[:300]
            return []
        with self._lock:
            self.last_error, self.last_ok = None, iso(now)
        return out
