#!/usr/bin/env python3
"""Rebuild data/wq_snapshot.json: latest sample per RiverDB station in data.wq.STATIONS.

Run from the repo root:  python3 -m data.tools.build_wq_snapshot
Pulls each station's history once (polite: sequential) and keeps only the latest visit.
"""
import json
import pathlib
import time
from datetime import datetime, timezone

from data import wq

out = {"_source": "RiverDB GraphQL (gql.riverdb.org), latest visit per station; data (c) the monitoring groups",
       "_built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "stations": {}}
for creek, stations in wq.STATIONS.items():
    for st in stations:
        try:
            latest = wq.latest_readings(wq._gql(st["id"], 120))
        except Exception as e:  # noqa: BLE001
            print("FAIL", st["id"], e)
            continue
        if latest:
            out["stations"][st["id"]] = latest
            print(creek, st["agency"], st["name"], latest["date"], latest["readings"])
        time.sleep(0.5)
p = pathlib.Path(wq.__file__).with_name("wq_snapshot.json")
p.write_text(json.dumps(out, indent=1) + "\n")
print("wrote", p, len(out["stations"]), "stations")
