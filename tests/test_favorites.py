"""Favorites are not the daemon's watchlist.

The `watchlist` table is what the daemon MONITORS -- seeded with the whole
S&P 500. Your favorites are what YOU care about, roughly ten names. Sharing one
table means `atrade watch NVDA` writes into a 500-row table and
`atrade watchlist` tries to price every constituent, which is exactly what
happened the first time it ran.

Same table, separate flag: the daemon keeps its coverage, you get your list.
"""
import pytest

from aethelark_trade.engine.favorites import (
    add_favorite,
    is_favorite,
    list_favorites,
    remove_favorite,
)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "fav.db"


def test_empty_by_default(db):
    assert list_favorites(db_path=db) == []


def test_adding_a_favorite_returns_true_once(db):
    assert add_favorite("NVDA", db_path=db) is True
    assert add_favorite("NVDA", db_path=db) is False


def test_favorites_come_back_in_the_order_added(db):
    for t in ("NVDA", "PLTR", "AMD"):
        add_favorite(t, db_path=db)
    assert list_favorites(db_path=db) == ["NVDA", "PLTR", "AMD"]


def test_tickers_are_normalised(db):
    add_favorite("  nvda ", db_path=db)
    assert list_favorites(db_path=db) == ["NVDA"]
    assert is_favorite("NvDa", db_path=db) is True


def test_removing_works_and_is_idempotent(db):
    add_favorite("NVDA", db_path=db)
    assert remove_favorite("NVDA", db_path=db) is True
    assert remove_favorite("NVDA", db_path=db) is False
    assert list_favorites(db_path=db) == []


def test_a_monitored_ticker_is_not_automatically_a_favorite(db):
    """The daemon's coverage must not become your list."""
    from aethelark_trade.engine.favorites import _connect

    conn = _connect(db)
    conn.execute("INSERT INTO watchlist (ticker) VALUES ('AAPL')")
    conn.commit()
    conn.close()

    assert is_favorite("AAPL", db_path=db) is False
    assert list_favorites(db_path=db) == []


def test_favoriting_a_monitored_ticker_keeps_the_single_row(db):
    """Flag it, don't duplicate it -- the daemon's row stays intact."""
    from aethelark_trade.engine.favorites import _connect

    conn = _connect(db)
    conn.execute("INSERT INTO watchlist (ticker, sector) VALUES ('AAPL','Tech')")
    conn.commit()
    conn.close()

    assert add_favorite("AAPL", db_path=db) is True
    assert list_favorites(db_path=db) == ["AAPL"]

    conn = _connect(db)
    rows = conn.execute("SELECT ticker, sector FROM watchlist WHERE ticker='AAPL'").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["sector"] == "Tech"      # daemon's metadata survived


def test_unfavoriting_does_not_stop_the_daemon_monitoring_it(db):
    """Dropping something from YOUR list must not delete it from coverage."""
    from aethelark_trade.engine.favorites import _connect

    add_favorite("AAPL", db_path=db)
    remove_favorite("AAPL", db_path=db)

    conn = _connect(db)
    still_there = conn.execute(
        "SELECT COUNT(*) AS n FROM watchlist WHERE ticker='AAPL'").fetchone()["n"]
    conn.close()
    assert still_there == 1
