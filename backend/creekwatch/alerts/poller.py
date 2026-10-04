"""Alert poller: per-source schedules, isolation, backoff, dedupe, NEW/ESCALATED-only push.

Adapter contract (agreed with the data lane; registry `data.alerts.ADAPTERS`):
    adapter.source: str, adapter.source_name: str, adapter.interval_s: int,
    adapter.fetch(ctx) -> list[Alert dict]   # the FULL current set for that source; may raise
Isolation: each fetch runs on its own worker thread with a deadline; a hung or failing source is
backed off (exponential, capped) and never blocks the others or the app's request threads.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .model import AlertInvalid, validate_alert
from .store import AlertStore

log = logging.getLogger("creekwatch.alerts")

MAX_ALERTS_PER_SOURCE = 500
MIN_INTERVAL_S, MAX_INTERVAL_S = 60, 6 * 3600
MAX_BACKOFF_S = 3600


@dataclass
class AlertContext:
    """What adapters may use (no DB handles): creeks, recent reports, cached conditions."""
    creeks: list[dict]
    reports_fn: Callable[[str, int], list[dict]]
    conditions_fn: Callable[[str], dict]
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def creek_ids(self) -> list[str]:
        return [c["id"] for c in self.creeks]

    def reports(self, creek_id: str, days: int = 14) -> list[dict]:
        return self.reports_fn(creek_id, days)

    def conditions(self, creek_id: str) -> dict:
        return self.conditions_fn(creek_id)


@dataclass
class SourceState:
    next_run: float = 0.0
    failures: int = 0
    running: bool = False
    started: float = 0.0


class Poller:
    def __init__(self, adapters: list[Any], store: AlertStore, ctx_factory: Callable[[], AlertContext],
                 push=None, fetch_timeout_s: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.adapters = {}
        for a in adapters:
            src = getattr(a, "source", None)
            if not isinstance(src, str) or src in self.adapters:
                log.error("skipping adapter with missing/duplicate source: %r", a)
                continue
            self.adapters[src] = a
        self.store, self.ctx_factory, self.push = store, ctx_factory, push
        self.fetch_timeout_s, self.clock = fetch_timeout_s, clock
        self.state = {s: SourceState() for s in self.adapters}
        self._pool = ThreadPoolExecutor(max_workers=max(2, len(self.adapters)), thread_name_prefix="alert-src")
        self._lock = threading.Lock()

    def interval(self, src: str) -> float:
        try:
            v = float(getattr(self.adapters[src], "interval_s", 600))
        except (TypeError, ValueError):
            v = 600
        return min(MAX_INTERVAL_S, max(MIN_INTERVAL_S, v))

    def _fetch(self, src: str, ctx: AlertContext) -> list[dict]:
        raw = self.adapters[src].fetch(ctx)
        if not isinstance(raw, (list, tuple)):
            raise TypeError(f"{src}.fetch returned {type(raw).__name__}, expected a list")
        good, bad = [], 0
        for item in list(raw)[:MAX_ALERTS_PER_SOURCE]:
            try:
                a = validate_alert(item)
            except AlertInvalid as e:
                bad += 1
                log.warning("%s: dropped invalid alert: %s", src, e)
                continue
            if a["source"] != src:
                bad += 1
                log.warning("%s: dropped alert claiming source %r", src, a["source"])
                continue
            good.append(a)
        if len(raw) > MAX_ALERTS_PER_SOURCE:
            log.warning("%s: returned %d alerts; kept the first %d", src, len(raw), MAX_ALERTS_PER_SOURCE)
        return good

    def _fail(self, src: str, why: str) -> None:
        st = self.state[src]
        st.failures += 1
        delay = min(MAX_BACKOFF_S, self.interval(src) * (2 ** min(st.failures, 6)))
        st.next_run = self.clock() + delay
        self.store.record_failure(src, why, st.failures)
        log.warning("alert source %s failed (%s); retry in %.0f s", src, why, delay)

    def run_due(self, force: bool = False) -> dict[str, Any]:
        """One poll cycle: launch every due source, wait (bounded) for them, store, push. Sync."""
        now = self.clock()
        ctx = self.ctx_factory()
        launched: dict[str, Future] = {}
        with self._lock:
            for src, st in self.state.items():
                if st.running:
                    if now - st.started > self.fetch_timeout_s * 10:
                        log.error("alert source %s has been stuck for %.0f s", src, now - st.started)
                    continue
                if force or st.next_run <= now:
                    st.running, st.started = True, now
                    fut = self._pool.submit(self._fetch, src, ctx)
                    fut.add_done_callback(lambda f, s=src: setattr(self.state[s], "running", False))
                    launched[src] = fut
        summary: dict[str, Any] = {"ran": [], "failed": {}, "new": [], "escalated": [], "pushed": 0}
        deadline = time.monotonic() + self.fetch_timeout_s
        for src, fut in launched.items():
            try:
                alerts = fut.result(timeout=max(0.01, deadline - time.monotonic()))
            except TimeoutError:
                self._fail(src, f"timeout after {self.fetch_timeout_s:.0f}s")  # thread finishes on its own
                summary["failed"][src] = "timeout"
                continue
            except Exception as e:
                self._fail(src, f"{type(e).__name__}: {str(e)[:200]}")
                summary["failed"][src] = type(e).__name__
                continue
            st = self.state[src]
            st.failures, st.next_run = 0, self.clock() + self.interval(src)
            summary["ran"].append(src)
            for ch in self.store.apply_fetch(src, alerts):
                if ch.kind in ("new", "escalated") and ch.alert["status"] == "active":
                    summary[ch.kind].append(ch.alert["id"])
                    # Claim first (atomic, DB-level): at most one process announces each (id, severity),
                    # even during the redeploy overlap. Claimed even with push off, so a later
                    # subscriber never receives a backlog.
                    if self.store.claim_push(ch.alert["id"], ch.alert["severity"]) and self.push is not None:
                        try:
                            summary["pushed"] += self.push.notify(ch.alert, ch.kind).get("sent", 0)
                        except Exception:
                            log.exception("push fan-out failed for %s", ch.alert["id"])
        self.store.expire_due()
        return summary

    def status(self) -> dict[str, Any]:
        now = self.clock()
        return {src: {"interval_s": self.interval(src), "failures": st.failures, "running": st.running,
                      "next_run_in_s": max(0, round(st.next_run - now))} for src, st in self.state.items()}

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def load_adapters(use_data_package: bool) -> list[Any]:
    """The data lane's registry, or nothing (the app runs fine with zero sources)."""
    if not use_data_package:
        return []
    try:
        from data.alerts import ADAPTERS  # type: ignore

        log.info("alert adapters: %s", [getattr(a, "source", "?") for a in ADAPTERS])
        return list(ADAPTERS)
    except Exception as e:
        log.warning("data.alerts unavailable (%s); no alert sources", e)
        return []


def main() -> None:  # CLI: python -m creekwatch.alerts.poller --once   (ops / systemd timer option)
    import argparse
    import json as _json

    from ..config import Settings
    from ..main import create_app

    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="run every source once and exit")
    a = ap.parse_args()
    app = create_app(Settings())
    p: Poller = app.state.alert_poller
    print(_json.dumps(p.run_due(force=a.once), indent=1))
    p.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    main()
