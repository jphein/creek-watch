"""Creek Watch API: FastAPI app serving /api/*, /uploads/* and the static PWA at /."""

from __future__ import annotations

import json
import logging
import math
import os
import platform
import socket
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import db
from .config import REPO_ROOT, Settings
from .data_iface import DataLayer, load_creeks, utcnow_iso
from .photos import HEIC_SUPPORTED, PhotoError, process_photo
from .ratelimit import RateLimiter

log = logging.getLogger("creekwatch")

WaterColor = Literal["clear", "cloudy", "brown", "green", "other"]
Amount = Literal["none", "some", "lots"]
Flow = Literal["dry", "low", "normal", "high", "flood"]
Odor = Literal["none", "earthy", "sewage", "chemical", "rotten", "other"]

REPORT_COLUMNS = ("id", "creek_id", "site_id", "lat", "lon", "observed_at", "created_at", "water_color", "algae",
                  "trash", "flow", "odor", "dead_fish", "wildlife_seen", "notes", "reporter_name", "photo_file", "flags")
HEALTH_WINDOW = timedelta(days=7)
_START = time.time()
_START_ISO = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- helpers ---------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def _line_points(geo: Any) -> list[tuple[float, float]]:
    """Pull (lat, lon) pairs out of any GeoJSON-ish structure ([lon, lat] order)."""
    out: list[tuple[float, float]] = []

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for k in ("geometry", "coordinates", "features", "geometries"):
                if k in x:
                    walk(x[k])
        elif isinstance(x, (list, tuple)):
            if len(x) >= 2 and all(isinstance(v, (int, float)) for v in x[:2]):
                out.append((float(x[1]), float(x[0])))
            else:
                for y in x:
                    walk(y)

    walk(geo)
    return out


def parse_iso_utc(value: str, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, f"{field} must be an ISO-8601 time, e.g. 2026-10-04T15:30:00Z")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_flags(r: dict[str, Any]) -> list[str]:
    flags = []
    if r["dead_fish"]:
        flags.append("dead_fish")
    if r["odor"] in ("sewage", "chemical"):
        flags.append(f"{r['odor']}_odor")
    if r["algae"] == "lots":
        flags.append("heavy_algae")
    if r["water_color"] == "brown":
        flags.append("brown_water")
    if r["flow"] == "flood":
        flags.append("flood")
    if r["trash"] == "lots":
        flags.append("heavy_trash")
    return flags


def client_ip(request: Request) -> str:
    # uvicorn --proxy-headers already rewrites request.client from X-Forwarded-For behind Caddy.
    return request.client.host if request.client else "unknown"


# ---- app -------------------------------------------------------------------

def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init(s.db_path)
        s.uploads_dir.mkdir(parents=True, exist_ok=True)
        yield

    app = FastAPI(title="Creek Watch API", version="0.1.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    creeks = load_creeks(s.sites_json)
    creek_by_id = {c["id"]: c for c in creeks}
    data = DataLayer(s.conditions_ttl_s)
    limiter = RateLimiter(s.rate_limit_count, s.rate_limit_window_s)
    photo_budget = RateLimiter(s.photo_budget, s.rate_limit_window_s)
    app.state.settings, app.state.data, app.state.limiter = s, data, limiter

    def row_to_report(row: Any) -> dict[str, Any]:
        r = dict(zip(REPORT_COLUMNS, row))
        r["dead_fish"] = bool(r["dead_fish"])
        # Privacy: never publish the reporter's exact GPS fix (could be their doorstep).
        r["lat"], r["lon"] = round(r["lat"], s.public_coord_decimals), round(r["lon"], s.public_coord_decimals)
        r["flags"] = json.loads(r["flags"] or "[]")
        pf = r.pop("photo_file")
        r["photo_url"] = f"/uploads/{pf}" if pf else None
        return r

    def fetch_reports(creek_id: str | None, since: str | None, limit: int) -> list[dict[str, Any]]:
        q, args = f"SELECT {', '.join(REPORT_COLUMNS)} FROM reports WHERE 1=1", []
        if creek_id:
            q += " AND creek_id = ?"
            args.append(creek_id)
        if since:
            q += " AND observed_at >= ?"
            args.append(since)
        q += " ORDER BY observed_at DESC, id DESC LIMIT ?"
        args.append(limit)
        with db.connect(s.db_path) as conn:
            return [row_to_report(tuple(r)) for r in conn.execute(q, args)]

    def require_creek(creek_id: str) -> dict[str, Any]:
        c = creek_by_id.get(creek_id)
        if not c:
            raise HTTPException(404, f"Unknown creek_id {creek_id!r}. Known: {', '.join(creek_by_id)}")
        return c

    # -- routes --------------------------------------------------------------

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/version")
    def version() -> dict[str, Any]:
        from realm_sigil import version_dict

        sha = os.environ.get("CREEKWATCH_GIT_SHA", "")
        branch = os.environ.get("CREEKWATCH_GIT_BRANCH", "")
        built = os.environ.get("CREEKWATCH_BUILT", "")
        dirty = False
        if not sha:  # dev checkout: ask git
            from realm_sigil.handler import _git_info

            g = _git_info(str(REPO_ROOT))
            sha, branch, dirty = g["hash"], branch or g["branch"], g["dirty"]
        return version_dict(
            "creekwatch", "Creek Watch: citizen creek reports + explainable creek-health score",
            "creature", "https://github.com/jphein/creek-watch",
            hash=sha[:7] or "dev", branch=branch or "unknown", dirty=dirty, built=built or _START_ISO,
            started=_START_ISO, uptime=int(time.time() - _START),
            runtime=f"python{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            os_info=f"{sys.platform}/{platform.machine()}", host=socket.gethostname(), pid=os.getpid(),
        )

    @app.get("/api/creeks")
    def list_creeks() -> list[dict[str, Any]]:
        return creeks

    @app.post("/api/reports", status_code=201)
    async def create_report(
        request: Request,
        creek_id: Annotated[str, Form()],
        lat: Annotated[float, Form(ge=-90, le=90)],
        lon: Annotated[float, Form(ge=-180, le=180)],
        water_color: Annotated[WaterColor, Form()],
        algae: Annotated[Amount, Form()],
        trash: Annotated[Amount, Form()],
        flow: Annotated[Flow, Form()],
        odor: Annotated[Odor, Form()],
        observed_at: Annotated[str | None, Form()] = None,
        site_id: Annotated[str | None, Form()] = None,
        dead_fish: Annotated[bool, Form()] = False,
        wildlife_seen: Annotated[str | None, Form(max_length=500)] = None,
        notes: Annotated[str | None, Form(max_length=1000)] = None,
        reporter_name: Annotated[str | None, Form(max_length=60)] = None,
        photo: Annotated[UploadFile | None, File()] = None,
    ) -> JSONResponse:
        retry = limiter.check(client_ip(request))
        if retry is not None:
            raise HTTPException(429, "Too many reports from this device. Please wait a few minutes.",
                                headers={"Retry-After": str(int(retry))})

        creek = require_creek(creek_id)
        if not (math.isfinite(lat) and math.isfinite(lon)):
            raise HTTPException(422, "lat/lon must be numbers")
        pts = [(st["lat"], st["lon"]) for st in creek["sites"]] + _line_points(creek.get("geojson_line"))
        nearest_km = min(haversine_km(lat, lon, a, b) for a, b in pts)
        if nearest_km > s.max_km_from_creek:
            raise HTTPException(422, f"That location is {nearest_km:.0f} km from {creek['name']}; "
                                     f"reports must be within {s.max_km_from_creek:.0f} km of the creek.")

        site_ids = {st["id"] for st in creek["sites"]}
        site_id = (site_id or "").strip() or None
        if site_id and site_id not in site_ids:
            raise HTTPException(422, f"site_id {site_id!r} is not on {creek['name']}")
        if not site_id:  # auto-pick the nearest named spot if the reporter is right at one
            best = min(creek["sites"], key=lambda st: haversine_km(lat, lon, st["lat"], st["lon"]))
            if haversine_km(lat, lon, best["lat"], best["lon"]) <= 1.5:
                site_id = best["id"]

        now = datetime.now(timezone.utc)
        obs = parse_iso_utc(observed_at, "observed_at") if observed_at else now
        if obs > now + timedelta(hours=1):
            raise HTTPException(422, "observed_at is in the future")
        if obs < now - timedelta(days=30):
            raise HTTPException(422, "observed_at is more than 30 days ago")

        photo_file = None
        if photo is not None and photo.filename:
            raw = await photo.read(s.max_photo_bytes + 1)
            if len(raw) > s.max_photo_bytes:
                raise HTTPException(413, f"Photo is larger than {s.max_photo_bytes // (1024 * 1024)} MB.")
            if raw:
                # Spent only here: after all validation, so junk requests can't drain it.
                if photo_budget.check("global") is not None:
                    raise HTTPException(503, "We're receiving a lot of photos right now. "
                                             "Please send your report without the photo, or try again in a few minutes.")
                try:
                    clean = await run_in_threadpool(process_photo, raw, s.photo_max_px)
                except PhotoError as e:
                    raise HTTPException(415, str(e))
                photo_file = f"{uuid.uuid4().hex}.jpg"
                (s.uploads_dir / photo_file).write_bytes(clean)

        clean_text = lambda v: (v or "").strip() or None  # noqa: E731
        rec = {
            "creek_id": creek_id, "site_id": site_id, "lat": round(lat, 6), "lon": round(lon, 6),
            "observed_at": iso(obs), "created_at": iso(now),
            "water_color": water_color, "algae": algae, "trash": trash, "flow": flow, "odor": odor,
            "dead_fish": bool(dead_fish), "wildlife_seen": clean_text(wildlife_seen), "notes": clean_text(notes),
            "reporter_name": clean_text(reporter_name), "photo_file": photo_file,
        }
        rec["flags"] = json.dumps(compute_flags(rec))
        cols = [c for c in REPORT_COLUMNS if c != "id"]
        with db.connect(s.db_path) as conn:
            cur = conn.execute(f"INSERT INTO reports ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                               [int(rec[c]) if c == "dead_fish" else rec[c] for c in cols])
            rid = cur.lastrowid
            row = conn.execute(f"SELECT {', '.join(REPORT_COLUMNS)} FROM reports WHERE id = ?", (rid,)).fetchone()
        log.info("report %s creek=%s site=%s photo=%s", rid, creek_id, site_id, bool(photo_file))
        return JSONResponse(row_to_report(tuple(row)), status_code=201)

    @app.get("/api/reports")
    def list_reports(
        creek_id: str | None = None,
        since: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[dict[str, Any]]:
        if creek_id:
            require_creek(creek_id)
        since_iso = iso(parse_iso_utc(since, "since")) if since else None
        return fetch_reports(creek_id, since_iso, limit)

    @app.get("/api/reports/{report_id}")
    def get_report(report_id: int) -> dict[str, Any]:
        with db.connect(s.db_path) as conn:
            row = conn.execute(f"SELECT {', '.join(REPORT_COLUMNS)} FROM reports WHERE id = ?", (report_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Report not found")
        return row_to_report(tuple(row))

    def _conditions(cid: str) -> dict[str, Any]:
        return data.conditions(cid)

    def _health(cid: str) -> dict[str, Any]:
        since = iso(datetime.now(timezone.utc) - HEALTH_WINDOW)
        reports = fetch_reports(cid, since, 500)
        try:
            return data.health(cid, reports, data.conditions(cid))
        except Exception:
            log.exception("compute_health(%s) failed", cid)
            raise HTTPException(503, "Health score is temporarily unavailable")

    @app.get("/api/conditions")
    def conditions(creek_id: str | None = None) -> dict[str, Any]:
        """One creek's conditions; omit creek_id for {creek_id: conditions} across all creeks."""
        if creek_id:
            require_creek(creek_id)
            return _conditions(creek_id)
        return {cid: _conditions(cid) for cid in creek_by_id}

    @app.get("/api/health")
    def health(creek_id: str | None = None) -> dict[str, Any]:
        """One creek's health score; omit creek_id for {creek_id: health} across all creeks."""
        if creek_id:
            require_creek(creek_id)
            return _health(creek_id)
        return {cid: _health(cid) for cid in creek_by_id}

    @app.get("/api/meta", include_in_schema=False)
    def meta() -> dict[str, Any]:
        return {"heic_supported": HEIC_SUPPORTED, "max_photo_mb": s.max_photo_bytes // (1024 * 1024),
                "max_km_from_creek": s.max_km_from_creek, "now": utcnow_iso()}

    # Static mounts last so /api/* always wins.
    s.uploads_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=s.uploads_dir), name="uploads")
    if (s.web_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=s.web_dir, html=True), name="web")
    else:
        log.warning("no web build at %s; serving API only", s.web_dir)

    return app

