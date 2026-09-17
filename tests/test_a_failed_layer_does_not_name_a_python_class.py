"""A layer that could not be scored says so in words, not in exception classes.

`_safe` turns any failure into an honest gap -- correct. But it put the
exception's class name into the gap's own summary:

    LayerScore.unavailable(f"{unavailable_msg} ({type(exc).__name__})")

so a layer that failed read "XBRL fundamentals unavailable (KeyError)".

That string is not for developers. Space-Eagle's `model_view` (core/module_bus/bus.py:56)
strips only `_`-prefixed keys, so every layer summary reaches the harness's brain
verbatim -- and that brain is Gemini 2.5 Flash, in the middle of a spoken turn.
"KeyError" spends its attention on a Python identifier that means nothing to it
and that it may repeat to the user.

The detail is not lost. `errors[layer]` still carries the class and the message,
which is where a developer looks.
"""
from __future__ import annotations

import pytest

from aethelark_trade.engine.engine import _safe

#: Anything that means an exception escaped into prose meant for a person.
PYTHON_WORDS = ("KeyError", "ValueError", "TypeError", "IndexError",
                "AttributeError", "RuntimeError", "Exception", "Traceback")


def test_the_summary_a_person_reads_names_no_python_class():
    errors: dict[str, str] = {}
    score = _safe(errors, "layer_1_fundamentals",
                  lambda: (_ for _ in ()).throw(KeyError("currentTradingPeriod")),
                  "XBRL fundamentals unavailable")

    leaked = [w for w in PYTHON_WORDS if w in score.summary]
    assert not leaked, (
        f"the layer summary reaches Gemini Flash verbatim and names a Python "
        f"class: {score.summary!r}")
    assert score.summary == "XBRL fundamentals unavailable"


def test_the_detail_is_still_kept_for_whoever_is_debugging():
    errors: dict[str, str] = {}
    _safe(errors, "layer_5_insider_conviction",
          lambda: (_ for _ in ()).throw(ValueError("no CIK on record")),
          "SEC Form 4 history unavailable")

    assert "layer_5_insider_conviction" in errors
    detail = errors["layer_5_insider_conviction"]
    assert "ValueError" in detail, "the class was dropped from the developer record too"
    assert "no CIK on record" in detail


def test_a_layer_that_works_is_untouched():
    from aethelark_trade.engine.types import LayerScore
    errors: dict[str, str] = {}
    good = LayerScore(score=71, summary="beating its sector", available=True)
    assert _safe(errors, "layer_4_sector_relativity", lambda: good, "unused") is good
    assert errors == {}
