"""Creek Watch alert sources (docs/ALERTS-SPEC.md): every source normalised to one Alert model.

    from data import alerts
    alerts.REGISTRY["nws"].fetch()            # -> [Alert, ...]; never raises (see .last_error)
    alerts.fetch_all()                        # all sources in parallel -> {alerts, errors, fetched_at}
    alerts.creekwatch_alerts(creek_id, health)  # data.score warnings -> Alerts

Verification notes, endpoints and licences: data/alerts/SOURCES.md.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
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
class _Adapter:
    def __init__(self, src: Source, fn=None):
        self.source, self.source_name, self.interval_s = src.id, src.name, src.poll_interval_s
        self._src, self._fn = src, fn

    def fetch(self, ctx) -> list[dict]:
        return self._fn(ctx) if self._fn else self._src._fetch(ctx.now)   # raises on failure

    def __repr__(self):
        return f"<alert adapter {self.source} every {self.interval_s}s>"


class _CreekWatchSource(Source):
    id, name, poll_interval_s = "creekwatch", "Creek Watch", 300


def _creekwatch_fetch(ctx) -> list[dict]:
    from .. import score
    out = []
    for cid in ctx.creek_ids:
        health = score.compute_health(cid, ctx.reports(cid, days=14), ctx.conditions(cid), now=ctx.now)
        out += creekwatch_alerts(cid, health, ctx.now)
    return out


ADAPTERS = [_Adapter(REGISTRY[i]) for i in ("nws", "nwps", "sso", "hab", "riverdb", "oehha")] + [
    _Adapter(REGISTRY["usgs"], lambda ctx: REGISTRY["usgs"].from_conditions(ctx.now, ctx.conditions)),
    _Adapter(_CreekWatchSource(), _creekwatch_fetch),
]

_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="creekwatch-alerts")


def fetch_all(source_ids=None, now: datetime | None = None, timeout_s: float = 20) -> dict:
    """Fetch the given sources (default: all) in parallel. A source that fails or runs past
    timeout_s contributes no alerts and an entry in `errors`; it never blocks the others."""
    now = now or datetime.now(timezone.utc)
    ids = list(source_ids or REGISTRY)
    futs = {_pool.submit(REGISTRY[i].fetch, now): i for i in ids if i in REGISTRY}
    done, pending = wait(futs, timeout=timeout_s)
    alerts: dict[str, dict] = {}
    errors: dict[str, str] = {}
    for f in done:
        sid = futs[f]
        for a in f.result():
            prev = alerts.get(a["id"])
            if prev is None or (a["updated"] or "") >= (prev["updated"] or ""):
                alerts[a["id"]] = a
        if REGISTRY[sid].last_error:
            errors[sid] = REGISTRY[sid].last_error
    for f in pending:
        errors[futs[f]] = f"timed out after {timeout_s:g}s"
    for i in ids:
        if i not in REGISTRY:
            errors[i] = "unknown source"
    ordered = sorted(alerts.values(), key=lambda a: a["effective"] or "", reverse=True)  # newest first
    ordered.sort(key=lambda a: -SEVERITY_ORDER[a["severity"]])                         # stable: by severity
    return {"alerts": ordered, "errors": errors, "fetched_at": iso(now)}
