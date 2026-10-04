"""SQLite storage. One short-lived connection per call; WAL so reads don't block the writer."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    creek_id      TEXT NOT NULL,
    site_id       TEXT,
    lat           REAL NOT NULL,
    lon           REAL NOT NULL,
    observed_at   TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    water_color   TEXT NOT NULL,
    algae         TEXT NOT NULL,
    trash         TEXT NOT NULL,
    flow          TEXT NOT NULL,
    odor          TEXT NOT NULL,
    dead_fish     INTEGER NOT NULL DEFAULT 0,
    wildlife_seen TEXT,
    notes         TEXT,
    reporter_name TEXT,
    photo_file    TEXT,
    flags         TEXT NOT NULL DEFAULT '[]',
    trash_removed INTEGER NOT NULL DEFAULT 0,
    trash_bags    INTEGER,
    location_kind TEXT
);
CREATE INDEX IF NOT EXISTS reports_creek_obs ON reports (creek_id, observed_at DESC);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    from .alerts.store import _add_column  # concurrency-safe ALTER ("duplicate column" = done)

    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        # reports created before the cleanup fields (CREATE IF NOT EXISTS doesn't add columns)
        _add_column(conn, "reports", "trash_removed", "INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "reports", "trash_bags", "INTEGER")
        _add_column(conn, "reports", "location_kind", "TEXT")   # NULL = named site or auto-picked
        conn.execute("CREATE INDEX IF NOT EXISTS reports_cleanups ON reports (creek_id) WHERE trash_removed = 1")
