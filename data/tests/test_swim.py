"""SYRCL swim-hole E. coli (RiverDB SYRCL_BACTERIA): regional context, exact 'EColi' only."""
import json
import pathlib
import threading
import time
from datetime import datetime, timezone

import pytest

from data import ingest, wq
from data.alerts.others import RiverDBBacteria

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "riverdb_swim_purdon_2026.json").read_text())["data"]["sitevisits"]
NOW = datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fresh():
    ingest.clear_cache()
    yield
    ingest.clear_cache()


def test_latest_ecoli_exact_param_from_real_fixture():
    assert wq.latest_ecoli(FIX) == {"date": "2026-08-08", "ecoli_mpn_100ml": 5.2}


def test_total_coliform_is_never_read_as_ecoli():
    visits = [{"date": "2026-08-08", "resultsv": [
        {"param": {"name": "TotalColiform"}, "mean": 2419.6, "unit": "MPN/100 mL", "is_valid": True}]}]
    assert wq.latest_ecoli(visits) is None


def test_swim_holes_live_then_snapshot_on_failure():
    live = wq.get_swim_holes(now=NOW, fetch=lambda ref: {"date": "2026-08-08", "ecoli_mpn_100ml": 6.0})
    assert len(live["stations"]) == 5 and all(s["live"] for s in live["stations"])
    assert all(s["credit"].startswith("South Yuba River Citizens League") for s in live["stations"])
    ingest.clear_cache()

    def down(ref):
        raise OSError("riverdb down")
    snap = wq.get_swim_holes(now=NOW, fetch=down)
    assert len(snap["stations"]) == 5 and not any(s["live"] for s in snap["stations"])
    assert {s["date"] for s in snap["stations"]} == {"2026-08-08"}       # committed snapshot


def test_riverdb_throttle_spaces_calls(monkeypatch):
    monkeypatch.setattr(wq, "MIN_INTERVAL_S", 0.25)
    monkeypatch.setattr(wq, "_last_call", [0.0])
    t0 = time.monotonic()
    for _ in range(3):
        wq._throttle()
    assert time.monotonic() - t0 >= 0.5                                  # 3 calls -> >= 2 gaps


def test_conditions_include_swim_holes_capped_when_slow(monkeypatch):
    monkeypatch.setattr(ingest, "WQ_WAIT_S", 0.2)
    release = threading.Event()

    def slow(ref, timeout, from_year=None):
        release.wait(3)
        return FIX
    monkeypatch.setattr(wq, "_gql", slow)
    t0 = time.monotonic()
    try:
        c = ingest.get_conditions("deer")
    finally:
        release.set()
    assert time.monotonic() - t0 < 0.6        # ONE shared 0.2 s cap for wq + swim, not 0.2 + 0.2 + ...
    sh = c["swim_holes"]
    assert c["water_quality"].get("capped") is True and sh["capped"] is True and len(sh["stations"]) == 5 and not any(s["live"] for s in sh["stations"])
    assert c["cache_ttl_hint_s"] == ingest.CAPPED_TTL_HINT_S


def test_swim_hole_bacteria_alert_is_regional(monkeypatch):
    hot = {"stations": [{"station_id": "S", "name": "Purdon Crossing", "river": "South Yuba River",
                         "lat": 39.33, "lon": -121.05, "date": "2026-09-30", "age_days": 4,
                         "ecoli_mpn_100ml": 900.0, "credit": wq.SWIM_CREDIT,
                         "source_url": "https://riverdb.org/org/SYRCL"}]}
    monkeypatch.setattr(wq, "get_swim_holes", lambda now=None, **kw: hot)
    monkeypatch.setattr(wq, "get_water_quality", lambda creek_id, now=None: {"stations": []})
    (a,) = [a for a in RiverDBBacteria().run(NOW) if a["id"].startswith("riverdb:S:")]
    assert a["area"]["creek_ids"] == [] and a["severity"] == "watch"
    assert "lowers this creek" not in a["summary"] and "900" in a["summary"]
    low = dict(hot["stations"][0], ecoli_mpn_100ml=5.2)
    monkeypatch.setattr(wq, "get_swim_holes", lambda now=None, **kw: {"stations": [low]})
    assert not [a for a in RiverDBBacteria().run(NOW) if a["id"].startswith("riverdb:S:")]
