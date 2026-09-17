"""Tests for Task 8: truthful company name resolution and absence reporting."""
import pytest

from aethelark_trade.engine.fetchers import company_name, fetch_quote, with_quote
from aethelark_trade.ticker_registry import company_name as registry_company_name


def test_unresolvable_company_returns_none_never_fabricated_corporation():
    """Rule broken: A layer that cannot measure something must report absence.

    company_name('NOTAREALCO') must return None, not 'NOTAREALCO Corporation'.
    """
    assert company_name("NOTAREALCO") is None
    assert registry_company_name("NOTAREALCO") is None
    assert company_name("XYZ123FAKE") is None
    assert company_name("") is None


def test_resolves_from_known_catalog():
    assert company_name("NVDA") == "NVIDIA Corp."
    assert company_name("AAPL") == "Apple Inc."
    assert company_name("MSFT") == "Microsoft Corporation"


def test_resolves_from_constituents_csv():
    # CRWD is in constituents.csv as 'CrowdStrike'
    name = company_name("CRWD")
    assert name is not None
    assert "CrowdStrike" in name
    assert "CRWD Corporation" not in name


def test_resolves_asml_correctly():
    name = company_name("ASML")
    assert name is not None
    assert "ASML" in name
    assert "ASML Corporation" not in name


def test_fetch_quote_on_unknown_symbol_reports_none_for_company_name(monkeypatch):
    """fetch_quote must not fabricate a company name for an unknown ticker."""
    class FakeFastInfo:
        last_price = 10.0
        previous_close = 10.0
        day_high = 10.5
        day_low = 9.5
        last_volume = 1000
        market_cap = 1000000

    class FakeTicker:
        def __init__(self, sym):
            self.fast_info = FakeFastInfo()

    import yfinance as yf
    monkeypatch.setattr(yf, "Ticker", FakeTicker)

    quote = fetch_quote("NOTAREALCO")
    assert quote["company_name"] is None
    assert quote["company_name"] != "NOTAREALCO Corporation"


def test_scorecard_renders_gracefully_with_unknown_company_name():
    """Scorecard enrichment handles company_name=None without error."""
    raw_scorecard = {
        "ticker": "NOTAREALCO",
        "composite_score": 50,
        "verdict": "NEUTRAL",
    }
    enriched = with_quote(raw_scorecard, "NOTAREALCO")
    assert enriched.get("company_name") is None or isinstance(enriched["company_name"], str)
