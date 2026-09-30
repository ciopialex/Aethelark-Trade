"""Off-plan selling must be material in dollars, not just large as a fraction.

Measured: META scored 18 (ABNORMAL_DISTRIBUTION) driven by Marc Andreessen
selling 426 shares -- $0.3M -- against a reported line of 176 shares
(frac 0.708). Executives hold stock across many vehicles, so a single Form 4
line's residual can be tiny; a $0.3M trade must not swing the verdict on a
$1.5T company. By contrast KO's CFO sold $19.1M off-plan at frac 0.446, which
is a genuine signal.
"""
from datetime import date

from aethelark_trade.engine.layers.insider import (
    MATERIALITY_FLOOR_USD,
    score_insider_conviction,
)
from aethelark_trade.parser import InsiderTransaction

AS_OF = date(2026, 8, 19)


def tx(*, shares, price, owned_after, code="S", planned=False,
       title="Chief Executive Officer", name="Jane Doe"):
    t = InsiderTransaction(
        filing_date=date(2026, 8, 10), accession_number="x",
        issuer_name="X", issuer_ticker="X", issuer_cik="1",
        insider_name=name, insider_cik=name, insider_title=title,
        is_director=False, is_officer=True, is_ten_percent_owner=False,
        is_other=False, transaction_date=date(2026, 8, 10),
        transaction_code=code, shares=shares, price_per_share=price,
        shares_owned_after=owned_after,
    )
    object.__setattr__(t, "is_10b5_1", planned)
    return t


def test_materiality_floor_is_documented():
    assert MATERIALITY_FLOOR_USD > 0


def test_an_immaterial_sale_cannot_trigger_the_bearish_tier():
    """The Andreessen case: 71% of a tiny reported line, but only $0.3M."""
    txs = [tx(shares=426, price=700.0, owned_after=176)]   # $298k, frac 0.708
    result = score_insider_conviction(txs, as_of=AS_OF)
    assert result.detail["tier"] != "ABNORMAL_DISTRIBUTION"
    assert 45 <= result.score <= 55


def test_a_material_sale_at_a_similar_fraction_does_trigger_it():
    """The KO CFO case: same order of fraction, but $19.1M of stock."""
    txs = [tx(shares=224_932, price=85.0, owned_after=279_917)]  # $19.1M, frac 0.446
    result = score_insider_conviction(txs, as_of=AS_OF)
    assert result.detail["tier"] == "ABNORMAL_DISTRIBUTION"


def test_the_floor_is_applied_per_insider_not_per_trade():
    """Five $400k sales by one executive add up to a material $2M exit."""
    txs = [tx(shares=4_000, price=100.0, owned_after=6_000 - i * 1_000,
              name="Serial Seller")
           for i in range(5)]
    result = score_insider_conviction(txs, as_of=AS_OF)
    assert result.detail["tier"] == "ABNORMAL_DISTRIBUTION"


def test_immaterial_selling_does_not_mask_a_material_seller():
    """One noisy small filer must not shield a genuine dumper."""
    txs = [
        tx(shares=426, price=700.0, owned_after=176, name="Small Fry"),
        tx(shares=224_932, price=85.0, owned_after=279_917, name="Real Dumper"),
    ]
    assert score_insider_conviction(txs, as_of=AS_OF).detail["tier"] == \
        "ABNORMAL_DISTRIBUTION"


def test_buying_is_subject_to_the_materiality_floor():
    """A buy below the materiality floor cannot move the layer into
    ACCUMULATION. A $50k purchase stays in ROUTINE."""
    txs = [tx(code="P", shares=500, price=100.0, owned_after=100_000)]
    assert score_insider_conviction(txs, as_of=AS_OF).detail["tier"] == "ROUTINE"


def test_immaterial_selling_is_still_counted_in_the_trade_tally():
    """Filtered from the abnormality signal, not hidden from the ledger."""
    txs = [tx(shares=426, price=700.0, owned_after=176)]
    detail = score_insider_conviction(txs, as_of=AS_OF).detail
    assert detail["trade_count"] == 1
    assert detail["sold_usd"] > 0
