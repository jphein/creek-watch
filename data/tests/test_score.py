"""Tests for data.score: run with `python3 -m pytest data/tests` from the repo root."""
from datetime import datetime, timedelta, timezone

import pytest

from data.score import compute_health, report_flags, band_for

NOW = datetime(2026, 10, 4, 18, 0, tzinfo=timezone.utc)


def ago(hours):
    return (NOW - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def report(hours_ago=2, **kw):
    r = dict(water_color="clear", algae="none", trash="none", flow="normal", odor="none",
             dead_fish=False, observed_at=ago(hours_ago))
    r.update(kw)
    return r


def conditions(rain24=0.0, rain_next=0.0, temp=70.0, pct=100, on_creek=True):
    return {
        "gauge": {"site_no": "11418500", "discharge_cfs": 5.0, "pct_of_median": pct, "on_creek": on_creek},
        "weather": {"temp_f": temp, "precip_24h_in": rain24, "precip_next_24h_in": rain_next, "station": "KGOO"},
        "fetched_at": ago(0.1),
    }


CLEAN = [report(h) for h in (2, 20, 40)]


def sig(res, name):
    return next(s for s in res["signals"] if s["name"] == name)


# --- shape / contract ------------------------------------------------------------
def test_contract_shape():
    res = compute_health("deer", CLEAN, conditions(), now=NOW)
    assert set(res) >= {"score", "band", "signals", "recent_report_count", "last_updated", "warnings"}
    assert 0 <= res["score"] <= 100
    assert res["band"] in {"good", "fair", "watch", "alert"}
    for s in res["signals"]:
        assert set(s) == {"name", "value", "weight", "explanation", "source"}
        assert s["explanation"] and s["source"]
    assert res["last_updated"].endswith("Z")


def test_score_is_explained_by_signals():
    """The score equals 100 plus the sum of signal weights (rounding aside), so it's auditable by hand."""
    res = compute_health("deer", [report(3, water_color="brown", trash="some")], conditions(rain24=0.3, temp=85), now=NOW)
    assert res["score"] == max(0, min(100, round(100 + sum(s["weight"] for s in res["signals"]))))


# --- public data only ------------------------------------------------------------
def test_zero_reports_public_data_only_is_sensible():
    res = compute_health("wolf", [], conditions(on_creek=False), now=NOW)
    assert res["recent_report_count"] == 0
    assert res["confidence"] == "low"
    assert res["band"] == "good"
    assert res["score"] == 90  # 100 - 10 held back for no eyes on the water
    assert sig(res, "report_coverage")["weight"] == -10


def test_no_conditions_and_no_reports_still_returns():
    res = compute_health("deer", None, None, now=NOW)
    assert res["band"] in {"good", "fair"}
    assert sig(res, "rain_24h")["value"] is None


def test_heavy_rain_and_heat_lower_public_only_score():
    calm = compute_health("deer", [], conditions(), now=NOW)["score"]
    stormy = compute_health("deer", [], conditions(rain24=1.2, temp=92, pct=400), now=NOW)["score"]
    assert stormy < calm
    assert stormy == 100 - 10 - 15 - 8 - 10


def test_offcreek_gauge_counts_a_quarter():
    on = compute_health("deer", [], conditions(pct=400, on_creek=True), now=NOW)
    off = compute_health("wolf", [], conditions(pct=400, on_creek=False), now=NOW)
    assert sig(on, "stream_flow")["weight"] == -10
    assert sig(off, "stream_flow")["weight"] == -2.5
    assert "context only" in sig(off, "stream_flow")["explanation"]


# --- perturbations that must flip the band ----------------------------------------
def test_dead_fish_flips_band_to_alert():
    base = compute_health("deer", CLEAN, conditions(), now=NOW)
    assert base["band"] == "good"
    pert = compute_health("deer", CLEAN + [report(1, dead_fish=True)], conditions(), now=NOW)
    assert pert["band"] == "alert"
    assert pert["score"] <= 39
    assert any(w["id"] == "contamination_alert" for w in pert["warnings"])


@pytest.mark.parametrize("odor", ["sewage", "chemical"])
def test_sewage_or_chemical_odor_is_alert(odor):
    res = compute_health("wolf", CLEAN + [report(5, odor=odor)], conditions(), now=NOW)
    assert res["band"] == "alert"


def test_old_dead_fish_downgrades_to_watch():
    res = compute_health("deer", CLEAN + [report(5 * 24, dead_fish=True)], conditions(), now=NOW)
    assert res["band"] == "watch"
    assert any(w["id"] == "contamination_followup" for w in res["warnings"])


def test_runoff_sediment_watch_needs_rain_and_brown_water():
    brown = CLEAN + [report(3, water_color="brown")]
    dry = compute_health("deer", brown, conditions(rain24=0.0), now=NOW)
    wet = compute_health("deer", brown, conditions(rain24=0.8), now=NOW)
    assert not any(w["id"] == "runoff_sediment_watch" for w in dry["warnings"])
    assert any(w["id"] == "runoff_sediment_watch" for w in wet["warnings"])
    assert wet["band"] == "watch"


def test_algal_bloom_watch_needs_algae_and_heat():
    algae = CLEAN + [report(3, algae="lots")]
    cool = compute_health("wolf", algae, conditions(temp=65), now=NOW)
    hot = compute_health("wolf", algae, conditions(temp=88), now=NOW)
    assert not any(w["id"] == "algal_bloom_watch" for w in cool["warnings"])
    assert any(w["id"] == "algal_bloom_watch" for w in hot["warnings"])
    assert BAND_ORDER(hot["band"]) >= BAND_ORDER("watch")


def test_rain_forecast_is_advisory_only():
    res = compute_health("deer", CLEAN, conditions(rain_next=0.9), now=NOW)
    assert any(w["id"] == "runoff_ahead" and w["level"] == "advisory" for w in res["warnings"])
    assert res["band"] == "good"


# --- windowing / weighting ---------------------------------------------------------
def test_reports_older_than_7_days_ignored():
    res = compute_health("deer", [report(8 * 24, dead_fish=True)], conditions(), now=NOW)
    assert res["recent_report_count"] == 0
    assert res["band"] == "good"


def test_future_reports_ignored():
    res = compute_health("deer", [report(-5, dead_fish=True)], conditions(), now=NOW)
    assert res["recent_report_count"] == 0


def test_newer_reports_weigh_more():
    new_bad = compute_health("deer", [report(1, trash="lots"), report(140)], conditions(), now=NOW)
    old_bad = compute_health("deer", [report(140, trash="lots"), report(1)], conditions(), now=NOW)
    assert sig(new_bad, "trash_lots")["weight"] < sig(old_bad, "trash_lots")["weight"]


def test_string_bools_and_case_tolerated():
    res = compute_health("deer", CLEAN + [report(1, dead_fish="true", odor="NONE")], conditions(), now=NOW)
    assert res["band"] == "alert"


def test_bad_timestamps_skipped():
    res = compute_health("deer", [dict(report(1), observed_at="not a date")], conditions(), now=NOW)
    assert res["recent_report_count"] == 0


# --- flags / bands ----------------------------------------------------------------
def test_report_flags():
    assert report_flags(report()) == []
    f = report_flags(report(dead_fish=True, odor="sewage", algae="lots", water_color="brown", trash="lots"))
    assert {"dead_fish_alert", "sewage_odor_alert", "algae_heavy", "brown_water", "trash_heavy"} <= set(f)


def test_band_thresholds():
    assert [band_for(x) for x in (100, 80, 79, 60, 59, 40, 39, 0)] == \
        ["good", "good", "fair", "fair", "watch", "watch", "alert", "alert"]


def BAND_ORDER(b):
    return {"good": 0, "fair": 1, "watch": 2, "alert": 3}[b]


def test_temperature_text_matches_threshold():
    """89.6°F displays as 90°F, so it must get the >=90 rule (seen live 2026-10-03)."""
    res = compute_health("deer", CLEAN, conditions(temp=89.6), now=NOW)
    s = sig(res, "air_temp")
    assert s["value"] == 90 and s["weight"] == -8 and "90°F" in s["explanation"]


# --- volunteer lab data ------------------------------------------------------------
def wq(age_days, **readings):
    return {"stations": [{"name": "Test station", "date": "2026-09-01", "age_days": age_days,
                          "readings": readings, "credit": "Test group via RiverDB"}]}


def with_wq(w):
    c = conditions()
    c["water_quality"] = w
    return c


def test_recent_low_oxygen_sample_costs_points():
    res = compute_health("deer", CLEAN, with_wq(wq(20, do_mg_l=4.2, ph=7.0)), now=NOW)
    s = sig(res, "volunteer_lab_data")
    assert s["weight"] == -15 and "dangerously low" in s["explanation"]


def test_ecoli_over_state_threshold():
    res = compute_health("deer", CLEAN, with_wq(wq(10, ecoli_mpn_100ml=900)), now=NOW)
    assert sig(res, "volunteer_lab_data")["weight"] == -12


def test_lab_sample_ageing():
    assert sig(compute_health("deer", CLEAN, with_wq(wq(100, do_mg_l=4)), now=NOW), "volunteer_lab_data")["weight"] == -7.5
    old = sig(compute_health("wolf", CLEAN, with_wq(wq(2400, do_mg_l=4)), now=NOW), "volunteer_lab_data")
    assert old["weight"] == 0 and "too old" in old["explanation"]


def test_healthy_lab_sample_no_penalty():
    s = sig(compute_health("deer", CLEAN, with_wq(wq(5, do_mg_l=9.1, ph=7.3, turbidity_ntu=1.3, water_temp_c=14)), now=NOW),
            "volunteer_lab_data")
    assert s["weight"] == 0 and "healthy" in s["explanation"]


def test_stream_flow_source_is_api_neutral():
    """Gauge data comes from the USGS Water Data API or legacy NWIS, so the source is just 'USGS <site>'."""
    assert sig(compute_health("deer", CLEAN, conditions(), now=NOW), "stream_flow")["source"] == "USGS 11418500"
    no_gauge = conditions(); no_gauge["gauge"] = None
    assert sig(compute_health("deer", CLEAN, no_gauge, now=NOW), "stream_flow")["source"] == "USGS"



# --- trash removal credit (optional report keys trash_removed / trash_bags) --------------
def test_trash_removed_still_counts_but_is_credited():
    plain = compute_health("deer", [report(2, trash="lots")], conditions(), now=NOW)
    cleaned = compute_health("deer", [report(2, trash="lots", trash_removed=True, trash_bags=3)], conditions(), now=NOW)
    assert sig(cleaned, "trash_lots")["weight"] == sig(plain, "trash_lots")["weight"] < 0   # still counts
    assert "reporter removed it (3 bags)" in sig(cleaned, "trash_lots")["explanation"]
    assert "removed" not in sig(plain, "trash_lots")["explanation"]


def test_trash_removed_multiple_reports_and_bad_bag_values():
    rs = [report(2, trash="some", trash_removed=True, trash_bags=1),
          report(5, trash="some", trash_removed="true", trash_bags="2"),
          report(8, trash="some", trash_removed=True, trash_bags=99),      # out of range: ignored
          report(9, trash="some")]
    e = sig(compute_health("deer", rs, conditions(), now=NOW), "trash_some")["explanation"]
    assert "In 3 of these the reporter removed it (3 bags)" in e
    one = sig(compute_health("deer", [report(2, trash="some", trash_removed=True)], conditions(), now=NOW),
              "trash_some")["explanation"]
    assert one.endswith("The reporter removed it. Thank you!")             # no bag count given


def test_trash_removed_keys_optional_and_flag():
    assert "trash_removed" in report_flags(report(trash="lots", trash_removed=True, trash_bags=2))
    assert "trash_removed" not in report_flags(report(trash="none", trash_removed=True))   # nothing to remove
    assert "trash_removed" not in report_flags(report(trash="lots"))
    compute_health("deer", [report(2, trash="lots")], conditions(), now=NOW)   # no new keys: fine



# --- orange water (possible mine drainage) -------------------------------------------------
def test_orange_water_signal_watch_and_flag():
    base = compute_health("wolf", CLEAN, conditions(), now=NOW)
    res = compute_health("wolf", CLEAN + [report(5, water_color="orange")], conditions(), now=NOW)
    s = sig(res, "water_orange")
    assert -12 <= s["weight"] < 0 and res["score"] < base["score"]
    assert "can be a sign of mine drainage" in s["explanation"]
    assert "natural iron seep" in s["explanation"]                          # natural-cause hedge
    assert "appropriate agency" in s["explanation"]
    assert "routes it to the Regional Water Board" not in s["explanation"]  # page doesn't say that
    assert "toxic" not in s["explanation"].lower()                       # careful wording, no overclaim
    assert "https://calepa.ca.gov/enforcement/complaints/" in s["explanation"]
    w = [w for w in res["warnings"] if w["id"] == "orange_water_watch"]
    assert w and w[0]["level"] == "watch" and BAND_ORDER(res["band"]) >= BAND_ORDER("watch")
    assert "toxic" not in w[0]["explanation"].lower()
    assert "natural iron seep" in w[0]["explanation"]
    assert "orange_water" in report_flags(report(water_color="orange"))
    assert "orange_water" not in report_flags(report(water_color="brown"))


def test_old_orange_report_no_watch_but_still_scored():
    res = compute_health("wolf", CLEAN + [report(4 * 24, water_color="orange")], conditions(), now=NOW)
    assert not any(w["id"] == "orange_water_watch" for w in res["warnings"])   # > 72 h: no watch
    assert sig(res, "water_orange")["weight"] < 0                             # still in the 7-day score


def test_orange_watch_becomes_creekwatch_alert():
    from data.alerts.others import creekwatch_alerts
    res = compute_health("deer", [report(2, water_color="orange")], conditions(), now=NOW)
    (a,) = [a for a in creekwatch_alerts("deer", res, NOW) if "orange" in a["id"]]
    assert (a["id"], a["severity"], a["category"]) == ("creekwatch:deer:orange_water_watch", "watch", "contamination")
