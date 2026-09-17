"""A ledger the host cannot carry is a ledger that answers wrongly.

Space-Eagle splits a module's payload in two: the card gets it whole, the
language model gets a copy clipped at 16,000 characters — mid-structure, with
a character count appended. Nothing rejects an oversized payload and nothing
used to say it happened.

Measured 2026-09-07 on the fixture beside this file, which is a real AMD
ledger: 182 filings, 47,586 characters. 121 were cut. The model answered from
the 61 that survived and reported $45M of selling against a true $118M — every
figure in it correct, the CEO's own sales entirely inside the truncated part,
and nothing about the answer looking broken.

This is a property over a real artifact: the busiest ledger this module has
actually produced, checked against the ceiling it has to pass through. It is
not a mirror — it asserts arithmetic and size, both of which can fail.
"""
import json
from pathlib import Path

import pytest

from aethelark_trade.engine.fetchers import TOP_SALES, insider_ledger_view

#: `MAX_OUTPUT_CHARS` in Space-Eagle's core/module_bus/bus.py. Duplicated
#: rather than imported: this repo must not depend on the host to build. If
#: the host ever raises it, this staying low costs nothing.
BUS_CEILING = 16000

FIXTURE = Path(__file__).parent / "fixtures" / "insider_ledger_AMD_180d.json"


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def view(rows) -> dict:
    return insider_ledger_view(rows, "AMD", 180, form144_notices=0)


def _model_copy(payload: dict) -> str:
    """What crosses to the model: `_`-prefixed keys stripped, at any depth.
    Mirrors `model_view` in the host's bus."""
    def strip(v):
        if isinstance(v, dict):
            return {k: strip(x) for k, x in v.items() if not k.startswith("_")}
        if isinstance(v, list):
            return [strip(x) for x in v]
        return v
    return json.dumps(strip(payload), ensure_ascii=False)


def test_the_model_copy_fits_the_bus(view):
    size = len(_model_copy(view))
    assert size <= BUS_CEILING, (
        f"{size:,} characters against a {BUS_CEILING:,} ceiling — the model "
        f"would be handed this cut in half, mid-object")


def test_the_card_still_gets_every_filing(view, rows):
    """The cap is for the model. The card can page through all of them."""
    assert len(view["_transactions"]) == len(rows)


def test_the_totals_are_computed_over_the_whole_ledger(view, rows):
    """The heart of it. A capped list is a sample; the totals beside it must
    still be true, or the summary is a second, quieter lie."""
    sales = [r for r in rows if r["code"] == "S"]
    assert view["sold"]["count"] == len(sales)
    assert view["sold"]["usd"] == pytest.approx(
        sum(abs(r["value"] or 0) for r in sales), rel=1e-9)


def test_the_largest_sale_is_named(view, rows):
    """Present because it is the largest, not because of where a byte offset
    fell. This is the one the truncated payload lost."""
    biggest = max((r for r in rows if r["code"] == "S"),
                  key=lambda r: abs(r["value"] or 0))
    match = [r for r in view["top_sales"]
             if r["insider"] == biggest["insider"]
             and r["usd"] == pytest.approx(abs(biggest["value"]))]
    assert match, (
        f"the largest sale — {biggest['insider']} "
        f"${abs(biggest['value']):,.0f} on {biggest['date']} — is not named")


def test_sales_are_named_biggest_first_and_capped(view):
    usd = [r["usd"] for r in view["top_sales"]]
    assert usd == sorted(usd, reverse=True)
    assert len(view["top_sales"]) <= TOP_SALES


def test_purchases_are_never_capped(rows):
    """An insider buying is the rare signal and there are seldom many. Losing
    one to save a hundred characters would throw away the reason to look."""
    buys = [dict(r, code="P") for r in rows[:TOP_SALES + 5]]
    view = insider_ledger_view(buys, "AMD", 180)
    assert len(view["buys"]) == len(buys) > TOP_SALES


def test_vesting_machinery_is_counted_not_sold(view, rows):
    """Codes M, F, A and G are not somebody deciding to sell. Conflating them
    is how a tax withholding gets reported as an insider dumping stock."""
    assert view["sold"]["count"] == sum(1 for r in rows if r["code"] == "S")
    assert sum(view["other"].values()) == sum(
        1 for r in rows if r["code"] not in ("S", "P"))


def test_an_empty_ledger_is_not_an_error(view):
    empty = insider_ledger_view([], "AMD", 180)
    assert empty["filings"] == 0
    assert empty["sold"] == {"count": 0, "usd": 0}
    assert empty["latest"] is None
