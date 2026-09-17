"""Rule 10b5-1 plan detection and its effect on insider conviction.

A trade executed under a pre-adopted 10b5-1 plan was scheduled months earlier;
the insider had no timing discretion, so it carries little information about
what they believe today. ARCHITECTURE.md Layer 5 calls for exactly this
distinction ("Net Accumulation vs Routine Sales").
"""
from datetime import date
from pathlib import Path

from aethelark_trade.engine.layers.insider import (
    PLANNED_TRADE_DISCOUNT,
    score_insider_conviction,
)
from aethelark_trade.parser import parse_form4_xml
from tests.test_liar_filter import tx

FIXTURES = Path(__file__).parent / "fixtures"
AS_OF = date(2026, 8, 19)


def load(name, filing_date):
    return parse_form4_xml((FIXTURES / name).read_text(), filing_date, name)


def test_parser_flags_a_real_10b5_1_filing():
    """NVDA 0001197647-26-000007 carries <aff10b5One>1</aff10b5One> and a
    footnote naming a plan adopted 2026-03-19."""
    txs = load("form4_NVDA_000119764726000007.xml", date(2026, 8, 7))
    assert all(t.is_10b5_1 for t in txs)


def test_parser_flags_a_real_discretionary_filing():
    """TSLA 0001104659-26-071970 carries <aff10b5One>0</aff10b5One>."""
    txs = load("form4_TSLA_000110465926071970.xml", date(2026, 6, 9))
    assert not any(t.is_10b5_1 for t in txs)


def test_scheduled_selling_is_discounted_against_discretionary_selling():
    """Identical dollar size; only the discretion differs."""
    discretionary = [tx(title="Chief Executive Officer", code="S", shares=100_000,
                        price=100.0, tx_date=date(2026, 8, 10))]
    planned = [tx(title="Chief Executive Officer", code="S", shares=100_000,
                  price=100.0, tx_date=date(2026, 8, 10))]
    object.__setattr__(planned[0], "is_10b5_1", True)

    assert score_insider_conviction(planned, as_of=AS_OF).score > \
           score_insider_conviction(discretionary, as_of=AS_OF).score


def test_discount_is_a_documented_fraction():
    assert 0.0 < PLANNED_TRADE_DISCOUNT < 1.0


def test_planned_flag_is_reported_in_detail():
    planned = [tx(title="Chief Executive Officer", code="S", shares=100_000,
                  price=100.0, tx_date=date(2026, 8, 10))]
    object.__setattr__(planned[0], "is_10b5_1", True)
    detail = score_insider_conviction(planned, as_of=AS_OF).detail
    assert detail["planned_trade_count"] == 1
    assert detail["discretionary_trade_count"] == 0
