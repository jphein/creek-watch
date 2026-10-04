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


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
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


def test_usgs_503_falls_back_to_new_api(monkeypatch):
    calls = []

    def fake(url, timeout):
        calls.append(url)
        if "waterservices.usgs.gov" in url:
            raise OSError("HTTP Error 503")
        return route(url)

    monkeypatch.setattr(ingest, "_http_get_text", fake)
    g = ingest.get_conditions("deer")["gauge"]
    assert g["discharge_cfs"] == 4.84 and g["observed_at"] == "2026-10-04T00:00:00Z"
    assert sum("waterservices" in u for u in calls) == 2   # retried once
    assert any("ogcapi" in u for u in calls)


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
