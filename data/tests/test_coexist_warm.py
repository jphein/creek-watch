"""#80 (DataLayer.warm + per-creek single-flight) x #81 (ingest single-flight + <=3 s RiverDB cap):
a startup warm-up racing a first visitor must make ONE RiverDB fetch per station, record no false
failure, answer fast, and fill the live cache for later requests."""
import collections
import json
import pathlib
import sys
import threading
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "backend"))
pytest.importorskip("creekwatch.data_iface")

from creekwatch.data_iface import DataLayer   # noqa: E402

from data import cdec, ingest, wq             # noqa: E402

FIX = pathlib.Path(__file__).parent / "fixtures"
RIVERDB = json.loads((FIX / "riverdb_syrcl_deer_below_nc.json").read_text())["data"]["sitevisits"]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    ingest.clear_cache()
    monkeypatch.setattr(ingest, "_http_get_text", lambda url, timeout: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(cdec, "_get_json", lambda url, timeout: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(ingest, "WQ_WAIT_S", 0.3)
    yield
    ingest.clear_cache()


def test_warmup_and_first_visitor_one_fetch_per_station_no_false_failure(monkeypatch):
    calls, release = collections.Counter(), threading.Event()

    def slow_riverdb(ref, timeout):           # RiverDB slow, like a cold process after a deploy
        calls[ref] += 1
        release.wait(5)
        return RIVERDB
    monkeypatch.setattr(wq, "_gql", slow_riverdb)

    dl = DataLayer(600, use_data_package=True)
    assert not dl.stubbed
    warm = threading.Thread(target=dl.warm, args=(["wolf", "deer"],), daemon=True)
    warm.start()
    time.sleep(0.05)
    t0 = time.monotonic()
    first = dl.conditions("deer")             # a visitor racing the warm-up
    assert time.monotonic() - t0 < 1.5        # capped (0.3 s here), never the full RiverDB wait
    assert first["water_quality"].get("capped") is True
    assert "cache_ttl_hint_s" not in first      # #82 honours the hint and strips it from the public dict
    assert not any(s["live"] for s in first["water_quality"]["stations"] if s["agency"] == "SYRCL")

    # The alert poller's RiverDB adapter calls wq directly (not through the DataLayer's per-creek
    # lock), so only ingest's single-flight stops it from re-fetching the stations in flight.
    from data.alerts.others import RiverDBBacteria
    # (The deer job fetches its two stations one after another, so the poller may legitimately own
    # the fetch of a station nobody has started yet; what must never happen is a SECOND fetch of
    # a station already in flight.)
    poll = threading.Thread(target=lambda: RiverDBBacteria().run(), daemon=True)
    poll.start()
    time.sleep(0.1)

    release.set()                             # RiverDB answers; the still-running job fills the cache
    warm.join(5)
    poll.join(5)
    assert not poll.is_alive()
    deadline = time.monotonic() + 3
    while ingest._peek("riverdb:17592187179149") is None and time.monotonic() < deadline:
        release.wait(0.05)

    assert set(calls) == {"17592187179149", "17592187179145"}
    assert all(n == 1 for n in calls.values()), dict(calls)          # ONE fetch per station
    assert not any(k.startswith("riverdb:") for k in ingest._failed)  # no false failure
    later = ingest.get_conditions("deer")                              # next uncached request: live
    assert all(s["live"] for s in later["water_quality"]["stations"] if s["agency"] == "SYRCL")
    assert all(n == 1 for n in calls.values())                         # ...still served from cache


def test_cold_concurrent_creeks_sharing_obs_kgoo_never_cache_a_none(monkeypatch):
    """Oracle #81: #80's lock is per creek, but obs:KGOO (and cdec:river) are shared. On a cold
    process, deer's request while wolf is fetching KGOO must get the real temperature, not a
    temp_f=None answer that DataLayer would cache for 600 s."""
    obs = (FIX / "nws_obs_KGOO.json").read_text()
    release = threading.Event()
    kgoo_calls = collections.Counter()

    def http(url, timeout):
        if "/observations/latest" in url:
            kgoo_calls["n"] += 1
            release.wait(5)                     # NWS slow on a cold start
            return obs
        raise OSError("offline")
    monkeypatch.setattr(ingest, "_http_get_text", http)
    dl = DataLayer(600, use_data_package=True)
    out = {}
    wolf = threading.Thread(target=lambda: out.setdefault("wolf", dl.conditions("wolf")), daemon=True)
    wolf.start()
    deadline = time.monotonic() + 3
    while "obs:KGOO" not in ingest._inflight and time.monotonic() < deadline:
        release.wait(0.01)
    deer = threading.Thread(target=lambda: out.setdefault("deer", dl.conditions("deer")), daemon=True)
    deer.start()
    release.wait(0.2)
    release.set()
    wolf.join(10)
    deer.join(10)
    assert kgoo_calls["n"] == 1                                   # one NWS call for both creeks
    for cid in ("wolf", "deer"):
        assert out[cid]["weather"] and out[cid]["weather"]["temp_f"] is not None, cid
