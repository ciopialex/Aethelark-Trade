"""Layer 5 must score insiders, not affiliated investment vehicles.

Measured: GOOGL scored 14 (ABNORMAL_DISTRIBUTION) driven entirely by
"GV 2019 GP, L.L.C." -- Google Ventures' general partner -- selling across 12
filings. A fund liquidating a position is portfolio management, not an
executive losing faith. ARCHITECTURE.md scopes this layer to
"Net CEO/Director Dollar Accumulation".
"""
from datetime import date

from aethelark_trade.engine.layers.insider import (
    is_scoreable_insider,
    score_insider_conviction,
)
from aethelark_trade.parser import InsiderTransaction

AS_OF = date(2026, 8, 19)


def tx(*, name, officer=False, director=False, ten_pct=False, other=False,
       code="S", shares=800_000, owned_after=200_000, title="", planned=False):
    t = InsiderTransaction(
        filing_date=date(2026, 8, 10), accession_number="x",
        issuer_name="X", issuer_ticker="X", issuer_cik="1",
        insider_name=name, insider_cik=name, insider_title=title,
        is_director=director, is_officer=officer, is_ten_percent_owner=ten_pct,
        is_other=other, transaction_date=date(2026, 8, 10),
        transaction_code=code, shares=shares, price_per_share=100.0,
        shares_owned_after=owned_after,
    )
    object.__setattr__(t, "is_10b5_1", planned)
    return t


def test_an_officer_is_scoreable():
    assert is_scoreable_insider(tx(name="Jane Doe", officer=True)) is True


def test_a_director_is_scoreable():
    assert is_scoreable_insider(tx(name="Jane Doe", director=True)) is True


def test_a_ten_percent_owner_that_is_neither_is_not_scoreable():
    """GV 2019 GP, L.L.C.: a fund GP, not a person with a seat."""
    assert is_scoreable_insider(
        tx(name="GV 2019 GP, L.L.C.", ten_pct=True)
    ) is False


def test_a_filer_with_no_role_at_all_is_not_scoreable():
    assert is_scoreable_insider(tx(name="Some Holdings LP")) is False


def test_a_director_who_is_also_a_ten_percent_owner_is_scoreable():
    """Sergey Brin files as isDirector=true AND isTenPercentOwner=true."""
    assert is_scoreable_insider(
        tx(name="Sergey Brin", director=True, ten_pct=True)
    ) is True


def test_a_fund_dumping_does_not_drag_the_layer_bearish():
    """The GOOGL case: one fund entity selling 80% of a line must not, on its
    own, put the whole company in ABNORMAL_DISTRIBUTION."""
    txs = [
        tx(name="GV 2019 GP, L.L.C.", ten_pct=True, code="S",
           shares=800_000, owned_after=200_000),
        tx(name="Real Director", director=True, code="S",
           shares=1_000, owned_after=500_000, planned=True),
    ]
    result = score_insider_conviction(txs, as_of=AS_OF)
    assert result.detail["tier"] != "ABNORMAL_DISTRIBUTION"
    assert 45 <= result.score <= 55


def test_a_real_executive_dumping_still_registers():
    """The filter must not become a blanket excuse to ignore selling."""
    txs = [tx(name="Jane Doe", officer=True, title="Chief Executive Officer",
              code="S", shares=800_000, owned_after=200_000)]
    result = score_insider_conviction(txs, as_of=AS_OF)
    assert result.detail["tier"] == "ABNORMAL_DISTRIBUTION"


def test_a_layer_of_only_entity_filers_is_unavailable():
    """No scoreable insider means no signal -- not a neutral fabrication."""
    txs = [tx(name="GV 2019 GP, L.L.C.", ten_pct=True)]
    assert score_insider_conviction(txs, as_of=AS_OF).available is False


def test_entity_filers_are_reported_as_excluded():
    txs = [
        tx(name="GV 2019 GP, L.L.C.", ten_pct=True),
        tx(name="Jane Doe", officer=True, code="S", shares=1_000,
           owned_after=500_000),
    ]
    detail = score_insider_conviction(txs, as_of=AS_OF).detail
    assert detail["excluded_non_insider_trades"] == 1
