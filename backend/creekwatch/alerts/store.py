"""SQLite alert store: dedupe by id, detect NEW / ESCALATED, expire what a source stopped reporting."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .model import SEVERITY_RANK

log = logging.getLogger("creekwatch.alerts")

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id                    TEXT PRIMARY KEY,
    source                TEXT NOT NULL,
    payload               TEXT NOT NULL,
    status                TEXT NOT NULL,
    severity              TEXT NOT NULL,
    category              TEXT NOT NULL,
    first_seen            TEXT NOT NULL,
    updated               TEXT NOT NULL,
    expires               TEXT,
    last_pushed_severity  TEXT,
    inactive_since        TEXT
);
CREATE INDEX IF NOT EXISTS alerts_status ON alerts (status, updated DESC);
CREATE INDEX IF NOT EXISTS alerts_source ON alerts (source, status);
CREATE TABLE IF NOT EXISTS alert_creeks (
    alert_id TEXT NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    creek_id TEXT NOT NULL,
    PRIMARY KEY (alert_id, creek_id)
);
CREATE TABLE IF NOT EXISTS alert_sources (
    source      TEXT PRIMARY KEY,
    last_run    TEXT,
    last_ok     TEXT,
    last_error  TEXT,
    failures    INTEGER NOT NULL DEFAULT 0,
    alert_count INTEGER NOT NULL DEFAULT 0,
    next_due    REAL
);
"""


# An alert that comes back after being inactive this long is a NEW incident: its push claim is
# re-armed (same id + same severity notifies again). Shorter gaps are flapping and stay quiet.
REARM_AFTER_S = 12 * 3600


def _minus(now: str, seconds: float) -> str:
    """ISO-Z timestamp `seconds` before `now` (same format, so string comparison in SQL is ordered)."""
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return (datetime.strptime(now, fmt) - timedelta(seconds=seconds)).strftime(fmt)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Change:
    alert: dict[str, Any]
    kind: str  # "new" | "escalated" | "updated" | "unchanged"


class AlertStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)
            cols = {r[1] for r in c.execute("PRAGMA table_info(alert_sources)")}
            if "next_due" not in cols:  # DBs created before the persisted schedule
                c.execute("ALTER TABLE alert_sources ADD COLUMN next_due REAL")
            if "inactive_since" not in {r[1] for r in c.execute("PRAGMA table_info(alerts)")}:
                c.execute("ALTER TABLE alerts ADD COLUMN inactive_since TEXT")
                # backfill: rows already inactive start their re-arm clock at migration time
                c.execute("UPDATE alerts SET inactive_since=? WHERE status!='active' AND inactive_since IS NULL",
                          (now_iso(),))

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=5000")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    # -- writes ----------------------------------------------------------------------------------

    def apply_fetch(self, source: str, alerts: Iterable[dict[str, Any]], now: str | None = None) -> list[Change]:
        """Upsert one SUCCESSFUL fetch of `source` (already validated alerts). Alerts this source
        previously had active but no longer returns become 'expired'. One transaction."""
        now = now or now_iso()
        changes: list[Change] = []
        seen: set[str] = set()
        with self._conn() as c:
            for a in alerts:
                if a["source"] != source or a["id"] in seen:
                    continue
                seen.add(a["id"])
                if a["expires"] and a["expires"] <= now and a["status"] == "active":
                    a = dict(a, status="expired")
                row = c.execute("SELECT payload, status, severity, first_seen, last_pushed_severity, "
                                "inactive_since FROM alerts WHERE id = ?", (a["id"],)).fetchone()
                payload = json.dumps(a, sort_keys=True, separators=(",", ":"))
                if row is None:
                    kind = "new" if a["status"] == "active" else "unchanged"
                    c.execute("INSERT INTO alerts (id, source, payload, status, severity, category, first_seen,"
                              " updated, expires, inactive_since) VALUES (?,?,?,?,?,?,?,?,?,?)",
                              (a["id"], source, payload, a["status"], a["severity"], a["category"], now,
                               a["updated"], a["expires"], None if a["status"] == "active" else now))
                else:
                    if row["payload"] == payload:
                        kind = "unchanged"
                    elif a["status"] == "active" and row["status"] != "active":
                        kind = "new"  # re-activated (claim re-arm, if due, happens atomically below)
                    elif (a["status"] == "active"
                          and SEVERITY_RANK[a["severity"]] > SEVERITY_RANK.get(row["severity"], -1)):
                        kind = "escalated"
                    else:
                        kind = "updated"
                    if kind != "unchanged":
                        # Compare-and-set re-arm, in the SAME statement as the status flip. SQLite evaluates
                        # SET expressions against the pre-update row, so only the writer that actually
                        # flips inactive(>=REARM_AFTER_S) -> active clears the claim; a concurrent poller
                        # that read the same stale row sees status already 'active' and keeps the claim.
                        c.execute("UPDATE alerts SET payload=?, status=?, severity=?, category=?, updated=?, "
                                  "expires=?, "
                                  "last_pushed_severity=CASE WHEN ?='active' AND status!='active' "
                                  "AND inactive_since IS NOT NULL AND inactive_since<=? "
                                  "THEN NULL ELSE last_pushed_severity END, "
                                  "inactive_since=CASE WHEN ?='active' THEN NULL "
                                  "ELSE COALESCE(inactive_since, ?) END WHERE id=?",
                                  (payload, a["status"], a["severity"], a["category"], a["updated"], a["expires"],
                                   a["status"], _minus(now, REARM_AFTER_S), a["status"], now, a["id"]))
                c.execute("DELETE FROM alert_creeks WHERE alert_id = ?", (a["id"],))
                c.executemany("INSERT OR IGNORE INTO alert_creeks VALUES (?, ?)",
                              [(a["id"], cid) for cid in a["area"]["creek_ids"]])
                changes.append(Change(a, kind))
            # resolve: active alerts of this source that the successful fetch no longer returned
            gone = [r["id"] for r in c.execute("SELECT id FROM alerts WHERE source=? AND status='active'", (source,))
                    if r["id"] not in seen]
            if gone and not seen:  # N>0 -> 0: legitimate (all resolved) but worth a look in the logs
                log.warning("alert source %s returned 0 alerts after %d active; expiring them", source, len(gone))
            for aid in gone:
                p = json.loads(c.execute("SELECT payload FROM alerts WHERE id=?", (aid,)).fetchone()[0])
                p.update(status="expired", updated=now)
                c.execute("UPDATE alerts SET status='expired', updated=?, payload=?, inactive_since=? WHERE id=?",
                          (now, json.dumps(p, sort_keys=True, separators=(",", ":")), now, aid))
            c.execute("INSERT INTO alert_sources (source, last_run, last_ok, last_error, failures, alert_count) "
                      "VALUES (?,?,?,NULL,0,?) ON CONFLICT(source) DO UPDATE SET last_run=excluded.last_run, "
                      "last_ok=excluded.last_ok, last_error=NULL, failures=0, alert_count=excluded.alert_count",
                      (source, now, now, len(seen)))
        return changes

    def record_failure(self, source: str, error: str, failures: int, next_due: float | None = None) -> None:
        now = now_iso()
        with self._conn() as c:
            c.execute("INSERT INTO alert_sources (source, last_run, last_error, failures, next_due) VALUES (?,?,?,?,?) "
                      "ON CONFLICT(source) DO UPDATE SET last_run=excluded.last_run, "
                      "last_error=excluded.last_error, failures=excluded.failures, next_due=excluded.next_due",
                      (source, now, error[:300], failures, next_due))

    def set_next_due(self, source: str, next_due: float) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO alert_sources (source, next_due) VALUES (?, ?) "
                      "ON CONFLICT(source) DO UPDATE SET next_due=excluded.next_due", (source, next_due))

    def schedule(self) -> dict[str, tuple[float | None, int]]:
        """Persisted {source: (next_due epoch s, consecutive failures)}: survives process restarts, so
        separate `--once` passes honour intervals and backoff."""
        with self._conn() as c:
            return {r["source"]: (r["next_due"], r["failures"]) for r in
                    c.execute("SELECT source, next_due, failures FROM alert_sources")}

    def expire_due(self, now: str | None = None) -> int:
        """Time-based expiry for every source (runs each poll cycle, even if a source is down)."""
        now = now or now_iso()
        with self._conn() as c:
            rows = c.execute("SELECT id, payload FROM alerts WHERE status='active' AND expires IS NOT NULL "
                             "AND expires <= ?", (now,)).fetchall()
            for r in rows:
                p = json.loads(r["payload"]); p.update(status="expired")
                c.execute("UPDATE alerts SET status='expired', payload=?, inactive_since=? WHERE id=?",
                          (json.dumps(p, sort_keys=True, separators=(",", ":")), now, r["id"]))
        return len(rows)

    def claim_push(self, alert_id: str, severity: str) -> bool:
        """Atomically claim the right to announce (alert_id, severity). Exactly one caller wins, even
        across processes sharing the DB (e.g. the redeploy staging container overlapping the live
        one): the UPDATE only matches if nothing at this severity or higher was announced yet."""
        rank = SEVERITY_RANK[severity]
        with self._conn() as c:
            cur = c.execute(
                "UPDATE alerts SET last_pushed_severity=? WHERE id=? AND (last_pushed_severity IS NULL OR "
                "CASE last_pushed_severity WHEN 'info' THEN 0 WHEN 'advisory' THEN 1 WHEN 'watch' THEN 2 "
                "WHEN 'alert' THEN 3 ELSE -1 END < ?)", (severity, alert_id, rank))
            return cur.rowcount == 1

    def mark_pushed(self, alert_id: str, severity: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE alerts SET last_pushed_severity=? WHERE id=?", (severity, alert_id))

    def needs_push(self, alert_id: str, severity: str) -> bool:
        """True if never pushed, or this severity is higher than what was last pushed."""
        with self._conn() as c:
            r = c.execute("SELECT last_pushed_severity FROM alerts WHERE id=?", (alert_id,)).fetchone()
        last = r["last_pushed_severity"] if r else None
        return last is None or SEVERITY_RANK[severity] > SEVERITY_RANK.get(last, -1)

    # -- reads -----------------------------------------------------------------------------------

    def query(self, creek_id: str | None = None, severity: str | None = None, category: str | None = None,
              status: str | None = "active", source: str | None = None, limit: int = 200) -> list[dict]:
        q, args = "SELECT a.payload FROM alerts a", []
        where = []
        if creek_id:
            q += " JOIN alert_creeks ac ON ac.alert_id = a.id"
            where.append("ac.creek_id = ?"); args.append(creek_id)
        if severity:  # minimum severity
            allowed = [s for s, r in SEVERITY_RANK.items() if r >= SEVERITY_RANK[severity]]
            where.append(f"a.severity IN ({','.join('?' * len(allowed))})"); args += allowed
        if category:
            where.append("a.category = ?"); args.append(category)
        if status:
            where.append("a.status = ?"); args.append(status)
        if source:
            where.append("a.source = ?"); args.append(source)
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY a.updated DESC, a.id LIMIT ?"; args.append(limit)
        with self._conn() as c:
            rows = [json.loads(r[0]) for r in c.execute(q, args)]
        return sorted(rows, key=lambda a: (SEVERITY_RANK[a["severity"]], a["updated"]), reverse=True)

    def get(self, alert_id: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT payload, first_seen FROM alerts WHERE id=?", (alert_id,)).fetchone()
        return (json.loads(r["payload"]) | {"first_seen": r["first_seen"]}) if r else None

    def first_seen(self, ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        with self._conn() as c:
            return {r[0]: r[1] for r in c.execute(
                f"SELECT id, first_seen FROM alerts WHERE id IN ({','.join('?' * len(ids))})", ids)}

    def sources(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM alert_sources ORDER BY source")]
