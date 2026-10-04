"""Volunteer water-quality monitoring data from RiverDB (riverdb.org).

RiverDB hosts the monitoring data of three local groups:
  SYRCL - South Yuba River Citizens League: monthly samples on Deer Creek above and
          below Nevada City (2022 to present). Fetched LIVE (cached 24 h).
  SSI   - Sierra Streams Institute (formerly Friends of Deer Creek): 2000 to 2023.
  WCCA  - Wolf Creek Community Alliance: 2017 to 2019 in RiverDB.
SSI and WCCA are historical, so their latest samples are a committed snapshot
(wq_snapshot.json, built by tools/build_wq_snapshot.py); that keeps us from re-pulling
20 years of history from a volunteer-run server.

Public entry point: get_water_quality(creek_id) -> {"stations": [...], "fetched_at"}.
It never raises. The data is the monitoring groups' own; every station carries a credit.
"""
from __future__ import annotations

import json
import pathlib
import urllib.request
from datetime import datetime, timezone

GQL = "https://gql.riverdb.org/graphql"
UA = "creekwatch/0.1 (+https://github.com/jphein/creek-watch)"
_DIR = pathlib.Path(__file__).resolve().parent

AGENCIES = {
    "SYRCL": {"name": "South Yuba River Citizens League", "url": "https://yubariver.org"},
    "SSI": {"name": "Sierra Streams Institute", "url": "https://sierrastreamsinstitute.org"},
    "WCCA": {"name": "Wolf Creek Community Alliance", "url": "https://wolfcreekalliance.org"},
}

# Stations on (or right at) our creeks, matched to the nearest Creek Watch site.
# live=True -> refreshed from RiverDB; otherwise served from wq_snapshot.json.
STATIONS = {
    "deer": [
        dict(agency="SYRCL", id="17592187179149", name="Deer Creek Below Nevada City",
             lat=39.2603646, lon=-121.0320418, site_id="deer-angkula-seo-bridge", live=True),
        dict(agency="SYRCL", id="17592187179145", name="Deer Creek Above Nevada City",
             lat=39.26816, lon=-121.00081, site_id=None, live=True),
        dict(agency="SSI", id="285873023368579", name="SSI Site 4 (Tribute Trail)",
             lat=39.2603, lon=-121.032, site_id="deer-angkula-seo-bridge"),
        dict(agency="SSI", id="285873023368607", name="SSI Site 17 (downtown)",
             lat=39.26045, lon=-121.01892, site_id="deer-calanan-park"),
        dict(agency="SSI", id="285873023368577", name="SSI Site 13 (Pioneer Park, Little Deer Creek)",
             lat=39.25901, lon=-121.00943, site_id="deer-pioneer-park"),
        dict(agency="SSI", id="285873023368591", name="SSI Site 5 (Bitney Springs Rd)",
             lat=39.2468, lon=-121.1088, site_id="deer-bitney-springs-rd"),
        dict(agency="SSI", id="285873023368581", name="SSI Site 7 (below Lake Wildwood)",
             lat=39.2333, lon=-121.2228, site_id="deer-pleasant-valley-rd"),
    ],
    "wolf": [
        dict(agency="WCCA", id="285873023374516", name="WCCA Site 2 (Idaho Maryland Rd at Brunswick Rd)",
             lat=39.224505, lon=-121.02629, site_id="wolf-loma-rica-trail"),
        dict(agency="WCCA", id="285873023374524", name="WCCA Site 5 (Idaho Maryland Rd at Railroad Ave)",
             lat=39.222642, lon=-121.049719, site_id=None),
        dict(agency="WCCA", id="285873023374532", name="WCCA Site 8 (Glenn Jones Park)",
             lat=39.2078806, lon=-121.0695512, site_id="wolf-glen-jones-park"),
        dict(agency="WCCA", id="285873023410886", name="WCCA Site 8.5 (above Little Wolf Creek)",
             lat=39.2033256, lon=-121.0673974, site_id="wolf-daspah-seyo-trail"),
        dict(agency="WCCA", id="285873023410889", name="WCCA Site 9.2 (Allison Ranch Rd)",
             lat=39.165863, lon=-121.061192, site_id="wolf-allison-ranch-rd"),
        dict(agency="WCCA", id="285873023374546", name="WCCA Site 15 (above the Bear River)",
             lat=39.045784, lon=-121.115951, site_id="wolf-wolf-rd"),
    ],
}

# RiverDB parameter names vary by group; map them onto one vocabulary.
PARAMS = {
    "water_temp_c": ("H2O_Temp", "H2OTemp", "H2OTemp_C", "Temp"),
    "do_mg_l": ("DO", "DOxy_mgL"),            # only when unit is mg/L
    "ph": ("pH",),
    "turbidity_ntu": ("Turb", "Turb_NTUs"),
    "conductivity_us_cm": ("Cond",),
    "ecoli_mpn_100ml": ("EColi",),
}

_Q = ("query getStationData($stationRef: ID) { sitevisits(stationRef: $stationRef) "
      "{ date resultsv { is_valid mean unit param { name } } } }")


def _gql(ref: str, timeout: float) -> list[dict]:
    body = json.dumps({"query": _Q, "variables": {"stationRef": ref}}).encode()
    req = urllib.request.Request(GQL, data=body, headers={"Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    if d.get("errors"):
        raise RuntimeError(str(d["errors"])[:200])
    return d["data"]["sitevisits"] or []


def latest_readings(visits: list[dict]) -> dict | None:
    """Most recent visit that has at least one usable reading, normalised."""
    for v in sorted((v for v in visits if v.get("date")), key=lambda v: v["date"], reverse=True):
        out = {}
        for r in v.get("resultsv") or []:
            name = (r.get("param") or {}).get("name")
            if r.get("is_valid") is False or r.get("mean") is None or not name:
                continue
            for key, names in PARAMS.items():
                if name in names and key not in out:
                    if key == "do_mg_l" and (r.get("unit") or "").lower() != "mg/l":
                        continue
                    out[key] = round(float(r["mean"]), 2)
        if out:
            dates = sorted(x["date"] for x in visits if x.get("date"))
            return {"date": v["date"][:10], "readings": out, "visit_count": len(visits),
                    "first_date": dates[0][:10]}
    return None


def _snapshot() -> dict:
    try:
        return json.loads((_DIR / "wq_snapshot.json").read_text())["stations"]
    except (OSError, KeyError, ValueError):
        return {}


def get_water_quality(creek_id: str, *, timeout_s: float = 10, now: datetime | None = None,
                      fetch=None, cached_only: bool = False) -> dict:
    """Latest volunteer lab/field readings for each station on the creek (never raises)."""
    from . import ingest  # shared TTL cache

    now = now or datetime.now(timezone.utc)
    # RiverDB is a small volunteer-run server: short timeout (failures back off 15 min in _cached).
    fetch = fetch or (lambda ref: latest_readings(_gql(ref, min(timeout_s, 5))))
    snap = _snapshot()
    stations = []
    for st in STATIONS.get(creek_id, []):
        data, live = None, False
        if st.get("live"):
            key = f"riverdb:{st['id']}"
            if cached_only:   # no network: whatever a previous (or still-running) fetch cached
                data = ingest._peek(key, ttl=86400)   # expired -> flagged stale -> live: false
            else:
                data = ingest._cached(key, 86400, lambda ref=st["id"]: fetch(ref))
            # A stale value served during back-off is NOT live (it's the last good fetch).
            live = data is not None and not data.get("stale")
        if data is None:
            data = snap.get(st["id"])
        if not data:
            continue
        age = (now.date() - datetime.fromisoformat(data["date"]).date()).days
        ag = AGENCIES[st["agency"]]
        stations.append({
            "agency": st["agency"], "station_id": st["id"], "name": st["name"],
            "lat": st["lat"], "lon": st["lon"], "site_id": st["site_id"],
            "date": data["date"], "age_days": age, "readings": data["readings"],
            "visit_count": data.get("visit_count"), "first_date": data.get("first_date"),
            "live": live,
            "stale": bool(data.get("stale")),
            "credit": f'{ag["name"]} volunteer monitoring, via RiverDB',
            "source_url": f'https://riverdb.org/org/{st["agency"]}',
            "agency_url": ag["url"],
        })
    stations.sort(key=lambda s: s["date"], reverse=True)
    return {"stations": stations,
            "fetched_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z")}
