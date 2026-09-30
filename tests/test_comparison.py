"""Slice 2 -- head-to-head 7-layer comparison."""
from datetime import date

import pytest

from aethelark_trade.engine.comparison import compare_results
from aethelark_trade.engine.engine import assemble_result
from aethelark_trade.engine.liar_filter import check_liar_filter
from aethelark_trade.engine.types import LayerScore

from aethelark_trade.engine.scoring import LAYER_WEIGHTS

CLEAN = check_liar_filter(50.0, [], as_of=date(2026, 8, 19))
NAMES = tuple(LAYER_WEIGHTS.keys())


def result(ticker, **scores):
    layers = {n: LayerScore(score=scores.get(n, 50), summary=f"{n}") for n in NAMES}
    return assemble_result(ticker, layers, CLEAN)


def test_higher_composite_wins():
    cmp = compare_results(result("NVDA", layer_1_fundamentals=90),
                          result("INTC", layer_1_fundamentals=30))
    assert cmp.winner == "NVDA"
    assert cmp.margin > 0


def test_margin_is_the_absolute_composite_gap():
    a, b = result("NVDA", layer_1_fundamentals=90), result("INTC", layer_1_fundamentals=30)
    cmp = compare_results(a, b)
    assert cmp.margin == abs(a.composite_score - b.composite_score)


def test_every_layer_is_diffed():
    cmp = compare_results(result("NVDA"), result("INTC"))
    assert [d.layer for d in cmp.layer_diffs] == list(NAMES)


def test_layer_delta_is_a_minus_b_and_names_the_layer_winner():
    cmp = compare_results(result("NVDA", layer_5_insider_conviction=80),
                          result("INTC", layer_5_insider_conviction=20))
    diff = next(d for d in cmp.layer_diffs if d.layer == "layer_5_insider_conviction")
    assert diff.delta == 60
    assert diff.winner == "NVDA"


def test_a_tied_layer_has_no_winner():
    cmp = compare_results(result("NVDA"), result("INTC"))
    assert all(d.winner is None for d in cmp.layer_diffs)
    assert cmp.layers_won_a == 0 and cmp.layers_won_b == 0


def test_layers_won_are_counted_per_side():
    cmp = compare_results(
        result("NVDA", layer_1_fundamentals=90, layer_5_insider_conviction=80),
        result("INTC", layer_4_sector_relativity=95),
    )
    assert cmp.layers_won_a == 2
    assert cmp.layers_won_b == 1


def test_a_layer_unavailable_on_one_side_is_not_a_win():
    a = result("NVDA")
    a.layers["layer_3_news_velocity"] = LayerScore.unavailable("no headlines")
    cmp = compare_results(a, result("INTC", layer_3_news_velocity=90))
    diff = next(d for d in cmp.layer_diffs if d.layer == "layer_3_news_velocity")
    assert diff.delta is None
    assert diff.winner is None


def test_comparison_serialises_for_the_module_bus():
    payload = compare_results(result("NVDA"), result("INTC")).to_dict()
    for key in ("ticker_a", "ticker_b", "winner", "margin", "layers"):
        assert key in payload
    assert len(payload["layers"]) == len(NAMES)
