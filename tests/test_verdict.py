"""Verdict banding and risk/reward asymmetry math."""
import pytest

from aethelark_trade.engine.scoring import asymmetry_ratio, verdict


@pytest.mark.parametrize(
    "score,expected",
    [
        (100, "BULLISH"), (84, "BULLISH"), (80, "BULLISH"),
        (79, "ACCUMULATE"), (60, "ACCUMULATE"),
        (59, "NEUTRAL"), (50, "NEUTRAL"), (40, "NEUTRAL"),
        (39, "CAUTION"), (20, "CAUTION"),
        (19, "BEARISH"), (0, "BEARISH"),
    ],
)
def test_verdict_bands(score, expected):
    assert verdict(score) == expected


def test_asymmetry_with_no_weak_layers_uses_irreducible_downside():
    """NVDA doc example: composite 84, weakest layer 51 (nothing below 50).
    Upside is 34 points over neutral; downside floors at the irreducible 10."""
    layers = {
        "layer_1_fundamentals": 82, "layer_2_macro_gravity": 51,
        "layer_3_news_velocity": 89, "layer_4_sector_relativity": 94,
        "layer_5_insider_conviction": 95, "layer_6_geopolitics": 62,
        "layer_7_supply_chain": 85,
    }
    assert asymmetry_ratio(84, layers) == pytest.approx(3.4, abs=0.05)


def test_weak_layers_drag_the_asymmetry_down():
    """Same composite, but two layers are broken -> downside widens, ratio falls."""
    layers = {
        "layer_1_fundamentals": 82, "layer_2_macro_gravity": 10,
        "layer_3_news_velocity": 89, "layer_4_sector_relativity": 94,
        "layer_5_insider_conviction": 95, "layer_6_geopolitics": 20,
        "layer_7_supply_chain": 85,
    }
    assert asymmetry_ratio(84, layers) < 1.5


def test_no_upside_yields_zero_asymmetry():
    assert asymmetry_ratio(45, {"layer_1_fundamentals": 45}) == 0.0
