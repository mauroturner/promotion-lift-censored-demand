"""A warehouse as small as the validation rules need it (U05): the two tables they read, with the names of the plan (section 5). U06 builds the
real one with ``warehouse.apply_schema``; the rules read only these columns of it."""

from __future__ import annotations

import sqlite3

import pandas as pd


def empty_store() -> sqlite3.Connection:
    """An in-memory SQLite with ``deliveries`` and ``series_days``, no row."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE deliveries (delivery_id TEXT PRIMARY KEY, status TEXT NOT NULL)")
    conn.execute("CREATE TABLE series_days (series_key INTEGER NOT NULL, date_key INTEGER NOT NULL, delivery_id TEXT NOT NULL, "
                 "PRIMARY KEY (series_key, date_key))")
    return conn


def load(conn: sqlite3.Connection, delivery_id: str, days: pd.DataFrame) -> None:
    """Mark `delivery_id` loaded and add its series-days."""
    conn.execute("INSERT OR REPLACE INTO deliveries VALUES (?, 'loaded')", (delivery_id,))
    conn.executemany("INSERT INTO series_days VALUES (?, ?, ?)", [(int(s), int(d), delivery_id) for s, d in zip(days["series_key"], days["date_key"])])
    conn.commit()
