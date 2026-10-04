"""CEDEN 2024 Wolf Creek bacteria history: shown as dated history, never as current conditions."""
import copy
import json
import pathlib

from data import history, score
from data.tools import build_ceden_history as builder

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "ceden_fib_wolf_2024.json").read_text())["records"]


def test_builder_keeps_exact_ecoli_only():
    built = builder.build(FIX)
    assert set(built) == set(history.ALL_STATIONS) and len(built) == 9
    assert all(len(st["samples"]) == 13 for st in built.values())          # 26 rows each: 13 E. coli + 13 TC
    assert len(FIX) == 234 and {r["Analyte"] for r in FIX} == {"E. coli", "Coliform, Total"}


def test_builder_rejects_unexpected_units():
    bad = copy.deepcopy(FIX)
    next(r for r in bad if r["Analyte"] == "E. coli")["Unit"] = "cfu/100 mL"
    try:
        builder.build(bad)
    except ValueError as e:
        assert "unit" in str(e)
    else:
        raise AssertionError("unit change not caught")


def test_snapshot_matches_fixture_build():
    snap = json.loads(history.SNAPSHOT.read_text())["stations"]
    assert snap == builder.build(FIX)


def test_wolf_history_numbers_and_wording():
    (study,) = history.get_bacteria_history("wolf")["studies"]
    assert study["title"] == "2024 Regional Board study" and study["is_current"] is False
    assert study["credit"] == "Central Valley Regional Water Quality Control Board via CEDEN"
    assert study["licence"].startswith("not specified")
    assert study["objective"]["gm_six_week"] == 100 and study["objective"]["stv"] == 320
    assert study["objective"]["url"] == "https://www.waterboards.ca.gov/plans_policies/docs/bacteria.pdf"
    st = {s["site_id"]: s for s in study["stations"]}
    wolf_rd, museum = st["wolf-wolf-rd"]["summary"], st["wolf-glen-jones-park"]["summary"]
    assert (wolf_rd["weeks_gm_over_objective"], wolf_rd["gm_over_first"], wolf_rd["gm_over_last"]) == \
        (4, "2024-07-17", "2024-08-07")
    assert museum["weeks_gm_over_objective"] == 0 and museum["gm6w_max_qualified"] == 41.0
    assert wolf_rd["max_ecoli"] == 648.8 and museum["max_ecoli"] == 770.1
    assert "at least 5 samples" in st["wolf-wolf-rd"]["text"]
    assert "unsafe" not in json.dumps(study).lower()


def test_gm_gate_excludes_thin_means():
    """Early 6-week 'means' from 1-3 samples (317, 226...) must not count as exceedances."""
    samples = history._snapshot()["stations"]["516NEV101"]["samples"]
    assert any(s["gm6w"] > 100 and s["gm6w_n"] < 5 for s in samples)       # they exist in the data...
    assert history.summarise(samples)["weeks_gm_over_objective"] == 4       # ...and are excluded


def test_other_creek_and_no_score_effect():
    assert history.get_bacteria_history("deer") == {"studies": []}
    cond = {"weather": {"temp_f": 70, "precip_24h_in": 0.0}, "gauge": None}
    base = score.compute_health("wolf", [], cond)
    with_hist = score.compute_health("wolf", [], dict(cond, bacteria_history=history.get_bacteria_history("wolf")))
    assert base["score"] == with_hist["score"] and base["warnings"] == with_hist["warnings"]


def test_all_nine_study_stations_mapped_first_then_upstream_to_downstream():
    (study,) = history.get_bacteria_history("wolf")["studies"]
    sts = study["stations"]
    assert [st["station_code"] for st in sts[:2]] == ["516NEV109", "516NEV101"]          # our two sites first
    assert [st["site_id"] for st in sts[:2]] == ["wolf-glen-jones-park", "wolf-wolf-rd"]
    others = sts[2:]
    assert len(others) == 7 and all(st["site_id"] is None for st in others)
    assert [st["lat"] for st in others] == sorted((st["lat"] for st in others), reverse=True)  # upstream -> downstream
    assert {st["waterbody"] for st in others} >= {"French Ravine (tributary)", "Cherry Creek (tributary)", "Wolf Creek"}
    assert all(st["summary"]["n_samples"] == 13 for st in sts)


def test_study_only_station_numbers():
    """Numbers from CEDEN; the Board's own map (independent copy) agrees on max and >320 counts."""
    (study,) = history.get_bacteria_history("wolf")["studies"]
    st = {s["station_code"]: s for s in study["stations"]}
    fr, cherry = st["516NEV114"]["summary"], st["516NEV113"]["summary"]
    assert (fr["max_ecoli"], fr["n_over_stv"], fr["weeks_gm_over_objective"]) == (2419.6, 2, 8)
    assert (cherry["max_ecoli"], cherry["n_over_stv"]) == (613.1, 2)
    assert st["516NEV107"]["summary"]["n_over_stv"] == 0
    assert "French Ravine at Hidden Valley Road" in st["516NEV114"]["text"]


def test_context_link_only_and_never_current_or_unsafe():
    (study,) = history.get_bacteria_history("wolf")["studies"]
    assert study["is_current"] is False and study["period"] == "2024-05-22 to 2024-09-04"
    assert study["context_url"] == "https://experience.arcgis.com/experience/1ea90c2492c94d1f999f200c6578af5a"
    snap = json.loads(history.SNAPSHOT.read_text())
    assert snap["_source"].startswith("CEDEN via data.ca.gov")          # numbers from CEDEN, not the ArcGIS CSV
    text = json.dumps(study).lower()
    assert "unsafe" not in text and "dangerous" not in text


def test_builder_main_fetches_all_nine_codes(tmp_path):
    asked = []
    doc = builder.main(lambda codes: asked.extend(codes) or FIX, out=tmp_path / "snap.json")
    assert sorted(asked) == sorted(history.ALL_STATIONS) and len(asked) == 9
    assert json.loads((tmp_path / "snap.json").read_text())["stations"] == doc["stations"] == builder.build(FIX)


def test_censored_maximum_is_never_shown_as_exact():
    """Oracle S1 on #109: French Ravine 2024-07-10 is ">2419.6" (above the test's upper limit)."""
    (study,) = history.get_bacteria_history("wolf")["studies"]
    st = {s["station_code"]: s for s in study["stations"]}
    fr = st["516NEV114"]
    assert fr["summary"]["max_qual"] == ">"
    assert "highest above 2419.6 MPN/100 mL (the test's upper limit)" in fr["text"]
    assert "highest 2419.6" not in fr["text"]
    wolf_rd = st["516NEV101"]                                   # an exact maximum keeps the plain wording
    assert wolf_rd["summary"]["max_qual"] is None and "highest 648.8 MPN/100 mL" in wolf_rd["text"]


def test_censored_low_and_ties():
    base = {"gm6w": None, "gm6w_n": None}
    low = [dict(base, date="2024-06-01", ecoli=1.0, qual="<"), dict(base, date="2024-06-08", ecoli=1.0, qual="<")]
    sm = history.summarise(low)
    assert sm["max_qual"] == "<" and "highest below 1 MPN/100 mL (the test's lower limit)" in history._sentence("X", sm)
    tie = [dict(base, date="2024-06-01", ecoli=2419.6, qual="="), dict(base, date="2024-06-08", ecoli=2419.6, qual=">")]
    assert history.summarise(tie)["max_qual"] == ">"           # a censored tie wins: never shown as exact
