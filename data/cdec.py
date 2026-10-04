"""California Data Exchange Center (CDEC, DWR): regional river flow and reservoir storage.

Keyless JSON (dynamicapp/req/JSONDataServlet). CDEC's own station pages label times
"DATE / TIME PDT", i.e. California local time, so timestamps are converted from
America/Los_Angeles to UTC. CDEC hourly data lags (often ~10-12 h), so every value
carries observed_at and age_hours, and the API/UI should show the observation time.

get_river(now=None, timeout_s=10) -> {"stations": [...], "fetched_at"}; never raises.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")
UA = "creekwatch/0.1 (+https://github.com/jphein/creek-watch)"
CREDIT = "California Department of Water Resources, CDEC"
STATIONS = {
    # Deer Creek nr Smartsville (DCS) is deliberately omitted: it mirrors USGS 11418500,
    # which data.ingest already reads directly.
    "JBR": {"name": "South Yuba River at Jones Bar", "kind": "river", "sensors": {20: "flow_cfs", 1: "stage_ft"},
            "note": "Below the Hwy 49 / Purdon / Edwards Crossing swim holes, above Englebright Lake."},
    "ENG": {"name": "Englebright Lake (Yuba River)", "kind": "reservoir",
            "sensors": {15: "storage_af", 6: "elevation_ft"},
            "note": "Reservoir on the Yuba River that the South Yuba flows into (Deer Creek joins the Yuba below its dam)."},
}


def _get_json(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(5 * 1024 * 1024 + 1)[: 5 * 1024 * 1024])


def parse_cdec_time(s: str) -> datetime | None:
    """'2026-10-3 9:00' (California local) -> aware UTC datetime."""
    try:
        local = datetime.strptime(s.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=PACIFIC)
    except (AttributeError, ValueError):
        return None
    return local.astimezone(timezone.utc)


def latest(records: list[dict]) -> dict:
    """Latest valid value per (station, sensor) from a JSONDataServlet response."""
    best: dict[tuple, tuple[datetime, float]] = {}
    for r in records:
        try:
            v = float(r.get("value"))
        except (TypeError, ValueError):
            continue
        if v <= -9998:                       # CDEC missing-value sentinel (-9999)
            continue
        t = parse_cdec_time(r.get("obsDate") or r.get("date") or "")
        if t is None:
            continue
        k = (r.get("stationId"), int(r.get("SENSOR_NUM")))
        if k not in best or t > best[k][0]:
            best[k] = (t, v)
    return best


def get_river(now: datetime | None = None, timeout_s: float = 10, fetch=None) -> dict:
    now = now or datetime.now(timezone.utc)
    start = (now.astimezone(PACIFIC) - timedelta(days=2)).strftime("%Y-%m-%d")
    end = (now.astimezone(PACIFIC) + timedelta(days=1)).strftime("%Y-%m-%d")
    sensors = sorted({n for s in STATIONS.values() for n in s["sensors"]})
    url = ("https://cdec.water.ca.gov/dynamicapp/req/JSONDataServlet"
           f"?Stations={','.join(STATIONS)}&SensorNums={','.join(map(str, sensors))}"
           f"&dur_code=H&Start={start}&End={end}")
    out = []
    try:
        best = latest((fetch or (lambda u: _get_json(u, timeout_s)))(url))
    except Exception:  # noqa: BLE001 - never raise; the caller shows "unavailable"
        best = {}
    for sid, meta in STATIONS.items():
        vals, times = {}, []
        for num, key in meta["sensors"].items():
            if (sid, num) in best:
                t, v = best[(sid, num)]
                vals[key] = round(v, 2)
                times.append(t)
        if not vals:
            continue
        obs = max(times)
        out.append({
            "station_id": sid, "name": meta["name"], "kind": meta["kind"], "note": meta["note"],
            **vals,
            "observed_at": obs.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "age_hours": round((now - obs).total_seconds() / 3600, 1),
            "credit": CREDIT,
            "source_url": f"https://cdec.water.ca.gov/dynamicapp/QueryF?s={sid}",
        })
    return {"stations": out, "fetched_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z")}
