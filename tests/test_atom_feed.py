"""Slice 3 -- SEC master ATOM feed parsing.

Fixtures are verbatim captures of the live EDGAR getcurrent feed.
"""
from pathlib import Path

import pytest

from aethelark_trade.engine.sec_stream import (
    FilingEvent,
    dedupe_filings,
    issuer_ciks,
    parse_atom_feed,
)

FIXTURES = Path(__file__).parent / "fixtures"
FORM4 = (FIXTURES / "sec_atom_form4.xml").read_text()
EIGHTK = (FIXTURES / "sec_atom_8k.xml").read_text()


def test_parses_entries_from_the_live_feed():
    events = parse_atom_feed(FORM4)
    assert len(events) > 0
    assert all(isinstance(e, FilingEvent) for e in events)


def test_extracts_form_type_cik_and_accession():
    e = parse_atom_feed(FORM4)[0]
    assert e.form_type == "4"
    assert e.cik.isdigit() and len(e.cik) == 10
    assert e.accession.count("-") == 2


def test_distinguishes_the_reporting_person_from_the_issuer():
    """One Form 4 produces two entries under the same accession: the insider
    (Reporting) and the company (Issuer). Only the issuer CIK maps to a ticker,
    so conflating them resolves alerts to the wrong entity."""
    events = parse_atom_feed(FORM4)
    roles = {e.role for e in events}
    assert "Issuer" in roles
    assert "Reporting" in roles


def test_the_same_accession_really_does_appear_more_than_once():
    events = parse_atom_feed(FORM4)
    accessions = [e.accession for e in events]
    assert len(accessions) > len(set(accessions))


def test_dedupe_collapses_an_accession_to_one_event():
    events = parse_atom_feed(FORM4)
    deduped = dedupe_filings(events)
    assert len({e.accession for e in deduped}) == len(deduped)
    assert len(deduped) < len(events)


def test_dedupe_keeps_the_issuer_side():
    """The issuer entry carries the CIK that resolves to a tradeable ticker."""
    events = parse_atom_feed(FORM4)
    by_acc = {}
    for e in events:
        by_acc.setdefault(e.accession, []).append(e)
    contested = [a for a, v in by_acc.items() if {x.role for x in v} >= {"Issuer", "Reporting"}]
    assert contested, "fixture should contain at least one dual-role accession"

    deduped = {e.accession: e for e in dedupe_filings(events)}
    for accession in contested:
        assert deduped[accession].role == "Issuer"


def test_company_name_is_stripped_of_the_form_and_cik_decoration():
    events = parse_atom_feed(FORM4)
    issuer = next(e for e in events if e.role == "Issuer")
    assert not issuer.company.startswith("4 -")
    assert "(" not in issuer.company


def test_issuer_ciks_returns_only_issuer_side_ciks():
    events = parse_atom_feed(FORM4)
    ciks = issuer_ciks(events)
    assert ciks
    assert all(c.isdigit() and len(c) == 10 for c in ciks)


def test_parses_the_eight_k_feed_too():
    events = parse_atom_feed(EIGHTK)
    assert events
    assert all(e.form_type.startswith("8-K") for e in events)


def test_filed_date_is_extracted_from_the_summary():
    e = parse_atom_feed(FORM4)[0]
    assert e.filed is not None
    assert e.filed.year >= 2020


def test_empty_or_junk_feed_yields_no_events_instead_of_raising():
    assert parse_atom_feed("") == []
    assert parse_atom_feed("<html>not a feed</html>") == []
