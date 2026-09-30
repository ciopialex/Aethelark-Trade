"""What the card says instead of a score.

The composite still exists and still sorts -- ranking needs an ordering. It is
simply no longer shown, because across every name this system has scored it
spans 45..64 on a 0-100 scale. A number that narrow is claiming a precision it
does not have, and "55" is not something a person can act on.

What a person can act on is a verdict and the reason for it. The reason names
the layer that actually moved the verdict, so it stays checkable: if the card
says "insiders are buying", the insiders bar is right there to verify it.

Every phrase here has to survive being read aloud by the voice layer and
understood by someone who has never used the product.
"""

from aethelark_trade.engine.scoring import NEUTRAL_SCORE, LAYER_WEIGHTS

# Plain language only. No sigma, no z-scores, no "asymmetry" -- if it needs a
# glossary it has already failed.
DRIVER_PHRASES: dict[str, dict[str, str]] = {
    "layer_1_fundamentals": {
        "high": "the business prints cash",
        "low": "the business is burning cash",
    },
    "layer_2_macro_gravity": {
        "high": "conditions are helping",
        "low": "rates are working against it",
    },
    "layer_3_news_velocity": {
        "high": "the story is heating up",
        "low": "the news has turned against it",
    },
    "layer_4_sector_relativity": {
        "high": "it is beating its own sector",
        "low": "it is losing to its own sector",
    },
    "layer_5_insider_conviction": {
        "high": "insiders are buying",
        "low": "insiders are heading for the exit",
    },
    "layer_6_geopolitics": {
        "high": "the market is calm",
        "low": "the market is under stress",
    },
    "layer_7_supply_chain": {
        "high": "its suppliers are healthy",
        "low": "its supply chain is strained",
    },
}

NO_DRIVER = "nothing stands out either way"

# Below this, a layer is too close to neutral to be worth naming as the reason.
MIN_DRIVER_DISTANCE = 8.0

# Weighted pull thresholds. The verdict is derived from the DRIVER rather than
# the composite: the composite sits in 45..64 for every name measured, so it
# returned NEUTRAL regardless of the dominant layer's value. Observed output:
# "NEUTRAL - insiders are heading for the exit", where verdict and reason
# disagreed.
STRONG_PULL = 6.0
MILD_PULL = 2.5

# An opposing layer worth naming. Below this the tension is not real enough to
# spend words on, and hedging every verdict makes all of them sound the same.
OPPOSITION_PULL = 3.0


def _pulls(scored: dict[str, float]) -> list[tuple[str, float]]:
    """(layer, signed weighted pull), strongest first."""
    out = []
    for name, score in scored.items():
        weight = LAYER_WEIGHTS.get(name)
        if weight is None:
            continue
        distance = score - NEUTRAL_SCORE
        if abs(distance) < MIN_DRIVER_DISTANCE:
            continue
        out.append((name, distance * weight))
    return sorted(out, key=lambda pair: -abs(pair[1]))


def driving_layer(scored: dict[str, float]) -> str | None:
    """The layer that moved the verdict most.

    Weighted distance from neutral, not raw distance: insiders at 86 (24% of
    the verdict) drove more than news at 88 (12%), even though news is the
    bigger number. Naming the bigger number would point at the wrong reason.
    """
    pulls = _pulls(scored)
    return pulls[0][0] if pulls else None


def driver_reason(scored: dict[str, float], layer: str | None = None) -> str:
    """The plain sentence explaining the verdict."""
    layer = layer or driving_layer(scored)
    if layer is None:
        return NO_DRIVER
    direction = "high" if scored[layer] >= NEUTRAL_SCORE else "low"
    return DRIVER_PHRASES[layer][direction]


def _phrase(scored, layer: str) -> str:
    direction = "high" if scored[layer] >= NEUTRAL_SCORE else "low"
    return DRIVER_PHRASES[layer][direction]


def verdict_line(scored: dict[str, float], composite: float | None = None):
    """(verdict, reason) -- what the card shows where the score used to be.

    ``composite`` is accepted and ignored for the verdict; it still ranks names
    against each other, it just no longer decides what a single card says.
    """
    pulls = _pulls(scored)
    if not pulls:
        return "NEUTRAL", NO_DRIVER

    layer, pull = pulls[0]
    reason = _phrase(scored, layer)

    # Name the largest opposing layer, if one exceeds OPPOSITION_PULL. This is
    # the same condition the Liar Filter detects, expressed in the reason text.
    for other, other_pull in pulls[1:]:
        if other_pull * pull < 0 and abs(other_pull) >= OPPOSITION_PULL:
            # Both joiners must take a CLAUSE -- the phrases are clauses, so
            # "despite the business prints cash" is not a sentence, and the
            # voice layer reads this out verbatim.
            joiner = "even though" if pull < 0 else "but"
            reason = f"{reason}, {joiner} {_phrase(scored, other)}"
            break

    if pull >= STRONG_PULL:
        return "ACCUMULATE", reason
    if pull >= MILD_PULL:
        return "WATCH", reason
    if pull <= -STRONG_PULL:
        return "AVOID", reason
    if pull <= -MILD_PULL:
        return "CAUTION", reason

    # Nothing was decisive enough to act on, so do not quote a reason as though
    # it were. Naming a mild layer here overclaims it ("the business prints
    # cash" for a 59) and attaches evidence to a verdict that declined to use it.
    return "NEUTRAL", NO_DRIVER
