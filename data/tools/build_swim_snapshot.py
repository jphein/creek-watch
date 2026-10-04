#!/usr/bin/env python3
"""Rebuild data/swim_snapshot.json: latest SYRCL E. coli per swim hole (RiverDB).

Run from the repo root:  python3 -m data.tools.build_swim_snapshot
Polite by construction: wq._gql enforces >= 5 s between RiverDB calls, and each query is
bounded to the current and previous year.
"""
import json
from datetime import datetime, timezone

from data import wq

now = datetime.now(timezone.utc)
out = {"_source": "RiverDB GraphQL, project SYRCL_BACTERIA, exact param 'EColi' (MPN/100 mL)",
       "_built": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "stations": {}}
for st in wq.SWIM_STATIONS:
    try:
        latest = wq.latest_ecoli(wq._gql(st["id"], 30, from_year=now.year - 1))
    except Exception as e:  # noqa: BLE001
        print("FAIL", st["name"], e)
        continue
    if latest:
        out["stations"][st["id"]] = latest
        print(st["name"], latest)
p = wq._DIR / "swim_snapshot.json"
p.write_text(json.dumps(out, indent=1) + "\n")
print("wrote", p, len(out["stations"]), "stations")
