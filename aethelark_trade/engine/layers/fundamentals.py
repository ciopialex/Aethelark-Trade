"""Layer 1 -- Fundamentals, sourced from SEC XBRL companyfacts.

docs/FACTS.md lists aethelark_trade/xbrl.py as the 10-K/10-Q parser, but that
module actually parses DEF 14A proxy statements (extract_proxy_xbrl). Company
financials therefore come from the SEC's companyfacts API, which is the same
dataset the Slice 3 bulk hydrator caches locally.

Filers do not agree on which US-GAAP concept holds a given line item, and a
company's choice drifts over time (NVDA's capex moved off
PaymentsToAcquirePropertyPlantAndEquipment after FY2012). Every field is
resolved through an ordered alias chain, first hit wins.
"""

from dataclasses import dataclass
from datetime import date

from aethelark_trade.engine.types import LayerScore

ANNUAL_FORMS = ("10-K", "20-F", "40-F")

# Ordered alias chains: most specific / most common first.
CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "Revenue",
        "RevenueFromContractsWithCustomers",
    ),
    "gross_profit": (
        "GrossProfit",
        "GrossProfitLoss",
    ),
    "cost_of_revenue": (
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
        "CostOfSales",
    ),
    "operating_income": (
        "OperatingIncomeLoss",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxes",
        "ProfitLossFromOperatingActivities",
        "OperatingProfit",
    ),
    "net_income": (
        "NetIncomeLoss",
        "ProfitLoss",
    ),
    "cash_from_operations": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        "CashFlowsFromUsedInOperatingActivities",
    ),
    "capex": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquirePropertyPlantAndEquipmentAndIntangibleAssets",
        "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        "PurchaseOfPropertyPlantAndEquipment",
    ),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "CommonStockholdersEquity",
        "Equity",
        "EquityAttributableToOwnersOfParent",
    ),
    "long_term_debt": (
        "LongTermDebtNoncurrent",
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
        "NoncurrentBorrowings",
        "BorrowingsNoncurrent",
        "LongTermBorrowings",
    ),
}

# Flat statutory rate for the NOPAT leg of ROIC. Effective rates swing on
# one-off items; a constant keeps the layer comparable across names.
ASSUMED_TAX_RATE = 0.21

# An annual period must span most of a year -- guards against a 10-K that also
# carries quarterly contexts under the same concept.
MIN_ANNUAL_DAYS = 300


@dataclass(frozen=True)
class FundamentalSnapshot:
    fiscal_year_end: date | None = None
    revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    cash_from_operations: float | None = None
    capex: float | None = None
    equity: float | None = None
    long_term_debt: float | None = None
    prior_revenue: float | None = None
    prior_gross_profit: float | None = None

    @property
    def gross_margin(self) -> float | None:
        if not self.revenue or self.gross_profit is None:
            return None
        return self.gross_profit / self.revenue

    @property
    def prior_gross_margin(self) -> float | None:
        if not self.prior_revenue or self.prior_gross_profit is None:
            return None
        return self.prior_gross_profit / self.prior_revenue

    @property
    def gross_margin_delta_pp(self) -> float | None:
        now, prior = self.gross_margin, self.prior_gross_margin
        if now is None or prior is None:
            return None
        return (now - prior) * 100.0

    @property
    def free_cash_flow(self) -> float | None:
        if self.cash_from_operations is None:
            return None
        return self.cash_from_operations - (self.capex or 0.0)

    @property
    def fcf_margin(self) -> float | None:
        fcf = self.free_cash_flow
        if fcf is None or not self.revenue:
            return None
        return fcf / self.revenue

    @property
    def roic(self) -> float | None:
        if self.operating_income is None:
            return None
        invested = (self.equity or 0.0) + (self.long_term_debt or 0.0)
        if invested <= 0:
            return None
        return (self.operating_income * (1 - ASSUMED_TAX_RATE)) / invested


def _annual_series(gaap: dict, concept: str) -> dict[str, float]:
    """{period_end_iso: value} for full-year facts of one concept."""
    node = gaap.get(concept)
    if not node:
        return {}
    series: dict[str, float] = {}
    for entries in node.get("units", {}).values():
        for e in entries:
            if e.get("form") not in ANNUAL_FORMS or e.get("fp") != "FY":
                continue
            start = e.get("start")
            if start:  # flow concept: require a full-year span
                span = (date.fromisoformat(e["end"]) - date.fromisoformat(start)).days
                if span < MIN_ANNUAL_DAYS:
                    continue
            series[e["end"]] = float(e["val"])
    return series


def _resolve(gaap: dict, field: str) -> dict[str, float]:
    """Merge the alias chain period-by-period, earlier aliases winning.

    Resolving whole-series-first is wrong: a concept a filer abandoned years
    ago still has *some* data, so it would shadow the concept they actually
    use today and silently yield None for the current year.
    """
    merged: dict[str, float] = {}
    for concept in reversed(CONCEPTS[field]):
        merged.update(_annual_series(gaap, concept))
    return merged


def extract_fundamentals(companyfacts: dict) -> FundamentalSnapshot:
    """Build a snapshot of the latest filed fiscal year plus the prior one."""
    facts = companyfacts.get("facts", {})
    gaap = dict(facts.get("us-gaap", {}))
    for k, v in facts.get("ifrs-full", {}).items():
        gaap.setdefault(k, v)

    resolved = {field: _resolve(gaap, field) for field in CONCEPTS}

    revenue_series = resolved["revenue"]
    if not revenue_series:
        return FundamentalSnapshot()

    periods = sorted(revenue_series)
    latest = periods[-1]
    prior = periods[-2] if len(periods) > 1 else None

    def at(field: str, period: str | None) -> float | None:
        if period is None:
            return None
        return resolved[field].get(period)

    gp = at("gross_profit", latest)
    if gp is None and at("revenue", latest) is not None and at("cost_of_revenue", latest) is not None:
        gp = at("revenue", latest) - at("cost_of_revenue", latest)

    prior_gp = at("gross_profit", prior)
    if prior_gp is None and at("revenue", prior) is not None and at("cost_of_revenue", prior) is not None:
        prior_gp = at("revenue", prior) - at("cost_of_revenue", prior)

    return FundamentalSnapshot(
        fiscal_year_end=date.fromisoformat(latest),
        revenue=at("revenue", latest),
        gross_profit=gp,
        operating_income=at("operating_income", latest),
        cash_from_operations=at("cash_from_operations", latest),
        capex=at("capex", latest),
        equity=at("equity", latest),
        long_term_debt=at("long_term_debt", latest),
        prior_revenue=at("revenue", prior),
        prior_gross_profit=prior_gp,
    )


# Sub-metric saturation points: the value at which a metric is ~76% of the way
# to its extreme. Chosen from what "great" looks like for a US large cap.
FCF_MARGIN_SATURATION = 0.25    # 25% free cash flow margin
ROIC_SATURATION = 0.20          # 20% return on invested capital
GM_DELTA_SATURATION_PP = 5.0    # 5pp of year-over-year gross margin move

# Cash conversion leads, capital efficiency follows, trend breaks the tie.
SUBMETRIC_WEIGHTS = {"fcf_margin": 0.40, "roic": 0.35, "gm_delta": 0.25}

#: SIC 6000-6799 is finance, insurance and real estate. For these filers cash
#: from operations is dominated by the loan book, the deposit base and trading
#: flows, so free cash flow margin measures how much lending grew this year and
#: not how much cash the business generates. Measured 2026-09-04 on the same
#: fiscal year: Citigroup -87.0%, JPMorgan -81.0%, American Express +38.7%.
#: Those three numbers do not rank three businesses, and the sentence the
#: engine built from them -- "the business is burning cash" about Citigroup --
#: is false.
FINANCIAL_SIC_MIN, FINANCIAL_SIC_MAX = 6000, 6799


def is_financial_filer(sic: int | None) -> bool:
    """Whether cash-flow margin is a meaningless measure for this filer."""
    return sic is not None and FINANCIAL_SIC_MIN <= sic <= FINANCIAL_SIC_MAX


def _saturating(value: float, scale: float) -> float:
    """Map an unbounded metric onto 0-100 with 50 as neutral."""
    import math

    return 50 + 50 * math.tanh(value / scale)


def score_fundamentals(
    snapshot: FundamentalSnapshot,
    market_cap: float | None = None,
    sic: int | None = None,
) -> LayerScore:
    """Score business quality: cash conversion, capital efficiency, margin trend.

    ``market_cap`` only adds the free-cash-flow yield to ``detail`` for the
    leaderboard's value leg. It deliberately does not move the score: Layer 1
    judges the business, not the price the market puts on it.

    ``sic`` decides whether free cash flow margin is a measure of this business
    at all. For a bank it is not, and the submetric is dropped rather than the
    whole layer: ROIC and the margin trend still mean what they say, the
    weights renormalise over what is left, and JPMorgan is scored on capital
    efficiency instead of on how much it lent this year.

    This keys on what kind of filer it is, not on which XBRL concepts happen to
    be absent. The previous rule -- both gross profit and operating income
    missing -- was undone without anyone noticing when the alias chain learned
    a concept banks do file, and the false sentence came straight back.
    """
    parts: dict[str, float] = {}
    fcf_is_meaningful = not is_financial_filer(sic)

    if snapshot.fcf_margin is not None and fcf_is_meaningful:
        parts["fcf_margin"] = _saturating(snapshot.fcf_margin, FCF_MARGIN_SATURATION)
    if snapshot.roic is not None:
        parts["roic"] = _saturating(snapshot.roic, ROIC_SATURATION)
    if snapshot.gross_margin_delta_pp is not None:
        parts["gm_delta"] = _saturating(
            snapshot.gross_margin_delta_pp, GM_DELTA_SATURATION_PP
        )

    if not parts:
        return LayerScore.unavailable("No XBRL fundamentals available")

    # Backstop for a filer SEC gives no SIC for: with no idea what kind of
    # business this is and no operating line of any sort, a cash-flow margin
    # cannot be said to be comparable. Where the SIC is known it decides, and
    # this does not fire.
    if sic is None and snapshot.gross_profit is None and snapshot.operating_income is None:
        return LayerScore.unavailable(
            "Operating income and gross profit unavailable; cash-flow margin not comparable"
        )

    weight_total = sum(SUBMETRIC_WEIGHTS[k] for k in parts)
    score = sum(SUBMETRIC_WEIGHTS[k] * v for k, v in parts.items()) / weight_total
    score = max(0, min(100, round(score)))

    bits = []
    if snapshot.gross_margin is not None:
        bits.append(f"{snapshot.gross_margin:.1%} Gross Margin")
    if snapshot.gross_margin_delta_pp is not None:
        bits.append(f"{snapshot.gross_margin_delta_pp:+.1f}pp YoY")
    if snapshot.fcf_margin is not None and fcf_is_meaningful:
        bits.append(f"{snapshot.fcf_margin:.1%} FCF Margin")
    if snapshot.roic is not None:
        bits.append(f"{snapshot.roic:.1%} ROIC")

    detail = {
        "fiscal_year_end": (
            snapshot.fiscal_year_end.isoformat() if snapshot.fiscal_year_end else None
        ),
        "revenue": snapshot.revenue,
        "gross_margin": snapshot.gross_margin,
        "gross_margin_delta_pp": snapshot.gross_margin_delta_pp,
        "fcf_margin": snapshot.fcf_margin,
        # The figure is still reported -- it was computed and it is real -- but
        # a consumer must be able to tell that it was kept out of the score.
        "fcf_margin_scored": fcf_is_meaningful and snapshot.fcf_margin is not None,
        "roic": snapshot.roic,
    }

    fcf = snapshot.free_cash_flow
    if market_cap and fcf is not None:
        detail["fcf_yield_pct"] = round(fcf / market_cap * 100.0, 4)

    return LayerScore(score=score, summary=" • ".join(bits), detail=detail)
