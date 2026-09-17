"""Layer 7 -- Supply-Chain Contagion.

docs/FACTS.md describes supply_chain.py as an adjacency matrix; it is actually
an async Crawlee discovery engine that writes rows into the supply_chain_edges
table. This layer scores the resolved graph: a company is only as healthy as
the suppliers it cannot replace.
"""

from dataclasses import dataclass

from aethelark_trade.engine.types import LayerScore

# Edge kinds. The distinction matters because momentum means opposite things:
# a supplier's equity rallying is capacity and solvency you can rely on, while
# an input commodity rallying is margin coming out of your own P&L.
SUPPLIER = "supplier"
INPUT_COST = "input_cost"

# Percentage move over the lookback at which an edge is fully healthy or fully
# stressed. Commodities and single-name suppliers both routinely move 20% a
# quarter, so that is where the signal should be saturated rather than linear.
MOMENTUM_SATURATION_PCT = 20.0


def health_from_momentum(pct_change: float, kind: str) -> float:
    """Map an edge's momentum onto health in [0, 1], 0.5 being neutral."""
    normalised = max(-1.0, min(1.0, pct_change / MOMENTUM_SATURATION_PCT))
    if kind == INPUT_COST:
        normalised = -normalised
    return 0.5 + 0.5 * normalised


@dataclass(frozen=True)
class SupplyEdge:
    """One dependency in the commercial graph."""

    counterparty: str
    relationship_type: str = "supplier"
    health: float = 0.5
    criticality: float = 1.0
    weight: float = 1.0
    attested: bool = False
    confidence: float = 1.0
    period_end: str = ""


def score_supply_chain(edges: list[SupplyEdge]) -> LayerScore:
    """Criticality-weighted health of the commercial graph."""
    usable = [e for e in edges if (e.criticality > 0 and e.weight > 0)]
    if not usable:
        return LayerScore.unavailable("No supply-chain dependencies mapped")

    def effective_weight(e: SupplyEdge) -> float:
        attest_mult = 1.0 if e.attested else 0.8
        return max(e.weight, e.criticality) * e.confidence * attest_mult

    weight_total = sum(effective_weight(e) for e in usable)
    health = sum(e.health * effective_weight(e) for e in usable) / max(weight_total, 1e-6)
    score = max(0, min(100, round(health * 100)))

    weakest = min(usable, key=lambda e: e.health)
    highest_weight_edge = max(usable, key=lambda e: e.weight)

    if weakest.health < 0.35:
        summary = (
            f"{weakest.counterparty} constrained ({weakest.health:.0%} capacity) "
            f"across {len(usable)} mapped dependencies"
        )
    elif highest_weight_edge.weight >= 0.20 and abs(highest_weight_edge.health - 0.5) < 0.15:
        summary = (
            f"{highest_weight_edge.weight:.0%} of revenue from {highest_weight_edge.counterparty}; "
            f"{highest_weight_edge.counterparty} quiet ({len(usable)} mapped dependencies)"
        )
    else:
        summary = (
            f"{health:.0%} weighted upstream capacity across "
            f"{len(usable)} mapped dependencies"
        )

    return LayerScore(
        score=score,
        summary=summary,
        detail={
            "edge_count": len(usable),
            "weighted_health": round(health, 4),
            "weakest_link": weakest.counterparty,
            "max_concentration": round(highest_weight_edge.weight, 4),
            "dominant_counterparty": highest_weight_edge.counterparty,
        },
    )
