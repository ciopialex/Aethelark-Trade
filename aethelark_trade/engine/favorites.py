"""Your list, kept separate from the daemon's coverage.

`watchlist` is what the daemon MONITORS and it is seeded with the whole
S&P 500. Your favorites are the handful of names you actually follow. Same
table, one extra flag -- so the daemon keeps its coverage and unfavoriting
something never removes it from monitoring.
"""

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".aethelark" / "aethelark.db"

# favorited_at uses millisecond resolution: datetime('now') is second-accurate,
# so adding three tickers in one breath ordered them alphabetically instead of
# by when you added them.
# Minimal shape; db.py owns the full schema. Created here only so a fresh
# database (or a test one) works without booting the daemon.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    ticker TEXT PRIMARY KEY,
    name TEXT,
    sector TEXT,
    industry TEXT,
    circuit_role TEXT,
    added_at TEXT DEFAULT (datetime('now')),
    last_scanned TEXT
);
"""

_MIGRATIONS = (
    "ALTER TABLE watchlist ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE watchlist ADD COLUMN favorited_at TEXT",
    # Ordering column. Timestamps are not enough: SQLite's strftime resolves to
    # milliseconds and returns the same value for statements issued inside one,
    # so adding three tickers in a breath ordered them alphabetically instead of
    # by when you added them. A counter cannot tie.
    "ALTER TABLE watchlist ADD COLUMN favorite_seq INTEGER",
)


def _connect(db_path=None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    for statement in _MIGRATIONS:
        try:
            conn.execute(statement)
        except sqlite3.OperationalError:
            pass                      # already applied
    conn.commit()
    return conn


def _norm(ticker: str) -> str:
    return ticker.strip().upper()


def add_favorite(ticker: str, db_path=None) -> bool:
    """Flag a ticker as yours. True if newly added."""
    ticker = _norm(ticker)
    conn = _connect(db_path)
    try:
        already = conn.execute(
            "SELECT is_favorite FROM watchlist WHERE ticker = ?", (ticker,)
        ).fetchone()
        if already is not None and already["is_favorite"]:
            return False

        # Upsert the flag without disturbing the daemon's metadata on that row.
        seq = conn.execute(
            "SELECT COALESCE(MAX(favorite_seq), 0) + 1 AS n FROM watchlist"
        ).fetchone()["n"]
        conn.execute(
            "INSERT INTO watchlist (ticker, is_favorite, favorited_at, favorite_seq) "
            "VALUES (?, 1, strftime('%Y-%m-%d %H:%M:%f','now'), ?) "
            "ON CONFLICT(ticker) DO UPDATE SET "
            " is_favorite = 1, "
            " favorited_at = strftime('%Y-%m-%d %H:%M:%f','now'), "
            " favorite_seq = excluded.favorite_seq",
            (ticker, seq),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def remove_favorite(ticker: str, db_path=None) -> bool:
    """Clear the flag. The row stays so the daemon keeps monitoring it."""
    ticker = _norm(ticker)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT is_favorite FROM watchlist WHERE ticker = ?", (ticker,)
        ).fetchone()
        if row is None or not row["is_favorite"]:
            return False
        conn.execute(
            "UPDATE watchlist SET is_favorite = 0, favorited_at = NULL, "
            "favorite_seq = NULL WHERE ticker = ?", (ticker,)
        )
        conn.commit()
        return True
    finally:
        conn.close()


def is_favorite(ticker: str, db_path=None) -> bool:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT is_favorite FROM watchlist WHERE ticker = ?", (_norm(ticker),)
        ).fetchone()
        return bool(row and row["is_favorite"])
    finally:
        conn.close()


def list_favorites(db_path=None) -> list[str]:
    """Your tickers, oldest favorite first."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT ticker FROM watchlist WHERE is_favorite = 1 "
            "ORDER BY favorite_seq, ticker"
        ).fetchall()
        return [r["ticker"] for r in rows]
    finally:
        conn.close()
