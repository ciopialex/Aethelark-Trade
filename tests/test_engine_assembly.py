"""Engine assembly: layer scores -> the dashboard scorecard contract.

The output shape is pinned to docs/UI_STATES.md section 2.
"""
from datetime import date

import pytest

from aethelark_trade.engine.engine import assemble_result
from aethelark_trade.engine.liar_filter import check_liar_filter
from aethelark_trade.engine.types import LayerScore

CLEAN = check_liar_filter(50.0, [], as_of=date(2026, 8, 19))


def doc_layers():
    """The seven scores from the documented NVDA card."""
    raw = {
        "layer_1_fundamentals": (82, "73.8% Gross Margin • Strong EPS Beat"),
        "layer_2_macro_gravity": (51, "4.2% 10Y Yield Headwind"),
        "layer_3_news_velocity": (89, "+45% 15-min Sentiment Acceleration"),
        "layer_4_sector_relativity": (94, "+2.4σ Alpha vs SMH Semiconductor Index"),
        "layer_5_insider_conviction": (95, "Net Zero Selling • +$12.5M Executive Buys"),
        "layer_6_geopolitics": (62, "Neutral Supply Chain"),
        "layer_7_supply_chain": (85, "TSMC Tier-1 Prime Capacity Allocation"),
    }
    return {k: LayerScore(score=s, summary=t) for k, (s, t) in raw.items()}


FIVE_WORDS = {"ACCUMULATE", "WATCH", "NEUTRAL", "CAUTION", "AVOID"}


def test_assembles_the_documented_composite_and_verdict():
    """The composite is still the composite. The verdict is no longer a band
    derived from it — BEHAVIOR_SPEC §30.2 — so this asserts the vocabulary
    rather than the word the old score-band function would have produced."""
    result = assemble_result("NVDA", doc_layers(), CLEAN)
    assert result.composite_score == 85
    assert result.verdict in FIVE_WORDS
    assert result.verdict not in {"BULLISH", "BEARISH", "HOLD"}   # §30.1
    assert result.reason, "§30.3 — a verdict this decisive carries a reason"


def test_json_shape_matches_the_ui_states_contract():
    payload = assemble_result("NVDA", doc_layers(), CLEAN).to_dict()
    for key in ("ticker", "composite_score", "verdict", "asymmetry_ratio",
                "invalidation_level", "layers", "liar_filter_status", "dossier_path"):
        assert key in payload, f"missing {key}"
    assert set(payload["layers"]) == set(doc_layers())
    for layer in payload["layers"].values():
        assert set(layer) >= {"score", "summary"}


def test_asymmetry_is_rendered_as_a_ratio_string():
    payload = assemble_result("NVDA", doc_layers(), CLEAN).to_dict()
    assert payload["asymmetry_ratio"].endswith(" : 1")


def test_unavailable_layers_are_excluded_from_the_composite_but_still_reported():
    layers = doc_layers()
    layers["layer_3_news_velocity"] = LayerScore.unavailable("No recent headlines")
    result = assemble_result("NVDA", layers, CLEAN)
    payload = result.to_dict()
    # still rendered for the dashboard...
    assert payload["layers"]["layer_3_news_velocity"]["available"] is False
    # ...but excluded from the weighted composite, which must not equal the
    # value you would get by scoring the missing layer as 50.
    assert result.composite_score != 79
    # Coverage is weight-based, not a headcount: losing news velocity costs
    # its 0.13 weight, not 1/7 of the matrix.
    assert result.coverage == pytest.approx(0.87, abs=0.01)


def test_divergence_is_surfaced_in_the_payload():
    from aethelark_trade.engine.liar_filter import LiarFilterResult

    dirty = LiarFilterResult("DIVERGENCE", 92.0, -18_200_000.0, 7, "test divergence")
    payload = assemble_result("NVDA", doc_layers(), dirty).to_dict()
    assert payload["liar_filter_status"] == "DIVERGENCE"


def test_invalidation_level_is_reported_when_a_support_price_is_known():
    result = assemble_result("NVDA", doc_layers(), CLEAN, ema25=118.50)
    assert "118.50" in result.to_dict()["invalidation_level"]
