"""Alert adapters on real captured fixtures (data/alerts/fixtures, 2026-10-03). No network."""
import copy
import json
import pathlib
import time
from datetime import datetime, timezone

import re
import types

import pytest

from data import alerts, score, wq
from data.alerts import http, model
from data.alerts.hab import HAB
from data.alerts.nwps import NWPS
from data.alerts.nws import NWS, stable_id
from data.alerts.others import OEHHA, RiverDBBacteria, creekwatch_alerts
from data.alerts.sso import SSO

ID_RE = re.compile(r"^[a-z0-9_]+:[A-Za-z0-9._:/#-]{1,200}$")   # backend validation (morpheus)
FIX = pathlib.Path(__file__).resolve().parent.parent / "alerts" / "fixtures"
NOW = datetime(2026, 10, 4, 3, 0, tzinfo=timezone.utc)        # Sat 2026-10-03 20:00 PDT
NWS_FIX = json.loads((FIX / "nws_active_point.json").read_text())
NWPS_FIX = json.loads((FIX / "nwps_gauges_region.json").read_text())
SSO_FIX = (FIX / "sso_spills_region.tsv").read_text()
HAB_FIX = {"result": json.loads((FIX / "fhabs_bbox.json").read_text())}
OEHHA_FIX = json.loads((FIX / "oehha_fish_advisories_nevada.json").read_text())


def route(nws=NWS_FIX, nwps=NWPS_FIX, sso=SSO_FIX, hab=HAB_FIX, oehha=OEHHA_FIX):
    def get_text(url, timeout=20, conditional=False, accept="*/*"):
        if "api.weather.gov/alerts" in url:
            return json.dumps(nws)
        if "api.water.noaa.gov" in url:
            return json.dumps(nwps)
        if "Cat1-2-3-Spills" in url:
            return sso
        if "datastore_search_sql" in url:
            return json.dumps(hab)
        if "datastore_search" in url:
            return json.dumps(oehha)
        raise AssertionError(f"unexpected URL {url}")
    return get_text


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(http, "get_text", route())
    monkeypatch.setattr(wq, "_gql", lambda ref, timeout: [])   # RiverDB: snapshot only


def assert_spec_shape(a):
    core = {"id", "source", "source_name", "category", "severity", "title", "summary",
            "instruction", "area", "effective", "expires", "updated", "status", "url", "attribution"}
    cap = {"event", "cap_urgency", "cap_severity", "cap_certainty"}   # optional CAP passthrough (NWS)
    assert core <= set(a) <= core | cap
    assert ID_RE.match(a["id"]), a["id"]                              # the API's validation regex
    assert set(a["area"]) == {"creek_ids", "site_ids", "lat", "lon", "polygon_geojson", "area_desc"}
    assert a["id"].startswith(a["source"] + ":")
    assert a["severity"] in model.SEVERITY_ORDER and a["category"] in model.CATEGORIES
    assert len(a["summary"]) <= 280 and a["url"].startswith("https://") and a["attribution"]
    assert a["effective"].endswith("Z")


# ---- NWS ------------------------------------------------------------------------------
def test_nws_heat_advisory_from_real_fixture():
    out = NWS().fetch(NOW)
    assert len(out) == 1
    a = out[0]
    assert_spec_shape(a)
    assert (a["category"], a["severity"], a["status"]) == ("heat", "watch", "active")  # CAP Moderate -> watch
    assert a["area"]["creek_ids"] == ["deer", "wolf"]                                  # both point queries hit
    assert a["id"] == "nws:urn:oid:2.49.0.1.840.0.ac066d5326fccb4cc6ad965c3ce88441c5c3dbad.001.1"  # thread root
    assert a["expires"] == "2026-10-08T05:00:00Z"   # 'ends' (Oct 7 22:00 PDT), not message 'expires'
    assert "Drink plenty of fluids" in a["instruction"]


def test_nws_update_keeps_id_cancel_marks_cancelled(monkeypatch):
    f = copy.deepcopy(NWS_FIX["features"][0])
    cancel = copy.deepcopy(f)
    cancel["properties"].update(id="urn:oid:new", messageType="Cancel", sent="2026-10-03T19:00:00-07:00")
    monkeypatch.setattr(http, "get_text", route(nws={"features": [f, cancel]}))
    out = NWS().fetch(NOW)
    assert len(out) == 1 and out[0]["status"] == "cancelled"
    assert out[0]["id"] == "nws:" + stable_id(f["properties"])


def test_nws_drops_non_water_events_and_expires(monkeypatch):
    aq = copy.deepcopy(NWS_FIX["features"][0]); aq["properties"]["event"] = "Air Quality Alert"
    old = copy.deepcopy(NWS_FIX["features"][0]); old["properties"].update(
        event="Flood Watch", severity="Severe", references=[], id="urn:oid:flood", ends="2026-10-01T00:00:00Z")
    monkeypatch.setattr(http, "get_text", route(nws={"features": [aq, old]}))
    out = NWS().fetch(NOW)
    assert [(a["category"], a["severity"], a["status"]) for a in out] == [("flood", "alert", "expired")]


# ---- NWPS -----------------------------------------------------------------------------
def test_nwps_quiet_today_then_minor_flood(monkeypatch):
    assert NWPS().fetch(NOW) == []          # real fixture: everything no_flooding / not_defined
    fx = copy.deepcopy(NWPS_FIX)
    g = next(x for x in fx["gauges"] if x["lid"] == "BRWC1")
    g["status"]["observed"]["floodCategory"] = "minor"
    monkeypatch.setattr(http, "get_text", route(nwps=fx))
    (a,) = NWPS().fetch(NOW)
    assert_spec_shape(a)
    assert (a["id"], a["severity"], a["category"]) == ("nwps:BRWC1:observed", "watch", "flood")


# ---- Sewage spills --------------------------------------------------------------------
def test_sso_wolf_creek_spill_active_then_expired():
    may = datetime(2026, 5, 10, tzinfo=timezone.utc)
    wolf = [a for a in SSO().fetch(may) if "Wolf Creek" in a["title"]]
    assert len(wolf) == 1
    a = wolf[0]
    assert_spec_shape(a)
    assert (a["severity"], a["status"], a["area"]["creek_ids"]) == ("alert", "active", ["wolf"])
    assert "1,000 gallons" in a["summary"] and "850 gallons reached Wolf Creek" in a["summary"]
    later = next(x for x in SSO().fetch(NOW) if x["id"] == a["id"])
    assert later["status"] == "expired"


def test_sso_skips_monthly_batches_and_old_spills():
    out = SSO().fetch(NOW)
    assert all("Monthly" not in a["summary"] for a in out)
    assert all(a["effective"] >= "2025-10-03" for a in out)          # 365-day history window


# ---- Algal blooms ---------------------------------------------------------------------
def test_hab_caution_open_reports_are_advisories():
    out = HAB().fetch(NOW)
    lotp = [a for a in out if "Lake of the Pines" in a["title"]]
    assert lotp and lotp[0]["severity"] == "advisory" and lotp[0]["status"] == "active"
    assert '"Caution"' in lotp[0]["summary"]
    for a in out:
        assert_spec_shape(a)
        assert model.in_region(a["area"]["lat"], a["area"]["lon"])


def test_hab_groups_rows_and_takes_most_severe():
    base = {"Bloom_Report_ID": 1, "Observation_Date": "2026-09-30T00:00:00", "Water_Body_Name": "Test Lake",
            "Bloom_Latitude": 39.2, "Bloom_Longitude": -121.0, "Case_Status": "Open"}
    recs = [dict(base, Advisory_Recommended=None), dict(base, Advisory_Recommended="Danger"),
            dict(base, Advisory_Recommended="Caution")]
    (a,) = HAB().from_records(recs, NOW)
    assert a["severity"] == "alert"


# ---- RiverDB bacteria / OEHHA ---------------------------------------------------------
def test_riverdb_ecoli_rule_and_ssi_link(monkeypatch):
    out = RiverDBBacteria().fetch(NOW)
    assert [a["id"] for a in out] == ["riverdb:ssi-pioneer-park-status"]   # today: no recent E. coli > 320
    assert out[0]["severity"] == "info" and "sierrastreamsinstitute.org" in out[0]["url"]
    hot = {"stations": [{"station_id": "X", "name": "Test Site", "date": "2026-09-25", "age_days": 8,
                         "readings": {"ecoli_mpn_100ml": 900.0}, "credit": "Test group via RiverDB",
                         "lat": 39.26, "lon": -121.03, "site_id": None, "source_url": "https://riverdb.org/x"}]}
    monkeypatch.setattr(wq, "get_water_quality", lambda creek_id, now=None: hot)
    bact = [a for a in RiverDBBacteria().fetch(NOW) if a["category"] == "bacteria" and a["severity"] == "watch"]
    assert bact and "900" in bact[0]["summary"] and "320" in bact[0]["summary"]


def test_oehha_attaches_by_name_not_distance():
    out = {a["title"].split(": ", 1)[1]: a for a in OEHHA().fetch(NOW)}
    assert out["Deer Creek"]["area"]["creek_ids"] == ["deer"]
    assert out["Englebright Lake"]["area"]["creek_ids"] == []     # near the Deer Creek line, but not the creek
    assert all(a["expires"] is None and a["severity"] == "info" for a in out.values())


# ---- Creek Watch rules + registry -----------------------------------------------------
def test_creekwatch_alerts_from_health():
    health = score.compute_health("deer", [{"observed_at": NOW.isoformat(), "dead_fish": True}], None, now=NOW)
    (a,) = creekwatch_alerts("deer", health, NOW)
    assert_spec_shape(a)
    assert (a["id"], a["severity"], a["category"]) == ("creekwatch:deer:contamination_alert", "alert", "contamination")


def test_fetch_all_isolates_failing_and_slow_sources(monkeypatch):
    def boom(now):
        raise RuntimeError("upstream down")
    monkeypatch.setattr(alerts.REGISTRY["nwps"], "_fetch", boom)
    monkeypatch.setattr(alerts.REGISTRY["oehha"], "_fetch", lambda now: time.sleep(3) or [])
    monkeypatch.setattr(alerts.REGISTRY["usgs"], "_fetch", lambda now: [])
    t0 = time.monotonic()
    r = alerts.fetch_all(now=NOW, timeout_s=1)
    assert time.monotonic() - t0 < 2.5
    assert "upstream down" in r["errors"]["nwps"] and "timed out" in r["errors"]["oehha"]
    assert any(a["source"] == "nws" for a in r["alerts"]) and any(a["source"] == "hab" for a in r["alerts"])
    sev = [model.SEVERITY_ORDER[a["severity"]] for a in r["alerts"]]
    assert sev == sorted(sev, reverse=True)
    assert len({a["id"] for a in r["alerts"]}) == len(r["alerts"])


# ---- E. coli rule in score.py ---------------------------------------------------------
def _wq(age, ecoli):
    return {"weather": {"temp_f": 70, "precip_24h_in": 0.0}, "gauge": None,
            "water_quality": {"stations": [
                {"name": "SYRCL newest", "date": "2026-09-30", "age_days": 3, "readings": {"do_mg_l": 9.0}},
                {"name": "SSI Site 13", "date": "2026-09-20", "age_days": age,
                 "readings": {"ecoli_mpn_100ml": ecoli}, "credit": "Sierra Streams Institute via RiverDB"}]}}


def test_score_ecoli_rule_fires_on_any_recent_station():
    h = score.compute_health("deer", [], _wq(13, 900), now=NOW)
    w = [w for w in h["warnings"] if w["id"] == "bacteria_watch"]
    assert w and "Sierra Streams Institute" in w[0]["explanation"] and "2026-09-20" in w[0]["explanation"]
    assert score.BAND_ORDER[h["band"]] >= score.BAND_ORDER["watch"]


def test_score_ecoli_rule_ignores_old_or_low_samples():
    for age, ec in ((90, 900), (13, 300)):
        h = score.compute_health("deer", [], _wq(age, ec), now=NOW)
        assert not any(w["id"] == "bacteria_watch" for w in h["warnings"])


# ---- API poller contract (ADAPTERS, fetch(ctx), full current set, raise on failure) -------
def ctx(reports=None, conditions=None):
    return types.SimpleNamespace(
        now=NOW, creek_ids=["wolf", "deer"], creeks=[],
        reports=lambda cid, days=14: (reports or {}).get(cid, []),
        conditions=lambda cid: (conditions or {}).get(cid, {"gauge": None, "weather": None}))


GAUGE = {"site_no": "11418500", "name": "DEER C NR SMARTSVILLE CA", "discharge_cfs": 40.0,
         "observed_at": "2026-10-04T02:45:00Z", "on_creek": True, "source_url": "https://waterdata.usgs.gov/x"}


def test_adapters_shape_and_ids():
    ads = {a.source: a for a in alerts.ADAPTERS}
    assert set(ads) == {"nws", "nwps", "sso", "hab", "riverdb", "oehha", "usgs", "creekwatch"}
    c = ctx(conditions={k: {"gauge": dict(GAUGE, pct_of_median=100)} for k in ("wolf", "deer")})
    for src, ad in ads.items():
        assert ad.source_name and ad.interval_s >= 300
        for a in ad.fetch(c):
            assert_spec_shape(a)


def test_nws_adapter_raises_on_partial_outage(monkeypatch):
    ok = route()

    def half(url, **kw):
        if "39.2081" in url:                       # Wolf point down, Deer point fine
            raise OSError("timeout")
        return ok(url, **kw)
    monkeypatch.setattr(http, "get_text", half)
    nws = next(a for a in alerts.ADAPTERS if a.source == "nws")
    with pytest.raises(RuntimeError, match="wolf"):
        nws.fetch(ctx())                           # never a partial set the store would 'resolve'
    assert NWS().fetch(NOW) == [] and alerts.REGISTRY["nws"].fetch(NOW) == []  # non-raising path still safe


def test_nws_cap_passthrough():
    (a,) = NWS().fetch(NOW)
    assert (a["event"], a["cap_severity"], a["cap_urgency"], a["cap_certainty"]) == \
        ("Heat Advisory", "Moderate", "Expected", "Likely")


def test_usgs_adapter_uses_ctx_and_raises_when_blind():
    usgs = next(a for a in alerts.ADAPTERS if a.source == "usgs")
    high = {k: {"gauge": dict(GAUGE, pct_of_median=450, on_creek=(k == "deer"))} for k in ("wolf", "deer")}
    out = usgs.fetch(ctx(conditions=high))
    deer = [a for a in out if a["area"]["creek_ids"] == ["deer"]]
    assert deer and deer[0]["category"] == "high_flow" and deer[0]["severity"] == "watch"
    with pytest.raises(RuntimeError, match="no usable gauge"):
        usgs.fetch(ctx())                          # gauge unknown: don't report "all clear"


def test_creekwatch_adapter_from_ctx_reports():
    cw = next(a for a in alerts.ADAPTERS if a.source == "creekwatch")
    dead = {"deer": [{"observed_at": "2026-10-04T02:00:00Z", "dead_fish": True}]}
    out = cw.fetch(ctx(reports=dead))
    assert [a["id"] for a in out] == ["creekwatch:deer:contamination_alert"]
    assert cw.fetch(ctx()) == []                   # warning gone -> full set empty -> store expires it
