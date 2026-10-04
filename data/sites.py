"""Load the static creek/site seed data (built by data/tools/build_sites.py)."""
from __future__ import annotations

import json
import math
import pathlib
from functools import lru_cache

_DIR = pathlib.Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def _raw():
    creeks = json.loads((_DIR / "sites.json").read_text())
    geo = json.loads((_DIR / "creeks.geojson").read_text())
    return creeks, geo


def load_creeks(with_geojson: bool = True) -> list[dict]:
    """Shape of GET /api/creeks: [{id,name,town,description,geojson_line?,sites:[...]}].

    geojson_line is a GeoJSON FeatureCollection of that creek's LineStrings
    (main stem plus any tributary a site sits on; see feature.properties.main_stem).
    """
    creeks, geo = _raw()
    out = []
    for c in creeks:
        c = dict(c, sites=[dict(s) for s in c["sites"]])
        if with_geojson:
            c["geojson_line"] = {"type": "FeatureCollection",
                                 "features": [f for f in geo["features"]
                                              if f["properties"]["creek_id"] == c["id"]]}
        out.append(c)
    return out


def creek_ids() -> list[str]:
    return [c["id"] for c in _raw()[0]]


def get_site(site_id: str) -> dict | None:
    for c in _raw()[0]:
        for s in c["sites"]:
            if s["id"] == site_id:
                return dict(s, creek_id=c["id"])
    return None


def _km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def distance_to_creek_km(creek_id: str, lat: float, lon: float) -> float:
    """Approximate distance (km) from a point to the nearest vertex of the creek's lines.

    Simplified vertices are up to ~0.9 km apart on straight reaches (e.g. through
    Lake Wildwood), so this overestimates by at most ~0.45 km: plenty for the API's
    "reject reports > 25 km from the creek" rule, not for anything finer.
    """
    _, geo = _raw()
    return min(_km((lat, lon), (y, x))
               for f in geo["features"] if f["properties"]["creek_id"] == creek_id
               for x, y in f["geometry"]["coordinates"])


def nearest_site(lat: float, lon: float, creek_id: str | None = None) -> tuple[dict, float] | None:
    """(site_with_creek_id, km) of the closest seed site, optionally within one creek."""
    best = None
    for c in _raw()[0]:
        if creek_id and c["id"] != creek_id:
            continue
        for s in c["sites"]:
            d = _km((lat, lon), (s["lat"], s["lon"]))
            if best is None or d < best[1]:
                best = (dict(s, creek_id=c["id"]), d)
    return best
