#!/usr/bin/env python3
"""Rebuild data/history_ceden_wolf_2024.json from CEDEN (data.ca.gov CKAN datastore SQL).

Run from the repo root:  python3 -m data.tools.build_ceden_history
Keeps only E. coli (exact analyte "E. coli", never total coliform) for the mapped stations.
"""
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from data import history

RESOURCE = "15a63495-8d9f-4a49-b43a-3092ef3106b9"   # FIB Monitoring Results, 2020 to present


def fetch(codes):
    in_list = ",".join(f"'{c}'" for c in codes if c.isalnum())
    sql = (f'SELECT "StationCode","StationName","SampleDate","Analyte","Unit","Result","ResultQualCode",'
           f'"6WeekGeoMean","6WeekCount","TargetLatitude","TargetLongitude","Project","MethodName" '
           f'FROM "{RESOURCE}" WHERE "StationCode" IN ({in_list}) ORDER BY "StationCode","SampleDate"')
    url = "https://data.ca.gov/api/3/action/datastore_search_sql?sql=" + urllib.parse.quote(sql)
    req = urllib.request.Request(url, headers={"User-Agent": "creekwatch/0.1 (+https://github.com/jphein/creek-watch)"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["result"]["records"]


def build(records):
    out = {}
    for r in records:
        if (r.get("Analyte") or "").strip() != "E. coli":      # exact: total coliform is a different test
            continue
        if (r.get("Unit") or "").strip() != "MPN/100 mL":
            raise ValueError(f"unexpected unit {r.get('Unit')!r}")
        st = out.setdefault(r["StationCode"], {
            "name": r["StationName"], "lat": float(r["TargetLatitude"]), "lon": float(r["TargetLongitude"]),
            "project": r["Project"], "method": r["MethodName"], "samples": []})
        st["samples"].append({
            "date": r["SampleDate"][:10], "ecoli": float(r["Result"]), "qual": r.get("ResultQualCode"),
            "gm6w": float(r["6WeekGeoMean"]) if r.get("6WeekGeoMean") not in (None, "") else None,
            "gm6w_n": int(float(r["6WeekCount"])) if r.get("6WeekCount") not in (None, "") else None,
        })
    for st in out.values():
        st["samples"].sort(key=lambda s: s["date"])
    return out


if __name__ == "__main__":
    recs = fetch(list(history.STATIONS))
    doc = {"_source": "CEDEN via data.ca.gov, resource " + RESOURCE, "_licence": history.STUDY["licence"],
           "_built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "stations": build(recs)}
    history.SNAPSHOT.write_text(json.dumps(doc, indent=1) + "\n")
    for code, st in doc["stations"].items():
        print(code, st["name"], len(st["samples"]), "E. coli samples", st["samples"][0]["date"], "..", st["samples"][-1]["date"])
