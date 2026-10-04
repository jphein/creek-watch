"""Creek Watch alert sources (docs/ALERTS-SPEC.md): every source normalised to one Alert model.

    from data import alerts
    alerts.REGISTRY["nws"].fetch()            # -> [Alert, ...]; never raises (see .last_error)
    alerts.fetch_all()                        # all sources in parallel -> {alerts, errors, fetched_at}
    alerts.creekwatch_alerts(creek_id, health)  # data.score warnings -> Alerts

Verification notes, endpoints and licences: data/alerts/SOURCES.md.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timezone

from .hab import HAB
from .model import SEVERITIES, SEVERITY_ORDER, Source, iso, make_alert
from .nwps import NWPS
from .nws import NWS
from .others import OEHHA, RiverDBBacteria, USGSFlow, creekwatch_alerts
from .sso import SSO

REGISTRY: dict[str, Source] = {s.id: s for s in (NWS(), NWPS(), USGSFlow(), SSO(), HAB(), RiverDBBacteria(), OEHHA())}

__all__ = ["ADAPTERS", "REGISTRY", "fetch_all", "creekwatch_alerts", "SEVERITY_ORDER", "SEVERITIES", "make_alert", "Source"]



# ---- API poller interface (agreed with morpheus-creekwatch-api) ----------------------------
# Each adapter: .source, .source_name, .interval_s, .fetch(ctx) -> list[Alert].
# Contract: a successful fetch returns the FULL current set (the store expires what's missing),
# so adapters RAISE on failure instead of returning a partial or empty list.
def _ctx_get(ctx, key, default=None):
    if ctx is None:
        return default
    if isinstance(ctx, dict):
        return ctx.get(key, default)
    return getattr(ctx, key, default)


def _ctx_now(ctx) -> datetime:
    now = _ctx_get(ctx, "now")
    if isinstance(now, datetime):
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


class _Adapter:
    def __init__(self, src: Source, fn=None):
        self.source, self.source_name, self.interval_s = src.id, src.name, src.poll_interval_s
        self._src, self._fn = src, fn

    def fetch(self, ctx=None) -> list[dict]:
        """RAISES on source failure (never swallow: the poller expires what a successful fetch omits)."""
        if self._fn:
            return self._fn(ctx)
        return self._src.run(_ctx_now(ctx))

    def __repr__(self):
        return f"<alert adapter {self.source} every {self.interval_s}s>"


class _CreekWatchSource(Source):
    id, name, poll_interval_s = "creekwatch", "Creek Watch", 300


def _creekwatch_fetch(ctx) -> list[dict]:
    from .. import score
    reports, conditions = _ctx_get(ctx, "reports"), _ctx_get(ctx, "conditions")
    if not callable(reports) or not callable(conditions):
        raise ValueError("creekwatch adapter needs ctx.reports and ctx.conditions")  # never 'all clear'
    now = _ctx_now(ctx)
    out = []
    for cid in _ctx_get(ctx, "creek_ids") or []:
        health = score.compute_health(cid, reports(cid, days=14), conditions(cid), now=now)
        out += creekwatch_alerts(cid, health, now)
    return out


def _usgs_fetch(ctx) -> list[dict]:
    conditions = _ctx_get(ctx, "conditions")
    src = REGISTRY["usgs"]
    if callable(conditions):
        return src.from_conditions(_ctx_now(ctx), conditions)
    return src.run(_ctx_now(ctx))      # no ctx: fall back to data.ingest


ADAPTERS = [_Adapter(REGISTRY[i]) for i in ("nws", "nwps", "sso", "hab", "riverdb", "oehha")] + [
    _Adapter(REGISTRY["usgs"], _usgs_fetch),
    _Adapter(_CreekWatchSource(), _creekwatch_fetch),
]

_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="creekwatch-alerts")


_inflight: dict[str, object] = {}
_inflight_lock = threading.Lock()


def fetch_all(source_ids=None, now: datetime | None = None, timeout_s: float = 20) -> dict:
    """Fetch the given sources (default: all) in parallel; never raises.

    - Each source gets its own deadline: max(timeout_s, source.deadline_s), so a slow-but-healthy
      source (the 10 MB sewage-spill file) isn't reported as timed out.
    - A source still running from a previous call is NOT resubmitted (in-flight guard); it is
      reported in `errors` as still running, so callers can't pile up threads on a hung upstream.
    """
    now = now or datetime.now(timezone.utc)
    ids = list(source_ids or REGISTRY)
    errors: dict[str, str] = {}
    futs = {}
    with _inflight_lock:
        for i in ids:
            if i not in REGISTRY:
                errors[i] = "unknown source"
                continue
            prev = _inflight.get(i)
            if prev is not None and not prev.done():
                errors[i] = "still running from a previous fetch; not resubmitted"
                continue
            f = _pool.submit(REGISTRY[i].fetch, now)
            _inflight[i] = f
            futs[f] = i
    start = time.monotonic()
    alerts: dict[str, dict] = {}
    for f, sid in futs.items():
        budget = max(timeout_s, REGISTRY[sid].deadline_s) - (time.monotonic() - start)
        try:
            result = f.result(timeout=max(0.0, budget))
        except FutureTimeout:
            errors[sid] = f"timed out after {max(timeout_s, REGISTRY[sid].deadline_s):g}s"
            continue
        for a in result:
            prev = alerts.get(a["id"])
            if prev is None or (a["updated"] or "") >= (prev["updated"] or ""):
                alerts[a["id"]] = a
        if REGISTRY[sid].last_error:
            errors[sid] = REGISTRY[sid].last_error
    ordered = sorted(alerts.values(), key=lambda a: a["effective"] or "", reverse=True)  # newest first
    ordered.sort(key=lambda a: -SEVERITY_ORDER[a["severity"]])                         # stable: by severity
    return {"alerts": ordered, "errors": errors, "fetched_at": iso(now)}
