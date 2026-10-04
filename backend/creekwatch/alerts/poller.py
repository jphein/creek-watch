"""Alert poller: per-source schedules, isolation, backoff, dedupe, NEW/ESCALATED-only push.

Adapter contract (agreed with the data lane; registry `data.alerts.ADAPTERS`):
    adapter.source: str, adapter.source_name: str, adapter.interval_s: int,
    adapter.fetch(ctx) -> list[Alert dict]   # the FULL current set for that source; may raise
Isolation: each fetch runs on its own worker thread with a deadline; a hung or failing source is
backed off (exponential, capped) and never blocks the others or the app's request threads.
"""

from __future__ import annotations

import logging
import os
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
MIN_INTERVAL_S, MAX_INTERVAL_S = 60, 7 * 86400   # honour the data lane's daily / 12 h sources
MAX_BACKOFF_S = 6 * 3600
FETCH_TIMEOUT_S = 90.0                        # SSO's 10 MB download needs > 60 s
# next_due = pass start + interval, but each pass reads the clock only after its start-up latency
# (docker exec + create_app). If this pass started with LESS latency than the previous one, it sees a
# source a few seconds short of due; without slack that source would slip a whole timer cycle.
DUE_SLACK_S = 30.0


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
                 push=None, fetch_timeout_s: float = FETCH_TIMEOUT_S, clock: Callable[[], float] = time.time,
                 load_error: str | None = None):
        self.adapters = {}
        for a in adapters:
            src = getattr(a, "source", None)
            if not isinstance(src, str) or src in self.adapters:
                log.error("skipping adapter with missing/duplicate source: %r", a)
                continue
            self.adapters[src] = a
        self.store, self.ctx_factory, self.push = store, ctx_factory, push
        self.fetch_timeout_s, self.clock = fetch_timeout_s, clock
        self.load_error = load_error
        self.state = {s: SourceState() for s in self.adapters}
        # Persisted schedule (wall clock): a fresh `--once` process resumes intervals and backoff.
        for src, (next_due, failures) in store.schedule().items():
            if src in self.state:
                self.state[src].next_run = next_due or 0.0
                self.state[src].failures = failures or 0
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
        delay = min(max(MAX_BACKOFF_S, self.interval(src)), self.interval(src) * (2 ** min(st.failures, 6)))
        st.next_run = self.clock() + delay
        self.store.record_failure(src, why, st.failures, st.next_run)
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
                if force or st.next_run <= now + DUE_SLACK_S:
                    st.running, st.started = True, now
                    fut = self._pool.submit(self._fetch, src, ctx)
                    fut.add_done_callback(lambda f, s=src: setattr(self.state[s], "running", False))
                    launched[src] = fut
        summary: dict[str, Any] = {"ran": [], "failed": {}, "new": [], "escalated": [], "pushed": 0,
                                   "skipped_not_due": sorted(set(self.state) - set(launched))}
        deadline = time.monotonic() + self.fetch_timeout_s
        for src, fut in launched.items():
            try:  # everything per source is isolated: no exception can abort the cycle or expire_due
                self._process(src, fut, deadline, summary, now)
            except Exception as e:
                log.exception("alert source %s: processing crashed", src)
                summary["failed"][src] = type(e).__name__
                try:
                    self._fail(src, f"processing {type(e).__name__}")
                except Exception:
                    log.exception("could not record failure for %s", src)
        try:
            self.store.expire_due()
        except Exception:
            log.exception("expire_due failed")
        return summary

    def _process(self, src: str, fut: Future, deadline: float, summary: dict[str, Any], started: float) -> None:
        try:
            alerts = fut.result(timeout=max(0.01, deadline - time.monotonic()))
        except TimeoutError:
            self._fail(src, f"timeout after {self.fetch_timeout_s:.0f}s")  # thread finishes on its own
            summary["failed"][src] = "timeout"
            return
        except Exception as e:
            self._fail(src, f"{type(e).__name__}: {str(e)[:200]}")
            summary["failed"][src] = type(e).__name__
            return
        st = self.state[src]
        changes = self.store.apply_fetch(src, alerts)
        # Schedule from the PASS START, not the fetch end, so fetch time never pushes the next run past
        # the next timer tick (with the 5-min timer, NWS used to slip a whole cycle).
        st.failures, st.next_run = 0, started + self.interval(src)
        self.store.set_next_due(src, st.next_run)
        summary["ran"].append(src)
        for ch in changes:
            if ch.kind in ("new", "escalated") and ch.alert["status"] == "active":
                summary[ch.kind].append(ch.alert["id"])
                # Claim first (atomic, DB-level): at most one process announces each (id, severity),
                # even during the redeploy overlap. Claimed even with push off, so a later
                # subscriber never receives a backlog.
                won = self.store.claim_push(ch.alert["id"], ch.alert["severity"])
                # Ops instrument (deploy's overlap test): every attempt logs its outcome with the pid.
                log.info("push claim %s id=%s sev=%s kind=%s pid=%d", "won" if won else "lost",
                         ch.alert["id"], ch.alert["severity"], ch.kind, os.getpid())
                if won and self.push is not None:
                    try:
                        summary["pushed"] += self.push.notify(ch.alert, ch.kind).get("sent", 0)
                    except Exception:
                        log.exception("push fan-out failed for %s", ch.alert["id"])

    def status(self) -> dict[str, Any]:
        now = self.clock()
        return {"adapters_loaded": len(self.adapters), "load_error": self.load_error,
                "sources": {src: {"interval_s": self.interval(src), "failures": st.failures, "running": st.running,
                                  "next_run_in_s": max(0, round(st.next_run - now))}
                            for src, st in self.state.items()}}

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def load_adapters(use_data_package: bool) -> tuple[list[Any], str | None]:
    """(adapters, load_error). Fails LOUD: a broken import is logged at ERROR and surfaced in
    /api/alerts/sources (adapters_loaded: 0, load_error), so a bad deploy is visible.
    CREEKWATCH_ALERT_ADAPTERS="module:attr" overrides the registry (tests/ops)."""
    import importlib
    import os

    spec = os.environ.get("CREEKWATCH_ALERT_ADAPTERS")
    if not use_data_package and not spec:
        return [], None
    mod_name, _, attr = (spec or "data.alerts:ADAPTERS").partition(":")
    try:
        adapters = list(getattr(importlib.import_module(mod_name), attr or "ADAPTERS"))
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:200]}"
        log.error("ALERT ADAPTERS FAILED TO LOAD from %s:%s (%s); no alert sources", mod_name, attr, err)
        return [], err
    if not adapters:
        log.error("alert adapter registry %s is empty", spec or "data.alerts:ADAPTERS")
        return [], "empty adapter registry"
    log.info("alert adapters: %s", [getattr(a, "source", "?") for a in adapters])
    return adapters, None


def main() -> int:
    """CLI for the systemd timer: `python -m creekwatch.alerts.poller --once`.
    --once  runs only the sources that are DUE per the persisted schedule (intervals + backoff).
    --force runs every source now (manual/debug).
    Exit 0 if anything ran OK or nothing was due; 2 if every source that ran failed; 3 if adapters failed to load."""
    import argparse
    import json as _json
    import sys

    from ..config import Settings
    from ..main import create_app

    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--once", action="store_true", help="run the sources that are due, then exit")
    g.add_argument("--force", action="store_true", help="run every source now, then exit")
    a = ap.parse_args()
    app = create_app(Settings())
    p: Poller = app.state.alert_poller
    if p.load_error or not p.adapters:
        print(_json.dumps({"error": "adapters not loaded", "load_error": p.load_error}), flush=True)
        return 3
    summary = p.run_due(force=a.force)
    print(_json.dumps(summary, indent=1), flush=True)
    if summary["failed"] and not summary["ran"]:
        return 2
    return 0


if __name__ == "__main__":
    import os as _os
    import sys as _sys

    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    code = main()
    _sys.stdout.flush(); _sys.stderr.flush()
    # os._exit: a hung adapter thread must not keep the timer's process alive (executor threads are
    # joined at normal interpreter exit). All DB writes are already committed at this point.
    _os._exit(code)
