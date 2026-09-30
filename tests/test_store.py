"""Scorecard cache backing `atrade leaderboard`."""
from datetime import date

import pytest

from aethelark_trade.engine.engine import assemble_result
from aethelark_trade.engine.liar_filter import check_liar_filter
from aethelark_trade.engine.store import (
    load_entries,
    load_scorecard,
    save_scorecard,
)
from aethelark_trade.engine.types import LayerScore

CLEAN = check_liar_filter(50.0, [], as_of=date(2026, 8, 19))
NAMES = ("layer_1_fundamentals", "layer_2_macro_gravity", "layer_3_news_velocity",
         "layer_4_sector_relativity", "layer_5_insider_conviction",
         "layer_6_geopolitics", "layer_7_supply_chain")


@pytest.fixture
def db(tmp_path):
    return tmp_path / "test_aethelark.db"


def result(ticker, quality=80, insider=70, fcf_yield=None):
    layers = {n: LayerScore(score=50, summary=n) for n in NAMES}
    layers["layer_1_fundamentals"] = LayerScore(
        score=quality, summary="fundamentals",
        detail={"fcf_yield_pct": fcf_yield} if fcf_yield is not None else {},
    )
    layers["layer_5_insider_conviction"] = LayerScore(score=insider, summary="insiders")
    return assemble_result(ticker, layers, CLEAN)


def test_saved_scorecard_round_trips(db):
    save_scorecard(result("NVDA"), db_path=db)
    loaded = load_scorecard("NVDA", db_path=db)
    assert loaded["ticker"] == "NVDA"
    assert loaded["composite_score"] == result("NVDA").composite_score


def test_loading_an_unknown_ticker_returns_none(db):
    assert load_scorecard("ZZZZ", db_path=db) is None


def test_rescoring_replaces_rather_than_duplicates(db):
    save_scorecard(result("NVDA", quality=80), db_path=db)
    save_scorecard(result("NVDA", quality=20), db_path=db)
    entries = load_entries(db_path=db)
    assert len(entries) == 1
    assert entries[0].quality == 20


def test_entries_expose_the_ranking_inputs(db):
    save_scorecard(result("NVDA", quality=85, insider=60, fcf_yield=3.2), db_path=db)
    entry = load_entries(db_path=db)[0]
    assert entry.ticker == "NVDA"
    assert entry.quality == 85
    assert entry.insider == 60
    assert entry.fcf_yield_pct == pytest.approx(3.2)


def test_unavailable_layers_do_not_poison_the_ranking_inputs(db):
    r = result("NVDA")
    r.layers["layer_5_insider_conviction"] = LayerScore.unavailable("no trades")
    save_scorecard(r, db_path=db)
    entry = load_entries(db_path=db)[0]
    # A name with no insider data must rank on its other merits, not inherit a
    # fabricated 50 that would outrank genuine insider selling.
    assert entry.insider is None


def test_entries_load_for_every_cached_ticker(db):
    for t in ("NVDA", "AAPL", "KO"):
        save_scorecard(result(t), db_path=db)
    assert {e.ticker for e in load_entries(db_path=db)} == {"NVDA", "AAPL", "KO"}


def test_empty_cache_loads_empty(db):
    assert load_entries(db_path=db) == []
