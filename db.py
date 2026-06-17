"""
SQLite store for Amsterdam housing listings.
Tracks every listing ever seen so we can detect new ones on each run.
"""
import sqlite3
from datetime import date
from pathlib import Path

DB_PATH = Path(__file__).parent / "listings.db"

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS listings (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    url         TEXT,
    rent_eur    INTEGER,
    size_m2     INTEGER,
    neighbourhood TEXT,
    available_from TEXT,
    source      TEXT,
    date_found  TEXT
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(CREATE_TABLE)
    conn.commit()
    return conn


def find_new(listings: list[dict]) -> list[dict]:
    """Return listings whose id is not already in the DB."""
    if not listings:
        return []
    conn = _connect()
    ids = [l["id"] for l in listings]
    placeholders = ",".join("?" * len(ids))
    existing = {
        row[0]
        for row in conn.execute(
            f"SELECT id FROM listings WHERE id IN ({placeholders})", ids
        )
    }
    conn.close()
    return [l for l in listings if l["id"] not in existing]


def save(listings: list[dict]) -> None:
    """Insert listings (ignore duplicates)."""
    if not listings:
        return
    today = date.today().isoformat()
    conn = _connect()
    conn.executemany(
        """
        INSERT OR IGNORE INTO listings
            (id, title, url, rent_eur, size_m2, neighbourhood, available_from, source, date_found)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                l.get("id", l["url"]),
                l.get("title"),
                l.get("url"),
                l.get("rent_eur"),
                l.get("size_m2"),
                l.get("neighbourhood"),
                l.get("available_from"),
                l.get("source"),
                today,
            )
            for l in listings
        ],
    )
    conn.commit()
    conn.close()


def count() -> int:
    conn = _connect()
    n = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    conn.close()
    return n
