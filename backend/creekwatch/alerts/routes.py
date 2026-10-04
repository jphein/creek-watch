"""HTTP surface for alerts: JSON API, Atom + CAP feeds, Web Push subscriptions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from ..ratelimit import RateLimiter, rate_key
from . import feeds
from .model import CATEGORIES, SEVERITY_RANK, STATUSES
from .push import PushService, SubscriptionInvalid, validate_endpoint, validate_subscription
from .store import AlertStore

MAX_BODY = 4096  # push subscription bodies are ~500 bytes


def register(app: FastAPI, store: AlertStore, push: PushService, poller, creek_ids: set[str],
             client_ip: Callable[[Request], str], public_url: str | None, sub_limiter: RateLimiter) -> None:

    def base_url(request: Request) -> str:
        return (public_url or str(request.base_url)).rstrip("/")

    def filters(creek_id, severity, category, status):
        if creek_id and creek_id not in creek_ids:
            raise HTTPException(404, f"Unknown creek_id {creek_id!r}")
        if severity and severity not in SEVERITY_RANK:
            raise HTTPException(422, "severity must be info, advisory, watch or alert (minimum)")
        if category and category not in CATEGORIES:
            raise HTTPException(422, f"unknown category {category!r}")
        if status not in STATUSES | {"all"}:
            raise HTTPException(422, "status must be active, expired, cancelled or all")
        return dict(creek_id=creek_id, severity=severity, category=category,
                    status=None if status == "all" else status)

    @app.get("/api/alerts")
    def list_alerts(creek_id: str | None = None, severity: str | None = None, category: str | None = None,
                    status: str = "active", limit: int = Query(200, ge=1, le=500)) -> list[dict[str, Any]]:
        return store.query(**filters(creek_id, severity, category, status), limit=limit)

    @app.get("/api/alerts/sources")
    def alert_sources() -> dict[str, Any]:
        return {"sources": store.sources(), "schedule": poller.status() if poller else {}}

    @app.get("/api/alerts/item")
    def get_alert(id: str = Query(..., max_length=240)) -> dict[str, Any]:  # ids contain ':' and '/'
        a = store.get(id)
        if not a:
            raise HTTPException(404, "Alert not found")
        return a

    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @app.get("/alerts.atom", include_in_schema=False)
    def atom(request: Request, creek_id: str | None = None, severity: str | None = None) -> Response:
        rows = store.query(**filters(creek_id, severity, None, "active"), limit=200)
        base = base_url(request)
        self_url = base + "/alerts.atom" + (f"?{request.url.query}" if request.url.query else "")
        title = "Creek Watch water alerts" + (f": {creek_id}" if creek_id else "")
        return Response(feeds.atom_feed(rows, base, self_url, _now(), title),
                        media_type="application/atom+xml; charset=utf-8",
                        headers={"Cache-Control": "public, max-age=120"})

    @app.get("/alerts.cap.xml", include_in_schema=False)
    def cap(request: Request, creek_id: str | None = None, severity: str | None = None,
            id: str | None = Query(None, max_length=240)) -> Response:
        if id:  # a single CAP 1.2 message
            a = store.get(id)
            if not a:
                raise HTTPException(404, "Alert not found")
            a.pop("first_seen", None)
            return Response(feeds.cap_document(a), media_type="application/cap+xml; charset=utf-8")
        rows = store.query(**filters(creek_id, severity, None, "active"), limit=200)
        base = base_url(request)
        self_url = base + "/alerts.cap.xml" + (f"?{request.url.query}" if request.url.query else "")
        return Response(feeds.cap_feed(rows, base, self_url, _now()),
                        media_type="application/atom+xml; charset=utf-8",
                        headers={"Cache-Control": "public, max-age=120"})

    # -- Web Push ------------------------------------------------------------------------------

    async def _json_body(request: Request) -> Any:
        clen = request.headers.get("content-length")
        if clen and (not clen.isdigit() or int(clen) > MAX_BODY):
            raise HTTPException(413, "body too large")
        raw = b""
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > MAX_BODY:
                raise HTTPException(413, "body too large")
        try:
            return json.loads(raw or b"null")
        except ValueError:
            raise HTTPException(422, "body must be JSON")

    def _limit(request: Request) -> None:
        retry = sub_limiter.check(rate_key(client_ip(request)))
        if retry is not None:
            raise HTTPException(429, "Too many requests; try again shortly.", headers={"Retry-After": str(int(retry))})

    @app.get("/api/push/vapid-public-key")
    def vapid_public_key() -> dict[str, str]:
        if not push.enabled:
            raise HTTPException(503, "Push notifications are not configured on this server.")
        return {"key": push.vapid.public}

    @app.post("/api/push/subscriptions", status_code=201)
    @app.post("/api/push/subscribe", status_code=201, include_in_schema=False)  # web lane's name
    async def subscribe(request: Request) -> JSONResponse:
        _limit(request)
        if not push.enabled:
            raise HTTPException(503, "Push notifications are not configured on this server.")
        try:
            sub = validate_subscription(await _json_body(request), creek_ids)
            result = push.upsert(sub)
        except SubscriptionInvalid as e:
            raise HTTPException(422, str(e))
        except OverflowError:
            raise HTTPException(503, "Subscriptions are full right now; please try again later.")
        filters = {"creek_ids": sub["creek_ids"], "min_severity": sub["min_severity"],
                   "severities": sub["severities"],
                   "quiet_hours": ({"start": sub["quiet_start"], "end": sub["quiet_end"], "tz": sub["tz"]}
                                   if sub["quiet_start"] else None)}
        sid = hashlib.sha256(sub["endpoint"].encode()).hexdigest()[:16]  # opaque; never echo the endpoint
        return JSONResponse({"id": sid, "status": result, "filters": filters, **filters},
                            status_code=201 if result == "created" else 200)

    @app.delete("/api/push/subscriptions", status_code=204)
    @app.post("/api/push/unsubscribe", status_code=204, include_in_schema=False)  # web lane's name
    async def unsubscribe(request: Request) -> Response:
        _limit(request)
        body = await _json_body(request)
        endpoint = (body or {}).get("endpoint") if isinstance(body, dict) else None
        try:
            validate_endpoint(endpoint)
        except SubscriptionInvalid as e:
            raise HTTPException(422, str(e))
        push.delete(endpoint)  # 204 whether or not it existed: don't leak which endpoints are subscribed
        return Response(status_code=204)
