"""CDEC regional river flow / reservoir storage, on a captured response (2026-10-03)."""
import json
import pathlib
from datetime import datetime, timezone

from data import cdec, ingest

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "cdec_jbr_eng.json").read_text())
NOW = datetime(2026, 10, 4, 4, 0, tzinfo=timezone.utc)


def test_cdec_times_are_california_local():
    assert cdec.parse_cdec_time("2026-10-3 19:00") == datetime(2026, 10, 4, 2, 0, tzinfo=timezone.utc)   # PDT
    assert cdec.parse_cdec_time("2026-01-15 19:00") == datetime(2026, 1, 16, 3, 0, tzinfo=timezone.utc)  # PST
    assert cdec.parse_cdec_time("garbage") is None


def test_latest_skips_missing_values():
    recs = [{"stationId": "JBR", "SENSOR_NUM": 20, "obsDate": "2026-10-3 18:00", "value": 36},
            {"stationId": "JBR", "SENSOR_NUM": 20, "obsDate": "2026-10-3 19:00", "value": -9999},
            {"stationId": "JBR", "SENSOR_NUM": 20, "obsDate": "2026-10-3 17:00", "value": 35}]
    (t, v), = cdec.latest(recs).values()
    assert v == 36 and t == datetime(2026, 10, 4, 1, 0, tzinfo=timezone.utc)


def test_get_river_from_fixture():
    r = cdec.get_river(now=NOW, fetch=lambda url: FIX)
    st = {s["station_id"]: s for s in r["stations"]}
    assert set(st) == {"JBR", "ENG"}                                  # DCS deliberately not used (mirrors USGS)
    assert st["JBR"]["flow_cfs"] > 0 and st["ENG"]["storage_af"] > 60000
    for s in st.values():
        assert s["observed_at"].endswith("Z") and s["age_hours"] >= 0
        assert s["credit"] == "California Department of Water Resources, CDEC"
        assert s["source_url"].startswith("https://cdec.water.ca.gov/")


def test_get_river_never_raises():
    def boom(url):
        raise OSError("cdec down")
    assert cdec.get_river(now=NOW, fetch=boom)["stations"] == []


def test_conditions_include_river(monkeypatch):
    monkeypatch.setattr(cdec, "_get_json", lambda url, timeout: FIX)
    monkeypatch.setattr(ingest, "_http_get_text", lambda url, timeout: (_ for _ in ()).throw(OSError("offline")))
    from data import wq
    monkeypatch.setattr(wq, "_gql", lambda ref, timeout: (_ for _ in ()).throw(OSError("offline")))
    ingest.clear_cache()
    c = ingest.get_conditions("deer")
    assert {s["station_id"] for s in c["river"]["stations"]} == {"JBR", "ENG"}
    ingest.clear_cache()
