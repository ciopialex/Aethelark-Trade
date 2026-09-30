"""An unavailable layer must not be able to hand anyone a number.

LayerScore.unavailable() returned score=50 while its own docstring said the
engine drops the layer "rather than scoring it 50 and diluting the verdict with
a fake datapoint". engine.py then emitted that 50 straight into the --json
payload, so any consumer reading `score` without also reading `available` --
the HUD, the voice layer, a future module -- received an invented neutral.

The invariant was written in prose and enforced nowhere. Making the field None
moves it from a comment into the type, where a checker can see it.
"""
import pytest

from aethelark_trade.engine.types import LayerScore


def test_an_available_layer_has_a_number():
    layer = LayerScore(score=78, summary="strong")
    assert layer.available is True
    assert layer.score == 78


def test_an_unavailable_layer_has_no_number_at_all():
    layer = LayerScore.unavailable("no filings")
    assert layer.available is False
    assert layer.score is None


def test_an_unavailable_layer_cannot_be_used_as_a_number():
    """The failure has to be loud. Silently yielding 50 is how a fabricated
    neutral reaches a verdict."""
    layer = LayerScore.unavailable("no filings")
    with pytest.raises(TypeError):
        _ = layer.score + 1


def test_constructing_an_unavailable_layer_with_a_score_is_refused():
    """There is no legitimate reason to carry a number you have declared
    meaningless, and allowing it re-opens the hole from the other side."""
    with pytest.raises(ValueError):
        LayerScore(score=50, summary="pretending", available=False)


def test_constructing_an_available_layer_without_a_score_is_refused():
    with pytest.raises(ValueError):
        LayerScore(score=None, summary="empty", available=True)


def test_score_or_returns_a_caller_chosen_default():
    """Callers that genuinely want a fallback must name it at the call site,
    so the substitution is visible in the code that depends on it."""
    assert LayerScore.unavailable("gone").score_or(0) == 0
    assert LayerScore(score=78, summary="x").score_or(0) == 78


def test_the_json_payload_reports_null_not_a_fabricated_fifty():
    from datetime import date

    from aethelark_trade.engine.engine import assemble_result
    from aethelark_trade.engine.liar_filter import check_liar_filter
    from aethelark_trade.engine.scoring import LAYER_WEIGHTS

    layers = {n: LayerScore(score=60, summary=n) for n in LAYER_WEIGHTS}
    layers["layer_3_news_velocity"] = LayerScore.unavailable("no headlines")
    payload = assemble_result(
        "NVDA", layers, check_liar_filter(50.0, [], as_of=date(2026, 8, 20))
    ).to_dict()

    missing = payload["layers"]["layer_3_news_velocity"]
    assert missing["available"] is False
    assert missing["score"] is None
