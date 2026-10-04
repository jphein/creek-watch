"""Dated bacteria history from official studies (CEDEN), shown as history, never as current conditions.

Today: the Central Valley Regional Water Quality Control Board's 2024 Wolf Creek microbial
source-tracking study (CEDEN project "RWB5 Microbial Source Tracking Wolf Cr Study 2024"),
committed as a snapshot (history_ceden_wolf_2024.json, built by tools/build_ceden_history.py).

get_bacteria_history(creek_id) -> {"studies": [...]}. No network, never raises.
Nothing here feeds the creek-health score: a 2024 study says nothing about today's water.
"""
from __future__ import annotations

import json
import math
import pathlib
from functools import lru_cache

_DIR = pathlib.Path(__file__).resolve().parent
SNAPSHOT = _DIR / "history_ceden_wolf_2024.json"

# State Water Board, 2019 ISWEBE Bacteria Provisions (REC-1, salinity <= 1 ppth):
# E. coli six-week rolling geometric mean <= 100 cfu/100 mL (calculated weekly) and
# STV 320 cfu/100 mL not exceeded by > 10% of samples in a calendar month.
OBJECTIVE = {
    "indicator": "E. coli",
    "gm_six_week": 100,
    "stv": 320,
    "units": "cfu/100 mL",
    "source": "State Water Resources Control Board, 2019 ISWEBE Bacteria Provisions (Part 3, REC-1)",
    "url": "https://www.waterboards.ca.gov/plans_policies/docs/bacteria.pdf",
}
GM_MIN_SAMPLES = 5   # only call a 6-week geometric mean "above the objective" with >= 5 samples behind it

STUDY = {
    "id": "rwb5-wolf-mst-2024",
    "title": "2024 Regional Board study",
    "project": "RWB5 Microbial Source Tracking Wolf Cr Study 2024",
    "agency": "Central Valley Regional Water Quality Control Board",
    "credit": "Central Valley Regional Water Quality Control Board via CEDEN",
    "source_url": "https://data.ca.gov/dataset/surface-water-fecal-indicator-bacteria-results",
    "licence": "not specified (California open data portal lists no licence for this dataset)",
    "method_note": ("Measured as MPN/100 mL (method SM 9223 B); the state objective is written in "
                    "cfu/100 mL. The two are commonly treated as comparable, not identical."),
    # The Board's own web map of this study, for context: LINK ONLY. Its CSV is licensed "no reproduction without
    # written permission", so the numbers here come from CEDEN, never from that map (scratch/api/waterboards-bacteria.md).
    "context_url": "https://experience.arcgis.com/experience/1ea90c2492c94d1f999f200c6578af5a",
    "context_label": "Regional Board's map of this study",
}
# CEDEN station code -> our site id (both within 15 m; see data/SOURCES.md)
STATIONS = {
    "516NEV109": {"creek_id": "wolf", "site_id": "wolf-glen-jones-park", "waterbody": "Wolf Creek"},
    "516NEV101": {"creek_id": "wolf", "site_id": "wolf-wolf-rd", "waterbody": "Wolf Creek"},
}
# The study's other 7 stations in the Wolf Creek watershed. No Creek Watch site there (site_id None): shown in the
# same dated past-study panel, never as a site's current conditions. Upstream -> downstream.
STUDY_ONLY_STATIONS = {
    "516NEV114": {"creek_id": "wolf", "site_id": None, "waterbody": "French Ravine (tributary)"},
    "516NEV107": {"creek_id": "wolf", "site_id": None, "waterbody": "Wolf Creek"},
    "516NEV115": {"creek_id": "wolf", "site_id": None, "waterbody": "Rattlesnake Creek (tributary)"},
    "516NEV104": {"creek_id": "wolf", "site_id": None, "waterbody": "Wolf Creek"},
    "516NEV113": {"creek_id": "wolf", "site_id": None, "waterbody": "Cherry Creek (tributary)"},
    "516NEV103": {"creek_id": "wolf", "site_id": None, "waterbody": "Wolf Creek"},
    "516NEV102": {"creek_id": "wolf", "site_id": None, "waterbody": "South Wolf Creek (tributary)"},
}
ALL_STATIONS = {**STATIONS, **STUDY_ONLY_STATIONS}


@lru_cache(maxsize=1)
def _snapshot() -> dict:
    try:
        return json.loads(SNAPSHOT.read_text())
    except (OSError, ValueError):
        return {"stations": {}}


def _gmean(xs):
    xs = [x for x in xs if x and x > 0]
    return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else None


def summarise(samples: list[dict]) -> dict:
    """Plain facts from one station's samples (E. coli only)."""
    ec = [s for s in samples if s.get("ecoli") is not None]
    qualified = [s for s in ec if (s.get("gm6w_n") or 0) >= GM_MIN_SAMPLES and s.get("gm6w") is not None]
    over = [s for s in qualified if s["gm6w"] > OBJECTIVE["gm_six_week"]]
    # Censored results: CEDEN qual ">" = above the test's upper limit (true value higher), "<" = below its lower limit.
    # On a tie for the highest value prefer ">", so a censored maximum is never presented as exact.
    top = max(ec, key=lambda s: (s["ecoli"], s.get("qual") == ">"), default=None)
    return {
        "n_samples": len(ec),
        "first_date": ec[0]["date"] if ec else None,
        "last_date": ec[-1]["date"] if ec else None,
        "max_ecoli": top["ecoli"] if top else None,
        "max_qual": (top.get("qual") if top and top.get("qual") in (">", "<") else None),
        "n_over_stv": sum(1 for s in ec if s["ecoli"] > OBJECTIVE["stv"]),
        "season_gmean": round(_gmean([s["ecoli"] for s in ec]), 1) if ec else None,
        "gm6w_max_qualified": round(max((s["gm6w"] for s in qualified), default=0), 1) if qualified else None,
        "weeks_gm_over_objective": len(over),
        "gm_over_first": over[0]["date"] if over else None,
        "gm_over_last": over[-1]["date"] if over else None,
    }


def _sentence(name: str, sm: dict) -> str:
    if not sm["n_samples"]:
        return f"No E. coli results for {name}."
    highest = {">": f"highest above {sm['max_ecoli']:g} MPN/100 mL (the test's upper limit)",
               "<": f"highest below {sm['max_ecoli']:g} MPN/100 mL (the test's lower limit)"}.get(
        sm.get("max_qual"), f"highest {sm['max_ecoli']:g} MPN/100 mL")
    parts = [f"{sm['n_samples']} E. coli samples at {name} ({sm['first_date']} to {sm['last_date']}), {highest}"]
    if sm["weeks_gm_over_objective"]:
        parts.append(f"the 6-week geometric mean was above the state objective of {OBJECTIVE['gm_six_week']} "
                     f"in {sm['weeks_gm_over_objective']} weekly calculations with at least {GM_MIN_SAMPLES} "
                     f"samples ({sm['gm_over_first']} to {sm['gm_over_last']})")
    elif sm["gm6w_max_qualified"] is not None:
        parts.append(f"the 6-week geometric mean stayed at or below the state objective of "
                     f"{OBJECTIVE['gm_six_week']} (highest {sm['gm6w_max_qualified']:g})")
    return "; ".join(parts) + "."


def get_bacteria_history(creek_id: str) -> dict:
    snap = _snapshot().get("stations") or {}
    stations = []
    for code, m in ALL_STATIONS.items():   # mapped stations first, then the study's others upstream -> downstream
        if m["creek_id"] != creek_id or code not in snap:
            continue
        st = snap[code]
        sm = summarise(st["samples"])
        stations.append({
            "station_code": code, "name": st["name"], "lat": st["lat"], "lon": st["lon"],
            "site_id": m["site_id"], "waterbody": m["waterbody"], "samples": st["samples"], "summary": sm,
            "text": _sentence(st["name"], sm),
        })
    if not stations:
        return {"studies": []}
    return {"studies": [dict(STUDY, objective=OBJECTIVE, gm_min_samples=GM_MIN_SAMPLES,
                             period="2024-05-22 to 2024-09-04", is_current=False, stations=stations)]}
