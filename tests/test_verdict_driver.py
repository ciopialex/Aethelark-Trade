"""The card says a verdict and its reason, not a composite score.

Measured range of the composite across every name this system has scored:
45..64 on a 0-100 scale. The number claims a precision it does not have, and
"55" tells a person nothing they can act on. The ordering it provides is still
needed for ranking -- so the score keeps sorting, and stops being displayed.

What replaces it is a verdict word plus the single layer that drove it, which
is auditable (you can check the named layer) and speakable (the eagle reads it
aloud verbatim).
"""
import pytest

from aethelark_trade.engine.scoring import LAYER_WEIGHTS
from aethelark_trade.engine.verdict import (
    DRIVER_PHRASES,
    driving_layer,
    verdict_line,
)

ALL = list(LAYER_WEIGHTS)


def layers(**over):
    base = {n: 50 for n in ALL}
    base.update(over)
    return base


# ------------------------------------------------------------ which layer drove it
def test_driver_is_the_layer_furthest_from_neutral_by_weight():
    """Insiders at 86 (24% weight) beats News at 88 (12% weight): the heavier
    layer moved the verdict more, even though the lighter one is a bigger number."""
    assert driving_layer(layers(layer_5_insider_conviction=86,
                                layer_3_news_velocity=88)) == "layer_5_insider_conviction"


def test_a_broken_layer_can_be_the_driver():
    """The reason for avoiding something is a reason too."""
    assert driving_layer(layers(layer_5_insider_conviction=5)) == \
        "layer_5_insider_conviction"


def test_all_neutral_has_no_driver():
    assert driving_layer(layers()) is None


def test_unavailable_layers_cannot_drive():
    scored = layers(layer_5_insider_conviction=95)
    del scored["layer_5_insider_conviction"]
    assert driving_layer(scored) != "layer_5_insider_conviction"


# ------------------------------------------------------------------- the sentence
def test_every_layer_has_phrases_for_both_directions():
    for name in ALL:
        assert name in DRIVER_PHRASES
        assert "high" in DRIVER_PHRASES[name] and "low" in DRIVER_PHRASES[name]


def test_line_names_the_verdict_and_the_reason():
    verdict, reason = verdict_line(layers(layer_5_insider_conviction=90))
    assert verdict in ("BULLISH", "ACCUMULATE", "NEUTRAL", "CAUTION", "BEARISH")
    assert reason == "insiders are buying"


def test_a_bad_driver_reads_as_a_warning():
    _, reason = verdict_line(layers(layer_5_insider_conviction=5))
    assert reason == "insiders are heading for the exit"


def test_reason_is_plain_language_with_no_jargon():
    """A 16-year-old has to understand it, so no sigma, no z-score, no alpha."""
    banned = ("sigma", "σ", "z-score", "asymmetry", "divergence", "percentile",
              "composite", "conviction index")
    for name in ALL:
        for direction in ("high", "low"):
            phrase = DRIVER_PHRASES[name][direction].lower()
            assert not any(b in phrase for b in banned), f"{name}/{direction}"
            assert len(phrase.split()) <= 7, f"{name}/{direction} is a paragraph"


def test_no_driver_still_produces_a_usable_line():
    verdict, reason = verdict_line(layers())
    assert verdict == "NEUTRAL"
    assert reason and "nothing" in reason.lower()


def test_the_line_is_speakable_verbatim():
    verdict, reason = verdict_line(layers(layer_1_fundamentals=88))
    spoken = f"{verdict.title()}. {reason.capitalize()}."
    assert "[" not in spoken and "{" not in spoken
    assert spoken.endswith(".")


# --------------------------------------------- verdict must agree with its reason
def test_verdict_never_contradicts_its_reason():
    """Measured on real KO data, the card said:

        NEUTRAL — insiders are heading for the exit

    The verdict came from the composite (pinned 45..64, so always NEUTRAL) while
    the reason came from the strongest layer. They disagreed, which is worse than
    either alone: it reads as a system that has not made up its mind.

    The verdict is now derived FROM the driver, so the two agree by construction.
    """
    bearish_driver = layers(layer_5_insider_conviction=11, layer_3_news_velocity=88)
    verdict, reason = verdict_line(bearish_driver)
    assert "exit" in reason
    assert verdict in ("AVOID", "CAUTION")


def test_strong_insider_buying_reads_as_accumulate():
    """Real INTC shape: insiders 86."""
    verdict, reason = verdict_line(layers(layer_5_insider_conviction=86,
                                          layer_4_sector_relativity=75))
    assert verdict == "ACCUMULATE"
    assert reason.startswith("insiders are buying")


def test_nothing_standing_out_is_neutral():
    verdict, reason = verdict_line(layers(layer_1_fundamentals=53))
    assert verdict == "NEUTRAL"


def test_the_opposing_signal_is_named():
    """KO: insiders fleeing while the story heats up. That tension IS the
    information -- hiding it would be hiding the Liar Filter in prose form."""
    _, reason = verdict_line(layers(layer_5_insider_conviction=11,
                                    layer_3_news_velocity=88))
    assert "but" in reason or "even though" in reason
    assert "story" in reason


def test_no_opposition_means_no_qualifier():
    """Everything pointing the same way should read cleanly, not hedge."""
    _, reason = verdict_line(layers(layer_5_insider_conviction=86,
                                    layer_1_fundamentals=80))
    assert "but" not in reason and "despite" not in reason


def test_a_weak_opposing_layer_is_not_worth_mentioning():
    _, reason = verdict_line(layers(layer_5_insider_conviction=86,
                                    layer_2_macro_gravity=47))
    assert "but" not in reason and "despite" not in reason


# ------------------------------------------------------ it gets read out loud
def test_the_opposition_clause_is_grammatical():
    """The phrases are clauses, so the joiner has to take a clause. "despite the
    business prints cash" is not English, and the voice layer says it verbatim."""
    _, reason = verdict_line(layers(layer_5_insider_conviction=11,
                                    layer_1_fundamentals=76))
    assert "despite the business prints" not in reason
    assert "even though" in reason or "but" in reason


def test_a_neutral_verdict_does_not_cite_a_reason_it_is_not_acting_on():
    """Real TSLA shape: fundamentals 59. That read "Neutral. The business prints
    cash." -- a claim too strong for a 59, attached to a verdict that declined to
    act on it. If nothing is decisive, say so."""
    verdict, reason = verdict_line(layers(layer_1_fundamentals=59))
    assert verdict == "NEUTRAL"
    assert reason == "nothing stands out either way"
