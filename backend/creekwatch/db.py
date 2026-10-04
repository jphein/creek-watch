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
    flags         TEXT NOT NULL DEFAULT '[]'
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
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
