"""Layer 4 -- Sector Relativity.

Absolute return tells you about the market; relative return tells you about the
company. This layer measures daily excess return over the name's sector ETF and
expresses it as a z-score (sigma), matching the "+2.4 sigma Alpha vs SMH"
rendering in docs/UI_STATES.md.
"""

import math
from statistics import mean, stdev

from aethelark_trade.engine.types import LayerScore

MIN_OBSERVATIONS = 20
TRADING_DAYS_PER_YEAR = 252

# Saturation point. At 2 sigma the layer reads clearly positive without
# reaching its maximum.
Z_SATURATION = 2.0


def _returns(series: list[float]) -> list[float]:
    out = []
    for prev, cur in zip(series, series[1:]):
        if prev:
            out.append((cur - prev) / prev)
    return out


def score_sector_relativity(
    stock_closes: list[float],
    sector_closes: list[float],
    sector_etf: str | None,
) -> LayerScore:
    """Score the name's risk-adjusted alpha against its sector ETF."""
    if not sector_etf:
        return LayerScore.unavailable("No sector ETF mapped")

    stock_r = _returns(stock_closes)
    sector_r = _returns(sector_closes)
    n = min(len(stock_r), len(sector_r))

    if n < MIN_OBSERVATIONS:
        return LayerScore.unavailable(
            f"Need {MIN_OBSERVATIONS}+ overlapping sessions vs {sector_etf}, got {n}"
        )

    excess = [s - b for s, b in zip(stock_r[-n:], sector_r[-n:])]
    mean_excess = mean(excess)
    dispersion = stdev(excess) if len(excess) > 1 else 0.0

    if dispersion == 0:
        # Perfectly tracking the sector: no alpha, no risk-adjusted signal.
        alpha_z = 0.0
    else:
        # Annualise the information ratio over a standard trading year (252 days).
        alpha_z = (mean_excess / dispersion) * math.sqrt(TRADING_DAYS_PER_YEAR)

    score = max(0, min(100, round(50 + 50 * math.tanh(alpha_z / Z_SATURATION))))

    return LayerScore(
        score=score,
        summary=(
            f"{alpha_z:+.1f}σ alpha vs {sector_etf} "
            f"({mean_excess * 100:+.2f}%/day excess over {n} sessions)"
        ),
        detail={
            "sector_etf": sector_etf,
            "alpha_z": round(alpha_z, 4),
            "mean_daily_excess": round(mean_excess, 6),
            "sessions": n,
        },
    )
