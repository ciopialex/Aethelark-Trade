"""SHIP_1.0 C1 — asking who owns a company.

The Schedule 13D/13G parser, its storage and its collector are all built and
wired. Nothing reached them: no command existed, so the eagle could not ask.
This is the command.

It answers a fact rather than a forecast, which is the class of thing this
product is supposed to be in -- who holds five percent or more of a company,
which of them filed as activists and which as passive accumulators.

Three honesty requirements, all of them learned the hard way elsewhere in this
codebase:

  - **Filings that failed to parse are counted, not hidden and not shown.**
    Measured 2026-09-05: 4 of 40 stored filings carry
    `filer_name = "Unknown Filer (Parsing Failed)"` with zero shares. Listing
    those as holders would state a falsehood; dropping them silently would
    overstate how complete the answer is. They are excluded from the holders and
    reported as a count.
  - **The answer says how old it is.** Ownership filings are episodic; the most
    recent 13G for a company may be two years old, and "who owns NVDA" answered
    from 2024 data without saying so is misleading.
  - **Having no filings is an answer.** It is not an error, and it does not mean
    nobody owns the company -- it means nobody crossed five percent and filed.
"""
from __future__ import annotations

import datetime as dt

import pytest

from aethelark_trade.schedule13 import Schedule13Filing


def _filing(name, pct, shares, activist=False, when=(2024, 6, 1), form="SC 13G"):
    return Schedule13Filing(
        filing_date=dt.date(*when), accession_number="x", form_type=form,
        issuer_name="Nvidia", issuer_ticker="NVDA", issuer_cik="", issuer_cusip="",
        filer_name=name, filer_cik="", filer_address="",
        shares_owned=shares, percent_of_class=pct,
        sole_voting_power=0.0, shared_voting_power=0.0,
        sole_dispositive_power=0.0, shared_dispositive_power=0.0,
        is_activist=activist, purpose="")


def _owners(filings, ticker="NVDA"):
    from aethelark_trade.owners import who_owns
    return who_owns(ticker, filings)


def test_holders_are_named_with_their_stakes_largest_first():
    answer = _owners([
        _filing("BlackRock, Inc", 7.3, 180_593_555),
        _filing("The Vanguard Group", 8.28, 204_504_938),
    ])
    assert [h["name"] for h in answer["holders"]] == ["The Vanguard Group", "BlackRock, Inc"]
    assert answer["holders"][0]["percent"] == 8.28
    assert answer["holders"][0]["shares"] == 204_504_938


def test_activists_are_separated_from_passive_accumulators():
    answer = _owners([
        _filing("Elliott Management", 6.0, 1_000, activist=True, form="SC 13D"),
        _filing("The Vanguard Group", 8.28, 204_504_938),
    ])
    stance = {h["name"]: h["stance"] for h in answer["holders"]}
    assert stance["Elliott Management"] == "activist"
    assert stance["The Vanguard Group"] == "passive"
    assert answer["activists"] == 1


def test_a_filing_that_failed_to_parse_is_counted_not_listed():
    answer = _owners([
        _filing("Unknown Filer (Parsing Failed) - SC 13G/A", 0.0, 0.0),
        _filing("The Vanguard Group", 8.28, 204_504_938),
    ])
    names = [h["name"] for h in answer["holders"]]
    assert "Unknown Filer (Parsing Failed) - SC 13G/A" not in " ".join(names), (
        "a filing nobody could read was presented as a holder")
    assert answer["unreadable"] == 1, (
        "the unreadable filing was dropped silently, which overstates how "
        "complete this answer is")


def test_the_same_holder_filing_twice_is_reported_once_at_its_latest():
    answer = _owners([
        _filing("The Vanguard Group", 8.32, 204_600_119, when=(2023, 2, 9)),
        _filing("The Vanguard Group", 8.28, 204_504_938, when=(2024, 2, 13)),
    ])
    assert len(answer["holders"]) == 1
    assert answer["holders"][0]["percent"] == 8.28, "an older filing won"


def test_the_answer_says_how_old_it_is():
    answer = _owners([_filing("The Vanguard Group", 8.28, 1, when=(2024, 2, 13))])
    assert answer["latest_filing"] == "2024-02-13"
    assert "2024" in answer["summary"]


def test_no_filings_is_an_answer_not_an_error():
    answer = _owners([])
    assert answer["holders"] == []
    assert answer["unreadable"] == 0
    said = answer["summary"].lower()
    assert "no" in said and "five percent" in said, (
        f"the summary must say nobody crossed the threshold, not that the "
        f"lookup failed: {answer['summary']!r}")


def test_the_summary_never_states_a_number_it_does_not_have():
    """s15. A holder whose percentage did not parse is not reported as 0%."""
    answer = _owners([_filing("Some Fund", 0.0, 5_000_000)])
    holder = answer["holders"][0]
    assert holder["percent"] is None, (
        "a percentage the filing did not carry was reported as 0.0, which is a "
        "claim that the fund owns none of the company")
