"""Test Task 5: Layer 2 company sensitivity and Layer 6 exclusion from composite."""
import pytest

from aethelark_trade.engine.layers.macro import (
    CompanySensitivity,
    MacroProxies,
    resolve_company_sensitivity,
    score_macro_gravity,
)
from aethelark_trade.engine.scoring import LAYER_WEIGHTS, composite_score


def test_two_different_companies_receive_different_layer2_scores():
    """Two companies scored on the same day must not receive identical Layer 2
    scores unless their sensitivities happen to match."""
    proxies = MacroProxies(
        yield_10y=4.5,
        vix=20.0,
        dollar_index=104.0,
        copper_change_pct=1.0,
    )
    # JPM (financials, benefits from higher yields) vs NEE (utility, rate-sensitive bond proxy)
    sens_jpm = resolve_company_sensitivity("JPM")
    sens_nee = resolve_company_sensitivity("NEE")

    score_jpm = score_macro_gravity(proxies, sensitivity=sens_jpm)
    score_nee = score_macro_gravity(proxies, sensitivity=sens_nee)

    assert score_jpm.score != score_nee.score
    # When rates are high (4.5% > 4.0% neutral), financial should outperform utility
    assert score_jpm.score > score_nee.score


def test_layer_6_dropped_from_composite_and_weights_reallocated():
    """Layer 6 describes market-wide conditions, not a company ordering.
    It must be dropped from the per-company composite and remaining weights reallocated to 1.0."""
    assert "layer_6_geopolitics" not in LAYER_WEIGHTS
    assert sum(LAYER_WEIGHTS.values()) == pytest.approx(1.0)
    # Ensure remaining 6 layers are present
    expected_layers = {
        "layer_1_fundamentals",
        "layer_2_macro_gravity",
        "layer_3_news_velocity",
        "layer_4_sector_relativity",
        "layer_5_insider_conviction",
        "layer_7_supply_chain",
    }
    assert set(LAYER_WEIGHTS.keys()) == expected_layers
