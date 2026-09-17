"""Slice 2 -- S&P 500 relative asymmetry ranking.

ROADMAP: rank by asymmetric mispricing = High Quality + Low Forward Multiple +
Insider Buying. Forward multiples need analyst estimates we do not license, so
cheapness is measured as free-cash-flow yield (FCF / market cap), which is
derivable from data already fetched for Layer 1.
"""
import pytest

from aethelark_trade.engine.leaderboard import (
    FCF_YIELD_NEUTRAL_PCT,
    RANK_WEIGHTS,
    LeaderboardEntry,
    rank_leaderboard,
    relative_asymmetry,
)


def entry(ticker, quality=50, insider=50, fcf_yield=None, composite=50):
    return LeaderboardEntry(ticker=ticker, composite=composite, quality=quality,
                            insider=insider, fcf_yield_pct=fcf_yield,
                            scored_at="2026-08-19T00:00:00+00:00")


def test_rank_weights_sum_to_one():
    assert sum(RANK_WEIGHTS.values()) == pytest.approx(1.0)


def test_quality_lifts_the_asymmetry():
    assert relative_asymmetry(entry("A", quality=90)) > relative_asymmetry(entry("B", quality=20))


def test_a_cheaper_name_outranks_an_expensive_twin():
    """Same quality and insiders; one yields 10% of its market cap in free cash."""
    cheap = entry("A", quality=70, insider=60, fcf_yield=10.0)
    rich = entry("B", quality=70, insider=60, fcf_yield=1.0)
    assert relative_asymmetry(cheap) > relative_asymmetry(rich)


def test_insider_buying_lifts_the_asymmetry():
    assert relative_asymmetry(entry("A", insider=95)) > relative_asymmetry(entry("B", insider=10))


def test_missing_valuation_renormalises_instead_of_scoring_zero():
    """A name we could not value must not be pushed to the bottom for it."""
    unpriced = entry("A", quality=80, insider=80, fcf_yield=None)
    assert relative_asymmetry(unpriced) > 60


def test_asymmetry_is_bounded():
    for e in (entry("A", quality=0, insider=0, fcf_yield=-50.0),
              entry("B", quality=100, insider=100, fcf_yield=100.0)):
        assert 0 <= relative_asymmetry(e) <= 100


def test_ranking_is_ordered_and_limited():
    entries = [entry(f"T{i}", quality=i * 10, insider=i * 10) for i in range(10)]
    ranked = rank_leaderboard(entries, limit=3)
    assert len(ranked) == 3
    assert [r.ticker for r in ranked] == ["T9", "T8", "T7"]
    assert [r.rank for r in ranked] == [1, 2, 3]
    assert ranked[0].asymmetry >= ranked[1].asymmetry >= ranked[2].asymmetry


def test_ranking_an_empty_universe_is_empty_not_an_error():
    assert rank_leaderboard([], limit=10) == []


def test_neutral_yield_anchor_is_documented():
    assert FCF_YIELD_NEUTRAL_PCT > 0


def test_sector_filtering_maps_healthcare_and_tech():
    from aethelark_trade.ticker_registry import TICKER_TO_SECTOR_ETF
    assert TICKER_TO_SECTOR_ETF.get("LLY") == "XLV"
    assert TICKER_TO_SECTOR_ETF.get("PFE") == "XLV"
    assert TICKER_TO_SECTOR_ETF.get("NVDA") == "XLK"
