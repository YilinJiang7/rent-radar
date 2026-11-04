"""SQLite schema and connection helper.

One file database (data/rentradar.sqlite). `build.py` recreates it from raw
files; the API and the agent only read from it.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    address TEXT, address_line1 TEXT, unit TEXT, city TEXT, zip TEXT,
    area_zip TEXT, area TEXT, zip_corrected INTEGER DEFAULT 0,
    lat REAL, lon REAL,
    price INTEGER, bedrooms REAL, bathrooms REAL, sqft INTEGER,
    property_type TEXT, listed_date TEXT, last_seen TEXT, days_on_market INTEGER,
    stale INTEGER DEFAULT 0,
    agent_name TEXT, office_name TEXT, mls_name TEXT,
    street_key TEXT, num_lo INTEGER, num_hi INTEGER,
    source_file TEXT
);

CREATE TABLE IF NOT EXISTS city_records (
    record_id TEXT PRIMARY KEY,
    date TEXT, year INTEGER,
    violation_type TEXT, description TEXT,
    signal TEXT, signal_source TEXT, building_level INTEGER,
    address TEXT, street_key TEXT, num_lo INTEGER, num_hi INTEGER,
    zip TEXT, parcel TEXT, owner TEXT, lat REAL, lon REAL
);
CREATE INDEX IF NOT EXISTS idx_records_street ON city_records(street_key);
CREATE INDEX IF NOT EXISTS idx_records_owner ON city_records(owner);

CREATE TABLE IF NOT EXISTS parcels (
    pid TEXT, street_key TEXT, num_lo INTEGER, num_hi INTEGER, unit TEXT, zip TEXT,
    owner TEXT, owner_occupied INTEGER, mail_city TEXT, mail_state TEXT,
    land_use TEXT, year_built INTEGER, units INTEGER
);
CREATE INDEX IF NOT EXISTS idx_parcels_street ON parcels(street_key);
CREATE INDEX IF NOT EXISTS idx_parcels_owner ON parcels(owner);

CREATE TABLE IF NOT EXISTS crashes (
    crash_id TEXT PRIMARY KEY, date TEXT, year INTEGER, lat REAL, lon REAL,
    severity TEXT, fatal INTEGER, injuries INTEGER, injury INTEGER,
    ped INTEGER, bike INTEGER, dark INTEGER, aadt INTEGER, street TEXT
);

CREATE TABLE IF NOT EXISTS stations (
    stop_id TEXT PRIMARY KEY, name TEXT, lat REAL, lon REAL,
    kind TEXT, lines TEXT
);

CREATE TABLE IF NOT EXISTS listing_records (
    listing_id TEXT, record_id TEXT, match_type TEXT,
    PRIMARY KEY (listing_id, record_id)
);

CREATE TABLE IF NOT EXISTS features (
    listing_id TEXT PRIMARY KEY,
    json TEXT
);
"""


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    p = Path(path or config.DB_PATH)
    conn = sqlite3.connect(str(p), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def reset(path: Path) -> sqlite3.Connection:
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    init(conn)
    return conn


def set_meta(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, json.dumps(value))
    )


def get_meta(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def insert_many(conn: sqlite3.Connection, table: str, rows: Iterable[dict]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    cols = list(rows[0].keys())
    sql = f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
    conn.executemany(sql, [tuple(r.get(c) for c in cols) for r in rows])
    return len(rows)
