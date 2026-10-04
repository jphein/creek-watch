"""Seam between the API and the data lane (repo-root `data/` package).

Contract (agreed shape; see docs/SPEC.md):
  data.ingest.get_conditions(creek_id: str) -> dict          # /api/conditions shape, never raises
  data.score.compute_health(creek_id, reports, conditions) -> dict  # /api/health shape, pure
  data/sites.json                                             # /api/creeks shape

Until the data lane's modules exist, the stubs below keep every endpoint working.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("creekwatch.data")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Approximate public access points; the data lane's sites.json supersedes these.
STUB_CREEKS: list[dict[str, Any]] = [
    {
        "id": "wolf-creek",
        "name": "Wolf Creek",
        "town": "Grass Valley",
        "sites": [
            {"id": "wolf-memorial-park", "name": "Memorial Park", "lat": 39.2253, "lon": -121.0607},
            {"id": "wolf-mill-st", "name": "Downtown (Mill St)", "lat": 39.2179, "lon": -121.0618},
            {"id": "wolf-creek-trail", "name": "Wolf Creek Trail", "lat": 39.2105, "lon": -121.0700},
        ],
    },
    {
        "id": "deer-creek",
        "name": "Deer Creek",
        "town": "Nevada City",
        "sites": [
            {"id": "deer-pioneer-park", "name": "Pioneer Park", "lat": 39.2632, "lon": -121.0229},
            {"id": "deer-tribute-trail", "name": "Deer Creek Tribute Trail", "lat": 39.2594, "lon": -121.0193},
            {"id": "deer-downtown", "name": "Downtown Nevada City", "lat": 39.2617, "lon": -121.0164},
        ],
    },
]


def load_creeks(sites_json: Path) -> list[dict[str, Any]]:
    # Default location: prefer the data lane's loader, which also attaches geojson_line from creeks.geojson.
    if sites_json.resolve() == (Path(__file__).resolve().parents[2] / "data" / "sites.json"):
        try:
            from data import sites  # type: ignore

            creeks = sites.load_creeks()
            log.info("loaded %d creeks via data.sites", len(creeks))
            return creeks
        except Exception as e:
            log.warning("data.sites unavailable (%s); reading %s directly", e, sites_json)
    try:
        creeks = json.loads(sites_json.read_text())
        if isinstance(creeks, dict):  # tolerate {"creeks": [...]}
            creeks = creeks.get("creeks", [])
        assert isinstance(creeks, list) and creeks and all("id" in c and "sites" in c for c in creeks)
        log.info("loaded %d creeks from %s", len(creeks), sites_json)
        return creeks
    except FileNotFoundError:
        log.warning("%s not found; using stub creeks", sites_json)
    except Exception as e:  # malformed file must not take the API down
        log.error("bad %s (%s); using stub creeks", sites_json, e)
    return STUB_CREEKS


# ---- stubs -----------------------------------------------------------------

def _stub_get_conditions(creek_id: str) -> dict[str, Any]:
    return {"gauge": None, "weather": None, "fetched_at": utcnow_iso(), "stub": True}


def _stub_compute_health(creek_id: str, reports: list[dict], conditions: dict) -> dict[str, Any]:
    score, signals = 85, []

    def sig(name, value, weight, explanation):
        nonlocal score
        score += weight
        signals.append({"name": name, "value": value, "weight": weight, "explanation": explanation, "source": "citizen reports"})

    if any(r["dead_fish"] for r in reports):
        sig("dead_fish", True, -40, "Someone reported dead fish this week. That can mean a toxic spill or low oxygen.")
    bad = [r for r in reports if r["odor"] in ("sewage", "chemical")]
    if bad:
        sig("odor", bad[0]["odor"], -30, f"{len(bad)} report(s) of a {bad[0]['odor']} smell, a possible pollution source.")
    if any(r["algae"] == "lots" for r in reports):
        sig("algae", "lots", -15, "Heavy algae was reported; blooms can harm pets and wildlife.")
    if any(r["water_color"] == "brown" for r in reports):
        sig("water_color", "brown", -10, "Brown water was reported, usually runoff carrying soil.")
    if not reports:
        signals.append({"name": "no_recent_reports", "value": 0, "weight": 0,
                        "explanation": "No citizen reports in the last 7 days, so this score is a baseline.", "source": "citizen reports"})
    score = max(0, min(100, score))
    band = "good" if score >= 75 else "fair" if score >= 55 else "watch" if score >= 35 else "alert"
    if any(s["name"] in ("dead_fish", "odor") for s in signals):
        band = "alert"
    return {"score": score, "band": band, "signals": signals, "recent_report_count": len(reports),
            "last_updated": utcnow_iso(), "stub": True}


def _resolve() -> tuple[Callable, Callable]:
    gc, ch = _stub_get_conditions, _stub_compute_health
    try:
        from data import ingest  # type: ignore

        gc = ingest.get_conditions
        log.info("using data.ingest.get_conditions")
    except Exception as e:
        log.warning("data.ingest unavailable (%s); conditions stubbed", e)
    try:
        from data import score  # type: ignore

        ch = score.compute_health
        log.info("using data.score.compute_health")
    except Exception as e:
        log.warning("data.score unavailable (%s); health stubbed", e)
    return gc, ch


class DataLayer:
    def __init__(self, conditions_ttl_s: int):
        self._get_conditions, self._compute_health = _resolve()
        self.ttl = conditions_ttl_s
        self._cache: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def conditions(self, creek_id: str) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(creek_id)
            if hit and now - hit[0] < self.ttl:
                return hit[1]
        try:
            result = self._get_conditions(creek_id)
        except Exception as e:  # upstream USGS/NWS hiccups must not 500 the page
            log.exception("get_conditions(%s) failed", creek_id)
            result = {"gauge": None, "weather": None, "fetched_at": utcnow_iso(), "error": str(e)}
            with self._lock:  # short negative cache so a dead upstream isn't hammered
                self._cache[creek_id] = (now - self.ttl + 60, result)
            return result
        with self._lock:
            self._cache[creek_id] = (now, result)
        return result

    def health(self, creek_id: str, reports: list[dict], conditions: dict) -> dict[str, Any]:
        return self._compute_health(creek_id, reports, conditions)
