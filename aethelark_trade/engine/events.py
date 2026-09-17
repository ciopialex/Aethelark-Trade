"""Dynamic Island event payloads for Space-Eagle.

Every schema here is pinned to docs/UI_STATES.md; the tests assert the exact
colours, durations and keys the HUD renders against, so a drift in either
direction fails rather than silently producing an unrenderable card.
"""

import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

from aethelark_trade.engine.liar_filter import OPEN_MARKET_BUY
from aethelark_trade.parser import InsiderTransaction

MODULE = "trade"

# MODULE_FACTORY_SPEC Pillar 4: the host reads
# `<tempdir>/<key>_dynamic_island.json`, resolving tempdir with
# tempfile.gettempdir() (Space-Eagle core/module_bus/manifest.py:616). This was
# hardcoded to "/tmp", which agrees with that on Linux and diverges on macOS
# (TMPDIR is /var/folders/...) and Windows -- the module would write a file the
# host never looks at, and the island would simply never update.
DYNAMIC_ISLAND_PATH = Path(tempfile.gettempdir()) / "atrade_dynamic_island.json"

# Event priority ordering when multiple events arrive simultaneously.
# Higher value = higher priority.
EVENT_PRIORITY = {
    "liar_filter_warning": 100,
    "form4_whale_buy": 90,
    "8k_material_event": 80,
    "relative_outlier_leader": 70,
    "scoring_progress": 10,
}


def event_priority(payload: dict) -> tuple[int, int]:
    """Sort key for prioritizing events: higher priority and longer duration win."""
    prio = EVENT_PRIORITY.get(payload.get("event", ""), 50)
    duration = int(payload.get("duration_ms", 0) or 0)
    return (prio, duration)


def write_dynamic_island_event(
    payload: dict,
    dest: Path | str = DYNAMIC_ISLAND_PATH,
) -> None:
    """Atomically write an event payload to the Dynamic Island file.

    Writes to a temporary file in the same directory first, then calls os.replace()
    to guarantee consumers never observe a partial write.
    """
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_name(f"{dest_path.name}.tmp.{os.getpid()}")
    try:
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(temp_path, dest_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


WHALE_BUY_THRESHOLD_USD = 1_000_000.0
WHALE_LOOKBACK_DAYS = 7


def _money(value: float) -> str:
    magnitude = abs(value)
    if magnitude >= 1e9:
        return f"${value / 1e9:,.1f}B"
    if magnitude >= 1e6:
        return f"${value / 1e6:,.1f}M"
    return f"${value / 1e3:,.0f}K"


def _event(event: str, icon: str, ticker: str, title: str, detail: str,
           badge: str, color: str, duration_ms: int) -> dict:
    return {
        "module": MODULE,
        "event": event,
        "icon": icon,
        "ticker": ticker.upper(),
        "title": title,
        "detail": detail,
        "badge": badge,
        "color": color,
        "duration_ms": duration_ms,
    }


# --- State A: Form 4 Insider Whale Buy -----------------------------------
def should_emit_whale_buy(
    transactions: list[InsiderTransaction],
    as_of: date,
    threshold: float = WHALE_BUY_THRESHOLD_USD,
    lookback_days: int = WHALE_LOOKBACK_DAYS,
) -> bool:
    """True when open-market insider *purchases* clear the threshold.

    Only code P counts. Option exercises and tax withholding routinely carry
    nine-figure notionals with no purchase decision behind them, and firing a
    whale-buy card on one would be the single most misleading alert the HUD
    could show.
    """
    cutoff = as_of - timedelta(days=lookback_days)
    bought = 0.0
    for tx in transactions:
        when = tx.transaction_date or tx.filing_date
        if when is None or when < cutoff or when > as_of:
            continue
        if tx.transaction_code != OPEN_MARKET_BUY or tx.total_value is None:
            continue
        bought += tx.total_value
    return bought >= threshold


def form4_whale_buy(ticker: str, insider: str, amount_usd: float, score: int) -> dict:
    return _event(
        event="form4_whale_buy",
        icon="🐋",
        ticker=ticker,
        title=f"{ticker.upper()} INSIDER WHALE BUY",
        detail=f"{insider} purchased +{_money(amount_usd)} (Score: {score}/100)",
        badge=f"+{_money(amount_usd)}",
        color="#00FFA3",
        duration_ms=8000,
    )


# --- State B: 8-K Material Contract / Acquisition -------------------------
EIGHT_K_ITEM_LABELS = {
    "1.01": "MATERIAL AGREEMENT",
    "1.02": "AGREEMENT TERMINATED",
    "2.01": "ACQUISITION COMPLETED",
    "5.02": "EXECUTIVE CHANGE",
}


def eight_k_material_event(ticker: str, item: str, description: str) -> dict:
    label = EIGHT_K_ITEM_LABELS.get(item, "MATERIAL EVENT")
    return _event(
        event="8k_material_event",
        icon="📜",
        ticker=ticker,
        title=f"{ticker.upper()} {label}",
        detail=f"Form 8-K Item {item}: {description}",
        badge="8-K Filed",
        color="#00E5FF",
        duration_ms=6000,
    )


# --- State C: Liar Filter Divergence --------------------------------------
def liar_filter_warning(ticker: str, sentiment_pct: float, csuite_net_usd: float) -> dict:
    return _event(
        event="liar_filter_warning",
        icon="⚠️",
        ticker=ticker,
        title=f"LIAR FILTER: {ticker.upper()} DIVERGENCE",
        detail=(
            f"Public Sentiment ({sentiment_pct:.0f}% Bullish) vs "
            f"C-Suite Net Dump -{_money(abs(csuite_net_usd))}"
        ),
        badge="Divergence",
        color="#FF9100",
        duration_ms=8000,
    )


# --- State D: Relative Asymmetry Leader -----------------------------------
def relative_outlier_leader(ticker: str, score: int, rank: int, detail: str) -> dict:
    return _event(
        event="relative_outlier_leader",
        icon="🎯",
        ticker=ticker,
        title="TOP RELATIVE ASYMMETRY",
        detail=f"${ticker.upper()}: {score}/100 Score • {detail}",
        badge=f"Rank #{rank}",
        color="#D4AF37",
        duration_ms=6000,
    )


# --- State E: Live Scoring Progress ---------------------------------------
def scoring_progress(ticker: str, detail: str) -> dict:
    return _event(
        event="scoring_progress",
        icon="⚡",
        ticker=ticker,
        title="SCORING 7 LAYERS...",
        detail=detail,
        badge="Scoring",
        color="#3B82F6",
        duration_ms=2000,
    )
