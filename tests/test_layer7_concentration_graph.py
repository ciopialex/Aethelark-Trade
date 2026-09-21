"""Tests for Task 7: Supply-Chain Contagion and SEC customer concentration graph.

Per docs/superpowers/specs/2026-09-03-supply-chain-graph-design.md:
- Extractor: parse XBRL customer concentration disclosures (CRUS 91/89/87% Apple; TenLargest produces no edge).
- Resolver: member tag to canonical counterparty and ticker.
- Direction convention: dependent -> counterparty.
- Absence reporting: company with no mapped dependencies reports unavailable, not 50.
- Scoring: commercial dependence and shock propagation.
"""
from datetime import date
import pytest

from aethelark_trade.engine.concentration import parse_concentration_facts
from aethelark_trade.engine.counterparty import resolve_counterparty
from aethelark_trade.engine.fetchers import build_supply_edges
from aethelark_trade.engine.layers.supply_chain import SupplyEdge, score_supply_chain


CRUS_XBRL_SNIPPET = """<?xml version="1.0" encoding="utf-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
             xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
             xmlns:us-gaap="http://fasb.org/us-gaap/2024"
             xmlns:crus="http://cirrus.com/20260328">

  <!-- FY2026 Apple 91% revenue -->
  <xbrli:context id="c-2026-apple-rev">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000772406</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="us-gaap:MajorCustomersAxis">crus:AppleIncMember</xbrldi:explicitMember>
        <xbrldi:explicitMember dimension="us-gaap:ConcentrationRiskByBenchmarkAxis">us-gaap:SalesRevenueNetMember</xbrldi:explicitMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:endDate>2026-03-28</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <us-gaap:ConcentrationRiskPercentage1 contextRef="c-2026-apple-rev">0.91</us-gaap:ConcentrationRiskPercentage1>

  <!-- FY2025 Apple 89% revenue -->
  <xbrli:context id="c-2025-apple-rev">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000772406</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="us-gaap:MajorCustomersAxis">crus:AppleIncMember</xbrldi:explicitMember>
        <xbrldi:explicitMember dimension="us-gaap:ConcentrationRiskByBenchmarkAxis">us-gaap:SalesRevenueNetMember</xbrldi:explicitMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:endDate>2025-03-29</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <us-gaap:ConcentrationRiskPercentage1 contextRef="c-2025-apple-rev">0.89</us-gaap:ConcentrationRiskPercentage1>

  <!-- FY2024 Apple 87% revenue -->
  <xbrli:context id="c-2024-apple-rev">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000772406</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="us-gaap:MajorCustomersAxis">crus:AppleIncMember</xbrldi:explicitMember>
        <xbrldi:explicitMember dimension="us-gaap:ConcentrationRiskByBenchmarkAxis">us-gaap:SalesRevenueNetMember</xbrldi:explicitMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:endDate>2024-03-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <us-gaap:ConcentrationRiskPercentage1 contextRef="c-2024-apple-rev">0.87</us-gaap:ConcentrationRiskPercentage1>

  <!-- Foxconn 39% accounts receivable -->
  <xbrli:context id="c-foxconn-ar">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000772406</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="us-gaap:MajorCustomersAxis">crus:FoxconnMember</xbrldi:explicitMember>
        <xbrldi:explicitMember dimension="us-gaap:ConcentrationRiskByBenchmarkAxis">us-gaap:AccountsReceivableMember</xbrldi:explicitMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:endDate>2026-03-28</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <us-gaap:ConcentrationRiskPercentage1 contextRef="c-foxconn-ar">0.39</us-gaap:ConcentrationRiskPercentage1>

  <!-- Aggregate disclosure: TenLargestCustomersMember 96% -->
  <xbrli:context id="c-aggregate-ten">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000772406</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="us-gaap:MajorCustomersAxis">crus:TenLargestCustomersMember</xbrldi:explicitMember>
        <xbrldi:explicitMember dimension="us-gaap:ConcentrationRiskByBenchmarkAxis">us-gaap:SalesRevenueNetMember</xbrldi:explicitMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:endDate>2026-03-28</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <us-gaap:ConcentrationRiskPercentage1 contextRef="c-aggregate-ten">0.96</us-gaap:ConcentrationRiskPercentage1>

</xbrli:xbrl>
"""


def test_extractor_parses_crus_facts_and_separates_aggregate():
    """Verify ASC 280 customer concentration facts from CRUS 10-K fixture."""
    res = parse_concentration_facts(CRUS_XBRL_SNIPPET, accession="0000772406-26-000018")
    facts = res.facts
    assert len(facts) == 4

    apple_facts = [f for f in facts if "Apple" in f.counterparty_tag]
    assert len(apple_facts) == 3
    apple_pcts = sorted([f.pct for f in apple_facts])
    assert apple_pcts == [0.87, 0.89, 0.91]

    foxconn_facts = [f for f in facts if "Foxconn" in f.counterparty_tag]
    assert len(foxconn_facts) == 1
    assert foxconn_facts[0].pct == 0.39
    assert foxconn_facts[0].risk_type == "receivable"

    # TenLargestCustomersMember must produce NO edge, only aggregate figure
    assert all("TenLargest" not in f.counterparty_tag for f in facts)
    assert res.aggregate_concentration == 0.96


def test_counterparty_resolver():
    """Verify resolution of member tags to tickers and names."""
    c_apple = resolve_counterparty("crus:AppleIncMember")
    assert c_apple.name == "Apple Inc"
    assert c_apple.ticker == "AAPL"
    assert c_apple.confidence == 1.0

    c_foxconn = resolve_counterparty("crus:FoxconnMember")
    assert "Foxconn" in c_foxconn.name
    assert c_foxconn.ticker is None  # Retained as unlisted node
    assert c_foxconn.confidence >= 0.8

    c_luxshare = resolve_counterparty("crus:LuxshareMember")
    assert "Luxshare" in c_luxshare.name
    assert c_luxshare.ticker is None
    assert c_luxshare.confidence >= 0.8

    c_ambiguous = resolve_counterparty("crus:CustomerAMember")
    assert c_ambiguous.ticker is None
    assert c_ambiguous.confidence < 0.5


def test_direction_convention_in_seeded_dataset():
    """Property test: every stored edge is (dependent, counterparty, kind, weight).

    Weight must represent the fraction of dependent's business attributable to
    counterparty.

    The seed dataset is a script in the operator's private repository, not part
    of this module. Layer 7 is not wired to a data source here (see CLAUDE.md),
    so the dataset is absent and this property has nothing to check against.
    Skipped rather than deleted: it is the convention any future loader must
    satisfy, and it runs as soon as one exists on the path.
    """
    seed = pytest.importorskip(
        "seed_svi", reason="no supply-chain seed dataset in this repository")

    for ticker, edges in seed.REAL_SUPPLY_CHAIN_EDGES.items():
        for edge in edges:
            assert edge["source"] == ticker
            assert 0.0 < edge["weight"] <= 1.0
            assert edge["type"] in ("customer_revenue", "customer_ar", "supplier", "assembler", "partner", "infrastructure")


def test_absence_reporting_when_no_edges():
    """A company with no mapped dependencies must report absence, NOT 50, NOT price momentum."""
    empty_edges = build_supply_edges("UNMAPPED_TICKER")
    assert empty_edges == []
    score_res = score_supply_chain(empty_edges)
    assert score_res.available is False
    assert "No supply-chain dependencies mapped" in score_res.summary


def test_crus_graph_health_and_concentration_summary():
    """CRUS has 91% concentration on AAPL; when AAPL is quiet, Layer 7 scores 50
    with an explicit summary.

    This reads seeded rows out of supply_chain_edges. Nothing in this module
    writes that table -- the loader lives in the operator's private repository
    -- so on a clean install the graph is empty and there is nothing to score.
    Skipped rather than deleted: it is the contract a future loader has to
    meet, and it starts running the moment one populates the table.
    """
    crus_edges = build_supply_edges("CRUS")
    if not crus_edges:
        pytest.skip("supply_chain_edges is empty; layer 7 has no loader here")
    assert len(crus_edges) >= 3
    assert any(e.counterparty == "AAPL" and e.weight == 0.91 for e in crus_edges)

    score_res = score_supply_chain(crus_edges)
    assert score_res.available is True
    assert score_res.score == 50
    assert "91% of revenue from AAPL" in score_res.summary
    assert "AAPL quiet" in score_res.summary


def test_counterparty_shock_propagates():
    """When a sole or dominant dependency faces distress, the score falls below 35."""
    distressed_edges = [
        SupplyEdge(counterparty="AAPL", relationship_type="customer_revenue",
                   weight=0.91, health=0.1, attested=True, confidence=1.0)
    ]
    res = score_supply_chain(distressed_edges)
    assert res.available is True
    assert res.score <= 20
    assert "AAPL constrained" in res.summary
