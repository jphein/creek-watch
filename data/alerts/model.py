"""Alert model (docs/ALERTS-SPEC.md), shared helpers, and the Source base class."""
from __future__ import annotations

import math
import threading
import urllib.parse
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


# Per-source https host allowlist and fallback portal. An alert url that isn't https on an
# allowed host (or contains characters that could break a feed) is replaced by the portal.
SOURCE_URLS = {
    "nws": ({"forecast.weather.gov", "alerts.weather.gov", "www.weather.gov", "api.weather.gov"},
            "https://www.weather.gov/sto/"),
    "nwps": ({"water.noaa.gov"}, "https://water.noaa.gov/"),
    "usgs": ({"waterdata.usgs.gov"}, "https://waterdata.usgs.gov/"),
    "sso": ({"ciwqs.waterboards.ca.gov", "www.waterboards.ca.gov"},
            "https://ciwqs.waterboards.ca.gov/ciwqs/readOnly/PublicReportSSOServlet?reportAction=criteria&reportId=sso_main"),
    "hab": ({"mywaterquality.ca.gov"}, "https://mywaterquality.ca.gov/habs/where/freshwater_events.html"),
    "riverdb": ({"riverdb.org", "sierrastreamsinstitute.org"}, "https://riverdb.org/"),
    "oehha": ({"oehha.ca.gov"}, "https://oehha.ca.gov/fish/advisories"),
    "creekwatch": ({"creekwatch.realm.watch"}, "https://creekwatch.realm.watch/"),
}
_BAD_URL_CHARS = set('<>"\' \t\r\n`')


def safe_url(source: str, url: str | None) -> str:
    hosts, portal = SOURCE_URLS.get(source, (set(), "https://creekwatch.realm.watch/"))
    try:
        u = urllib.parse.urlsplit(url or "")
    except ValueError:
        return portal
    if u.scheme != "https" or u.hostname not in hosts or any(c in _BAD_URL_CHARS for c in (url or "")):
        return portal
    return url


MAX_POLYGON_POINTS = 2000


def safe_polygon(geom):
    """Only Polygon/MultiPolygon with a bounded number of numeric points; anything else -> None."""
    if not isinstance(geom, dict) or geom.get("type") not in ("Polygon", "MultiPolygon"):
        return None
    rings = geom.get("coordinates")
    rings = [rings] if geom["type"] == "Polygon" else rings
    n = 0
    try:
        for poly in rings:
            for ring in poly:
                for pt in ring:
                    n += 1
                    if n > MAX_POLYGON_POINTS or len(pt) < 2 or not all(isinstance(c, (int, float)) for c in pt[:2]):
                        return None
    except TypeError:
        return None
    return {"type": geom["type"], "coordinates": geom["coordinates"]}


def make_alert(*, source: str, source_id: str, source_name: str, category: str, severity: str,
               title: str, summary: str, url: str, attribution: str, effective, updated=None,
               expires=None, status: str = "active", instruction: str | None = None,
               lat=None, lon=None, polygon_geojson=None, area_desc: str = "",
               creek_ids=None, site_ids=None) -> dict:
    """Build a spec-shaped Alert dict. Raises ValueError on a bad enum or missing effective time
    (explicit raises, not asserts, so they survive `python -O`)."""
    if category not in CATEGORIES:
        raise ValueError(f"bad category {category!r}")
    if severity not in SEVERITY_ORDER:
        raise ValueError(f"bad severity {severity!r}")
    if status not in STATUSES:
        raise ValueError(f"bad status {status!r}")
    eff = parse_time(effective)
    if eff is None:
        raise ValueError(f"bad effective time {effective!r}")
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
            "polygon_geojson": safe_polygon(polygon_geojson),
            "area_desc": clip(area_desc, 200),
        },
        "effective": iso(eff),
        "expires": iso(parse_time(expires)),
        "updated": iso(parse_time(updated) or eff),
        "status": status,
        "url": safe_url(source, url),
        "attribution": attribution,
    }


class Source:
    """One alert source. Subclasses implement _fetch(now) -> list[Alert].

    run(now)   -> raises on source failure (used by the API poller via ADAPTERS)
    fetch(now) -> never raises; failures go to .last_error (used by fetch_all/scripts)
    Bad individual records are skipped (self.skip) and counted, never fail the whole source.
    """

    id = "base"
    name = "base"
    attribution = ""
    poll_interval_s = 900
    deadline_s = 30          # wall-clock budget for one fetch; >= the source's HTTP timeout

    def __init__(self):
        self.last_error: str | None = None
        self.last_ok: str | None = None
        self.last_skipped = 0
        self._skips: list[str] = []
        self._lock = threading.Lock()

    def _fetch(self, now: datetime) -> list[dict]:  # pragma: no cover - abstract
        raise NotImplementedError

    def skip(self, record_hint, err: Exception) -> None:
        self._skips.append(f"{record_hint}: {type(err).__name__}: {err}"[:200])

    def run(self, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(timezone.utc)
        self._skips = []
        raw = self._fetch(now)                       # source-level failure propagates
        out, idx = [], {}
        for a in raw:                                # one alert per id in a full-set result
            if a["id"] in idx:
                out[idx[a["id"]]] = a
            else:
                idx[a["id"]] = len(out)
                out.append(a)
        with self._lock:
            self.last_ok, self.last_skipped = iso(now), len(self._skips)
            self.last_error = (f"{len(self._skips)} record(s) skipped; first: {self._skips[0]}"
                               if self._skips else None)
        return out

    def fetch(self, now: datetime | None = None) -> list[dict]:
        try:
            return self.run(now)
        except Exception as e:  # noqa: BLE001 - one bad source must never break the others
            with self._lock:
                self.last_error = f"{type(e).__name__}: {e}"[:300]
            return []
