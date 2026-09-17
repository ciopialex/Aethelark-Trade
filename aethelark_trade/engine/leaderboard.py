"""Slice 2 -- cross-sectional relative asymmetry ranking.

The roadmap asks for High Quality + Low Forward Multiple + Insider Buying.
Forward multiples require analyst estimates this system does not license, so
cheapness is free-cash-flow yield (FCF / market cap) computed from the same
companyfacts pull Layer 1 already makes. It is a harsher measure than forward
P/E -- it cannot be flattered by a hopeful estimate.
"""

import math
from dataclasses import dataclass

# A ~5% free cash flow yield is roughly fair for a US large cap; above that a
# name is paying you to own it, below it you are paying for growth.
FCF_YIELD_NEUTRAL_PCT = 5.0
FCF_YIELD_SCALE_PCT = 4.0

RANK_WEIGHTS = {"quality": 0.40, "value": 0.35, "insider": 0.25}


@dataclass(frozen=True)
class LeaderboardEntry:
    ticker: str
    composite: int
    quality: int | None
    insider: int | None
    fcf_yield_pct: float | None
    scored_at: str
    age_seconds: float | None = None


@dataclass(frozen=True)
class RankedEntry:
    rank: int
    ticker: str
    asymmetry: float
    composite: int
    quality: int | None
    insider: int | None
    fcf_yield_pct: float | None
    scored_at: str
    age_seconds: float | None = None


def _value_score(fcf_yield_pct: float) -> float:
    return 50 + 50 * math.tanh(
        (fcf_yield_pct - FCF_YIELD_NEUTRAL_PCT) / FCF_YIELD_SCALE_PCT
    )


def relative_asymmetry(entry: LeaderboardEntry) -> float:
    """Blend quality, cheapness and insider conviction into a 0-100 rank score."""
    parts: dict[str, float] = {}
    if entry.quality is not None:
        parts["quality"] = float(entry.quality)
    if entry.insider is not None:
        parts["insider"] = float(entry.insider)
    if entry.fcf_yield_pct is not None:
        parts["value"] = _value_score(entry.fcf_yield_pct)

    # Every leg missing means nothing was measured; fall back to the composite
    # rather than inventing a rank out of an empty blend.
    if not parts:
        return round(float(entry.composite), 2)

    weight_total = sum(RANK_WEIGHTS[k] for k in parts)
    score = sum(RANK_WEIGHTS[k] * v for k, v in parts.items()) / weight_total
    return round(max(0.0, min(100.0, score)), 2)


def rank_leaderboard(entries: list[LeaderboardEntry], limit: int = 10) -> list[RankedEntry]:
    """Order a universe by relative asymmetry, best first."""
    scored = sorted(
        ((relative_asymmetry(e), e) for e in entries),
        key=lambda pair: (-pair[0], pair[1].ticker),
    )
    return [
        RankedEntry(
            rank=i,
            ticker=e.ticker,
            asymmetry=score,
            composite=e.composite,
            quality=e.quality,
            insider=e.insider,
            fcf_yield_pct=e.fcf_yield_pct,
            scored_at=e.scored_at,
            age_seconds=e.age_seconds,
        )
        for i, (score, e) in enumerate(scored[:limit], start=1)
    ]
