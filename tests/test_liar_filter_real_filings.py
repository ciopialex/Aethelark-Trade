"""Liar Filter against real SEC Form 4 XML captured from EDGAR.

Fixtures in tests/fixtures/ are verbatim filings, not synthesized samples.
"""
from datetime import date
from pathlib import Path

import pytest

from aethelark_trade.engine.liar_filter import check_liar_filter, csuite_net_flow
from aethelark_trade.parser import parse_form4_xml

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str, filing_date: date):
    xml = (FIXTURES / name).read_text()
    return parse_form4_xml(xml, filing_date, name.split("_")[-1].removesuffix(".xml"))


def test_musk_option_exercise_is_not_counted_as_a_seven_billion_dollar_buy():
    """Real filing 0001104659-26-075213: Musk exercises 303,960,630 options
    (code M, $7.09B notional) and withholds 17,531,857 shares for tax (code F,
    $7.09B notional). Neither is an open-market decision -- net flow is zero.
    Counting M/F would fabricate a multi-billion-dollar conviction signal."""
    txs = load("form4_TSLA_000110465926075213.xml", date(2026, 6, 17))
    assert len(txs) == 3
    assert {t.transaction_code for t in txs} == {"M", "F"}
    assert csuite_net_flow(txs, as_of=date(2026, 6, 17)) == 0.0


def test_real_cfo_open_market_sale_is_counted():
    """Real filing 0001104659-26-071970: CFO Vaibhav Taneja sells 2,605.5
    shares at $402.197 (code S) = $1,047,924.28 of genuine distribution."""
    txs = load("form4_TSLA_000110465926071970.xml", date(2026, 6, 9))
    net = csuite_net_flow(txs, as_of=date(2026, 6, 9))
    assert net == pytest.approx(-1_047_924.28, abs=0.01)


def test_real_cfo_sale_is_below_the_divergence_threshold():
    """$1.05M of selling is real but an order of magnitude under the $10M bar,
    so even maximal euphoria stays CLEAN."""
    txs = load("form4_TSLA_000110465926071970.xml", date(2026, 6, 9))
    result = check_liar_filter(100.0, txs, as_of=date(2026, 6, 9))
    assert result.status == "CLEAN"


def test_real_director_gift_produces_no_csuite_flow():
    """Real filing 0001197647-26-000007: NVDA director Tench Coxe gifts 500,000
    shares (code G). A gift is neither a buy nor a sale, and a director is not
    the C-suite."""
    txs = load("form4_NVDA_000119764726000007.xml", date(2026, 8, 7))
    assert txs[0].transaction_code == "G"
    assert csuite_net_flow(txs, as_of=date(2026, 8, 7)) == 0.0
