"""Liar Filter: divergence between public euphoria and C-suite behaviour.

Spec: docs/UI_STATES.md State C -- news sentiment >= 80% bullish while
C-suite net Form 4 selling >= $10,000,000 inside a 7-day window.

Zero mocks: these build real aethelark_trade.parser.InsiderTransaction objects.
"""
from datetime import date

import pytest

from aethelark_trade.engine.liar_filter import (
    CSUITE_SELL_THRESHOLD_USD,
    EUPHORIA_THRESHOLD_PCT,
    LOOKBACK_DAYS,
    check_liar_filter,
)
from aethelark_trade.parser import InsiderTransaction


def tx(*, title, code, shares, price, tx_date, officer=True, director=False,
       owned_after=None):
    """Build a real InsiderTransaction (not a mock).

    owned_after defaults to 10x the trade size so the insider is moving ~10%
    of their stake -- a realistic trade, not a full liquidation. Layer 5 scores
    the fraction of a position moved, so leaving this at zero would make every
    fixture look like a total exit.
    """
    if owned_after is None:
        owned_after = shares * 10
    return InsiderTransaction(
        filing_date=tx_date,
        accession_number="0000000000-00-000000",
        issuer_name="Example Corp",
        issuer_ticker="EXMP",
        issuer_cik="0000000001",
        insider_name="Jane Doe",
        insider_cik="0000000002",
        insider_title=title,
        is_director=director,
        is_officer=officer,
        is_ten_percent_owner=False,
        is_other=False,
        transaction_date=tx_date,
        transaction_code=code,
        shares=shares,
        price_per_share=price,
        shares_owned_after=owned_after,
    )


AS_OF = date(2026, 8, 19)


def test_thresholds_match_the_ui_spec():
    assert EUPHORIA_THRESHOLD_PCT == 80.0
    assert CSUITE_SELL_THRESHOLD_USD == 10_000_000.0
    assert LOOKBACK_DAYS == 7


def test_euphoria_plus_heavy_csuite_selling_is_a_divergence():
    txs = [tx(title="Chief Executive Officer", code="S", shares=200_000,
              price=90.0, tx_date=date(2026, 8, 15))]  # $18.0M sold
    result = check_liar_filter(news_sentiment_pct=92.0, transactions=txs, as_of=AS_OF)
    assert result.status == "DIVERGENCE"
    assert result.csuite_net_usd == pytest.approx(-18_000_000.0)


def test_euphoria_without_heavy_selling_is_clean():
    txs = [tx(title="Chief Executive Officer", code="S", shares=1_000,
              price=90.0, tx_date=date(2026, 8, 15))]  # $90k, far under threshold
    result = check_liar_filter(news_sentiment_pct=92.0, transactions=txs, as_of=AS_OF)
    assert result.status == "CLEAN"


def test_heavy_selling_without_euphoria_is_clean():
    """Insiders selling into bad news is congruent, not a lie."""
    txs = [tx(title="Chief Executive Officer", code="S", shares=200_000,
              price=90.0, tx_date=date(2026, 8, 15))]
    result = check_liar_filter(news_sentiment_pct=35.0, transactions=txs, as_of=AS_OF)
    assert result.status == "CLEAN"


def test_selling_outside_the_seven_day_window_is_ignored():
    txs = [tx(title="Chief Executive Officer", code="S", shares=200_000,
              price=90.0, tx_date=date(2026, 8, 1))]  # 18 days stale
    result = check_liar_filter(news_sentiment_pct=92.0, transactions=txs, as_of=AS_OF)
    assert result.status == "CLEAN"
    assert result.csuite_net_usd == 0.0


def test_director_selling_does_not_count_as_csuite():
    txs = [tx(title="Director", code="S", shares=200_000, price=90.0,
              tx_date=date(2026, 8, 15), officer=False, director=True)]
    result = check_liar_filter(news_sentiment_pct=92.0, transactions=txs, as_of=AS_OF)
    assert result.status == "CLEAN"


def test_csuite_buys_net_against_sells():
    """A CFO buying back offsets the CEO's sale -- net is what matters."""
    txs = [
        tx(title="Chief Executive Officer", code="S", shares=200_000, price=90.0,
           tx_date=date(2026, 8, 15)),                      # -$18.0M
        tx(title="Chief Financial Officer", code="P", shares=150_000, price=90.0,
           tx_date=date(2026, 8, 16)),                      # +$13.5M
    ]
    result = check_liar_filter(news_sentiment_pct=92.0, transactions=txs, as_of=AS_OF)
    assert result.csuite_net_usd == pytest.approx(-4_500_000.0)
    assert result.status == "CLEAN"


def test_option_exercises_are_not_open_market_sales():
    """Code M (option exercise) is compensation plumbing, not conviction."""
    txs = [tx(title="Chief Executive Officer", code="M", shares=500_000,
              price=90.0, tx_date=date(2026, 8, 15))]
    result = check_liar_filter(news_sentiment_pct=92.0, transactions=txs, as_of=AS_OF)
    assert result.status == "CLEAN"
    assert result.csuite_net_usd == 0.0
