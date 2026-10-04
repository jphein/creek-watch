"""CEDEN 2024 Wolf Creek bacteria history: shown as dated history, never as current conditions."""
import copy
import json
import pathlib

from data import history, score
from data.tools import build_ceden_history as builder

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "ceden_fib_wolf_2024.json").read_text())["records"]


def test_builder_keeps_exact_ecoli_only():
    built = builder.build(FIX)
    assert set(built) == {"516NEV109", "516NEV101"}
    assert all(len(st["samples"]) == 13 for st in built.values())          # 26 rows each: 13 E. coli + 13 TC
    assert len(FIX) == 52 and {r["Analyte"] for r in FIX} == {"E. coli", "Coliform, Total"}


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
