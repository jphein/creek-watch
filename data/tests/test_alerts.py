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

ID_RE = re.compile(r"^[a-z0-9_]{1,32}:[A-Za-z0-9._:/#-]{1,200}$")   # backend validate_alert (#39)
FIX = pathlib.Path(__file__).resolve().parent.parent / "alerts" / "fixtures"
NOW = datetime(2026, 10, 4, 3, 0, tzinfo=timezone.utc)        # Sat 2026-10-03 20:00 PDT
NWS_FIX = json.loads((FIX / "nws_active_point.json").read_text())
NWPS_FIX = json.loads((FIX / "nwps_gauges_region.json").read_text())
SSO_FIX = (FIX / "sso_spills_region.tsv").read_text()
HAB_FIX = {"result": json.loads((FIX / "fhabs_bbox.json").read_text())}
OEHHA_FIX = json.loads((FIX / "oehha_fish_advisories_nevada.json").read_text())


def route(nws=NWS_FIX, nwps=NWPS_FIX, sso=SSO_FIX, hab=HAB_FIX, oehha=OEHHA_FIX):
    def get_text(url, timeout=20, conditional=False, accept="*/*", **kw):
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
    cap = {"event", "cap_urgency", "cap_severity", "cap_certainty",   # optional CAP passthrough (NWS)
           "cap_identifier", "cap_sender", "cap_sent"}
    assert core <= set(a) <= core | cap
    assert ID_RE.match(a["id"]) and a["id"].startswith(a["source"] + ":"), a["id"]  # API validation
    assert not any(c in a["url"] for c in '<>"\' '), a["url"]
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
    monkeypatch.setattr(alerts.REGISTRY["oehha"], "deadline_s", 1)
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
    assert w and "Sierra Streams Institute" in w[0]["explanation"] and "Sep 20, 2026" in w[0]["explanation"]
    assert "unsafe" not in w[0]["explanation"].lower() and "not a single-sample limit" in w[0]["explanation"]
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


def test_fetch_all_inflight_guard_and_per_source_deadline(monkeypatch):
    import threading as th
    gate = th.Event()
    monkeypatch.setattr(alerts.REGISTRY["sso"], "_fetch", lambda now: gate.wait(5) and [])
    monkeypatch.setattr(alerts.REGISTRY["sso"], "deadline_s", 0.3)
    r1 = alerts.fetch_all(["sso"], now=NOW, timeout_s=0.1)
    assert r1["errors"]["sso"] == "timed out after 0.3s"            # its own deadline, not timeout_s
    r2 = alerts.fetch_all(["sso"], now=NOW, timeout_s=0.1)
    assert "still running" in r2["errors"]["sso"]                    # not resubmitted while hung
    gate.set()
    time.sleep(0.2)
    monkeypatch.setattr(alerts.REGISTRY["sso"], "_fetch", lambda now: [])
    assert alerts.fetch_all(["sso"], now=NOW)["errors"] == {}         # free again once it finished


def test_sso_http_cap_and_deadline_passed(monkeypatch):
    seen = {}

    def spy(url, **kw):
        seen.update(kw)
        return SSO_FIX
    monkeypatch.setattr(http, "get_text", spy)
    SSO().run(NOW)
    assert seen["max_bytes"] == 50 * 1024 * 1024 and seen["deadline_s"] <= alerts.REGISTRY["sso"].deadline_s


def test_sso_dedupes_spill_event_ids():
    ids = [a["id"] for a in SSO().run(datetime(2026, 6, 10, tzinfo=timezone.utc))]
    assert ids and len(ids) == len(set(ids))



def test_sso_same_event_twice_reported_once(monkeypatch):
    lines = SSO_FIX.splitlines()
    cat1 = next(ln for ln in lines[1:] if "\tCategory 1 Spill\t" in ln and "Wolf Creek" in ln)
    monkeypatch.setattr(http, "get_text", route(sso="\n".join(lines + [cat1]) + "\n"))
    ids = [a["id"] for a in SSO().run(datetime(2026, 5, 10, tzinfo=timezone.utc))]
    assert ids.count("sso:906581") == 1


# ---- Oracle must-fixes: bounded HTTP, url allowlist, per-record isolation, raising shim ----
class _FakeResp:
    def __init__(self, chunks, length=None, delay=0.0):
        self._chunks, self.headers, self._delay = list(chunks), {"Content-Length": length} if length else {}, delay

    def read(self, n):
        time.sleep(self._delay)
        return self._chunks.pop(0) if self._chunks else b""


def test_http_bounded_read_size_and_deadline():
    with pytest.raises(http.ResponseTooLarge):
        http._read_bounded(_FakeResp([b"x" * 600] * 3), max_bytes=1000, deadline=time.monotonic() + 5)
    with pytest.raises(http.ResponseTooLarge):
        http._read_bounded(_FakeResp([], length="999999"), max_bytes=1000, deadline=time.monotonic() + 5)
    with pytest.raises(http.DeadlineExceeded):           # slow drip: each read is fast enough, total isn't
        http._read_bounded(_FakeResp([b"x"] * 100, delay=0.05), max_bytes=10_000, deadline=time.monotonic() + 0.2)
    assert http._read_bounded(_FakeResp([b"ab", b"cd"]), max_bytes=10, deadline=time.monotonic() + 5) == b"abcd"


def test_make_alert_url_allowlist_and_explicit_raises():
    base = dict(source="hab", source_id="1", source_name="x", category="algal_bloom", severity="info",
                title="t", summary="s", attribution="a", effective=NOW)
    portal = model.SOURCE_URLS["hab"][1]
    assert model.make_alert(url="https://evil.example/x", **base)["url"] == portal
    assert model.make_alert(url="http://mywaterquality.ca.gov/x", **base)["url"] == portal
    assert model.make_alert(url='https://mywaterquality.ca.gov/"><script>', **base)["url"] == portal
    ok = "https://mywaterquality.ca.gov/habs/x.html"
    assert model.make_alert(url=ok, **base)["url"] == ok
    with pytest.raises(ValueError):
        model.make_alert(url=ok, **dict(base, severity="extreme"))
    with pytest.raises(ValueError):
        model.make_alert(url=ok, **dict(base, effective="not a date"))


def test_nws_polygon_capped():
    poly = {"type": "Polygon", "coordinates": [[[0.0, 0.0]] * (model.MAX_POLYGON_POINTS + 1)]}
    assert model.safe_polygon(poly) is None
    assert model.safe_polygon({"type": "GeometryCollection", "geometries": []}) is None
    small = {"type": "Polygon", "coordinates": [[[-121.0, 39.2], [-121.1, 39.2], [-121.0, 39.3], [-121.0, 39.2]]]}
    assert model.safe_polygon(small) == small


def test_nwps_lid_quoted_in_url(monkeypatch):
    fx = copy.deepcopy(NWPS_FIX)
    g = next(x for x in fx["gauges"] if x["lid"] == "BRWC1")
    g["lid"] = "BRW/../C1"
    g["status"]["observed"]["floodCategory"] = "major"
    monkeypatch.setattr(http, "get_text", route(nwps=fx))
    (a,) = NWPS().run(NOW)
    assert a["url"] == "https://water.noaa.gov/gauges/BRW%2F..%2FC1" and "/../" not in a["url"]


def test_per_record_isolation_skips_bad_keeps_rest(monkeypatch):
    fx = copy.deepcopy(NWPS_FIX)
    for lid, cat in (("BRWC1", "minor"), ("MRYC1", "minor")):
        next(x for x in fx["gauges"] if x["lid"] == lid)["status"]["observed"]["floodCategory"] = cat
    del next(x for x in fx["gauges"] if x["lid"] == "MRYC1")["name"]      # malformed record
    monkeypatch.setattr(http, "get_text", route(nwps=fx))
    src = NWPS()
    out = src.run(NOW)
    assert [a["id"] for a in out] == ["nwps:BRWC1:observed"]            # bad one skipped, good one kept
    assert src.last_skipped == 1 and "MRYC1" in src.last_error
    recs = HAB_FIX["result"]["records"] + [{"Bloom_Report_ID": "X", "Observation_Date": "2026-09-01",
                                            "Bloom_Latitude": "not-a-number", "Case_Status": "Open"}]
    h = HAB()
    good = h.from_records(recs, NOW)
    assert good and h._skips and all(a["id"] != "hab:X" for a in good)


def test_adapter_fetch_propagates_source_failure(monkeypatch):
    def boom(now):
        raise RuntimeError("upstream exploded")
    for ad in alerts.ADAPTERS:
        if ad.source in ("usgs", "creekwatch"):
            continue
        monkeypatch.setattr(alerts.REGISTRY[ad.source], "_fetch", boom)
        for c in (None, {"now": NOW}, ctx()):
            with pytest.raises(RuntimeError, match="upstream exploded"):
                ad.fetch(c)
    cw = next(a for a in alerts.ADAPTERS if a.source == "creekwatch")
    with pytest.raises(ValueError):
        cw.fetch(None)                                                  # no reports accessor: not 'all clear'


def test_bacteria_ages_and_dedupes(monkeypatch):
    def station(age):
        return {"stations": [{"station_id": "S13", "name": "SSI Site 13", "date": "2026-09-20", "age_days": age,
                              "readings": {"ecoli_mpn_100ml": 900.0}, "credit": "Sierra Streams Institute via RiverDB",
                              "lat": 39.259, "lon": -121.009, "site_id": "deer-pioneer-park",
                              "source_url": "https://riverdb.org/org/SSI"}]}
    for age, want in ((5, "watch"), (30, "advisory"), (61, None)):
        monkeypatch.setattr(wq, "get_water_quality", lambda creek_id, now=None, a=age: station(a))
        got = [a for a in RiverDBBacteria().run(NOW) if a["id"].startswith("riverdb:S13")]
        assert [a["severity"] for a in got] == ([want] if want else [])
        if got:
            assert "unsafe" not in got[0]["summary"].lower() and "MPN/100 mL" in got[0]["summary"]
        h = score.compute_health("deer", [], {"water_quality": station(age)}, now=NOW)
        lvl = [w["level"] for w in h["warnings"] if w["id"] == "bacteria_watch"]
        assert lvl == ([want] if want else [])
        assert not [a for a in creekwatch_alerts("deer", h, NOW) if a["category"] == "bacteria"]  # no double report


PORTAL_NWS = model.SOURCE_URLS["nws"][1]


@pytest.mark.parametrize("url,expected", [
    ("https://evil.example\\@forecast.weather.gov/x", PORTAL_NWS),   # browsers: '\' == '/', host evil.example
    ("https://evil.example\\.forecast.weather.gov/", PORTAL_NWS),
    ("https://user:pw@forecast.weather.gov/", PORTAL_NWS),            # userinfo
    ("https://forecast.weather.gov@evil.example/", PORTAL_NWS),
    ("https://forecast.weather.gov:8443/", PORTAL_NWS),               # non-443 port
    ("https://forecast.weather.gov/\t", PORTAL_NWS),                  # control char (WHATWG strips tabs)
    ("https://forec\u00e4st.weather.gov/", PORTAL_NWS),               # non-ASCII / IDN
    ("javascript:alert(1)", PORTAL_NWS),
    ("https://alerts.weather.gov/x", PORTAL_NWS),                     # NXDOMAIN host: not allowlisted
    ("https://forecast.weather.gov/MapClick.php?lat=39.2&lon=-121.0",
     "https://forecast.weather.gov/MapClick.php?lat=39.2&lon=-121.0"),
    ("https://forecast.weather.gov:443/x", "https://forecast.weather.gov/x"),
    ("https://FORECAST.weather.gov/x", "https://forecast.weather.gov/x"),
    ("HTTPS://forecast.weather.gov/x", "https://forecast.weather.gov/x"),   # #39's regex is case-sensitive
])
def test_safe_url_rejects_parser_differentials(url, expected):
    """Regression for the background security review (urlsplit vs browser host disagreement),
    plus normalisation so downstream case-sensitive checks never drop a valid alert."""
    got = model.safe_url("nws", url)
    assert got == expected
    assert got.startswith("https://") and got == got.strip()


def test_real_adapter_urls_survive_strict_check():
    for src in (NWS(), HAB(), OEHHA()):
        for a in src.run(NOW):
            assert a["url"] != model.SOURCE_URLS[src.id][1] or src.id == "hab", (src.id, a["url"])


def test_nws_cap_reference_fields_are_latest_message(monkeypatch):
    (a,) = NWS().run(NOW)
    p = NWS_FIX["features"][0]["properties"]
    assert (a["cap_identifier"], a["cap_sender"], a["cap_sent"]) == (p["id"], "w-nws.webmaster@noaa.gov", p["sent"])
    assert a["cap_identifier"] != a["id"].split(":", 1)[1]           # latest message, not the thread root
    f = copy.deepcopy(NWS_FIX["features"][0]); f["properties"]["sender"] = "a, b"
    monkeypatch.setattr(http, "get_text", route(nws={"features": [f]}))
    (b,) = NWS().run(NOW)
    assert "cap_sender" not in b                                      # would break "sender,identifier,sent"


# ---- skips must not read as an all-clear under the API's full-set store ------------------
def _nwps_with(n_good, n_bad):
    fx = copy.deepcopy(NWPS_FIX)
    gauges = []
    for i in range(n_good + n_bad):
        g = copy.deepcopy(next(x for x in fx["gauges"] if x["lid"] == "BRWC1"))
        g["lid"] = f"G{i}"
        g["status"]["observed"]["floodCategory"] = "minor"
        if i >= n_good:
            del g["name"]                                          # malformed record
        gauges.append(g)
    fx["gauges"] = gauges
    return fx


@pytest.mark.parametrize("good,bad,raises", [(0, 5, True), (4, 6, True), (9, 1, False), (5, 5, False)])
def test_skips_dominate_raises_instead_of_resolving(monkeypatch, good, bad, raises):
    monkeypatch.setattr(http, "get_text", route(nwps=_nwps_with(good, bad)))
    src = NWPS()
    if raises:
        with pytest.raises(RuntimeError, match="records failed to parse"):
            src.run(NOW)
        assert src.fetch(NOW) == [] and "records failed to parse" in src.last_error   # non-raising path
    else:
        out = src.run(NOW)
        assert len(out) == good and src.last_skipped == bad


def test_schema_change_on_every_source_raises(monkeypatch):
    """Upstream renames a key: every record breaks -> each adapter raises, never returns []."""
    broken_hab = {"result": {"records": [dict(r, Observation_Date="garbage-date", Bloom_Latitude="x")
                                         for r in HAB_FIX["result"]["records"]]}}
    broken_sso = SSO_FIX.replace("LATITUDE", "LAT_DD", 1)                     # renamed column
    broken_oehha = {"result": {"records": [{k.replace("Latitude", "Lat"): v for k, v in r.items()}
                                           for r in OEHHA_FIX["result"]["records"]]}}
    broken_nws = {"features": [{"properties": {k: v for k, v in f["properties"].items() if k != "event"}}
                               for f in NWS_FIX["features"]]}
    monkeypatch.setattr(http, "get_text", route(nwps=_nwps_with(0, 3), hab=broken_hab, sso=broken_sso,
                                                oehha=broken_oehha, nws=broken_nws))
    for src in (NWPS(), HAB(), SSO(), OEHHA(), NWS()):
        with pytest.raises(RuntimeError):
            src.run(NOW)


def test_http_refuses_redirects():
    import urllib.error
    h = http._NoRedirect()
    req = __import__("urllib.request").request.Request("https://api.weather.gov/x")
    with pytest.raises(urllib.error.HTTPError, match="redirect"):
        h.redirect_request(req, None, 302, "Found", {}, "http://169.254.169.254/latest/meta-data")
    assert any(isinstance(x, http._NoRedirect) for x in http._opener.handlers)
