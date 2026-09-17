"""Layer 6 -- Macro Regime Stress from live market proxies.

Replaces the GDELT path: geo_pulse's daemon has never run, so the layer was
permanently unavailable. Volatility and the 10Y-2Y curve are always priced.
"""
import pytest

from aethelark_trade.engine.layers.geopolitics import (
    CURVE_NEUTRAL_SPREAD,
    RegimeProxies,
    curve_spread,
    score_macro_regime,
)


def test_unavailable_without_any_proxy():
    assert score_macro_regime(RegimeProxies()).available is False


def test_curve_spread_is_ten_year_minus_two_year():
    assert curve_spread(RegimeProxies(yield_10y=4.706, yield_2y=4.170)) == \
        pytest.approx(0.536, abs=1e-9)


def test_curve_spread_is_none_without_both_legs():
    assert curve_spread(RegimeProxies(yield_10y=4.7)) is None


def test_inverted_curve_and_panic_vol_is_a_stressed_regime():
    stressed = RegimeProxies(vix=38.0, yield_10y=3.6, yield_2y=4.9)  # -1.3 inverted
    assert score_macro_regime(stressed).score < 30


def test_steep_curve_and_calm_vol_is_a_benign_regime():
    benign = RegimeProxies(vix=12.0, yield_10y=4.8, yield_2y=2.6)  # +2.2 steep
    assert score_macro_regime(benign).score > 70


def test_inversion_is_scored_worse_than_a_flat_curve_at_equal_vol():
    flat = RegimeProxies(vix=18.0, yield_10y=4.0, yield_2y=4.0)
    inverted = RegimeProxies(vix=18.0, yield_10y=4.0, yield_2y=5.0)
    assert score_macro_regime(inverted).score < score_macro_regime(flat).score


def test_scores_on_vix_alone_when_the_curve_is_missing():
    result = score_macro_regime(RegimeProxies(vix=12.0))
    assert result.available is True
    assert result.score > 50


def test_current_market_reading_is_not_extreme():
    """Measured 2026-08-19: VIX 15.84, 10Y 4.706, 2Y 4.170."""
    result = score_macro_regime(RegimeProxies(vix=15.84, yield_10y=4.706, yield_2y=4.170))
    assert 40 <= result.score <= 75
    assert "0.54" in result.summary


def test_neutral_spread_anchor_is_documented():
    assert 0.0 <= CURVE_NEUTRAL_SPREAD <= 1.5


def test_bounded_under_extremes():
    for p in (RegimeProxies(vix=200.0, yield_10y=0.1, yield_2y=9.0),
              RegimeProxies(vix=1.0, yield_10y=9.0, yield_2y=0.1)):
        assert 0 <= score_macro_regime(p).score <= 100
