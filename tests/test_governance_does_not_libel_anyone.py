"""Governance names a real executive and then makes a claim about them.

`decode_governance_summary()` can return "Management is looting the ship",
attached to a named CEO, and the module hands that to a voice that reads it
aloud. The bar for that sentence is therefore not "usually right".

Two things went wrong at once, and both are covered here.

**The sign.** SEC's "Compensation Actually Paid" is a mark-to-market figure
that includes the change in fair value of unvested equity, so it is
legitimately negative in a year the stock fell. The percent change divided by
the *signed* denominator, and a negative over a negative flips the result.
Measured on INTC 2026-09-21: pay moved from -$78.5M to -$82.2M -- a 4.7%
decrease -- and the formula returned +4.7%, tripping the branch that publishes
the looting accusation. `engine/governance.py:_pct_change` had always divided
by `abs(oldest)`, so the structured field said -4.7 while the spoken sentence
said "rose 4.7%".

**The vocabulary.** `VERDICTS` called itself a closed set matching the
emitter and did not match it: three emitted verdicts were missing and one
listed verdict was emitted by nothing.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from aethelark_trade.engine.governance import (
    BEARISH_VERDICTS, VERDICTS, _classify, _pct_change,
)

XBRL_SOURCE = (Path(__file__).resolve().parent.parent
               / "aethelark_trade" / "xbrl.py").read_text(encoding="utf-8")


class _Cell:
    """Minimal stand-in for the XBRL amount rows the decoder consumes."""

    def __init__(self, amount, year=2026):
        self.amount = amount
        self.year = year


# ------------------------------------------------------------------ the sign

def test_a_pay_cut_is_never_reported_as_a_rise():
    """The INTC case, as arithmetic. -78.5M -> -82.2M is a cut."""
    pct, latest, oldest = _pct_change([_Cell(-82_216_617.0), _Cell(-78_501_522.0)])
    assert pct is not None
    assert pct < 0, f"pay fell but the change came back {pct:+.1f}%"
    assert round(pct, 1) == -4.7


@pytest.mark.parametrize("latest,oldest,expect_positive", [
    (-82_216_617.0, -78_501_522.0, False),   # more negative -> a cut
    (-70_000_000.0, -80_000_000.0, True),    # less negative -> a rise
    (120.0, 100.0, True),                    # ordinary rise
    (80.0, 100.0, False),                    # ordinary cut
    (50.0, -100.0, True),                    # crossed zero upward
])
def test_direction_survives_a_negative_denominator(latest, oldest, expect_positive):
    pct, _, _ = _pct_change([_Cell(latest), _Cell(oldest)])
    assert pct is not None
    assert (pct > 0) is expect_positive, (
        f"{oldest} -> {latest} reported {pct:+.1f}%, which is the wrong direction")


def test_the_prose_divides_by_an_absolute_value_too():
    """The structured field and the spoken sentence come from different files.

    governance.py was right and xbrl.py was wrong, which is the worst version
    of this bug: the payload looked correct while the voice did not.
    """
    signed = re.search(
        r"pay_change\s*=\s*\(latest_pay\s*-\s*oldest_pay\)\s*/\s*\(oldest_pay\s+if",
        XBRL_SOURCE)
    assert signed is None, (
        "xbrl.py divides the pay change by a signed denominator again; a "
        "negative 'Compensation Actually Paid' will flip the sign and the "
        "looting branch will fire on a pay cut")
    assert "abs(oldest_pay)" in XBRL_SOURCE
    assert "abs(oldest_tsr)" in XBRL_SOURCE


def test_the_accusation_branch_still_requires_a_genuine_rise():
    """Guard the condition itself, not just the arithmetic feeding it."""
    assert "if tsr_change < 0 and pay_change > 0:" in XBRL_SOURCE, (
        "the TOTAL DRAIN branch changed shape; re-check what it now asserts "
        "about a named person")


# ----------------------------------------------------------- the vocabulary

def _emitted_verdicts() -> set[str]:
    """Verdict names as they appear in the sentences xbrl.py can return."""
    return set(re.findall(r"\[bold [a-z0-9]+\]([A-Z][A-Z ]+?)\s*\(", XBRL_SOURCE))


def test_every_verdict_the_decoder_emits_is_classifiable():
    missing = sorted(_emitted_verdicts() - set(VERDICTS))
    assert not missing, (
        f"xbrl.py emits {missing} and engine/governance.VERDICTS does not list "
        f"them, so they classify as UNKNOWN and the card draws no label")


def test_no_verdict_is_listed_that_nothing_emits():
    emitted = _emitted_verdicts()
    dead = sorted(v for v in VERDICTS if v != "UNKNOWN" and v not in emitted)
    assert not dead, f"VERDICTS lists {dead}, which no branch produces"


def test_bearish_verdicts_are_all_real_verdicts():
    assert set(BEARISH_VERDICTS) <= set(VERDICTS)


def test_shared_pain_is_not_treated_as_bearish():
    """Management taking a bigger cut than shareholders argues for trust."""
    assert "SHARED PAIN" not in BEARISH_VERDICTS


@pytest.mark.parametrize("verdict", [v for v in VERDICTS if v != "UNKNOWN"])
def test_classify_recognises_each_verdict_in_a_sentence(verdict):
    assert _classify(f"{verdict} (Neutral): something happened.") == verdict


def test_an_unrecognised_sentence_is_unknown_not_a_guess():
    assert _classify("Governance trend is stable but unsignalized.") == "UNKNOWN"
