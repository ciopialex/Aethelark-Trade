"""Layer 5 must measure conviction, not company size.

Scoring raw dollars makes every mega-cap look maximally bearish: routine
selling at a $4T company dwarfs a bet-the-house purchase at a small cap.
Conviction is what fraction of their OWN position an insider moved.
"""
from datetime import date

from aethelark_trade.engine.layers.insider import score_insider_conviction
from aethelark_trade.parser import InsiderTransaction

AS_OF = date(2026, 8, 19)


def tx(*, code, shares, price, owned_after, title="Chief Executive Officer"):
    return InsiderTransaction(
        filing_date=date(2026, 8, 10), accession_number="0000000000-00-000000",
        issuer_name="X", issuer_ticker="X", issuer_cik="1",
        insider_name="Jane Doe", insider_cik="2", insider_title=title,
        is_director=False, is_officer=True, is_ten_percent_owner=False,
        is_other=False, transaction_date=date(2026, 8, 10),
        transaction_code=code, shares=shares, price_per_share=price,
        shares_owned_after=owned_after,
    )


def test_trimming_a_sliver_of_a_huge_position_is_not_maximally_bearish():
    """$400M sold, but the insider still holds 99% of their stake. That is
    diversification, not a loss of faith -- it must not pin the layer to zero."""
    txs = [tx(code="S", shares=2_000_000, price=200.0, owned_after=198_000_000)]
    assert score_insider_conviction(txs, as_of=AS_OF).score > 20


def test_dumping_most_of_a_position_is_maximally_bearish():
    """Same insider, same company, sells 80% of what they hold."""
    txs = [tx(code="S", shares=2_000_000, price=200.0, owned_after=500_000)]
    assert score_insider_conviction(txs, as_of=AS_OF).score < 20


def test_identical_conviction_scores_the_same_above_the_materiality_floor():
    """Both insiders sell 20% of their position. Dollar sizes differ 100x, but
    both clear MATERIALITY_FLOOR_USD, so the score depends on conviction only."""
    mega = [tx(code="S", shares=1_000_000, price=200.0, owned_after=4_000_000)]
    mid = [tx(code="S", shares=10_000, price=200.0, owned_after=40_000)]
    assert score_insider_conviction(mega, as_of=AS_OF).score == \
           score_insider_conviction(mid, as_of=AS_OF).score


def test_the_materiality_floor_is_calibrated_for_large_caps():
    """Known limitation, recorded deliberately.

    MATERIALITY_FLOOR_USD is an absolute dollar amount, so it reintroduces a
    company-size dependency below the floor: a $200k sale is noise for a
    mega-cap executive but could be a controlling holder's whole stake at a
    micro-cap. The scored universe is the S&P 500 / Nasdaq-100, where $1M is a
    reasonable noise gate. Applying this layer to small caps needs a floor
    scaled to market cap instead.
    """
    from aethelark_trade.engine.layers.insider import MATERIALITY_FLOOR_USD

    below = [tx(code="S", shares=1_000, price=200.0, owned_after=4_000)]  # $200k
    above = [tx(code="S", shares=1_000_000, price=200.0, owned_after=4_000_000)]
    assert below[0].total_value < MATERIALITY_FLOOR_USD
    assert above[0].total_value > MATERIALITY_FLOOR_USD
    # Same 20% fraction, different treatment -- by design, and only below the floor.
    assert score_insider_conviction(below, as_of=AS_OF).score != \
           score_insider_conviction(above, as_of=AS_OF).score


def test_a_meaningful_buy_still_reads_bullish():
    txs = [tx(code="P", shares=50_000, price=100.0, owned_after=150_000)]
    assert score_insider_conviction(txs, as_of=AS_OF).score > 70


def test_missing_position_data_still_produces_a_score():
    """Older filings omit sharesOwnedFollowingTransaction; the layer must
    degrade rather than crash or silently score neutral."""
    txs = [tx(code="S", shares=10_000, price=100.0, owned_after=0.0)]
    result = score_insider_conviction(txs, as_of=AS_OF)
    assert result.available is True
    assert 0 <= result.score <= 100
