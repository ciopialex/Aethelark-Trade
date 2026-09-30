"""Local scorecard cache.

`atrade leaderboard` ranks the S&P 500 / Nasdaq-100, but a full 7-layer
evaluation costs several SEC and market round trips per name -- scanning a
500-name universe live would take hours and hammer EDGAR. Per ROADMAP Slice 2
the leaderboard ranks *cached* scores, which `atrade analyze` and
`atrade leaderboard --refresh` populate.
"""

import json
import sqlite3
from pathlib import Path

from aethelark_trade.engine.leaderboard import LeaderboardEntry
from aethelark_trade.engine.scoring import SCORING_MODEL_VERSION

DEFAULT_DB_PATH = Path.home() / ".aethelark" / "aethelark.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS aethelark_scorecards (
    ticker         TEXT PRIMARY KEY,
    scored_at      TEXT NOT NULL,
    composite      INTEGER NOT NULL,
    verdict        TEXT NOT NULL,
    quality        INTEGER,
    insider        INTEGER,
    fcf_yield_pct  REAL,
    model_version  TEXT NOT NULL DEFAULT 'unknown',
    payload_json   TEXT NOT NULL
);
"""

# Rows written before versioning existed carry no model identity, so they are
# treated as superseded -- which is correct: they predate the current math.
_MIGRATIONS = (
    "ALTER TABLE aethelark_scorecards "
    "ADD COLUMN model_version TEXT NOT NULL DEFAULT 'unknown'",
)


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    for statement in _MIGRATIONS:
        try:
            conn.execute(statement)
        except sqlite3.OperationalError:
            pass          # already applied
    conn.commit()
    return conn


def _age_seconds(scored_at: str) -> float | None:
    """Seconds since the scorecard was generated, or None if unreadable."""
    from datetime import datetime, timezone

    try:
        when = datetime.fromisoformat(scored_at)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).total_seconds()


def _layer_score(result, layer: str) -> int | None:
    """Score for a layer, or None when the layer had no data.

    Returning None rather than the neutral 50 matters: the leaderboard
    renormalizes around missing legs, so a name with no insider filings ranks
    on its other merits instead of inheriting a fabricated neutral that would
    outrank a name with genuine, measured insider selling.
    """
    entry = result.layers.get(layer)
    if entry is None or not entry.available:
        return None
    return entry.score


def save_scorecard(result, db_path: Path | None = None,
                   model_version: str | None = None) -> None:
    """Persist (or replace) one ticker's scorecard."""
    fundamentals = result.layers.get("layer_1_fundamentals")
    fcf_yield = None
    if fundamentals is not None and fundamentals.available:
        fcf_yield = fundamentals.detail.get("fcf_yield_pct")

    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO aethelark_scorecards "
            "(ticker, scored_at, composite, verdict, quality, insider, "
            " fcf_yield_pct, model_version, payload_json) VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(ticker) DO UPDATE SET "
            " scored_at=excluded.scored_at, composite=excluded.composite, "
            " verdict=excluded.verdict, quality=excluded.quality, "
            " insider=excluded.insider, fcf_yield_pct=excluded.fcf_yield_pct, "
            " model_version=excluded.model_version, "
            " payload_json=excluded.payload_json",
            (
                result.ticker,
                result.generated_at,
                result.composite_score,
                result.verdict,
                _layer_score(result, "layer_1_fundamentals"),
                _layer_score(result, "layer_5_insider_conviction"),
                fcf_yield,
                model_version or SCORING_MODEL_VERSION,
                json.dumps(result.to_dict(), default=str),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_scorecard(ticker: str, db_path: Path | None = None) -> dict | None:
    """The full cached payload for one ticker, enriched with staleness metrics."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT payload_json, model_version, scored_at FROM aethelark_scorecards "
            "WHERE ticker = ?",
            (ticker.upper(),),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    payload = json.loads(row["payload_json"])
    payload["model_version"] = row["model_version"]
    scored_at = row["scored_at"] if "scored_at" in row.keys() else payload.get("generated_at")
    age = _age_seconds(scored_at)
    payload["age_seconds"] = age
    payload["age_days"] = round(age / 86400.0, 1) if age is not None else None
    payload["is_stale"] = (age or 0) > 86400 * 7
    return payload


def load_entries(db_path: Path | None = None) -> list[LeaderboardEntry]:
    """Cached scorecards produced by the CURRENT scoring model.

    Scores from a superseded model are withheld rather than ranked, so a single
    ranking never combines output from two scoring models. stale_model_count()
    reports how many were withheld.
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT ticker, scored_at, composite, quality, insider, fcf_yield_pct "
            "FROM aethelark_scorecards WHERE model_version = ?",
            (SCORING_MODEL_VERSION,),
        ).fetchall()
    finally:
        conn.close()

    return [
        LeaderboardEntry(
            ticker=r["ticker"],
            composite=r["composite"],
            quality=r["quality"],
            insider=r["insider"],
            fcf_yield_pct=r["fcf_yield_pct"],
            scored_at=r["scored_at"],
            age_seconds=_age_seconds(r["scored_at"]),
        )
        for r in rows
    ]


def stale_model_count(db_path: Path | None = None) -> int:
    """How many cached scorecards predate the current scoring model."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM aethelark_scorecards "
            "WHERE model_version != ?",
            (SCORING_MODEL_VERSION,),
        ).fetchone()
    finally:
        conn.close()
    return int(row["n"]) if row else 0


def cached_tickers(db_path: Path | None = None) -> list[str]:
    conn = _connect(db_path)
    try:
        return [r["ticker"] for r in
                conn.execute("SELECT ticker FROM aethelark_scorecards").fetchall()]
    finally:
        conn.close()
