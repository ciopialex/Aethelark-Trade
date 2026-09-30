"""Test Task 6: Layer 3 sentiment classifier and catalyst awareness."""
from datetime import datetime, timezone
import pytest

from aethelark_trade.sentiment import analyze_headline
from aethelark_trade.engine.layers.news_velocity import (
    Headline,
    headline_tone,
    score_news_velocity,
)

NOW = datetime(2026, 8, 19, 15, 0, tzinfo=timezone.utc)

TEST_HEADLINES_TABLE = [
    # 1. Strong guidance and earnings beats
    ("Crushes earnings, raises guidance", "BULLISH", 80, 100),
    ("Posts record quarterly profit, beats revenue estimates", "BULLISH", 80, 100),
    ("Blowout quarter: revenue up 45% year-over-year", "BULLISH", 80, 100),
    ("FDA approves landmark cancer therapy, stock surges 25%", "BULLISH", 80, 100),
    ("Authorizes $10B share buyback program and hikes dividend", "BULLISH", 70, 100),
    ("Wins $5B cloud contract with Department of Defense", "BULLISH", 70, 100),
    ("Upgraded to Strong Buy at Goldman Sachs on accelerating growth", "BULLISH", 70, 100),
    ("Company raises full-year profit outlook on strong demand", "BULLISH", 75, 100),

    # 2. Guidance cuts, drops, accounting/legal catastrophe
    ("Plunges 40% after guidance cut, CFO departs", "BEARISH", 0, 20),
    ("Misses EPS by $0.40, cuts full-year guidance", "BEARISH", 0, 20),
    ("CEO resigns amid DOJ accounting probe", "BEARISH", 0, 20),
    ("SEC launches investigation into revenue recognition, shares sink 15%", "BEARISH", 0, 20),
    ("Auditor resigns citing internal control deficiencies", "BEARISH", 0, 20),
    ("Files for Chapter 11 bankruptcy protection", "BEARISH", 0, 15),
    ("Defaulted on senior notes coupon payment", "BEARISH", 0, 15),
    ("Downgraded to Sell at Morgan Stanley following market share loss", "BEARISH", 0, 30),
    ("Issues profit warning as demand slumps in Europe", "BEARISH", 0, 25),

    # 3. Neutral boilerplate with zero classifiable tone
    ("Company reports Q3 revenue", "NEUTRAL", None, None),
    ("Annual meeting of shareholders scheduled for June 10", "NEUTRAL", None, None),
    ("To participate in upcoming investor conference", "NEUTRAL", None, None),
    ("Files Form 10-Q with SEC for second quarter", "NEUTRAL", None, None),
]


@pytest.mark.parametrize("title,expected_sentiment,min_score,max_score", TEST_HEADLINES_TABLE)
def test_headline_table_directional_correctness(title, expected_sentiment, min_score, max_score):
    res = analyze_headline(title, source="Reuters")
    assert res["sentiment"] == expected_sentiment

    if expected_sentiment == "NEUTRAL":
        # Neutral headlines with zero sentiment signal must report low confidence / unavailable, not 50
        assert res["confidence"] == 0.0
        score_res = score_news_velocity([Headline(title, NOW, "Reuters")], now=NOW)
        assert score_res.available is False
    else:
        assert res["confidence"] > 0.0
        score_res = score_news_velocity([Headline(title, NOW, "Reuters")], now=NOW)
        assert score_res.available is True
        assert min_score <= score_res.score <= max_score


def test_two_headlines_that_matter_most():
    """Specific assertion for the two critical investor headlines in Task 6."""
    h_bull = Headline("Crushes earnings, raises guidance", NOW, "Reuters")
    score_bull = score_news_velocity([h_bull], now=NOW)
    assert score_bull.available is True
    assert score_bull.score >= 80

    h_bear = Headline("Plunges 40% after guidance cut, CFO departs", NOW, "Reuters")
    score_bear = score_news_velocity([h_bear], now=NOW)
    assert score_bear.available is True
    assert score_bear.score <= 20
