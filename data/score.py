"""Creek-health score and early-warning rules for Creek Watch.

Rule-based and explainable on purpose: no machine learning. Every point the score
loses is a signal with a plain-language explanation and a source, so a reader can
check each step by hand. See data/README.md for the full table and its limits.

Public entry points (pure functions, no I/O):
    compute_health(creek_id, reports, conditions, now=None) -> dict
    report_flags(report) -> list[str]
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

WINDOW_DAYS = 7          # reports older than this are ignored
HALF_LIFE_H = 72.0       # a report's weight halves every 3 days
ALERT_RECENT_H = 72      # dead fish / sewage / chemical inside this window -> alert
RUNOFF_RECENT_H = 48
ORANGE_RECENT_H = 72     # orange water inside this window -> watch (possible mine drainage)     # brown/cloudy reports inside this window count toward runoff watch

BANDS = [(80, "good"), (60, "fair"), (40, "watch"), (0, "alert")]
BAND_ORDER = {"good": 0, "fair": 1, "watch": 2, "alert": 3}
BAND_CAP = {"fair": 79, "watch": 59, "alert": 39}   # highest score allowed in a forced band

# Citizen-report penalties: max points lost if *every* recent report shows the condition.
# The actual penalty is max_points * (recency-weighted share of recent reports that show it).
REPORT_RULES = [
    # (signal name, field, values, max points, plain-language why)
    ("dead_fish", "dead_fish", {True}, 40,
     "Dead fish usually mean something in the water stressed or poisoned them: low oxygen, heat, or a spill."),
    ("odor_sewage_chemical", "odor", {"sewage", "chemical"}, 30,
     "A sewage or chemical smell points to a leak, spill or illegal discharge, which is a risk to people and pets as well as fish."),
    ("odor_rotten", "odor", {"rotten"}, 10,
     "A rotten-egg smell can be natural decay in still water, but it also comes with low oxygen."),
    ("water_brown", "water_color", {"brown"}, 15,
     "Brown water carries soil. Sediment smothers the gravel that insects and fish eggs need, and it carries pollutants with it."),
    ("water_orange", "water_color", {"orange"}, 12,
     "Orange water can be a sign of mine drainage (iron and other metals) from old mine sites "
     "upstream. Avoid contact, and report it through CalEPA's environmental complaint form "
     "(https://calepa.ca.gov/enforcement/complaints/), which routes it to the Regional Water Board."),
    ("water_green", "water_color", {"green"}, 10,
     "Green water often means algae growing on extra nutrients (fertilizer, septic, pet waste)."),
    ("water_cloudy", "water_color", {"cloudy"}, 6,
     "Cloudy water has some suspended sediment or algae, which is a mild warning sign."),
    ("algae_lots", "algae", {"lots"}, 15,
     "Lots of algae can use up the oxygen at night and some kinds make toxins that are dangerous to dogs."),
    ("algae_some", "algae", {"some"}, 5,
     "Some algae is normal in summer, so this is a small deduction."),
    ("trash_lots", "trash", {"lots"}, 10,
     "Lots of trash harms wildlife and often means runoff from streets or camps is reaching the creek."),
    ("trash_some", "trash", {"some"}, 4,
     "Some trash was seen."),
    ("flow_flood", "flow", {"flood"}, 10,
     "Flood flow scours the banks and flushes street runoff into the creek."),
    ("flow_dry", "flow", {"dry"}, 8,
     "A dry or nearly dry bed strands fish and insects. That's common in late summer on foothill creeks, but still stressful."),
]


# Volunteer lab/field sample thresholds (screening values, see data/README.md):
#   DO >= 7.0 mg/L: Central Valley Basin Plan minimum for cold-water (COLD) habitat
#   pH 6.5-8.5:     Central Valley Basin Plan objective
#   E. coli 320 MPN/100 mL: CA statewide bacteria objective (REC-1 statistical threshold value)
#   water temp > 20 C: rule of thumb for stress on trout and other cold-water life
#   turbidity > 10 / 25 NTU: rule of thumb for elevated / high (no fixed numeric objective here)
ECOLI_LIMIT = 320     # MPN/100 mL: CA statewide REC-1 statistical threshold value (STV) -
                      # an objective for the distribution of samples, NOT a single-sample limit
ECOLI_WATCH_DAYS = 14 # bacteria warning is "watch" for 2 weeks after the test, then "advisory"
WQ_FULL_DAYS = 60     # samples this recent count fully
WQ_HALF_DAYS = 180    # ... this recent count half; older ones are shown as context only


def _wq_penalties(r: dict) -> list[tuple[str, float]]:
    out = []
    do = r.get("do_mg_l")
    if do is not None:
        if do < 5:
            out.append((f"dissolved oxygen {do} mg/L is dangerously low for fish", 15))
        elif do < 7:
            out.append((f"dissolved oxygen {do} mg/L is below the 7 mg/L cold-water standard", 6))
    ph = r.get("ph")
    if ph is not None and not 6.5 <= ph <= 8.5:
        out.append((f"pH {ph} is outside the 6.5-8.5 standard", 5))
    ec = r.get("ecoli_mpn_100ml")
    if ec is not None and ec > 320:
        out.append((f"E. coli {ec:g} MPN/100 mL is above California's 320 recreational threshold", 12))
    t = r.get("water_temp_c")
    if t is not None and t > 20:
        out.append((f"water {t} °C is warm enough to stress trout", 5))
    tu = r.get("turbidity_ntu")
    if tu is not None:
        if tu > 25:
            out.append((f"turbidity {tu} NTU is high (muddy)", 8))
        elif tu > 10:
            out.append((f"turbidity {tu} NTU is elevated", 4))
    return out


def ecoli_text(ec: float, name: str, date_iso: str, credit: str | None = None) -> str:
    """Accurate E. coli wording, shared with data.alerts (no 'unsafe': 320 is an STV)."""
    d = datetime.fromisoformat(str(date_iso)[:10])
    who = f"{credit}: a" if credit else "A"
    return (f"{who} volunteer test on {d:%b %-d, %Y} measured E. coli of {ec:g} MPN/100 mL at {name}, "
            f"above California's recreational water-quality threshold of {ECOLI_LIMIT} "
            "(a statistical threshold, not a single-sample limit).")


def _fmt_readings(r: dict) -> str:
    names = {"do_mg_l": ("DO", "mg/L"), "ph": ("pH", ""), "water_temp_c": ("water", "°C"),
             "turbidity_ntu": ("turbidity", "NTU"), "ecoli_mpn_100ml": ("E. coli", "/100 mL"),
             "conductivity_us_cm": ("conductivity", "µS/cm")}
    return ", ".join(f"{names[k][0]} {v:g}{(' ' + names[k][1]) if names[k][1] else ''}"
                     for k, v in r.items() if k in names)


# --------------------------------------------------------------------------- utils
def _parse_time(v) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _truthy(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "on"}
    return bool(v)


def _field(r: dict, field: str):
    v = r.get(field)
    if field == "dead_fish":
        return _truthy(v)
    return v.strip().lower() if isinstance(v, str) else v


def _bags(r: dict) -> int | None:
    v = r.get("trash_bags")
    if isinstance(v, bool) or v is None:
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= 20 else None


def _trash_removed_note(reports: list[dict]) -> str:
    """Trash still counts (it shows runoff/dumping reached the creek), but credit cleanups.
    trash_removed / trash_bags are optional: older reports and other callers won't have them."""
    removed = [r for r in reports if _truthy(r.get("trash_removed"))]
    if not removed:
        return ""
    bags = sum(b for b in (_bags(r) for r in removed) if b)
    bag_txt = f" ({bags} bag{'s' if bags != 1 else ''})" if bags else ""
    if len(reports) == 1:
        return f" The reporter removed it{bag_txt}. Thank you!"
    return f" In {len(removed)} of these the reporter removed it{bag_txt}. Thank you!"


def band_for(score: float) -> str:
    for lo, name in BANDS:
        if score >= lo:
            return name
    return "alert"


def report_flags(report: dict) -> list[str]:
    """Flags for a single report (returned by POST /api/reports)."""
    f = []
    if _field(report, "dead_fish"):
        f.append("dead_fish_alert")
    odor = _field(report, "odor")
    if odor in ("sewage", "chemical"):
        f.append(f"{odor}_odor_alert")
    if _field(report, "algae") == "lots":
        f.append("algae_heavy")
    if _field(report, "water_color") == "brown":
        f.append("brown_water")
    if _field(report, "water_color") == "green":
        f.append("green_water")
    if _field(report, "water_color") == "orange":
        f.append("orange_water")
    if _field(report, "trash") == "lots":
        f.append("trash_heavy")
    if _truthy(report.get("trash_removed")) and _field(report, "trash") in ("some", "lots"):
        f.append("trash_removed")
    if _field(report, "flow") == "flood":
        f.append("flood_flow")
    return f


# ---------------------------------------------------------------------------- core
def compute_health(creek_id: str, reports: list[dict] | None, conditions: dict | None,
                   now: datetime | None = None) -> dict:
    """Score 0-100 (higher = healthier), band, explained signals and early warnings.

    reports: dicts with SPEC fields (water_color, algae, trash, flow, odor, dead_fish,
             observed_at). Older than 7 days or in the future (>1 h) are ignored.
    conditions: output of data.ingest.get_conditions(), or None.
    """
    now = _parse_time(now) or datetime.now(timezone.utc)
    signals: list[dict] = []
    warnings: list[dict] = []
    forced = "good"  # minimum band forced by early-warning rules

    def sig(name, value, weight, explanation, source):
        signals.append({"name": name, "value": value, "weight": round(weight, 1),
                        "explanation": explanation, "source": source})

    def warn(wid, level, title, explanation):
        nonlocal forced
        warnings.append({"id": wid, "level": level, "title": title, "explanation": explanation})
        if level in BAND_ORDER and BAND_ORDER[level] > BAND_ORDER[forced]:
            forced = level

    # ---- recent reports, recency-weighted
    recent = []
    for r in reports or []:
        t = _parse_time(r.get("observed_at"))
        if t is None or t > now + timedelta(hours=1) or now - t > timedelta(days=WINDOW_DAYS):
            continue
        age_h = max(0.0, (now - t).total_seconds() / 3600)
        recent.append((r, t, age_h, 0.5 ** (age_h / HALF_LIFE_H)))
    total_w = sum(w for *_, w in recent)

    weather = (conditions or {}).get("weather") or {}
    gauge = (conditions or {}).get("gauge")
    rain24 = weather.get("precip_24h_in")
    rain_next = weather.get("precip_next_24h_in")
    temp = weather.get("temp_f")
    if temp is not None:
        temp = round(temp)  # thresholds and text use the same whole-degree number
    wsrc = "NWS api.weather.gov (station %s)" % weather.get("station", "?")
    rsrc = "Open-Meteo hourly precipitation (gridded model data)"

    # ---- public data: rain
    if rain24 is None:
        sig("rain_24h", None, 0, "Rainfall data is unavailable right now, so it isn't counted.", rsrc)
    else:
        if rain24 >= 1.0:
            w, why = -15, "Heavy rain in the last 24 hours washes oil, sediment and litter off streets into the creek."
        elif rain24 >= 0.5:
            w, why = -10, "Substantial rain in the last 24 hours flushes street runoff into the creek."
        elif rain24 >= 0.1:
            w, why = -4, "Light rain in the last 24 hours brings a little runoff."
        else:
            w, why = 0, "No meaningful rain in the last 24 hours, so there's no runoff pulse."
        sig("rain_24h", rain24, w, f"{rain24:.2f} in of rain. {why}", rsrc)

    # ---- public data: heat (air temperature as a proxy for water temperature)
    if temp is None:
        sig("air_temp", None, 0, "Air temperature is unavailable right now.", wsrc)
    else:
        if temp >= 90:
            w, why = -8, "Very hot air warms shallow water, which holds less oxygen and speeds up algae growth."
        elif temp >= 80:
            w, why = -4, "Warm air warms the creek a little, so there is less oxygen and more algae growth."
        else:
            w, why = 0, "Mild temperatures put no heat stress on the creek."
        sig("air_temp", temp, w, f"{temp:.0f}°F air temperature (we have no water thermometer, so this is a proxy). {why}", wsrc)

    # ---- public data: gauge flow vs normal for this date
    if gauge and gauge.get("pct_of_median") is not None:
        pct = gauge["pct_of_median"]
        on_creek = bool(gauge.get("on_creek"))
        scale = 1.0 if on_creek else 0.25   # off-creek gauge = context only
        where = ("on this creek" if on_creek else
                 "on the Bear River far downstream, so this is context only and counts for a quarter")
        if pct >= 300:
            w, why = -10, "Flow is far above normal for this date: storm runoff and stirred-up sediment."
        elif pct >= 150:
            w, why = -3, "Flow is above normal for this date."
        elif pct < 25:
            w, why = -6, "Flow is far below normal for this date. Low water warms quickly and concentrates pollutants."
        elif pct < 50:
            w, why = -3, "Flow is below normal for this date."
        else:
            w, why = 0, "Flow is in the normal range for this date."
        sig("stream_flow", pct, w * scale,
            f"USGS gauge {gauge.get('site_no')} reads {gauge.get('discharge_cfs')} cfs, which is {pct}% of the "
            f"long-term median for this date (gauge is {where}). {why}",
            f"USGS {gauge.get('site_no')}")
    else:
        sig("stream_flow", None, 0, "No usable stream-gauge reading right now.", "USGS")

    # ---- volunteer lab/field samples (RiverDB: SYRCL, SSI, WCCA)
    wq_st = ((conditions or {}).get("water_quality") or {}).get("stations") or []
    if wq_st:
        st = wq_st[0]  # most recent sample on this creek
        age = st.get("age_days")
        age = 10 ** 6 if age is None else age
        scale = 1.0 if age <= WQ_FULL_DAYS else 0.5 if age <= WQ_HALF_DAYS else 0.0
        pens = _wq_penalties(st.get("readings") or {})
        total = -sum(p for _, p in pens) * scale
        when = f"{st.get('date')} ({age} days ago)"
        if scale == 0:
            how = ("This sample is too old to count toward today's score; it is shown as background, "
                   "and it is the most recent volunteer sample published for this creek.")
        elif pens:
            how = "Out of range: " + "; ".join(t for t, _ in pens) + "." + (
                " The sample is 2-6 months old, so it counts half." if scale < 1 else "")
        else:
            how = "All readings are within healthy ranges." + (
                " The sample is 2-6 months old." if scale < 1 else "")
        sig("volunteer_lab_data", st.get("date"), total,
            f"Latest volunteer water test, {st.get('name')}, {when}: {_fmt_readings(st.get('readings') or {})}. {how}",
            st.get("credit") or "RiverDB volunteer monitoring")
    else:
        sig("volunteer_lab_data", None, 0, "No volunteer water-test data is available right now.",
            "RiverDB volunteer monitoring")

    # E. coli advisory: ANY recent volunteer test on this creek above California's 320 recreational threshold
    # (checked across all stations; the newest station may not measure E. coli at all).
    hot = [s for s in wq_st
           if (s.get("readings") or {}).get("ecoli_mpn_100ml") is not None
           and s["readings"]["ecoli_mpn_100ml"] > ECOLI_LIMIT
           and s.get("age_days") is not None and s["age_days"] <= WQ_FULL_DAYS]
    if hot:
        worst = max(hot, key=lambda s: s["readings"]["ecoli_mpn_100ml"])
        level = "watch" if worst["age_days"] <= ECOLI_WATCH_DAYS else "advisory"
        warn("bacteria_watch", level, "E. coli above the recreational threshold",
             ecoli_text(worst["readings"]["ecoli_mpn_100ml"], worst.get("name") or "a monitoring site",
                        worst["date"], worst.get("credit")) +
             " Consider skipping swimming there until a newer test comes back lower.")

    # ---- citizen reports
    n = len(recent)
    if n == 0:
        sig("report_coverage", 0, -10,
            "Nobody has filed a report for this creek in the last 7 days, so the score uses public data only "
            "and holds back 10 points until someone takes a look.", "Creek Watch citizen reports")
    elif n < 3:
        sig("report_coverage", n, -5,
            f"Only {n} report(s) this week, so a single observation can swing the picture. 5 points are held back.",
            "Creek Watch citizen reports")
    else:
        sig("report_coverage", n, 0, f"{n} reports this week give a reasonable picture.", "Creek Watch citizen reports")

    if n:
        for name, field, values, pts, why in REPORT_RULES:
            hit_w = sum(w for r, _, _, w in recent if _field(r, field) in values)
            if hit_w == 0:
                continue
            share = hit_w / total_w
            count = sum(1 for r, *_ in recent if _field(r, field) in values)
            extra = _trash_removed_note([r for r, *_ in recent if _field(r, field) in values]) \
                if field == "trash" else ""
            sig(name, round(share, 2), -pts * share,
                f"{count} of {n} recent report(s) ({share:.0%} once newer reports are weighted more). {why}{extra}",
                "Creek Watch citizen reports")

    # ---- early-warning rules
    def recent_with(pred, hours):
        return [(r, t) for r, t, age, _ in recent if age <= hours and pred(r)]

    severe = recent_with(lambda r: _field(r, "dead_fish") or _field(r, "odor") in ("sewage", "chemical"),
                         ALERT_RECENT_H)
    older_severe = recent_with(lambda r: _field(r, "dead_fish") or _field(r, "odor") in ("sewage", "chemical"),
                               WINDOW_DAYS * 24)
    if severe:
        kinds = sorted({"dead fish" if _field(r, "dead_fish") else f"{_field(r, 'odor')} odor" for r, _ in severe})
        warn("contamination_alert", "alert", "Possible contamination",
             f"Reported in the last 3 days: {', '.join(kinds)}. Keep people and dogs out of the water. "
             "If you see a spill, call the CalOES spill line at 1-800-852-7550.")
    elif older_severe:
        warn("contamination_followup", "watch", "Recent contamination report",
             "Dead fish or a sewage/chemical smell was reported 3 to 7 days ago. A fresh look would help confirm it has cleared.")

    muddy = recent_with(lambda r: _field(r, "water_color") in ("brown", "cloudy"), RUNOFF_RECENT_H)
    if rain24 is not None and rain24 >= 0.5 and muddy:
        warn("runoff_sediment_watch", "watch", "Runoff / sediment watch",
             f"{rain24:.2f} in of rain in 24 h and {len(muddy)} report(s) of brown or cloudy water. "
             "Storm runoff is carrying sediment and street pollutants into the creek.")
    elif rain_next is not None and rain_next >= 0.5:
        warn("runoff_ahead", "advisory", "Heavy rain forecast",
             f"About {rain_next:.2f} in of rain is forecast in the next 24 h. A runoff pulse is likely, "
             "so reports during or after the storm are especially useful.")

    orange = recent_with(lambda r: _field(r, "water_color") == "orange", ORANGE_RECENT_H)
    if orange:
        warn("orange_water_watch", "watch", "Orange water reported",
             f"{len(orange)} report(s) of orange water in the last 3 days. Orange water can be a sign of "
             "mine drainage (iron and other metals) from old mine sites. Avoid contact until it clears, "
             "and report it through CalEPA's environmental complaint form (https://calepa.ca.gov/enforcement/complaints/).")

    bloomy = recent_with(lambda r: _field(r, "algae") == "lots" or _field(r, "water_color") == "green",
                         WINDOW_DAYS * 24)
    if bloomy and temp is not None and temp >= 80:
        warn("algal_bloom_watch", "watch", "Algal bloom watch",
             f"{len(bloomy)} report(s) of heavy algae or green water with {temp:.0f}°F heat. Some blooms are toxic: "
             "keep dogs out of the water and don't let them drink it.")

    # ---- combine
    raw = 100 + sum(s["weight"] for s in signals)
    score = max(0, min(100, round(raw)))
    band = band_for(score)
    if BAND_ORDER[forced] > BAND_ORDER[band]:
        capped = min(score, BAND_CAP[forced])
        sig("early_warning_cap", forced, capped - score,
            f"An early-warning rule put this creek on '{forced}', so the score is capped at {BAND_CAP[forced]}.",
            "Creek Watch early-warning rules")
        score, band = capped, forced

    times = [t for _, t, _, _ in recent]
    for k in ("fetched_at",):
        t = _parse_time((conditions or {}).get(k))
        if t:
            times.append(t)
    last = max(times) if times else now

    # Confidence is about eyes on the water: public data alone can't see trash, algae or fish.
    confidence = "low" if n == 0 else ("high" if n >= 6 and weather else "medium")

    return {
        "creek_id": creek_id,
        "score": score,
        "band": band,
        "signals": signals,
        "warnings": warnings,
        "recent_report_count": n,
        "confidence": confidence,
        "last_updated": _iso(last),
        "method": "rule-based v1; see /about (data/README.md)",
    }
