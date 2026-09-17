"""Layers 2, 3, 4, 6, 7 -- pure scoring math."""
from datetime import date, datetime, timedelta, timezone

import pytest

from aethelark_trade.engine.layers.macro import MacroProxies, score_macro_gravity
from aethelark_trade.engine.layers.news_velocity import Headline, score_news_velocity
from aethelark_trade.engine.layers.sector_relativity import score_sector_relativity
from aethelark_trade.engine.layers.supply_chain import SupplyEdge, score_supply_chain

NOW = datetime(2026, 8, 19, 15, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- Layer 2
def test_macro_unavailable_when_no_proxies():
    assert score_macro_gravity(MacroProxies()).available is False


def test_falling_yields_and_calm_vol_are_a_tailwind():
    easy = MacroProxies(yield_10y=3.2, vix=12.0, dollar_index=98.0, copper_change_pct=2.0)
    assert score_macro_gravity(easy).score > 60


def test_high_yields_and_panic_vol_are_a_headwind():
    tight = MacroProxies(yield_10y=6.5, vix=42.0, dollar_index=115.0, copper_change_pct=-5.0)
    assert score_macro_gravity(tight).score < 40


def test_documented_ten_year_headwind_lands_near_the_doc_value():
    """docs/UI_STATES.md renders '4.2% 10Y Yield Headwind' at score 51."""
    result = score_macro_gravity(MacroProxies(yield_10y=4.2, vix=18.0))
    assert 40 <= result.score <= 62
    assert "4.2" in result.summary


# ---------------------------------------------------------------- Layer 3
def test_news_unavailable_with_no_headlines():
    assert score_news_velocity([], now=NOW).available is False


def test_bullish_recent_headlines_score_high():
    heads = [
        Headline("Company beats earnings, raises guidance, record profit surge",
                 NOW - timedelta(minutes=5), "Reuters"),
        Headline("Analysts upgrade on strong growth and expanding margins",
                 NOW - timedelta(minutes=10), "Bloomberg"),
    ]
    assert score_news_velocity(heads, now=NOW).score > 60


def test_bearish_headlines_score_low():
    heads = [
        Headline("Company misses estimates, cuts guidance amid weak demand",
                 NOW - timedelta(minutes=5), "Reuters"),
        Headline("Probe launched into accounting fraud, shares plunge",
                 NOW - timedelta(minutes=8), "Bloomberg"),
    ]
    assert score_news_velocity(heads, now=NOW).score < 40


def test_fresh_news_outweighs_stale_news_of_equal_tone():
    """Velocity is the point: a 5-minute-old beat matters more than a 3-day-old one."""
    text = "Company beats earnings and raises guidance on record profit"
    fresh = [Headline(text, NOW - timedelta(minutes=5), "Reuters")]
    stale = [Headline(text, NOW - timedelta(days=3), "Reuters")]
    assert score_news_velocity(fresh, now=NOW).score > score_news_velocity(stale, now=NOW).score


def test_sentiment_pct_is_exposed_for_the_liar_filter():
    heads = [Headline("record profit surge beats raises guidance upgrade",
                      NOW - timedelta(minutes=5), "Reuters")]
    result = score_news_velocity(heads, now=NOW)
    assert 0.0 <= result.detail["sentiment_pct"] <= 100.0


# ---------------------------------------------------------------- Layer 4
def test_relativity_needs_both_series():
    assert score_sector_relativity([1.0, 2.0], [], sector_etf="XLK").available is False


def test_outperforming_the_sector_scores_above_neutral():
    days = 60
    stock = [100 * (1.004 ** i) for i in range(days)]   # +0.4%/day
    sector = [100 * (1.001 ** i) for i in range(days)]  # +0.1%/day
    result = score_sector_relativity(stock, sector, sector_etf="XLK")
    assert result.available is True
    assert result.score > 55
    assert result.detail["alpha_z"] > 0


def test_underperforming_the_sector_scores_below_neutral():
    days = 60
    stock = [100 * (0.997 ** i) for i in range(days)]
    sector = [100 * (1.002 ** i) for i in range(days)]
    assert score_sector_relativity(stock, sector, sector_etf="XLK").score < 45


def test_identical_series_is_exactly_neutral():
    series = [100 * (1.002 ** i) for i in range(60)]
    result = score_sector_relativity(series, list(series), sector_etf="XLK")
    assert result.score == 50


# Layer 6 now lives in tests/test_layer6_regime.py (market-proxy regime,
# replacing the never-populated GDELT path).


# ---------------------------------------------------------------- Layer 7
def test_supply_chain_unavailable_without_edges():
    assert score_supply_chain([]).available is False


def test_disrupted_suppliers_drag_the_score_down():
    healthy = [SupplyEdge("TSM", "supplier", 0.9), SupplyEdge("ASML", "supplier", 0.85)]
    broken = [SupplyEdge("TSM", "supplier", 0.15), SupplyEdge("ASML", "supplier", 0.2)]
    assert score_supply_chain(healthy).score > score_supply_chain(broken).score


def test_supply_chain_bounded_and_reports_edge_count():
    result = score_supply_chain([SupplyEdge("TSM", "supplier", 0.9)])
    assert 0 <= result.score <= 100
    assert result.detail["edge_count"] == 1


# ------------------------------------------------- Layer 3 source trust
def test_official_wire_outweighs_a_blog_of_identical_tone():
    """A PR Newswire release is a company statement; a Motley Fool post is an
    opinion. Same words, different evidentiary weight."""
    from aethelark_trade.engine.layers.news_velocity import headline_tone

    text = "Company announces record contract award and strong buyback"
    assert headline_tone(text, "PR Newswire") > headline_tone(text, "Motley Fool")


def test_clickbait_is_discounted():
    from aethelark_trade.engine.layers.news_velocity import headline_tone

    plain = headline_tone("Company posts record profit", "Reuters")
    bait = headline_tone("Is this record profit stock about to explode?", "Reuters")
    assert abs(bait) < abs(plain)


def test_neutral_headline_has_zero_tone():
    from aethelark_trade.engine.layers.news_velocity import headline_tone

    assert headline_tone("Company schedules its annual meeting", "Reuters") == 0.0
