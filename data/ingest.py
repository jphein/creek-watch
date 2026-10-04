"""Public-data ingest for Creek Watch: USGS gauges, NWS weather, Open-Meteo rainfall.

Public entry point:  get_conditions(creek_id) -> dict  (shape of GET /api/conditions)

Design rules:
- Keyless, public sources only; standard library only.
- Never raises on upstream trouble: a failed source becomes null and the rest still
  returns. A failed refresh serves the last good value marked "stale": true.
- In-process TTL cache, so calling it on every request is fine. Sources are fetched
  in parallel; worst case latency is about one timeout.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

log = logging.getLogger("creekwatch.data")
PACIFIC = ZoneInfo("America/Los_Angeles")
UA = "creekwatch/0.1 (+https://github.com/jphein/creek-watch)"

# Per-creek source config. See data/SOURCES.md for how these were chosen.
SOURCES = {
    "wolf": {
        "gauge": {
            "site_no": "11424000",
            "on_creek": False,
            "note": "Wolf Creek has no live stream gauge. This is the Bear River near "
                    "Wheatland, about 38 km downstream of Grass Valley and below Camp Far "
                    "West Reservoir: regional context only, not a Wolf Creek reading.",
        },
        "point": (39.2081, -121.0696),  # Wolf Creek Trail, Grass Valley
        "nws_station": "KGOO",          # Nevada County Air Park, ~6 km E of downtown GV
        "nws_forecast": "https://api.weather.gov/gridpoints/STO/61,93/forecast",
    },
    "deer": {
        "gauge": {
            "site_no": "11418500",
            "on_creek": True,
            "note": "USGS gauge on Deer Creek itself near Smartsville, about 22 km "
                    "downstream of Nevada City and below Lake Wildwood, so town-level "
                    "changes show up late and damped.",
        },
        "point": (39.2603, -121.0335),  # Deer Creek Tribute Trail, Nevada City
        "nws_station": "KGOO",          # Nevada County Air Park, ~4.5 km SE of NC
        "nws_forecast": "https://api.weather.gov/gridpoints/STO/63,95/forecast",
    },
}

GAUGE_NAMES = {"11424000": "BEAR R NR WHEATLAND CA", "11418500": "DEER C NR SMARTSVILLE CA"}

WQ_WAIT_S = 3.0   # don't hold a request longer than this for RiverDB; answer from the snapshot

TTL = {"gauge": 900, "weather": 900, "stats": 86400}


# --------------------------------------------------------------------------- http
def _http_get_text(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/geo+json, application/json, text/plain"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _http_get_json(url: str, timeout: float):
    return json.loads(_http_get_text(url, timeout))


def _retry_once(fn):
    """USGS WaterServices throws intermittent 503s (seen 2026-10-03): retry once, then give up."""
    try:
        return fn()
    except Exception:  # noqa: BLE001
        time.sleep(0.5)
        return fn()


# -------------------------------------------------------------------------- cache
_cache: dict[str, tuple[float, object]] = {}
_failed: dict[str, float] = {}
_inflight: set[str] = set()   # keys with a fetch running right now (never start a duplicate)
_lock = threading.Lock()


FAIL_BACKOFF_S = 900   # after a failed refresh, don't retry that upstream for 15 min


def _stale(hit):
    if hit and hit[1] is not None:
        return dict(hit[1], stale=True) if isinstance(hit[1], dict) else hit[1]
    return None


def _cached(key: str, ttl: float, fn):
    """Return fn() cached for ttl seconds. On failure, serve last good value as stale.

    Failures are remembered for FAIL_BACKOFF_S: until then we serve stale/None immediately
    instead of re-calling a down upstream on every request (2026-10-03: RiverDB refusing
    connections made every uncached /api/conditions take ~16 s)."""
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        failed_at = _failed.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    if failed_at is not None and now - failed_at < FAIL_BACKOFF_S:
        return _stale(hit)
    with _lock:
        if key in _inflight:      # another request/prewarm is already fetching this: don't pile on
            return _stale(hit)
        _inflight.add(key)
    err = None
    try:
        val = fn()
    except Exception as e:  # noqa: BLE001 - any upstream failure degrades to stale/None
        val, err = None, e
    with _lock:
        _inflight.discard(key)
        if val is not None:
            _cache[key] = (now, val)
            _failed.pop(key, None)
        else:
            _failed[key] = now
    if val is None:
        # At most one line per upstream per FAIL_BACKOFF_S: the back-off above stops re-calls.
        log.warning("upstream %s failed (%s); serving %s for %d min", key,
                    f"{type(err).__name__}: {err}"[:200] if err else "no data",
                    "last good value" if hit else "nothing", FAIL_BACKOFF_S // 60)
    return val if val is not None else _stale(hit)


def _peek(key: str):
    """Cached value for key without fetching (fresh, or flagged stale), else None."""
    with _lock:
        hit = _cache.get(key)
    return hit[1] if hit else None


def clear_cache():
    with _lock:
        _cache.clear()
        _failed.clear()
        _inflight.clear()


def _utc_iso(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc) \
            .isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ------------------------------------------------------------------------ fetchers
def fetch_gauge(site_no: str, timeout: float = 8) -> dict | None:
    """Latest discharge/stage: the new USGS Water Data OGC API first (~0.25 s), then legacy
    NWIS WaterServices (measured 0.6-7.6 s and intermittent 503s on 2026-10-03)."""
    try:
        got = fetch_gauge_ogc(site_no, timeout)
        if got:
            return got
    except Exception:  # noqa: BLE001
        pass
    return fetch_gauge_nwis(site_no, timeout)


def fetch_gauge_ogc(site_no: str, timeout: float = 8) -> dict | None:
    """USGS Water Data OGC API (the successor to WaterServices)."""
    url = (f"https://api.waterdata.usgs.gov/ogcapi/v0/collections/latest-continuous/items"
           f"?f=json&monitoring_location_id=USGS-{site_no}&parameter_code=00060,00065")
    feats = _http_get_json(url, timeout).get("features") or []
    if not feats:
        return None
    out = {"site_no": site_no, "name": GAUGE_NAMES.get(site_no, site_no),
           "discharge_cfs": None, "gage_height_ft": None, "observed_at": None, "provisional": None,
           "source_url": f"https://waterdata.usgs.gov/monitoring-location/{site_no}/"}
    for f in feats:
        p = f.get("properties") or {}
        try:
            v = float(p.get("value"))
        except (TypeError, ValueError):
            continue
        if p.get("parameter_code") == "00060":
            out["discharge_cfs"] = v
        elif p.get("parameter_code") == "00065":
            out["gage_height_ft"] = v
        obs = _utc_iso(p.get("time"))
        if obs and (out["observed_at"] is None or obs > out["observed_at"]):
            out["observed_at"] = obs
        out["provisional"] = (p.get("approval_status") or "").lower() == "provisional"
    return out if out["observed_at"] else None


def fetch_gauge_nwis(site_no: str, timeout: float = 8) -> dict | None:
    url = (f"https://waterservices.usgs.gov/nwis/iv/?format=json&sites={site_no}"
           f"&parameterCd=00060,00065&siteStatus=all")
    d = _http_get_json(url, timeout)
    ts = d["value"]["timeSeries"]
    if not ts:
        return None
    out = {"site_no": site_no, "name": ts[0]["sourceInfo"]["siteName"],
           "discharge_cfs": None, "gage_height_ft": None, "observed_at": None,
           "provisional": None,
           "source_url": f"https://waterdata.usgs.gov/monitoring-location/{site_no}/"}
    for t in ts:
        code = t["variable"]["variableCode"][0]["value"]
        vals = t["values"][0]["value"]
        if not vals:
            continue
        last = vals[-1]
        try:
            v = float(last["value"])
        except (TypeError, ValueError):
            continue
        nodata = t["variable"].get("noDataValue")
        if nodata is not None and v == nodata:
            continue
        if code == "00060":
            out["discharge_cfs"] = v
        elif code == "00065":
            out["gage_height_ft"] = v
        obs = _utc_iso(last["dateTime"])
        if obs and (out["observed_at"] is None or obs > out["observed_at"]):
            out["observed_at"] = obs
        out["provisional"] = "P" in (last.get("qualifiers") or [])
    return out


def fetch_flow_median(site_no: str, when: datetime | None = None, timeout: float = 8) -> dict | None:
    """Long-term daily percentiles of discharge for today's calendar day (USGS stat service)."""
    when = when or datetime.now(timezone.utc)
    url = (f"https://waterservices.usgs.gov/nwis/stat/?format=rdb&sites={site_no}"
           f"&statReportType=daily&statTypeCd=median,p25,p75&parameterCd=00060")
    text = _retry_once(lambda: _http_get_text(url, timeout))
    if text.lstrip().startswith("<"):
        return None  # HTML error page
    rows = [ln.split("\t") for ln in text.splitlines() if ln and not ln.startswith("#")]
    if len(rows) < 3:
        return None
    hdr = rows[0]
    idx = {h: i for i, h in enumerate(hdr)}
    local = when.astimezone(PACIFIC)  # USGS daily stats are by local calendar day
    for r in rows[2:]:
        try:
            if int(r[idx["month_nu"]]) == local.month and int(r[idx["day_nu"]]) == local.day:
                return {"p25_cfs": float(r[idx["p25_va"]]), "median_cfs": float(r[idx["p50_va"]]),
                        "p75_cfs": float(r[idx["p75_va"]]),
                        "years": f'{r[idx["begin_yr"]]}-{r[idx["end_yr"]]}',
                        "source_url": url}
        except (KeyError, ValueError, IndexError):
            continue
    return None


def fetch_nws_obs(station: str, timeout: float = 8) -> dict | None:
    url = f"https://api.weather.gov/stations/{station}/observations/latest"
    p = _http_get_json(url, timeout)["properties"]
    c = (p.get("temperature") or {}).get("value")
    return {"temp_f": None if c is None else round(c * 9 / 5 + 32, 1),
            "description": p.get("textDescription") or None,
            "observed_at": _utc_iso(p.get("timestamp")),
            "station": station,
            "source_url": f"https://api.weather.gov/stations/{station}/observations/latest"}


def fetch_nws_forecast(url: str, timeout: float = 8) -> dict | None:
    periods = _http_get_json(url, timeout)["properties"]["periods"]
    if not periods:
        return None
    p0 = periods[0]
    pop = (p0.get("probabilityOfPrecipitation") or {}).get("value")
    return {"forecast_short": f'{p0["name"]}: {p0["shortForecast"]}, {p0["temperature"]}°{p0.get("temperatureUnit", "F")}',
            "precip_chance_pct": pop,
            "source_url": url}


def fetch_rain(lat: float, lon: float, timeout: float = 8, now: datetime | None = None) -> dict | None:
    """Past-24h and next-24h precipitation (inches) from Open-Meteo hourly (gridded model data)."""
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           f"&hourly=precipitation&past_days=2&forecast_days=2&precipitation_unit=inch&timezone=UTC")
    d = _http_get_json(url, timeout)
    now = (now or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    past = nxt = 0.0
    seen_past = seen_next = 0
    for t, v in zip(d["hourly"]["time"], d["hourly"]["precipitation"]):
        ts = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
        if v is None:
            continue
        if now - timedelta(hours=24) < ts <= now:
            past += v; seen_past += 1
        elif now < ts <= now + timedelta(hours=24):
            nxt += v; seen_next += 1
    return {"precip_24h_in": round(past, 2) if seen_past else None,
            "precip_next_24h_in": round(nxt, 2) if seen_next else None,
            "source_url": f"https://open-meteo.com/en/docs#latitude={lat}&longitude={lon}"}


def flow_stats(site_no: str, when: datetime | None = None) -> dict | None:
    """Long-term daily discharge percentiles for this calendar day, from the committed
    snapshot data/flow_stats.json (the live USGS stat service 503s often, and
    60-90-year percentiles do not change week to week). fetch_flow_median() is the
    live equivalent, used to refresh the snapshot."""
    try:
        snap = _flow_snapshot()
        site = snap["sites"][site_no]
    except (OSError, KeyError, ValueError):
        return None
    day = (when or datetime.now(timezone.utc)).astimezone(PACIFIC).strftime("%m-%d")
    v = site["days"].get(day) or site["days"].get("02-28" if day == "02-29" else day)
    if not v:
        return None
    return {"p25_cfs": v[0], "median_cfs": v[1], "p75_cfs": v[2], "years": site["years"]}


_snap = None


def _flow_snapshot():
    global _snap
    if _snap is None:
        import pathlib
        _snap = json.loads((pathlib.Path(__file__).with_name("flow_stats.json")).read_text())
    return _snap


# ---------------------------------------------------------------------- public API
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="creekwatch-ingest")


def prewarm(creek_ids=None) -> threading.Thread:
    """Warm every creek's conditions in a daemon thread and return at once.

    Call at app startup so the first visitor after a (re)deploy doesn't wait on cold
    upstreams (RiverDB timeouts measured at ~10 s per fresh process on 2026-10-03).
    Never blocks the caller and never raises."""
    ids = list(creek_ids or SOURCES)

    def run():
        for cid in ids:
            t0 = time.time()
            try:
                get_conditions(cid)   # module-global lookup, so tests can patch it
                log.info("prewarmed conditions for %s in %.1fs", cid, time.time() - t0)
            except Exception as e:  # noqa: BLE001
                log.warning("prewarm %s failed: %s", cid, e)

    t = threading.Thread(target=run, name="creekwatch-prewarm", daemon=True)
    t.start()
    return t


def get_conditions(creek_id: str, *, max_age_s: int | None = None, timeout_s: float = 8) -> dict:
    """Current public conditions for one creek, shaped like GET /api/conditions.

    {gauge: {...}|null, weather: {...}|null, fetched_at}. Unknown creek -> ValueError.
    """
    if creek_id not in SOURCES:
        raise ValueError(f"unknown creek_id {creek_id!r}")
    cfg = SOURCES[creek_id]
    g = cfg["gauge"]
    ttl = (lambda k: max_age_s if max_age_s is not None else TTL[k])
    lat, lon = cfg["point"]

    jobs = {
        "gauge": lambda: _cached(f"gauge:{g['site_no']}", ttl("gauge"), lambda: fetch_gauge(g["site_no"], timeout_s)),
        "obs": lambda: _cached(f"obs:{cfg['nws_station']}", ttl("weather"), lambda: _retry_once(lambda: fetch_nws_obs(cfg["nws_station"], timeout_s))),
        "fc": lambda: _cached(f"fc:{cfg['nws_forecast']}", ttl("weather"), lambda: _retry_once(lambda: fetch_nws_forecast(cfg["nws_forecast"], timeout_s))),
        "rain": lambda: _cached(f"rain:{lat},{lon}", ttl("weather"), lambda: _retry_once(lambda: fetch_rain(lat, lon, timeout_s))),
    }
    from . import wq   # lazy: wq imports ingest
    jobs["wq"] = lambda: wq.get_water_quality(creek_id, timeout_s=timeout_s)
    from . import cdec
    jobs["river"] = lambda: _cached("cdec:river", ttl("gauge"), lambda: cdec.get_river(timeout_s=timeout_s))
    futs = {k: _pool.submit(fn) for k, fn in jobs.items()}
    res = {}
    for k, f in futs.items():
        try:
            res[k] = f.result(timeout=WQ_WAIT_S if k == "wq" else timeout_s * 2 + 2)
        except Exception:  # noqa: BLE001
            res[k] = None
            if k == "wq":
                # RiverDB slow (e.g. a cold process after a deploy): answer now from the snapshot
                # plus any cached live value; the job keeps running and fills the cache for the
                # next request. No fetch here, and no failure is recorded for the still-running job.
                try:
                    res[k] = wq.get_water_quality(creek_id, timeout_s=timeout_s, cached_only=True)
                except Exception:  # noqa: BLE001
                    res[k] = None

    gauge = None
    if res["gauge"]:
        gauge = dict(res["gauge"], on_creek=g["on_creek"], note=g["note"])
        st = flow_stats(g["site_no"])
        gauge["median_cfs_today"] = st["median_cfs"] if st else None
        gauge["p25_cfs_today"] = st["p25_cfs"] if st else None
        gauge["p75_cfs_today"] = st["p75_cfs"] if st else None
        gauge["pct_of_median"] = (round(100 * gauge["discharge_cfs"] / st["median_cfs"])
                                  if st and st["median_cfs"] and gauge["discharge_cfs"] is not None else None)
        gauge["stats_years"] = st["years"] if st else None

    weather = None
    obs, fc, rain = res["obs"], res["fc"], res["rain"]
    if obs or fc or rain:
        weather = {
            "temp_f": obs["temp_f"] if obs else None,
            "conditions": obs["description"] if obs else None,
            "precip_24h_in": rain["precip_24h_in"] if rain else None,
            "precip_next_24h_in": rain["precip_next_24h_in"] if rain else None,
            "forecast_short": fc["forecast_short"] if fc else None,
            "precip_chance_pct": fc["precip_chance_pct"] if fc else None,
            "observed_at": obs["observed_at"] if obs else None,
            "station": cfg["nws_station"],
            "source_url": (obs or fc or {}).get("source_url") or cfg["nws_forecast"],
            "forecast_url": cfg["nws_forecast"],
            "precip_source_url": rain["source_url"] if rain else None,
            "stale": any(bool(x and x.get("stale")) for x in (obs, fc, rain)),
        }
    water_quality = res.get("wq") or {"stations": []}
    river = res.get("river") or {"stations": []}
    from . import history
    try:   # dated official studies (static snapshot, no network); never affects the score
        bacteria_history = history.get_bacteria_history(creek_id)
    except Exception:  # noqa: BLE001
        bacteria_history = {"studies": []}
    return {"creek_id": creek_id, "gauge": gauge, "weather": weather,
            "water_quality": water_quality, "river": river,
            "bacteria_history": bacteria_history, "fetched_at": _now_iso()}


if __name__ == "__main__":  # python3 -m data.ingest
    import sys
    for cid in sys.argv[1:] or list(SOURCES):
        print(json.dumps(get_conditions(cid), indent=2))
