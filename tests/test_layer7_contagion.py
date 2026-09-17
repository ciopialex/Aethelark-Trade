"""Layer 7 -- Supply-Chain Contagion from supplier and input-cost momentum."""
import pytest

from aethelark_trade.engine.layers.supply_chain import (
    INPUT_COST,
    MOMENTUM_SATURATION_PCT,
    SUPPLIER,
    SupplyEdge,
    health_from_momentum,
    score_supply_chain,
)


def test_a_strengthening_supplier_is_healthy():
    """TSM rallying means foundry capacity and pricing power are intact."""
    assert health_from_momentum(+20.0, SUPPLIER) > 0.8


def test_a_collapsing_supplier_is_unhealthy():
    assert health_from_momentum(-20.0, SUPPLIER) < 0.2


def test_rising_input_costs_are_unhealthy_for_the_buyer():
    """Copper up 20% is margin pressure for whoever has to buy it."""
    assert health_from_momentum(+20.0, INPUT_COST) < 0.2


def test_falling_input_costs_are_healthy_for_the_buyer():
    assert health_from_momentum(-20.0, INPUT_COST) > 0.8


def test_supplier_and_input_cost_respond_in_opposite_directions():
    assert health_from_momentum(+10.0, SUPPLIER) > 0.5
    assert health_from_momentum(+10.0, INPUT_COST) < 0.5


def test_flat_momentum_is_neutral_for_both_kinds():
    assert health_from_momentum(0.0, SUPPLIER) == pytest.approx(0.5)
    assert health_from_momentum(0.0, INPUT_COST) == pytest.approx(0.5)


def test_health_is_bounded():
    for pct in (-500.0, 500.0):
        for kind in (SUPPLIER, INPUT_COST):
            assert 0.0 <= health_from_momentum(pct, kind) <= 1.0


def test_saturation_is_documented():
    assert MOMENTUM_SATURATION_PCT > 0


def test_layer_reflects_momentum_derived_health():
    """A ticker whose foundry is rallying and whose inputs are cheapening
    must outscore one facing the reverse."""
    good = [SupplyEdge("TSM", SUPPLIER, health_from_momentum(+15.0, SUPPLIER), 2.0),
            SupplyEdge("HG=F", INPUT_COST, health_from_momentum(-10.0, INPUT_COST))]
    bad = [SupplyEdge("TSM", SUPPLIER, health_from_momentum(-15.0, SUPPLIER), 2.0),
           SupplyEdge("HG=F", INPUT_COST, health_from_momentum(+10.0, INPUT_COST))]
    assert score_supply_chain(good).score > score_supply_chain(bad).score
    assert score_supply_chain(good).score != 50


def test_critical_supplier_outweighs_a_minor_input():
    """Criticality is the point: NVDA cannot swap foundries, it can hedge copper."""
    edges = [SupplyEdge("TSM", SUPPLIER, 0.1, criticality=3.0),
             SupplyEdge("HG=F", INPUT_COST, 0.9, criticality=0.5)]
    assert score_supply_chain(edges).score < 40
