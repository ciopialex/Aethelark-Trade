"""Layer 2 -- Macro Gravity.

docs/FACTS.md calls macro_observatory.py a FRED client; it is actually a
yfinance GILECFS proxy reader (^TNX, ^VIX, DX-Y.NYB, HG=F) and it is async.
This layer takes the resolved proxy values as plain numbers so the math stays
synchronous and testable; see engine.py for the fetch side.
"""

import math
from dataclasses import dataclass

from aethelark_trade.engine.types import LayerScore

# Neutral anchors and the spread over which each proxy swings the score.
YIELD_NEUTRAL, YIELD_SCALE = 4.0, 1.5        # 10Y Treasury, percent
VIX_NEUTRAL, VIX_SCALE = 18.0, 10.0          # implied vol
DOLLAR_NEUTRAL, DOLLAR_SCALE = 103.0, 10.0   # DXY
COPPER_SCALE = 5.0                           # % change, growth proxy

PROXY_WEIGHTS = {"yield": 0.40, "vix": 0.30, "dollar": 0.15, "copper": 0.15}


@dataclass(frozen=True)
class CompanySensitivity:
    """Per-company sensitivity to macroeconomic factors."""

    beta: float = 1.0               # Sensitivity to market volatility (VIX)
    rate_sensitivity: float = 1.0   # Sensitivity to interest rates / 10Y yield (higher = more drag from high rates)
    cyclicality: float = 1.0        # Sensitivity to economic growth / commodity cycles (copper & dollar)


# Structural sector baseline sensitivities
SECTOR_SENSITIVITIES: dict[str, CompanySensitivity] = {
    "XLRE": CompanySensitivity(beta=0.85, rate_sensitivity=1.8, cyclicality=0.7),
    "XLU": CompanySensitivity(beta=0.60, rate_sensitivity=1.6, cyclicality=0.4),
    "XLK": CompanySensitivity(beta=1.25, rate_sensitivity=1.2, cyclicality=1.1),
    "XLY": CompanySensitivity(beta=1.20, rate_sensitivity=1.1, cyclicality=1.4),
    "XLI": CompanySensitivity(beta=1.05, rate_sensitivity=0.9, cyclicality=1.5),
    "XLE": CompanySensitivity(beta=1.10, rate_sensitivity=0.5, cyclicality=1.6),
    "XLF": CompanySensitivity(beta=1.10, rate_sensitivity=-0.3, cyclicality=1.2),
    "XLV": CompanySensitivity(beta=0.75, rate_sensitivity=0.7, cyclicality=0.5),
    "XLP": CompanySensitivity(beta=0.65, rate_sensitivity=0.8, cyclicality=0.4),
    "XLC": CompanySensitivity(beta=1.05, rate_sensitivity=1.0, cyclicality=1.0),
    "XLB": CompanySensitivity(beta=1.10, rate_sensitivity=0.9, cyclicality=1.5),
}


def resolve_company_sensitivity(
    ticker: str,
    closes: list[float] | None = None,
    sector_etf: str | None = None,
    debt_to_equity: float | None = None,
) -> CompanySensitivity:
    """Resolve company-level macro sensitivity from sector, leverage, and realized vol."""
    from aethelark_trade.ticker_registry import get_sector_etf

    sector = sector_etf or get_sector_etf(ticker)
    base = SECTOR_SENSITIVITIES.get(
        sector or "",
        CompanySensitivity(beta=1.0, rate_sensitivity=1.0, cyclicality=1.0),
    )

    rate_sens = base.rate_sensitivity
    if debt_to_equity is not None and debt_to_equity > 0:
        # Scale rate sensitivity with debt leverage
        leverage_factor = min(1.5, max(0.5, 0.7 + 0.3 * debt_to_equity))
        rate_sens = round(rate_sens * leverage_factor, 2)

    beta = base.beta
    if closes and len(closes) >= 20:
        returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
        vol = (sum(r ** 2 for r in returns) / len(returns)) ** 0.5
        vol_annualized = vol * (252 ** 0.5)
        market_vol = 0.16
        realized_beta = max(0.4, min(2.5, vol_annualized / market_vol))
        beta = round(0.5 * base.beta + 0.5 * realized_beta, 2)

    return CompanySensitivity(
        beta=beta,
        rate_sensitivity=rate_sens,
        cyclicality=base.cyclicality,
    )


@dataclass(frozen=True)
class MacroProxies:
    """Market-implied macro state. None means the proxy could not be fetched."""

    yield_10y: float | None = None
    vix: float | None = None
    dollar_index: float | None = None
    copper_change_pct: float | None = None


def _saturating(value: float, scale: float) -> float:
    return 50 + 50 * math.tanh(value / scale)


def score_macro_gravity(
    proxies: MacroProxies,
    sensitivity: CompanySensitivity | None = None,
) -> LayerScore:
    """Score the monetary tide an equity is swimming against, weighted by its sensitivity.

    Rising yields, rising vol and a strong dollar all tighten conditions and
    pull the score down; industrial-metal strength signals real growth and
    pushes it up. The effect of each macro variable is scaled by the company's
    specific rate sensitivity, beta, and cyclicality.
    """
    sens = sensitivity or CompanySensitivity()
    parts: dict[str, float] = {}
    bits: list[str] = []

    if proxies.yield_10y is not None:
        delta = proxies.yield_10y - YIELD_NEUTRAL
        effective_delta = delta * sens.rate_sensitivity
        parts["yield"] = _saturating(-effective_delta, YIELD_SCALE)
        direction = "Headwind" if effective_delta > 0 else "Tailwind"
        bits.append(f"{proxies.yield_10y:.1f}% 10Y Yield {direction}")

    if proxies.vix is not None:
        delta = proxies.vix - VIX_NEUTRAL
        effective_delta = delta * sens.beta
        parts["vix"] = _saturating(-effective_delta, VIX_SCALE)
        bits.append(f"VIX {proxies.vix:.1f}")

    if proxies.dollar_index is not None:
        delta = proxies.dollar_index - DOLLAR_NEUTRAL
        effective_delta = delta * sens.cyclicality
        parts["dollar"] = _saturating(-effective_delta, DOLLAR_SCALE)
        bits.append(f"DXY {proxies.dollar_index:.1f}")

    if proxies.copper_change_pct is not None:
        effective_copper = proxies.copper_change_pct * sens.cyclicality
        parts["copper"] = _saturating(effective_copper, COPPER_SCALE)
        bits.append(f"Copper {proxies.copper_change_pct:+.1f}%")

    if not parts:
        return LayerScore.unavailable("Macro proxies unavailable")

    weight_total = sum(PROXY_WEIGHTS[k] for k in parts)
    score = sum(PROXY_WEIGHTS[k] * v for k, v in parts.items()) / weight_total
    return LayerScore(
        score=max(0, min(100, round(score))),
        summary=" • ".join(bits),
        detail={
            "yield_10y": proxies.yield_10y,
            "vix": proxies.vix,
            "dollar_index": proxies.dollar_index,
            "copper_change_pct": proxies.copper_change_pct,
            "beta": sens.beta,
            "rate_sensitivity": sens.rate_sensitivity,
            "cyclicality": sens.cyclicality,
        },
    )
