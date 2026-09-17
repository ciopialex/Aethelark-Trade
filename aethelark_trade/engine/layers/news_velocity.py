"""Layer 3 -- News Velocity.

Not just tone: the *rate of change* of tone. A beat announced five minutes ago
is tradeable; the same beat three days old is priced in. Each headline's
contribution decays exponentially with age.

aethelark_trade.sentiment.get_sentiment_signal needs FINNHUB_API_KEY, which is
absent from this deployment's .env, so tone is scored with the keyless lexicon
in that same module (analyze_headline) over Google News RSS headlines.
"""

import math
from dataclasses import dataclass
from datetime import datetime

from aethelark_trade.engine.types import LayerScore
from aethelark_trade.sentiment import SOURCE_BLOG, SOURCE_OFFICIAL, analyze_headline

# A headline's weight halves roughly every 6 hours: the 15-minute spark the
# architecture calls for dominates, while day-old news fades rather than cuts off.
HALF_LIFE_HOURS = 6.0
MAX_AGE_HOURS = 72.0

# analyze_headline returns a label, not a magnitude. Tone is that label scaled
# by how much the source is worth as evidence: a company's own wire release is
# a statement of fact it can be sued over; a blog post is an opinion.
OFFICIAL_TRUST = 1.25
MEDIA_TRUST = 1.0
BLOG_TRUST = 0.6
CLICKBAIT_DISCOUNT = 0.5


@dataclass(frozen=True)
class Headline:
    title: str
    published: datetime
    source: str = ""


def _decay(age_hours: float) -> float:
    return 0.5 ** (age_hours / HALF_LIFE_HOURS)


def headline_tone(title: str, source: str = "") -> float:
    """Signed, source-weighted tone for one headline."""
    verdict = analyze_headline(title, source)
    tone = verdict.get("tone")
    if tone is None:
        base = {"BULLISH": 1.0, "BEARISH": -1.0}.get(verdict.get("sentiment", ""), 0.0)
    else:
        base = float(tone)

    if base == 0.0:
        return 0.0

    source_lower = source.lower()
    if verdict.get("is_official") or any(s in source_lower for s in SOURCE_OFFICIAL):
        trust = OFFICIAL_TRUST
    elif any(s in source_lower for s in SOURCE_BLOG):
        trust = BLOG_TRUST
    else:
        trust = MEDIA_TRUST

    if verdict.get("is_clickbait"):
        trust *= CLICKBAIT_DISCOUNT

    return base * trust


def score_news_velocity(headlines: list[Headline], now: datetime) -> LayerScore:
    """Recency-weighted sentiment spark over the trailing window."""
    weighted_sum = 0.0
    weight_total = 0.0
    considered = 0
    classifiable_count = 0
    freshest_hours: float | None = None

    for h in headlines:
        age_hours = (now - h.published).total_seconds() / 3600.0
        if age_hours < 0 or age_hours > MAX_AGE_HOURS:
            continue
        verdict = analyze_headline(h.title, h.source)
        tone = headline_tone(h.title, h.source)
        weight = _decay(age_hours)
        considered += 1

        if verdict.get("confidence", 0.0) > 0 and abs(tone) > 0:
            classifiable_count += 1
            weighted_sum += tone * weight
            weight_total += weight

        if freshest_hours is None or age_hours < freshest_hours:
            freshest_hours = age_hours

    if considered == 0 or classifiable_count == 0 or weight_total == 0 or freshest_hours is None:
        return LayerScore.unavailable("No classifiable news sentiment")

    # Normalise by the decayed weight but never by less than one full headline.
    mean_tone = weighted_sum / max(weight_total, 1.0)
    score = max(0, min(100, round(50 + 50 * math.tanh(mean_tone))))

    return LayerScore(
        score=score,
        summary=(
            f"{considered} headlines • freshest {freshest_hours:.1f}h old • "
            f"weighted tone {mean_tone:+.2f}"
        ),
        detail={
            "headline_count": considered,
            "weighted_tone": round(mean_tone, 4),
            # The Liar Filter compares this against C-suite selling.
            "sentiment_pct": float(score),
            "freshest_age_hours": round(freshest_hours, 2),
        },
    )
