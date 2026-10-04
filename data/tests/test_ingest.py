"""Tests for data.ingest against real API responses captured 2026-10-03 (data/tests/fixtures)."""
import json
import pathlib
from datetime import datetime, timezone

import pytest

from data import ingest

FIX = pathlib.Path(__file__).parent / "fixtures"


def route(url: str) -> str:
    if "waterservices.usgs.gov/nwis/iv" in url:
        return (FIX / "usgs_iv_11418500.json").read_text()
    if "api.waterdata.usgs.gov/ogcapi" in url:
        return (FIX / "usgs_ogc_11418500.json").read_text()
    if "/observations/latest" in url:
        return (FIX / "nws_obs_KGOO.json").read_text()
    if "/forecast" in url and "weather.gov" in url:
        return (FIX / "nws_forecast_STO_63_95.json").read_text()
    if "open-meteo" in url:
        return (FIX / "openmeteo_deer.json").read_text()
    raise AssertionError(f"unexpected URL {url}")


CDEC_FIX = json.loads((FIX / "cdec_jbr_eng.json").read_text())


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    from data import cdec
    monkeypatch.setattr(cdec, "_get_json", lambda url, timeout: CDEC_FIX)   # no network in tests
    ingest.clear_cache()
    monkeypatch.setattr(ingest.time, "sleep", lambda s: None)
    yield
    ingest.clear_cache()


def test_get_conditions_from_fixtures(monkeypatch):
    monkeypatch.setattr(ingest, "_http_get_text", lambda url, timeout: route(url))
    c = ingest.get_conditions("deer")
    g, w = c["gauge"], c["weather"]
    assert g["site_no"] == "11418500" and g["on_creek"] is True
    assert g["discharge_cfs"] == 4.84 and g["gage_height_ft"] == 2.5
    assert g["observed_at"] == "2026-10-04T00:00:00Z"   # 17:00 PDT -> UTC
    assert g["median_cfs_today"] is not None and g["pct_of_median"] is not None
    assert w["temp_f"] is not None and w["forecast_short"]
    assert w["precip_24h_in"] is not None
    assert c["fetched_at"].endswith("Z")


def test_gauge_uses_new_usgs_api_first(monkeypatch):
    calls = []
    monkeypatch.setattr(ingest, "_http_get_text", lambda url, timeout: calls.append(url) or route(url))
    g = ingest.get_conditions("deer")["gauge"]
    assert g["discharge_cfs"] == 4.84 and g["observed_at"] == "2026-10-04T00:00:00Z"
    assert any("ogcapi" in u for u in calls) and not any("waterservices" in u for u in calls)


def test_new_usgs_api_down_falls_back_to_legacy_nwis(monkeypatch):
    def fake(url, timeout):
        if "ogcapi" in url:
            raise OSError("HTTP Error 503")
        return route(url)

    monkeypatch.setattr(ingest, "_http_get_text", fake)
    g = ingest.get_conditions("deer")["gauge"]
    assert g["discharge_cfs"] == 4.84 and g["name"] == "DEER C NR SMARTSVILLE CA"


def test_everything_down_gives_nulls_not_exceptions(monkeypatch):
    def boom(url, timeout):
        raise OSError("network down")

    monkeypatch.setattr(ingest, "_http_get_text", boom)
    c = ingest.get_conditions("wolf")
    assert c["gauge"] is None and c["weather"] is None and c["fetched_at"]


def test_stale_value_served_when_refresh_fails(monkeypatch):
    monkeypatch.setattr(ingest, "_http_get_text", lambda url, timeout: route(url))
    first = ingest.get_conditions("deer")
    assert first["weather"]["stale"] is False

    def boom(url, timeout):
        raise OSError("down")

    monkeypatch.setattr(ingest, "_http_get_text", boom)
    again = ingest.get_conditions("deer", max_age_s=0)   # force refresh -> fails -> stale
    assert again["gauge"]["discharge_cfs"] == 4.84
    assert again["weather"]["stale"] is True


def test_unknown_creek():
    with pytest.raises(ValueError):
        ingest.get_conditions("nope")


def test_flow_stats_snapshot():
    st = ingest.flow_stats("11418500", datetime(2026, 10, 4, 1, 0, tzinfo=timezone.utc))  # = Oct 3 PDT
    assert st == {"p25_cfs": 3.2, "median_cfs": 5.2, "p75_cfs": 9.5, "years": st["years"]}
    assert ingest.flow_stats("00000000") is None


def test_rain_window_sums_past_24h(monkeypatch):
    times = [f"2026-10-0{d}T{h:02d}:00" for d in (3, 4) for h in range(24)]
    precip = [0.0] * len(times)
    precip[times.index("2026-10-03T20:00")] = 0.4   # within past 24h of now
    precip[times.index("2026-10-04T10:00")] = 0.3   # in the next 24h
    payload = {"hourly": {"time": times, "precipitation": precip}}
    monkeypatch.setattr(ingest, "_http_get_text", lambda url, timeout: json.dumps(payload))
    r = ingest.fetch_rain(39.0, -121.0, now=datetime(2026, 10, 4, 6, 0, tzinfo=timezone.utc))
    assert r["precip_24h_in"] == 0.4 and r["precip_next_24h_in"] == 0.3


def test_transient_weather_failure_is_retried(monkeypatch):
    seen = {"n": 0}

    def flaky(url, timeout):
        if "open-meteo" in url and seen["n"] == 0:
            seen["n"] += 1
            raise OSError("transient")
        return route(url)

    monkeypatch.setattr(ingest, "_http_get_text", flaky)
    assert ingest.get_conditions("deer")["weather"]["precip_24h_in"] is not None


# --- RiverDB volunteer water quality ---------------------------------------------
from data import wq  # noqa: E402

RIVERDB = json.loads((FIX / "riverdb_syrcl_deer_below_nc.json").read_text())["data"]["sitevisits"]


@pytest.fixture(autouse=True)
def no_network_riverdb(monkeypatch):
    monkeypatch.setattr(wq, "_gql", lambda ref, timeout: RIVERDB)


def test_latest_readings_normalises_riverdb():
    r = wq.latest_readings(RIVERDB)
    assert r["date"] == "2026-08-08"
    assert r["readings"]["do_mg_l"] == 9.1 and r["readings"]["ph"] == 7.3
    assert r["readings"]["water_temp_c"] == 14.13


def test_latest_readings_skips_invalid_and_percent_do():
    visits = [{"date": "2026-01-01", "resultsv": [
        {"is_valid": False, "mean": 1.0, "unit": "mg/L", "param": {"name": "DO"}},
        {"is_valid": True, "mean": 95.0, "unit": "%", "param": {"name": "DO"}},
        {"is_valid": True, "mean": 7.0, "unit": "none", "param": {"name": "pH"}}]}]
    assert wq.latest_readings(visits)["readings"] == {"ph": 7.0}


def test_water_quality_live_and_snapshot(monkeypatch):
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    out = wq.get_water_quality("deer", now=now)
    first = out["stations"][0]
    assert first["agency"] == "SYRCL" and first["live"] is True and first["age_days"] == 57
    assert any(s["agency"] == "SSI" and s["live"] is False for s in out["stations"])  # from snapshot
    assert all(s["credit"] for s in out["stations"])


def test_water_quality_riverdb_down_falls_back_to_snapshot(monkeypatch):
    def boom(ref, timeout):
        raise OSError("riverdb down")
    monkeypatch.setattr(wq, "_gql", boom)
    out = wq.get_water_quality("deer")
    syrcl = [s for s in out["stations"] if s["agency"] == "SYRCL"]
    assert syrcl and all(s["live"] is False for s in syrcl)


def test_conditions_include_water_quality(monkeypatch):
    monkeypatch.setattr(ingest, "_http_get_text", lambda url, timeout: route(url))
    c = ingest.get_conditions("wolf")
    assert c["water_quality"]["stations"][0]["agency"] == "WCCA"



def test_failed_refresh_backs_off_instead_of_retrying_every_call(monkeypatch):
    calls = {"n": 0}

    def down():
        calls["n"] += 1
        raise OSError("upstream refusing")

    assert ingest._cached("k", 60, lambda: {"v": 1}) == {"v": 1}
    clock = {"t": ingest.time.time() + 120}                       # past the ttl
    monkeypatch.setattr(ingest.time, "time", lambda: clock["t"])
    first = ingest._cached("k", 60, down)
    second = ingest._cached("k", 60, down)
    assert first == second == {"v": 1, "stale": True}
    assert calls["n"] == 1                                         # second call didn't hit upstream
    clock["t"] += ingest.FAIL_BACKOFF_S + 1
    ingest._cached("k", 60, down)
    assert calls["n"] == 2                                         # retried after the backoff
    assert ingest._cached("k2", 60, down) is None                  # no stale value: None, still fast


def test_backoff_clears_on_success(monkeypatch):
    ingest._cached("k3", 0, lambda: (_ for _ in ()).throw(OSError("x")))
    clock = {"t": ingest.time.time() + ingest.FAIL_BACKOFF_S + 1}
    monkeypatch.setattr(ingest.time, "time", lambda: clock["t"])
    assert ingest._cached("k3", 0, lambda: {"ok": 1}) == {"ok": 1}
    assert "k3" not in ingest._failed
