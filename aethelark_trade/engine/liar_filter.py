"""The Liar Filter: divergence between what a company says and what its
officers do with their own money.

Public sentiment is cheap talk. A Form 4 is a sworn filing. When the tape is
euphoric and the C-suite is quietly dumping into that strength, the two
signals disagree and the filing is the one with legal consequences attached.

Spec: docs/UI_STATES.md State C.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from aethelark_trade.parser import InsiderTransaction

EUPHORIA_THRESHOLD_PCT = 80.0
CSUITE_SELL_THRESHOLD_USD = 10_000_000.0
LOOKBACK_DAYS = 7

# Only open-market conviction trades count. Option exercises (M), gifts (G),
# tax withholding (F) and grants (A) are compensation plumbing -- an executive
# has no discretion over their timing, so they carry no signal.
OPEN_MARKET_BUY = "P"
OPEN_MARKET_SELL = "S"


@dataclass(frozen=True)
class LiarFilterResult:
    status: str                  # "CLEAN" or "DIVERGENCE"
    news_sentiment_pct: float
    csuite_net_usd: float        # negative = net selling
    window_days: int
    detail: str


def _is_csuite(tx: InsiderTransaction) -> bool:
    """Officers only. Directors are the board, not the C-suite."""
    return bool(tx.is_officer or tx.is_ceo or tx.is_cfo)


def csuite_net_flow(
    transactions: list[InsiderTransaction],
    as_of: date,
    window_days: int = LOOKBACK_DAYS,
) -> float:
    """Net open-market dollar flow by officers inside the window.

    Positive means net accumulation, negative means net distribution.
    """
    cutoff = as_of - timedelta(days=window_days)
    net = 0.0
    for tx in transactions:
        when = tx.transaction_date or tx.filing_date
        if when is None or when < cutoff or when > as_of:
            continue
        if not _is_csuite(tx):
            continue
        if tx.total_value is None:
            continue
        if tx.transaction_code == OPEN_MARKET_BUY:
            net += tx.total_value
        elif tx.transaction_code == OPEN_MARKET_SELL:
            net -= tx.total_value
    return net


def check_liar_filter(
    news_sentiment_pct: float,
    transactions: list[InsiderTransaction],
    as_of: date,
    window_days: int = LOOKBACK_DAYS,
) -> LiarFilterResult:
    """Flag euphoric coverage running against heavy C-suite distribution."""
    net = csuite_net_flow(transactions, as_of, window_days)

    euphoric = news_sentiment_pct >= EUPHORIA_THRESHOLD_PCT
    dumping = net <= -CSUITE_SELL_THRESHOLD_USD

    if euphoric and dumping:
        return LiarFilterResult(
            status="DIVERGENCE",
            news_sentiment_pct=news_sentiment_pct,
            csuite_net_usd=net,
            window_days=window_days,
            detail=(
                f"Public Sentiment ({news_sentiment_pct:.0f}% Bullish) "
                f"vs C-Suite Net Dump ${net / 1e6:,.1f}M"
            ),
        )

    return LiarFilterResult(
        status="CLEAN",
        news_sentiment_pct=news_sentiment_pct,
        csuite_net_usd=net,
        window_days=window_days,
        detail="No sentiment/insider divergence detected",
    )
