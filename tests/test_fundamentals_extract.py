"""Layer 1 extraction from real SEC companyfacts JSON.

Fixtures are genuine SEC data (concept-trimmed to keep the repo light);
every number asserted below is what NVDA/INTC actually filed.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from aethelark_trade.engine.layers.fundamentals import extract_fundamentals

FIXTURES = Path(__file__).parent / "fixtures"


def facts(ticker: str) -> dict:
    return json.loads((FIXTURES / f"companyfacts_{ticker}.json").read_text())


@pytest.fixture(scope="module")
def nvda():
    return extract_fundamentals(facts("NVDA"))


def test_picks_the_most_recent_annual_period(nvda):
    assert nvda.fiscal_year_end == date(2026, 1, 25)


def test_extracts_revenue_from_the_concept_actually_used(nvda):
    """NVDA reports under `Revenues`; its
    RevenueFromContractWithCustomerExcludingAssessedTax series stopped in 2022."""
    assert nvda.revenue == pytest.approx(215_938_000_000, rel=1e-6)


def test_falls_back_to_an_alias_when_the_primary_capex_concept_is_stale(nvda):
    """PaymentsToAcquirePropertyPlantAndEquipment last appears for FY2012.
    Real FY2026 capex sits in PaymentsToAcquireProductiveAssets = $6.042B."""
    assert nvda.capex == pytest.approx(6_042_000_000, rel=1e-6)


def test_gross_margin_matches_filed_figures(nvda):
    # 153.46B / 215.94B
    assert nvda.gross_margin == pytest.approx(0.7107, abs=0.001)


def test_free_cash_flow_is_operating_cash_less_capex(nvda):
    # 102.72B - 6.042B
    assert nvda.free_cash_flow == pytest.approx(96_676_000_000, rel=1e-4)
    assert nvda.fcf_margin == pytest.approx(0.4477, abs=0.001)


def test_gross_margin_expansion_is_measured_against_the_prior_year(nvda):
    """FY2025 GM was 97.86/130.50 = 74.99%; FY2026 is 71.07%.
    Margins contracted ~3.9pp despite revenue nearly doubling."""
    assert nvda.gross_margin_delta_pp == pytest.approx(-3.9, abs=0.2)


def test_roic_uses_operating_income_over_invested_capital(nvda):
    # 130.39B * (1-0.21) / (157.29B equity + 7.47B long-term debt)
    assert nvda.roic == pytest.approx(0.625, abs=0.01)


def test_a_different_filer_with_different_concepts_also_extracts():
    """INTC has no `Revenues` concept at all - it files SalesRevenueNet /
    RevenueFromContractWithCustomerExcludingAssessedTax."""
    intc = extract_fundamentals(facts("INTC"))
    assert intc.revenue is not None and intc.revenue > 0
    assert intc.gross_margin is not None
