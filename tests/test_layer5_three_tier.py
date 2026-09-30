"""Layer 5 -- three-tier normalization curve.

Buying and selling are asymmetric in information content. An insider BUYING is
rare, voluntary and paid for out of pocket. An insider SELLING is the normal
end of an equity compensation cycle -- especially on a Rule 10b5-1 plan adopted
months earlier. Scoring both on one symmetric curve made every mega-cap read
maximally bearish for doing something entirely routine.

Bands (per spec):
  * Genuine open-market purchases (code P)        -> 80-100  BULLISH
  * Routine / planned selling at historical pace  -> 45-55   NEUTRAL
  * Abnormal discretionary dumping                -> 0-20    BEARISH
"""
from datetime import date

import pytest

from aethelark_trade.engine.layers.insider import (
    ABNORMAL_SELL_CONVICTION,
    BEARISH_BAND,
    BULLISH_BAND,
    NEUTRAL_BAND,
    score_insider_conviction,
)
from aethelark_trade.parser import InsiderTransaction

AS_OF = date(2026, 8, 19)


def tx(*, code, shares, price, owned_after, title="Chief Executive Officer",
       planned=False, when=date(2026, 8, 10)):
    t = InsiderTransaction(
        filing_date=when, accession_number="0000000000-00-000000",
        issuer_name="X", issuer_ticker="X", issuer_cik="1",
        insider_name="Jane Doe", insider_cik="2", insider_title=title,
        is_director=False, is_officer=True, is_ten_percent_owner=False,
        is_other=False, transaction_date=when, transaction_code=code,
        shares=shares, price_per_share=price, shares_owned_after=owned_after,
    )
    object.__setattr__(t, "is_10b5_1", planned)
    return t


# ------------------------------------------------------------- band bounds
def test_bands_are_the_documented_ranges():
    assert BULLISH_BAND == (80, 100)
    assert NEUTRAL_BAND == (45, 55)
    assert BEARISH_BAND == (0, 20)


def test_bands_do_not_overlap():
    assert BEARISH_BAND[1] < NEUTRAL_BAND[0]
    assert NEUTRAL_BAND[1] < BULLISH_BAND[0]


# ------------------------------------------------- TIER 1: genuine buying
def test_an_open_market_purchase_scores_bullish():
    txs = [tx(code="P", shares=50_000, price=100.0, owned_after=200_000)]
    score = score_insider_conviction(txs, as_of=AS_OF).score
    assert BULLISH_BAND[0] <= score <= BULLISH_BAND[1]


def test_a_tiny_purchase_stays_routine_below_floor():
    """A purchase below the materiality floor cannot move into the bullish band."""
    txs = [tx(code="P", shares=100, price=100.0, owned_after=1_000_000)]
    score = score_insider_conviction(txs, as_of=AS_OF).score
    assert NEUTRAL_BAND[0] <= score <= NEUTRAL_BAND[1]


def test_a_bigger_purchase_scores_higher_within_the_band():
    small = [tx(code="P", shares=15_000, price=100.0, owned_after=500_000)]
    large = [tx(code="P", shares=200_000, price=100.0, owned_after=500_000)]
    assert score_insider_conviction(large, as_of=AS_OF).score > \
           score_insider_conviction(small, as_of=AS_OF).score


def test_buying_outweighs_concurrent_routine_selling():
    txs = [
        tx(code="P", shares=50_000, price=100.0, owned_after=200_000),
        tx(code="S", shares=10_000, price=100.0, owned_after=190_000, planned=True),
    ]
    assert score_insider_conviction(txs, as_of=AS_OF).score >= BULLISH_BAND[0]


# --------------------------------------------- TIER 2: routine liquidation
def test_routine_planned_selling_is_neutral_not_bearish():
    """The mega-cap case that used to flatline at 0: a large 10b5-1 sale."""
    txs = [tx(code="S", shares=100_000, price=200.0, owned_after=900_000, planned=True)]
    score = score_insider_conviction(txs, as_of=AS_OF).score
    assert NEUTRAL_BAND[0] <= score <= NEUTRAL_BAND[1]


def test_even_a_very_large_planned_sale_stays_neutral():
    """Plan size is set months ahead; it is not a same-day opinion."""
    txs = [tx(code="S", shares=400_000, price=200.0, owned_after=600_000, planned=True)]
    score = score_insider_conviction(txs, as_of=AS_OF).score
    assert NEUTRAL_BAND[0] <= score <= NEUTRAL_BAND[1]


def test_several_routine_plan_sales_stay_neutral():
    txs = [tx(code="S", shares=30_000, price=200.0, owned_after=500_000,
              planned=True, when=date(2026, 8, d)) for d in (5, 8, 12, 15)]
    score = score_insider_conviction(txs, as_of=AS_OF).score
    assert NEUTRAL_BAND[0] <= score <= NEUTRAL_BAND[1]


def test_modest_discretionary_selling_is_neutral():
    """Trimming below the abnormality threshold is housekeeping, not a signal."""
    txs = [tx(code="S", shares=5_000, price=100.0, owned_after=995_000)]
    score = score_insider_conviction(txs, as_of=AS_OF).score
    assert NEUTRAL_BAND[0] <= score <= NEUTRAL_BAND[1]


# ------------------------------------------- TIER 3: abnormal dumping only
def test_abnormal_discretionary_dumping_is_bearish():
    """Selling most of a position, off-plan, in one window."""
    txs = [tx(code="S", shares=800_000, price=100.0, owned_after=200_000)]
    score = score_insider_conviction(txs, as_of=AS_OF).score
    assert BEARISH_BAND[0] <= score <= BEARISH_BAND[1]


def test_a_bigger_dump_scores_lower_within_the_band():
    big = [tx(code="S", shares=800_000, price=100.0, owned_after=200_000)]
    total = [tx(code="S", shares=990_000, price=100.0, owned_after=10_000)]
    assert score_insider_conviction(total, as_of=AS_OF).score <= \
           score_insider_conviction(big, as_of=AS_OF).score


def test_the_same_size_dump_on_a_plan_is_not_bearish():
    """This is the whole point of the tier split: identical dollar size and
    identical position fraction, separated only by whether the insider chose
    the moment."""
    size = dict(code="S", shares=800_000, price=100.0, owned_after=200_000)
    discretionary = score_insider_conviction([tx(**size)], as_of=AS_OF).score
    planned = score_insider_conviction([tx(**size, planned=True)], as_of=AS_OF).score
    assert discretionary <= BEARISH_BAND[1]
    assert planned >= NEUTRAL_BAND[0]


def test_abnormality_threshold_is_documented():
    assert ABNORMAL_SELL_CONVICTION > 0


# ---------------------------------------------------------------- general
def test_no_activity_remains_unavailable():
    assert score_insider_conviction([], as_of=AS_OF).available is False


def test_detail_reports_the_tier_and_its_components():
    txs = [tx(code="S", shares=100_000, price=200.0, owned_after=900_000, planned=True)]
    detail = score_insider_conviction(txs, as_of=AS_OF).detail
    assert detail["tier"] == "ROUTINE"
    assert detail["planned_trade_count"] == 1
    assert "buy_conviction" in detail
    assert "discretionary_sell_conviction" in detail


def test_tier_labels_cover_all_three_bands():
    buy = [tx(code="P", shares=50_000, price=100.0, owned_after=200_000)]
    dump = [tx(code="S", shares=900_000, price=100.0, owned_after=100_000)]
    plan = [tx(code="S", shares=50_000, price=100.0, owned_after=950_000, planned=True)]
    assert score_insider_conviction(buy, as_of=AS_OF).detail["tier"] == "ACCUMULATION"
    assert score_insider_conviction(dump, as_of=AS_OF).detail["tier"] == "ABNORMAL_DISTRIBUTION"
    assert score_insider_conviction(plan, as_of=AS_OF).detail["tier"] == "ROUTINE"


def test_every_score_stays_inside_a_band():
    cases = [
        [tx(code="P", shares=10, price=1.0, owned_after=10**9)],
        [tx(code="S", shares=10**7, price=1000.0, owned_after=1)],
        [tx(code="S", shares=1, price=1.0, owned_after=10**9, planned=True)],
    ]
    for txs in cases:
        s = score_insider_conviction(txs, as_of=AS_OF).score
        in_band = (BEARISH_BAND[0] <= s <= BEARISH_BAND[1]
                   or NEUTRAL_BAND[0] <= s <= NEUTRAL_BAND[1]
                   or BULLISH_BAND[0] <= s <= BULLISH_BAND[1])
        assert in_band, f"score {s} fell between bands"
