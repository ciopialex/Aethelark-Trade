"""The spoken answer has to sound like a friend, not an instrument panel.

The product is a conversation. Every layer emits a dense `summary` for the
card -- "-0.7σ alpha vs XLK (-0.08%/day excess over 119 sessions)" -- and none
of that can reach a voice.

The case that matters most is the one that happens most. Measured across NVDA,
JPM, KO and AMT, a typical company is missing two of its layers, so "I don't
know" is the sentence this engine says more than any other. These tests hold
it to saying that like a person rather than like a failed sensor.
"""
from __future__ import annotations

import re

import pytest

from aethelark_trade.engine import speech
from aethelark_trade.engine.speech import say_layer, say_coverage, spoken_answer

ALL_LAYERS = (
    "layer_1_fundamentals", "layer_2_macro_gravity", "layer_3_news_velocity",
    "layer_4_sector_relativity", "layer_5_insider_conviction",
    "layer_6_geopolitics", "layer_7_supply_chain",
)

#: Vocabulary that belongs on a card and never in a sentence someone hears.
#:
#: The em dash is deliberately NOT here. It is ordinary prose punctuation and a
#: natural pause when spoken -- "NVIDIA Corp. -- it looks interesting" is how
#: someone talks. The bullet is a different thing: it is a field separator from
#: the card layout, and hearing one means a telemetry line reached the voice.
JARGON = ("σ", "sigma", "alpha_z", "10b5-1", "bps", "pp ", "FCF", "ROIC",
          "n/a", "N/A", "None", "null", "NaN", "•")


# ------------------------------------------------------------ every layer

@pytest.mark.parametrize("name", ALL_LAYERS)
def test_every_layer_can_speak_when_it_has_nothing(name):
    """Absence is the commonest answer; it still has to be a sentence."""
    said = say_layer(name, {"available": False, "detail": {}})
    assert said, f"{name} says nothing when it has no data"
    assert said[0].isupper(), f"{name} absence does not start a sentence: {said!r}"
    assert said.endswith("."), f"{name} absence is not punctuated: {said!r}"


@pytest.mark.parametrize("name", ALL_LAYERS)
def test_absence_never_sounds_like_a_broken_sensor(name):
    said = say_layer(name, {"available": False, "detail": {}}).lower()
    for banned in ("no classifiable", "unavailable", "error", "failed",
                   "none", "null", "n/a"):
        assert banned not in said, f"{name} absence reads as a fault: {said!r}"


@pytest.mark.parametrize("name", ALL_LAYERS)
def test_no_layer_leaks_jargon_into_speech(name):
    """Both branches -- with data and without."""
    rich = {
        "available": True,
        "detail": {"gross_margin": 0.71, "fcf_margin": 0.44, "roic": 0.62,
                   "gross_margin_delta_pp": -3.9, "yield_10y": 4.97, "vix": 15.0,
                   "rate_sensitivity": 0.86, "headline_count": 18,
                   "weighted_tone": 0.0007, "freshest_age_hours": 0.45,
                   "alpha_z": -0.69, "sector_etf": "XLK", "sessions": 119,
                   "tier": "ROUTINE", "sold_usd": 660665685.48, "bought_usd": 0.0,
                   "planned_trade_count": 6, "discretionary_trade_count": 14,
                   "edge_count": 3, "weakest_link": "Customer One",
                   "max_concentration": 0.25},
    }
    for layer in (rich, {"available": False, "detail": {}}):
        said = say_layer(name, layer)
        for bad in JARGON:
            assert bad not in said, f"{name} spoke {bad!r}: {said!r}"


@pytest.mark.parametrize("name", ALL_LAYERS)
def test_no_raw_float_precision_reaches_the_ear(name):
    """0.7106808435754708 is 'about 71%'. Nobody says nine decimal places."""
    said = say_layer(name, {
        "available": True,
        "detail": {"gross_margin": 0.7106808435754708,
                   "fcf_margin": 0.44770258129648327,
                   "roic": 0.6251789247520666, "alpha_z": -0.69361111,
                   "sessions": 119, "sector_etf": "XLK", "vix": 15.0600004,
                   "yield_10y": 4.970000267, "weighted_tone": 0.00071111,
                   "headline_count": 18, "tier": "ROUTINE",
                   "sold_usd": 660665685.48, "max_concentration": 0.2511111},
    })
    long_decimal = re.search(r"\d+\.\d{3,}", said)
    assert long_decimal is None, f"{name} spoke raw precision: {long_decimal!r} in {said!r}"


# --------------------------------------------------------- specific voices

def test_banks_and_reits_are_explained_not_reported_as_missing():
    """No gross profit is accounting, not a data failure -- and the layer IS
    available, so 'I couldn't read it' would be a lie."""
    said = say_layer("layer_1_fundamentals",
                     {"available": True, "detail": {"roic": 0.072}})
    assert "couldn't" not in said.lower()
    assert "7%" in said


def test_insider_buying_is_called_out_as_unusual():
    said = say_layer("layer_5_insider_conviction", {
        "available": True,
        "detail": {"tier": "ACCUMULATION", "bought_usd": 12_500_000.0,
                   "sold_usd": 0.0}})
    assert "buying" in said.lower()
    assert "$13 million" in said or "$12 million" in said


def test_heavy_selling_is_not_softened_into_routine():
    said = say_layer("layer_5_insider_conviction", {
        "available": True,
        "detail": {"tier": "ABNORMAL_DISTRIBUTION", "sold_usd": 65_300_000.0,
                   "discretionary_trade_count": 4}}).lower()
    assert "heavily" in said
    assert "routine" not in said


def test_a_quiet_news_week_is_not_a_broken_feed():
    said = say_layer("layer_3_news_velocity",
                     {"available": False, "detail": {}}).lower()
    assert "nothing much in the news" in said


# ------------------------------------------------------------- whole answer

def _result(**over):
    base = {
        "company_name": "NVIDIA Corp.", "ticker": "NVDA",
        "verdict": "ACCUMULATE", "reason": "the business prints cash",
        "coverage": 0.76, "liar_filter_status": "CLEAN",
        "layers": {
            "layer_1_fundamentals": {"available": True, "detail": {
                "gross_margin": 0.71, "fcf_margin": 0.45, "roic": 0.62}},
            "layer_7_supply_chain": {"available": False, "detail": {}},
        },
    }
    base.update(over)
    return base


def test_the_answer_opens_with_the_company_and_the_verdict():
    said = spoken_answer(_result())
    assert said.startswith("NVIDIA Corp."), said[:60]
    assert "interesting" in said


def test_a_reason_fragment_is_capitalised_after_the_opener():
    """Layers write reasons as clauses; '. the business' reads as a typo."""
    said = spoken_answer(_result())
    assert ". The business prints cash." in said, said


def test_partial_coverage_is_admitted_out_loud():
    said = spoken_answer(_result(coverage=0.76)).lower()
    assert "partial" in said or "couldn't check" in said


def test_very_low_coverage_tells_you_not_to_lean_on_it():
    assert "wouldn't" in say_coverage(0.3).lower()


def test_full_coverage_adds_no_disclaimer():
    assert say_coverage(1.0) == ""


def test_a_liar_filter_divergence_is_surfaced_not_buried():
    said = spoken_answer(_result(
        liar_filter_status="DIVERGENCE",
        liar_filter_detail="reported margins do not match the cash flow statement"))
    assert "doesn't add up" in said
    assert "cash flow statement" in said


def test_the_whole_answer_carries_no_jargon():
    said = spoken_answer(_result())
    for bad in JARGON:
        assert bad not in said, f"spoke {bad!r}: {said!r}"


def test_a_missing_layer_still_gets_said():
    said = spoken_answer(_result()).lower()
    assert "depend on" in said, "the absent supply-chain layer was silently dropped"


def test_it_survives_a_payload_with_nothing_in_it():
    """A bad ticker must not become a stack trace in the middle of speech."""
    assert isinstance(spoken_answer({}), str)
    assert spoken_answer(None) == ""
    assert say_layer("layer_1_fundamentals", None) == ""
    assert say_layer("not_a_layer", {"available": True}) == ""
