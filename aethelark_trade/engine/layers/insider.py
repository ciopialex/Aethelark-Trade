"""Layer 5 -- Insider Conviction, scored on a three-tier normalization curve.

Buying and selling are asymmetric in information content:

* An insider BUYING on the open market is rare, voluntary, and paid for out of
  their own pocket. There is one credible reason to do it.
* An insider SELLING is the ordinary end of an equity compensation cycle. At a
  mega-cap it happens every quarter, usually on a Rule 10b5-1 plan adopted
  months earlier, and says nothing about what management believes today.

Scoring both on one symmetric curve made every large-cap read maximally
bearish for behaving completely normally -- measured: META, GOOGL, KO and MSFT
all pinned near 0 while showing no buying at all, which is simply what
mega-cap compensation looks like.

Bands:
    ACCUMULATION          80-100   genuine open-market purchases
    ROUTINE               45-55    planned or modest liquidation
    ABNORMAL_DISTRIBUTION  0-20    heavy off-plan dumping only
"""

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from aethelark_trade.engine.liar_filter import OPEN_MARKET_BUY, OPEN_MARKET_SELL
from aethelark_trade.engine.types import LayerScore
from aethelark_trade.parser import InsiderTransaction

LOOKBACK_DAYS = 90

BULLISH_BAND = (80, 100)
NEUTRAL_BAND = (45, 55)
BEARISH_BAND = (0, 20)

# Fraction of their own stake an insider must liquidate OFF-PLAN before it
# reads as a loss of faith rather than housekeeping. Normalised so a CEO
# selling 30% off-plan sits exactly on the line.
ABNORMAL_SELL_CONVICTION = 0.30

# Spread above the threshold over which the bearish band is traversed.
ABNORMAL_SELL_SCALE = 0.50

# Buy conviction that reaches ~76% of the way up the bullish band.
BUY_SATURATION = 0.25

# A Rule 10b5-1 sale was scheduled before the insider held the information, so
# it contributes at a fraction of a discretionary decision's weight.
PLANNED_TRADE_DISCOUNT = 0.25

# CEO weight is the reference point: role_weight 2.0 maps to 1.0x influence.
REFERENCE_ROLE_WEIGHT = 2.0

# Off-plan selling below this dollar amount cannot move the layer bearish.
# A single Form 4 line reports only the shares held in THAT account, so an
# executive with holdings spread across trusts and vehicles can show a residual
# of a few hundred shares -- measured: Marc Andreessen selling 426 META shares
# ($0.3M) against a 176-share line scored frac 0.708 and dragged a $1.5T
# company into ABNORMAL_DISTRIBUTION. Fraction needs a size gate to mean
# anything. Applied per insider, so a series of small sales that add up to a
# real exit still registers.
MATERIALITY_FLOOR_USD = 1_000_000.0


@dataclass(frozen=True)
class InsiderFlow:
    buy_conviction: float
    discretionary_sell_conviction: float
    planned_sell_intensity: float
    bought_usd: float
    sold_usd: float
    considered: int
    planned: int
    discretionary: int
    excluded: int
    tier: str


def _position_fraction(tx: InsiderTransaction) -> float:
    """What share of their own holding a single trade moved, in [0, 1]."""
    if not tx.shares:
        return 0.0
    owned_after = tx.shares_owned_after or 0.0
    if tx.transaction_code == OPEN_MARKET_SELL:
        position = owned_after + tx.shares
    else:
        position = max(owned_after, tx.shares)
    if position <= 0:
        return 0.0
    return min(tx.shares / position, 1.0)


def is_scoreable_insider(tx: InsiderTransaction) -> bool:
    """True for a person with a seat at the table.

    ARCHITECTURE.md scopes Layer 5 to CEO/Director accumulation. A filer that
    is only a ten-percent owner is typically an affiliated fund or holding
    vehicle -- measured: "GV 2019 GP, L.L.C." (Google Ventures' GP) alone put
    GOOGL into ABNORMAL_DISTRIBUTION by unwinding a position across 12
    filings. That is portfolio management, not a loss of faith by anyone who
    knows what the quarter looks like.

    Somebody who is BOTH a director and a ten-percent owner (Sergey Brin) is
    still an insider and still counts.
    """
    return bool(tx.is_officer or tx.is_director)


def _in_window(tx: InsiderTransaction, as_of: date, lookback_days: int) -> bool:
    when = tx.transaction_date or tx.filing_date
    if when is None:
        return False
    return (as_of - timedelta(days=lookback_days)) <= when <= as_of


def aggregate_by_insider(
    transactions: list[InsiderTransaction], as_of: date, lookback_days: int
) -> dict:
    """Roll trades up per person before measuring conviction.

    A single Form 4 splits one decision across several lines, and each line's
    sharesOwnedFollowingTransaction may describe only a sub-account (a trust,
    an indirect holding). Summing per-line fractions therefore inflates without
    bound -- measured 11.16 for GOOGL, which would mean insiders sold eleven
    times their entire stake. Aggregating per insider first fixes the
    denominator to that person's actual position.
    """
    people: dict[str, dict] = defaultdict(
        lambda: {"bought": 0.0, "disc_sold": 0.0, "planned_sold": 0.0,
                 "peak_holding": 0.0, "role_weight": 1.0,
                 "bought_usd": 0.0, "sold_usd": 0.0, "disc_sold_usd": 0.0}
    )

    for tx in transactions:
        if not _in_window(tx, as_of, lookback_days):
            continue
        if tx.transaction_code not in (OPEN_MARKET_BUY, OPEN_MARKET_SELL):
            continue
        if tx.total_value is None:
            continue
        if not is_scoreable_insider(tx):
            continue

        key = tx.insider_cik or tx.insider_name
        person = people[key]
        person["role_weight"] = max(person["role_weight"], tx.role_weight)
        person["peak_holding"] = max(person["peak_holding"], tx.shares_owned_after or 0.0)

        if tx.transaction_code == OPEN_MARKET_BUY:
            person["bought"] += tx.shares
            person["bought_usd"] += tx.total_value
        elif getattr(tx, "is_10b5_1", False):
            person["planned_sold"] += tx.shares
            person["sold_usd"] += tx.total_value
        else:
            person["disc_sold"] += tx.shares
            person["sold_usd"] += tx.total_value
            person["disc_sold_usd"] += tx.total_value

    return dict(people)


def measure_flow(
    transactions: list[InsiderTransaction],
    as_of: date,
    lookback_days: int = LOOKBACK_DAYS,
) -> InsiderFlow:
    """Reduce a filing history to the three tier-selecting quantities."""
    people = aggregate_by_insider(transactions, as_of, lookback_days)

    buy_conviction = 0.0
    abnormality = 0.0
    planned_intensity = 0.0
    bought_usd = sold_usd = 0.0
    considered = planned = discretionary = 0

    for person in people.values():
        sold = person["disc_sold"] + person["planned_sold"]
        base = person["peak_holding"] + sold
        role = min(person["role_weight"], 3.0) / REFERENCE_ROLE_WEIGHT

        if base > 0:
            # Abnormality is the maximum across insiders, not the sum or the
            # mean: averaging one heavy seller across a quiet board reduces the
            # value below the threshold. Only insiders whose off-plan selling
            # clears the materiality floor are considered.
            if person["disc_sold_usd"] >= MATERIALITY_FLOOR_USD:
                abnormality = max(abnormality, (person["disc_sold"] / base) * role)
            planned_intensity = max(planned_intensity, person["planned_sold"] / base)

        buy_base = max(person["peak_holding"], person["bought"])
        if buy_base > 0 and person["bought_usd"] >= MATERIALITY_FLOOR_USD:
            # Symmetrically with abnormality, buy conviction is the maximum across
            # insiders whose purchases clear the materiality floor. A buy below the
            # floor cannot move the layer into accumulation, and multiple small
            # buyers cannot out-vote heavy off-plan liquidation.
            buy_conviction = max(buy_conviction, (person["bought"] / buy_base) * role)

        bought_usd += person["bought_usd"]
        sold_usd += person["sold_usd"]

    excluded = 0
    for tx in transactions:
        if not _in_window(tx, as_of, lookback_days):
            continue
        if tx.transaction_code not in (OPEN_MARKET_BUY, OPEN_MARKET_SELL):
            continue
        if tx.total_value is None:
            continue
        if not is_scoreable_insider(tx):
            excluded += 1
            continue
        considered += 1
        if tx.transaction_code == OPEN_MARKET_SELL and getattr(tx, "is_10b5_1", False):
            planned += 1
        else:
            discretionary += 1

    if buy_conviction > 0 and buy_conviction >= abnormality:
        tier = "ACCUMULATION"
    elif abnormality >= ABNORMAL_SELL_CONVICTION:
        tier = "ABNORMAL_DISTRIBUTION"
    else:
        tier = "ROUTINE"

    return InsiderFlow(
        buy_conviction=buy_conviction,
        discretionary_sell_conviction=abnormality,
        planned_sell_intensity=planned_intensity,
        bought_usd=bought_usd,
        sold_usd=sold_usd,
        considered=considered,
        planned=planned,
        discretionary=discretionary,
        excluded=excluded,
        tier=tier,
    )


def _band_score(flow: InsiderFlow) -> int:
    if flow.tier == "ACCUMULATION":
        low, high = BULLISH_BAND
        return round(low + (high - low) * math.tanh(flow.buy_conviction / BUY_SATURATION))

    if flow.tier == "ABNORMAL_DISTRIBUTION":
        low, high = BEARISH_BAND
        excess = flow.discretionary_sell_conviction - ABNORMAL_SELL_CONVICTION
        return round(high - (high - low) * math.tanh(excess / ABNORMAL_SELL_SCALE))

    low, high = NEUTRAL_BAND
    pressure = (
        flow.discretionary_sell_conviction
        + PLANNED_TRADE_DISCOUNT * flow.planned_sell_intensity
    ) / ABNORMAL_SELL_CONVICTION
    return round(high - (high - low) * min(1.0, pressure))


TIER_LABELS = {
    "ACCUMULATION": "Insider accumulation",
    "ROUTINE": "Routine liquidation",
    "ABNORMAL_DISTRIBUTION": "Abnormal insider distribution",
}


def score_insider_conviction(
    transactions: list[InsiderTransaction],
    as_of: date,
    lookback_days: int = LOOKBACK_DAYS,
) -> LayerScore:
    """Score insider conviction on the three-tier curve."""
    flow = measure_flow(transactions, as_of, lookback_days)

    if flow.considered == 0:
        return LayerScore.unavailable(
            f"No open-market insider trades in {lookback_days}d"
        )

    score = max(0, min(100, _band_score(flow)))
    net = flow.bought_usd - flow.sold_usd
    if net >= 0:
        money = f"+${net / 1e6:,.1f}M net buying"
    else:
        money = f"-${abs(net) / 1e6:,.1f}M net selling"

    return LayerScore(
        score=score,
        summary=(
            f"{TIER_LABELS[flow.tier]} • {money} • "
            f"{flow.discretionary} discretionary / {flow.planned} on 10b5-1 plans "
            f"({lookback_days}d)"
        ),
        detail={
            "tier": flow.tier,
            "buy_conviction": round(flow.buy_conviction, 4),
            "discretionary_sell_conviction": round(flow.discretionary_sell_conviction, 4),
            "planned_sell_intensity": round(flow.planned_sell_intensity, 4),
            "bought_usd": round(flow.bought_usd, 2),
            "sold_usd": round(flow.sold_usd, 2),
            "trade_count": flow.considered,
            "planned_trade_count": flow.planned,
            "discretionary_trade_count": flow.discretionary,
            "excluded_non_insider_trades": flow.excluded,
        },
    )
