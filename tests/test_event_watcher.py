"""Slice 3 -- turning live filings into Dynamic Island payloads.

The SEC fetch is injected as a loader so the decision logic runs against real
fixture filings and the real Form 4 parser -- no mocking of either.
"""
from datetime import date
from pathlib import Path

import pytest

from aethelark_trade.engine.sec_stream import FilingEvent
from aethelark_trade.engine.watch import EventWatcher

FIXTURES = Path(__file__).parent / "fixtures"

CIK_MAP = {"0001045810": "NVDA", "0001318605": "TSLA", "0000050863": "INTC"}


def filing(form_type="4", cik="0001045810", accession="0001045810-26-000001",
           role="Issuer", company="NVIDIA CORP", filed=date(2026, 8, 19)):
    return FilingEvent(form_type=form_type, company=company, cik=cik, role=role,
                       accession=accession, filed=filed,
                       updated="2026-08-19T10:00:00-04:00", link="")


def loader(name):
    """Serve a real filing document for any accession."""
    text = (FIXTURES / name).read_text()
    return lambda cik, accession, form_type: text


def watcher(**kw):
    kw.setdefault("cik_map", CIK_MAP)
    kw.setdefault("as_of", date(2026, 8, 19))
    return EventWatcher(**kw)


def test_non_issuer_entries_are_ignored():
    """The Reporting-person row duplicates the Issuer row for the same
    accession; acting on both would double-fire every alert."""
    w = watcher(loader=loader("form4_TSLA_000110465926075213.xml"))
    assert w.handle(filing(role="Reporting")) == []


def test_unknown_cik_is_ignored():
    w = watcher(loader=loader("form4_TSLA_000110465926075213.xml"))
    assert w.handle(filing(cik="9999999999")) == []


def test_ticker_outside_the_tracked_universe_is_skipped_by_default():
    w = watcher(loader=loader("form4_TSLA_000110465926075213.xml"),
                cik_map={"0000000001": "ZZZZ"}, restrict_to_universe=True)
    assert w.handle(filing(cik="0000000001")) == []


def test_musk_option_exercise_does_not_fire_a_whale_buy():
    """The $7.09B exercise/withholding pair must stay silent. Firing a whale
    card on it would be the most misleading alert the HUD could show."""
    w = watcher(loader=loader("form4_TSLA_000110465926075213.xml"))
    assert w.handle(filing(cik="0001318605")) == []


def test_a_real_open_market_purchase_fires_a_whale_buy(tmp_path):
    """Synthesised from a real filing: same schema, code P, $2.5M."""
    source = (FIXTURES / "form4_TSLA_000110465926071970.xml").read_text()
    bought = source.replace("<transactionCode>S</transactionCode>",
                            "<transactionCode>P</transactionCode>")
    # The whale window is 7 days wide, so anchor on the filing's own date.
    w = watcher(loader=lambda c, a, f: bought, as_of=date(2026, 6, 9))
    payloads = w.handle(filing(cik="0001318605", filed=date(2026, 6, 9)))
    assert len(payloads) == 1
    assert payloads[0]["event"] == "form4_whale_buy"
    assert payloads[0]["ticker"] == "TSLA"
    assert payloads[0]["color"] == "#00FFA3"


def test_a_director_gift_does_not_fire_a_whale_buy():
    w = watcher(loader=loader("form4_NVDA_000119764726000007.xml"))
    assert w.handle(filing()) == []


def test_the_same_accession_is_only_acted_on_once():
    source = (FIXTURES / "form4_TSLA_000110465926071970.xml").read_text()
    bought = source.replace("<transactionCode>S</transactionCode>",
                            "<transactionCode>P</transactionCode>")
    w = watcher(loader=lambda c, a, f: bought, as_of=date(2026, 6, 9))
    first = w.handle(filing(cik="0001318605", accession="acc-1", filed=date(2026, 6, 9)))
    second = w.handle(filing(cik="0001318605", accession="acc-1", filed=date(2026, 6, 9)))
    assert len(first) == 1
    assert second == []


def test_a_loader_failure_degrades_to_no_event_instead_of_crashing():
    def broken(cik, accession, form_type):
        raise RuntimeError("SEC 503")

    w = watcher(loader=broken)
    assert w.handle(filing()) == []


def test_eight_k_material_agreement_fires_a_cyan_card():
    html = "<html>Item 1.01 Entry into a Material Definitive Agreement</html>"
    w = watcher(loader=lambda c, a, f: html)
    payloads = w.handle(filing(form_type="8-K", cik="0000050863"))
    assert len(payloads) == 1
    assert payloads[0]["event"] == "8k_material_event"
    assert payloads[0]["color"] == "#00E5FF"
    assert "1.01" in payloads[0]["detail"]


def test_an_eight_k_with_no_material_item_stays_silent():
    html = "<html>Item 7.01 Regulation FD Disclosure</html>"
    w = watcher(loader=lambda c, a, f: html)
    assert w.handle(filing(form_type="8-K", cik="0000050863")) == []
