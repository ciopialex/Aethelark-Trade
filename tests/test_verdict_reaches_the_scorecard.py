"""BEHAVIOR_SPEC §30 — the verdict a person actually sees.

`engine/verdict.py` implements the whole of §30 and is pinned by 22 tests. None
of them prove the engine *calls* it: `assemble_result` used the old score-band
function in `scoring.py`, so every card ever drawn showed a band derived from
the composite — the exact thing §30.2 forbids.

These are the wiring tests. They assert on what `analyze` hands the island.
"""
from __future__ import annotations

from aethelark_trade.engine.engine import assemble_result
from aethelark_trade.engine.liar_filter import LiarFilterResult
from aethelark_trade.engine.types import LayerScore

FIVE_WORDS = {"ACCUMULATE", "WATCH", "NEUTRAL", "CAUTION", "AVOID"}
BANNED = {"BULLISH", "BEARISH", "HOLD"}


def _result(scores: dict[str, int]):
    layers = {name: LayerScore(score=s, summary=f"{name} at {s}")
              for name, s in scores.items()}
    return assemble_result(
        ticker="TEST", layers=layers,
        liar_filter=LiarFilterResult(status="CLEAN", news_sentiment_pct=50.0,
                                     csuite_net_usd=0.0, window_days=90,
                                     detail="no divergence"),
        ema25=100.0,
    )


ALL_NEUTRAL = {n: 50 for n in (
    "layer_1_fundamentals", "layer_2_macro_gravity", "layer_3_news_velocity",
    "layer_4_sector_relativity", "layer_5_insider_conviction",
    "layer_6_geopolitics", "layer_7_supply_chain")}


def test_the_verdict_is_one_of_exactly_five_words():
    """§30.1. A sixth word in the verdict slot breaks the spec."""
    for shift in (0, 20, 40, -20, -40):
        scores = {n: max(0, min(100, v + shift)) for n, v in ALL_NEUTRAL.items()}
        assert _result(scores).verdict in FIVE_WORDS


def test_the_old_score_band_vocabulary_never_appears():
    """§30.1 falsification. BULLISH/BEARISH/HOLD are what scoring.py emits."""
    for shift in (0, 25, 45, -25, -45):
        scores = {n: max(0, min(100, v + shift)) for n, v in ALL_NEUTRAL.items()}
        assert _result(scores).verdict not in BANNED


def test_a_verdict_comes_with_a_reason():
    """§30.3. Every verdict except NEUTRAL carries one plain clause."""
    scores = dict(ALL_NEUTRAL, layer_5_insider_conviction=95)
    got = _result(scores)
    assert got.verdict != "NEUTRAL"
    assert got.reason, "a verdict without a reason breaks §30.3"


def test_neutral_quotes_no_evidence():
    """§30.5. A mild factor is never quoted as though it decided something."""
    got = _result(ALL_NEUTRAL)
    assert got.verdict == "NEUTRAL"
    assert got.reason == "nothing stands out either way"


def test_the_reason_reaches_the_card_payload():
    """The island reads to_dict(). A reason the payload drops is not on screen."""
    scores = dict(ALL_NEUTRAL, layer_5_insider_conviction=95)
    payload = _result(scores).to_dict()
    assert "reason" in payload, "to_dict() drops the reason before the card sees it"
    assert payload["reason"]
    assert payload["verdict"] in FIVE_WORDS


def test_the_reason_carries_no_jargon():
    """§30.8. No sigma, no z-score, no 'asymmetry', no formula."""
    scores = dict(ALL_NEUTRAL, layer_4_sector_relativity=8)
    reason = _result(scores).reason.lower()
    for jargon in ("sigma", "σ", "z-score", "asymmetry", "composite", "weighted"):
        assert jargon not in reason, f"{jargon!r} is jargon (§30.8)"
