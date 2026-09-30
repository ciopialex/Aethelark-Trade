"""Pure scoring math for the Aethelark 7-layer matrix.

Every function here is deterministic and I/O-free so it can be tested
against real numbers with zero mocks.

Layer weights encode the architecture's thesis: the two *legally attested*
layers (SEC fundamentals 24%, SEC Form 4 insider conviction 26%) carry 50% of
the composite, cross-sectional alpha carries 16%, and the slow context layers
(macro gravity, geopolitics) are deliberately light so they modulate rather
than dominate a single-name verdict.

The figures above are read off LAYER_WEIGHTS below and must be changed with
them. They said 46% and 15% while the weights summed to 50% and 16% -- the
numbers anyone would quote when deciding whether this model is worth using.
"""

# Identity of the scoring math itself. Bump this whenever a layer's formula,
# banding or weighting changes, so cached scorecards computed by the previous
# model can be recognised and withheld rather than silently ranked alongside
# current ones. Observed once already: a leaderboard ranked META on a Layer 5
# curve that had been replaced hours earlier.
SCORING_MODEL_VERSION = "2026-09-04.company-macro"

LAYER_WEIGHTS: dict[str, float] = {
    "layer_1_fundamentals": 0.24,
    "layer_2_macro_gravity": 0.10,
    "layer_3_news_velocity": 0.13,
    "layer_4_sector_relativity": 0.16,
    "layer_5_insider_conviction": 0.26,
    "layer_7_supply_chain": 0.11,
}

NON_COMPOSITE_LAYERS: set[str] = {"layer_6_geopolitics"}

NEUTRAL_SCORE = 50


def composite_score(layers: dict[str, float]) -> int:
    """Weighted 0-100 composite across whichever layers have data.

    Layers absent from ``layers`` are treated as *unknown*, not as zero: the
    surviving weights are renormalized so a stock with partial coverage is not
    punished for data we simply could not fetch. With no coverage at all the
    verdict is neutral, never bearish.
    """
    relevant = {}
    for name, score in layers.items():
        if name in NON_COMPOSITE_LAYERS:
            continue
        if name not in LAYER_WEIGHTS:
            raise KeyError(name)
        relevant[name] = score

    weight_total = sum(LAYER_WEIGHTS[name] for name in relevant)
    if weight_total == 0:
        return NEUTRAL_SCORE
    total = sum(LAYER_WEIGHTS[name] * score for name, score in relevant.items())
    return round(total / weight_total)


# Verdict bands over the 0-100 composite.
VERDICT_BANDS: tuple[tuple[int, str], ...] = (
    (80, "BULLISH"),
    (60, "ACCUMULATE"),
    (40, "NEUTRAL"),
    (20, "CAUTION"),
    (0, "BEARISH"),
)

# Points of thesis you can always lose to market beta, however clean the
# scorecard looks. Prevents a flawless card from reporting infinite asymmetry.
IRREDUCIBLE_DOWNSIDE = 10.0

# Above this the ratio stops being informative, so we clamp rather than
# print a number that implies false precision.
MAX_ASYMMETRY = 9.9


def verdict(score: float) -> str:
    """Map a composite score onto its verdict band."""
    for floor, label in VERDICT_BANDS:
        if score >= floor:
            return label
    return "BEARISH"


def asymmetry_ratio(composite: float, layers: dict[str, float]) -> float:
    """Reward-to-risk ratio implied by the scorecard.

    Upside is the composite's distance above neutral. Downside is driven by
    the layers that are actually broken (scoring below neutral), weight-averaged
    so a heavy layer failing hurts more than a light one, and floored at
    ``IRREDUCIBLE_DOWNSIDE``.

    Note: docs/UI_STATES.md renders an illustrative "3.8 : 1" for the NVDA card
    but supplies no inputs for it; this formula yields 3.4 : 1 for that card.
    """
    upside = max(composite - NEUTRAL_SCORE, 0.0)
    if upside == 0:
        return 0.0

    weak = {n: s for n, s in layers.items() if n in LAYER_WEIGHTS and s < NEUTRAL_SCORE}
    weak_weight = sum(LAYER_WEIGHTS[n] for n in weak)
    if weak_weight > 0:
        drag = sum(LAYER_WEIGHTS[n] * (NEUTRAL_SCORE - s) for n, s in weak.items())
        downside = drag / weak_weight
    else:
        downside = 0.0

    downside = max(downside, IRREDUCIBLE_DOWNSIDE)
    return round(min(upside / downside, MAX_ASYMMETRY), 2)
