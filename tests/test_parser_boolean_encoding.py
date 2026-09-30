"""Form 4 role flags must survive both XML boolean encodings.

SEC filer agents emit xsd:boolean as either "1"/"0" or "true"/"false"; both are
valid. parser.py compared against "1" only, so every filing from an agent using
the word form silently reported the insider as neither an officer nor a
director. That is not a cosmetic loss:

  * liar_filter._is_csuite() keys off is_officer, so C-suite selling by anyone
    whose title does not literally contain "CEO"/"CFO" went uncounted.
  * Layer 5 cannot distinguish a fund entity from a named executive without it.
"""
from datetime import date
from pathlib import Path

from aethelark_trade.parser import parse_form4_xml

FIXTURES = Path(__file__).parent / "fixtures"


def load(name, filing_date=date(2026, 8, 11)):
    return parse_form4_xml((FIXTURES / name).read_text(), filing_date, name)


def test_word_form_booleans_are_honoured():
    """Real GOOGL filing 0001193125-26-345383 (Sergey Brin) encodes
    <isDirector>true</isDirector> rather than 1."""
    raw = (FIXTURES / "form4_GOOGL_000119312526345383.xml").read_text()
    assert "<isDirector>true</isDirector>" in raw

    txs = load("form4_GOOGL_000119312526345383.xml")
    assert txs, "fixture should yield at least one transaction"
    assert all(t.is_director for t in txs)


def test_word_form_ten_percent_owner_is_honoured():
    """Brin is also flagged isTenPercentOwner=true."""
    txs = load("form4_GOOGL_000119312526345383.xml")
    assert all(t.is_ten_percent_owner for t in txs)


def test_word_form_false_stays_false():
    txs = load("form4_GOOGL_000119312526345383.xml")
    assert not any(t.is_officer for t in txs)


def test_digit_form_booleans_still_work():
    """Regression guard: the "1"/"0" encoding must keep parsing."""
    raw = (FIXTURES / "form4_TSLA_000110465926071970.xml").read_text()
    assert "<isOfficer>1</isOfficer>" in raw

    txs = load("form4_TSLA_000110465926071970.xml", date(2026, 6, 9))
    assert all(t.is_officer for t in txs)
    assert not any(t.is_director for t in txs)


def test_digit_form_director_still_works():
    txs = load("form4_NVDA_000119764726000007.xml", date(2026, 8, 7))
    assert all(t.is_director for t in txs)
    assert not any(t.is_officer for t in txs)
