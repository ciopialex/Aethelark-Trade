"""Layer 5: Insider Conviction scoring (0-100)."""
from datetime import date

import pytest

from aethelark_trade.engine.layers.insider import (
    BUY_SATURATION,
    score_insider_conviction,
)
from tests.test_liar_filter import tx

AS_OF = date(2026, 8, 19)


def test_no_filings_is_unavailable_not_zero():
    """Superseded expectation: this used to assert score == 50. An unavailable
    layer now carries no number at all, so nothing downstream can mistake a
    placeholder for a measurement."""
    result = score_insider_conviction([], as_of=AS_OF)
    assert result.available is False
    assert result.score is None


def test_pure_buying_scores_bullish():  # noqa: D103
    txs = [tx(title="Chief Executive Officer", code="P", shares=100_000,
              price=100.0, tx_date=date(2026, 8, 10))]  # $10M x2.0 role weight
    result = score_insider_conviction(txs, as_of=AS_OF)
    assert result.available is True
    assert result.score > 75


def test_modest_selling_is_routine_not_bearish():
    """Superseded contract: this used to assert < 25 on a symmetric curve.
    Selling ~9% of a stake is ordinary compensation liquidation, so it now
    lands in the neutral band. Only off-plan dumping is bearish -- see
    tests/test_layer5_three_tier.py."""
    txs = [tx(title="Chief Executive Officer", code="S", shares=100_000,
              price=100.0, tx_date=date(2026, 8, 10))]
    result = score_insider_conviction(txs, as_of=AS_OF)
    assert 45 <= result.score <= 55
    assert result.detail["tier"] == "ROUTINE"


def test_cfo_conviction_outweighs_a_directors():
    """parser.role_weight ranks CFO (3.0) above CEO (2.0) above board (1.0):
    the CFO sees the numbers before anyone else."""
    cfo = [tx(title="Chief Financial Officer", code="P", shares=10_000,
              price=100.0, tx_date=date(2026, 8, 10))]
    board = [tx(title="Director", code="P", shares=10_000, price=100.0,
                tx_date=date(2026, 8, 10), officer=False, director=True)]
    assert score_insider_conviction(cfo, as_of=AS_OF).score > \
           score_insider_conviction(board, as_of=AS_OF).score


def test_score_is_bounded_to_zero_hundred_under_absurd_size():
    txs = [tx(title="Chief Financial Officer", code="P", shares=10_000_000,
              price=1000.0, tx_date=date(2026, 8, 10))]  # $10B
    result = score_insider_conviction(txs, as_of=AS_OF)
    assert 0 <= result.score <= 100


def test_buying_alongside_equal_selling_reads_as_accumulation():
    """Superseded contract: this used to net to ~50 on a symmetric curve.
    Under the tier model a voluntary purchase is the rarer, more informative
    act, so an insider who both bought and sold the same size is accumulating
    -- they chose to put money in when they had no obligation to."""
    txs = [
        tx(title="Chief Executive Officer", code="P", shares=50_000, price=100.0,
           tx_date=date(2026, 8, 10), owned_after=500_000),
        tx(title="Chief Executive Officer", code="S", shares=50_000, price=100.0,
           tx_date=date(2026, 8, 11), owned_after=450_000),
    ]
    result = score_insider_conviction(txs, as_of=AS_OF)
    assert result.detail["tier"] == "ACCUMULATION"
    assert result.score >= 80


def test_saturation_constant_is_documented():
    assert 0 < BUY_SATURATION <= 1.0


def test_small_buy_below_materiality_floor_does_not_produce_accumulation():
    """A small buy (below MATERIALITY_FLOOR_USD) must not move the layer into
    ACCUMULATION or the bullish band (80-100)."""
    # $200k buy by CEO (below $1M floor)
    small_buy = [tx(title="Chief Executive Officer", code="P", shares=2_000,
                    price=100.0, tx_date=date(2026, 8, 10))]
    result = score_insider_conviction(small_buy, as_of=AS_OF)
    assert result.detail["tier"] != "ACCUMULATION"
    assert result.score <= 55


def test_token_buyers_cannot_outvote_heavy_seller():
    """Multiple buyers with lower conviction than a CEO liquidating off-plan
    must not flip the tier to ACCUMULATION by summing."""
    from aethelark_trade.engine.layers.insider import measure_flow
    from aethelark_trade.parser import InsiderTransaction

    # CEO sells 35% of stake off-plan for $3.5M (abnormality = 0.35)
    txs = [
        InsiderTransaction(
            filing_date=date(2026, 8, 10), accession_number="0000000000-00-000000",
            issuer_name="Example Corp", issuer_ticker="EXMP", issuer_cik="0000000001",
            insider_name="Jane Doe", insider_cik="0000000002", insider_title="Chief Executive Officer",
            is_director=False, is_officer=True, is_ten_percent_owner=False, is_other=False,
            transaction_date=date(2026, 8, 10), transaction_code="S", shares=35_000, price_per_share=100.0,
            shares_owned_after=65_000,
        )
    ]
    # Eight distinct directors each buy $1.5M with 0.05 role-weighted conviction
    # Under sum: 8 * 0.05 = 0.40 > 0.35, out-voting the CEO!
    # Under max: max(0.05) = 0.05 < 0.35, CEO's heavy sell controls the tier.
    for i in range(8):
        txs.append(
            InsiderTransaction(
                filing_date=date(2026, 8, 10), accession_number=f"0000000000-00-00000{i}",
                issuer_name="Example Corp", issuer_ticker="EXMP", issuer_cik="0000000001",
                insider_name=f"Director {i}", insider_cik=f"000000001{i}", insider_title="Director",
                is_director=True, is_officer=False, is_ten_percent_owner=False, is_other=False,
                transaction_date=date(2026, 8, 10), transaction_code="P", shares=15_000, price_per_share=100.0,
                shares_owned_after=135_000,
            )
        )
    flow = measure_flow(txs, as_of=AS_OF)
    assert flow.tier == "ABNORMAL_DISTRIBUTION"
    assert flow.buy_conviction < flow.discretionary_sell_conviction

