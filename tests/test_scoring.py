"""Pure-math tests for the 7-layer composite scoring core.

Zero mocks: these exercise real functions with real numeric inputs.
"""
import pytest

from aethelark_trade.engine.scoring import (
    LAYER_WEIGHTS,
    composite_score,
)


def test_layer_weights_sum_to_one():
    assert sum(LAYER_WEIGHTS.values()) == pytest.approx(1.0)


def test_composite_reproduces_documented_nvda_example():
    """docs/UI_STATES.md section 2 gives layer scores; with Layer 6 dropped
    from the per-company composite, composite is 85."""
    layers = {
        "layer_1_fundamentals": 82,
        "layer_2_macro_gravity": 51,
        "layer_3_news_velocity": 89,
        "layer_4_sector_relativity": 94,
        "layer_5_insider_conviction": 95,
        "layer_6_geopolitics": 62,
        "layer_7_supply_chain": 85,
    }
    assert composite_score(layers) == 85


def test_composite_renormalizes_when_layers_are_unavailable():
    """A layer with no data must not be scored as zero - it drops out and the
    remaining weights renormalize. Here only L1 and L5 are available."""
    layers = {"layer_1_fundamentals": 80, "layer_5_insider_conviction": 90}
    # weights 0.24 and 0.26 renormalize to 0.48 / 0.52
    # 80*0.48 + 90*0.52 = 85.2 -> 85
    assert composite_score(layers) == 85


def test_composite_of_no_available_layers_is_neutral_fifty():
    assert composite_score({}) == 50


def test_composite_rejects_unknown_layer_name():
    with pytest.raises(KeyError):
        composite_score({"layer_8_astrology": 99})
