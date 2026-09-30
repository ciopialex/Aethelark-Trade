"""Layer 1 scoring: quality metrics -> 0-100."""
import json
from pathlib import Path

import pytest

from aethelark_trade.engine.layers.fundamentals import (
    FundamentalSnapshot,
    extract_fundamentals,
    score_fundamentals,
)

FIXTURES = Path(__file__).parent / "fixtures"


def snap(ticker):
    return extract_fundamentals(
        json.loads((FIXTURES / f"companyfacts_{ticker}.json").read_text())
    )


def test_empty_snapshot_is_unavailable():
    result = score_fundamentals(FundamentalSnapshot())
    assert result.available is False


def test_a_cash_gushing_compounder_scores_high():
    """NVDA FY2026: 44.8% FCF margin, 62.5% ROIC."""
    result = score_fundamentals(snap("NVDA"))
    assert result.available is True
    assert result.score >= 70


def test_a_cash_burning_turnaround_scores_below_neutral():
    """INTC FY2025: -9.4% FCF margin, -1.1% ROIC."""
    result = score_fundamentals(snap("INTC"))
    assert result.score < 50


def test_quality_leader_outscores_the_turnaround():
    assert score_fundamentals(snap("NVDA")).score > score_fundamentals(snap("INTC")).score


def test_margin_contraction_is_penalised_against_an_identical_twin():
    """Same cash economics; only the gross-margin trend differs."""
    base = dict(revenue=100e9, gross_profit=70e9, operating_income=40e9,
                cash_from_operations=30e9, capex=5e9, equity=50e9,
                long_term_debt=10e9, prior_revenue=80e9)
    expanding = FundamentalSnapshot(**base, prior_gross_profit=52e9)   # 65.0% -> 70.0%
    contracting = FundamentalSnapshot(**base, prior_gross_profit=60e9)  # 75.0% -> 70.0%
    assert score_fundamentals(expanding).score > score_fundamentals(contracting).score


def test_score_stays_in_bounds_for_extreme_inputs():
    absurd = FundamentalSnapshot(
        revenue=1e9, gross_profit=0.99e9, operating_income=50e9,
        cash_from_operations=40e9, capex=0.0, equity=1e6, long_term_debt=0.0,
        prior_revenue=1e9, prior_gross_profit=0.01e9,
    )
    assert 0 <= score_fundamentals(absurd).score <= 100


def test_summary_reports_the_real_metrics():
    result = score_fundamentals(snap("NVDA"))
    assert "71.1%" in result.summary          # gross margin
    assert result.detail["roic"] == pytest.approx(0.625, abs=0.01)


def test_fcf_yield_is_computed_when_market_cap_is_known():
    """NVDA FY2026 FCF is $96.676B. At a $5.322T cap that is a 1.82% yield --
    the value leg the leaderboard ranks on."""
    result = score_fundamentals(snap("NVDA"), market_cap=5_322e9)
    assert result.detail["fcf_yield_pct"] == pytest.approx(1.82, abs=0.02)


def test_fcf_yield_is_absent_without_a_market_cap():
    assert "fcf_yield_pct" not in score_fundamentals(snap("NVDA")).detail


def test_fcf_yield_does_not_change_the_quality_score():
    """Valuation is a leaderboard input, not a quality judgement. Layer 1 must
    score the business identically however the market prices it."""
    assert score_fundamentals(snap("NVDA"), market_cap=5_322e9).score == \
           score_fundamentals(snap("NVDA")).score


def test_financial_institution_without_operating_metrics_is_unavailable():
    """JPMorgan and Citigroup report cash flows driven by loans and deposits,
    and no Gross Profit or Operating Income. FCF margin is meaningless for
    them and must report unavailable rather than 0 or 96."""
    jpm_snap = FundamentalSnapshot(
        revenue=182_447_000_000.0,
        cash_from_operations=-147_782_000_000.0,
        equity=362_438_000_000.0,
    )
    result_jpm = score_fundamentals(jpm_snap)
    assert result_jpm.available is False
    assert result_jpm.score is None
    assert "unavailable" in result_jpm.summary.lower() or "not comparable" in result_jpm.summary.lower()

    axp_snap = FundamentalSnapshot(
        revenue=41_304_000_000.0,
        cash_from_operations=18_428_000_000.0,
        capex=2_425_000_000.0,
        equity=33_474_000_000.0,
    )
    result_axp = score_fundamentals(axp_snap)
    assert result_axp.available is False
    assert result_axp.score is None



# --- what kind of filer this is, not which concepts happen to be missing ----
#
# The rule above this line was written on 2026-09-03 and was undone the same
# day. It fired when gross profit AND operating income were both absent; an
# unrelated commit then widened the operating-income alias chain to include
# IncomeLossFromContinuingOperationsBeforeIncomeTaxes..., which banks do file,
# so the condition stopped being true and the meaningless figure walked back in
# at 40% of the layer. Nothing went red: the test above builds a snapshot with
# no operating income, so it kept passing while the product regressed.
#
# The snapshots below are shaped like the real filings, operating income and
# all, measured 2026-09-04.

JPM_REAL = FundamentalSnapshot(
    revenue=182_447_000_000.0,
    gross_profit=None,                       # banks report none, by nature
    operating_income=72_595_000_000.0,       # they do report this
    cash_from_operations=-147_782_000_000.0,  # the loan book, not the business
    equity=362_438_000_000.0,
)


def test_a_bank_is_not_scored_on_a_measure_that_does_not_apply_to_banks():
    """SIC 6021 is a national commercial bank. -81% FCF margin is how much
    lending grew, not how much cash the business made, and it must not reach
    the score or the summary."""
    result = score_fundamentals(JPM_REAL, sic=6021)

    assert result.available is True, "a bank still has measurable capital efficiency"
    assert "FCF Margin" not in result.summary, result.summary
    assert result.detail["fcf_margin_scored"] is False
    assert result.detail["fcf_margin"] is not None, (
        "the figure was computed and stays reportable; it is only kept out of "
        "the score")


def test_the_rule_survives_an_alias_chain_learning_a_new_concept():
    """The regression, pinned. Operating income present is exactly the state
    that undid the previous rule; it must change nothing here."""
    with_oi = score_fundamentals(JPM_REAL, sic=6021)
    without_oi = score_fundamentals(
        FundamentalSnapshot(
            revenue=JPM_REAL.revenue,
            cash_from_operations=JPM_REAL.cash_from_operations,
            equity=JPM_REAL.equity,
        ),
        sic=6021,
    )
    assert "FCF Margin" not in with_oi.summary
    assert "FCF Margin" not in without_oi.summary


def test_an_ordinary_company_still_gets_its_cash_flow_scored():
    """The rule must not quietly disarm layer 1 for everyone else. SIC 7372 is
    prepackaged software."""
    result = score_fundamentals(snap("NVDA"), sic=3674)
    assert "FCF Margin" in result.summary, result.summary
    assert result.detail["fcf_margin_scored"] is True


def test_a_filer_sec_gives_no_sic_for_falls_back_to_the_conservative_rule():
    """With no idea what kind of business this is and no operating line at all,
    a cash-flow margin cannot be called comparable."""
    result = score_fundamentals(
        FundamentalSnapshot(revenue=1.0e9, cash_from_operations=-5.0e8), sic=None)
    assert result.available is False


def test_the_reason_the_eagle_reads_aloud_is_not_false_about_a_bank():
    """The whole point. Citigroup's card said "the business is burning cash",
    which is not true, and the voice layer speaks the clause verbatim."""
    from aethelark_trade.engine.verdict import verdict_line

    citi = FundamentalSnapshot(
        revenue=81_100_000_000.0,
        operating_income=19_828_000_000.0,
        cash_from_operations=-70_400_000_000.0,
        equity=208_100_000_000.0,
    )
    layer1 = score_fundamentals(citi, sic=6021)
    _, reason = verdict_line({"layer_1_fundamentals": layer1.score,
                              "layer_4_sector_relativity": 70.0})
    assert "burning cash" not in reason, reason
