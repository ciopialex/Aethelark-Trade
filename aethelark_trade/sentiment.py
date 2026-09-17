"""
Psychological Shield & Sentiment Analysis.
Integrates Finnhub AI Sentiment (News + Social) with a fallback to the 
deterministic Loughran-McDonald Lexicon.

Layer 3 of the seven-layer radar.
"""

import os
import re
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# --- Optional Finnhub Integration ---
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")
_finnhub_client = None

if FINNHUB_API_KEY:
    try:
        import finnhub
        _finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)
        logger.info("Finnhub API initialized for Sentiment Analysis.")
    except ImportError:
        logger.warning("Finnhub API key found, but 'finnhub-python' not installed.")

# --- 1. The "Clickbait" Filter (The Pastel Filter) ---
CLICKBAIT_PATTERNS = [
    r"you won't believe", r"shocking truth", r"here is why", r"here's why",
    r"forget (?:tesla|nvidia|apple|amazon|meta|google|microsoft|\w+)",
    r"is it too late", r"should you buy", r"expert reveals", r"millionaire",
    r"\b\d+x\b", r"next (?:tesla|nvidia|apple|amazon)",
    r"scam\b", r"exposed\b", r"secret\b", r"nightmare\b",
    r"dream stock", r"miracle\b", r"holy grail", r"game changer"
]
COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in CLICKBAIT_PATTERNS]

# --- 2. High-Impact Catalyst Patterns (Asymmetric Financial Signals) ---
CATALYST_PATTERNS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"\b(?:raises?|hiked|boosts?|lifts?|increases?|upgraded?)\s+(?:(?:full[- ]year|fy|q\d|annual|revenue|earnings|profit|margin)\s+)*(?:guidance|forecast|outlook)\b", re.I), 1.8),
    (re.compile(r"\b(?:guidance|forecast|outlook)\s+(?:raised|hiked|boosted|lifted|increased|upgraded)\b", re.I), 1.8),
    (re.compile(r"\bups?\s+guidance\b", re.I), 1.5),

    (re.compile(r"\b(?:cuts?|slashed|lowered|reduced|withdrew|withdraws?|downgraded?)\s+(?:(?:full[- ]year|fy|q\d|annual|revenue|earnings|profit|margin)\s+)?guidance\b", re.I), -2.2),
    (re.compile(r"\bguidance\s+(?:cut|slashed|lowered|reduced|withdrawn|downgrade)\b", re.I), -2.2),
    (re.compile(r"\bslashes?\s+(?:full[- ]year\s+|annual\s+)?(?:forecast|outlook|guidance)\b", re.I), -2.2),
    (re.compile(r"\blowers?\s+(?:full[- ]year\s+|annual\s+)?(?:forecast|outlook|guidance)\b", re.I), -2.0),
    (re.compile(r"\bprofit\s+warning\b", re.I), -2.0),
    (re.compile(r"\bwithdraws?\s+guidance\b", re.I), -2.2),

    # Earnings Surprises & Execution
    (re.compile(r"\bcrushes?\s+(?:earnings|estimates|expectations|forecasts?)\b", re.I), 1.8),
    (re.compile(r"\bblowout\s+(?:quarter|earnings|results)\b", re.I), 1.7),
    (re.compile(r"\bbeats?\s+(?:earnings|estimates|expectations|on top and bottom|revenue estimates|by\b)", re.I), 1.5),
    (re.compile(r"\bearnings\s+beat\b", re.I), 1.5),
    (re.compile(r"\brecord\s+(?:quarterly\s+)?(?:profit|earnings|revenue|sales)\b", re.I), 1.5),
    (re.compile(r"\bprofit\s+(?:surges?|jumps?|soars?|doubles?|triples?)\b", re.I), 1.5),
    (re.compile(r"\brevenue\s+(?:surges?|jumps?|soars?|accelerates?)\b", re.I), 1.4),

    (re.compile(r"\bmisses?\s+(?:earnings|estimates|expectations|forecasts?|eps)\b", re.I), -1.8),
    (re.compile(r"\bearnings\s+miss\b", re.I), -1.8),
    (re.compile(r"\bprofit\s+(?:falls?|drops?|plunges?|slumps?|tumbles?|declines?|sinks?)\b", re.I), -1.5),
    (re.compile(r"\brevenue\s+(?:falls?|drops?|plunges?|slumps?|declines?|sinks?)\b", re.I), -1.4),
    (re.compile(r"\bposts?\s+(?:wider\s+)?loss\b", re.I), -1.4),

    # Accounting, Fraud, Regulators, Distress (Asymmetric Negative)
    (re.compile(r"\baccounting\s+(?:probe|fraud|irregularities|scandal|investigation|issues?)\b", re.I), -2.8),
    (re.compile(r"\b(?:sec|doj)\s+(?:probe|investigation|inquiry|charges|subpoena|launches investigation)\b", re.I), -2.5),
    (re.compile(r"\bcriminal\s+(?:probe|investigation|charges|indictment|fraud)\b", re.I), -2.8),
    (re.compile(r"\b(?:investigation|probe)\s+into\s+(?:fraud|revenue recognition)\b", re.I), -2.8),
    (re.compile(r"\bauditor\s+(?:resigns?|quits?|departure)\b", re.I), -2.6),
    (re.compile(r"\b(?:chapter\s+11|bankruptcy|bankrupt|insolvent|receivership)\b", re.I), -3.0),
    (re.compile(r"\bdefaults?\s+(?:on\s+debt|on\s+notes?|on\s+coupon|payment)\b", re.I), -2.7),
    (re.compile(r"\bdefaulted\s+(?:on\s+debt|on\s+senior|on\s+notes?|on\s+coupon)\b", re.I), -2.7),

    # Executive changes under distress
    (re.compile(r"\bcfo\s+(?:departs?|resigns?|steps down|quits?|replaced|ousted)\b", re.I), -1.6),
    (re.compile(r"\bceo\s+(?:fired|ousted|steps down amid|resigns amid)\b", re.I), -2.2),

    # Approvals, Buybacks, Upgrades / Downgrades
    (re.compile(r"\bfda\s+(?:approves?|approval|clears?|clearance)\b", re.I), 1.6),
    (re.compile(r"\bfda\s+(?:rejects?|denies?|rejection|halts?)\b", re.I), -2.0),
    (re.compile(r"\b(?:authorizes?|announces?)\s+\$[\d\.]+[bm]\s+(?:share\s+)?buyback\b", re.I), 1.4),
    (re.compile(r"\bhikes?\s+dividend\b", re.I), 1.3),
    (re.compile(r"\bcuts?\s+dividend\b", re.I), -1.8),
    (re.compile(r"\bupgraded?\s+to\s+(?:buy|outperform|overweight|strong buy)\b", re.I), 1.3),
    (re.compile(r"\bdowngraded?\s+to\s+(?:sell|underperform|underweight|strong sell)\b", re.I), -1.5),
    (re.compile(r"\b(?:wins?|awarded|secures?)\s+(?:\$[\d\.]+[bm]\s+)?(?:[\w-]+\s+)*contract\b", re.I), 1.5),
]

PERCENT_DROP_RE = re.compile(
    r"\b(?:plunges?|drops?|tumbles?|sinks?|falls?|slides?|crashes?|down|slumps?)\s+(?:by\s+)?(\d+(?:\.\d+)?)\s*%",
    re.I,
)
PERCENT_SURGE_RE = re.compile(
    r"\b(?:surges?|jumps?|soars?|spikes?|rallies?|up|gains?)\s+(?:by\s+)?(\d+(?:\.\d+)?)\s*%",
    re.I,
)

# --- 3. The "Hard Fact" Lexicon (Secondary Nuances) ---
POSITIVE_WORDS = {
    "profitable", "beat", "surpass", "exceed", "record",
    "approved", "approval", "authorize", "authorization", "awarded",
    "buyback", "repurchase", "outperform", "bullish",
    "unveil", "breakthrough", "accelerate", "accelerating",
}

NEGATIVE_WORDS = {
    "unprofitable", "miss", "missed", "halt", "halted",
    "terminate", "terminated", "termination", "lawsuit",
    "litigation", "investigation", "probe", "subpoena", "fraud",
    "scandal", "breach", "bankrupt", "bankruptcy", "insolvent",
    "default", "underperform", "bearish", "recall", "ousted",
    "slump", "slumping",
}

SOURCE_OFFICIAL = {"business wire", "pr newswire", "globenewswire", "sec", "company announcement"}
SOURCE_MEDIA = {"reuters", "bloomberg", "cnbc", "wsj", "marketwatch", "barrons", "ft.com", "yahoofinance"}
SOURCE_BLOG = {"motley fool", "seeking alpha", "benzinga", "investorplace", "tipranks", "zacks", "barchart"}


def analyze_headline(headline: str, source: str = "") -> dict:
    """Asymmetric headline tone classifier."""
    text = headline.lower()
    source_lower = source.lower()

    is_official = any(s in source_lower for s in SOURCE_OFFICIAL)
    is_blog = any(s in source_lower for s in SOURCE_BLOG)
    is_clickbait = "?" in headline or any(p.search(text) for p in COMPILED_PATTERNS)

    catalyst_weight = 0.0
    found_signal = False

    # 1. Percentage moves
    drop_match = PERCENT_DROP_RE.search(text)
    if drop_match:
        pct = float(drop_match.group(1))
        if pct >= 20.0:
            catalyst_weight -= 2.5
        elif pct >= 10.0:
            catalyst_weight -= 1.8
        elif pct >= 5.0:
            catalyst_weight -= 1.0
        else:
            catalyst_weight -= 0.5
        found_signal = True

    surge_match = PERCENT_SURGE_RE.search(text)
    if surge_match:
        pct = float(surge_match.group(1))
        if pct >= 20.0:
            catalyst_weight += 2.2
        elif pct >= 10.0:
            catalyst_weight += 1.6
        elif pct >= 5.0:
            catalyst_weight += 1.0
        else:
            catalyst_weight += 0.5
        found_signal = True

    # 2. Catalyst pattern matches
    for pattern, weight in CATALYST_PATTERNS:
        if pattern.search(text):
            catalyst_weight += weight
            found_signal = True

    # 3. Word lexicon matches
    words = set(re.findall(r'\b[a-z]{3,}\b', text))
    pos_matches = words.intersection(POSITIVE_WORDS)
    neg_matches = words.intersection(NEGATIVE_WORDS)

    word_weight = (len(pos_matches) * 0.5) - (len(neg_matches) * 0.7)
    total_weight = catalyst_weight + word_weight

    # Zero classifiable signal check
    if not found_signal and not pos_matches and not neg_matches:
        sentiment = "NEUTRAL"
        tone = 0.0
        confidence = 0.0
    elif total_weight > 0.3:
        sentiment = "BULLISH"
        tone = round(min(3.0, total_weight), 2)
        confidence = round(min(1.0, 0.4 + 0.2 * abs(total_weight)), 2)
    elif total_weight < -0.3:
        sentiment = "BEARISH"
        tone = round(max(-3.0, total_weight), 2)
        confidence = round(min(1.0, 0.4 + 0.2 * abs(total_weight)), 2)
    else:
        sentiment = "NEUTRAL"
        tone = 0.0
        confidence = 0.0

    color = "white"
    if is_official:
        color = "bold green" if sentiment == "BULLISH" else ("bold red" if sentiment == "BEARISH" else "bold white")
    elif is_blog or is_clickbait:
        color = "#90ee90" if sentiment == "BULLISH" else ("#ffcccb" if sentiment == "BEARISH" else "dim white")
    else:
        color = "green" if sentiment == "BULLISH" else ("red" if sentiment == "BEARISH" else "white")

    return {
        "sentiment": sentiment,
        "tone": tone,
        "confidence": confidence,
        "is_clickbait": is_clickbait,
        "is_official": is_official,
        "style": color,
    }

def get_sentiment_signal(ticker: str) -> dict:
    """Get Layer 3 sentiment signal. Uses Finnhub AI if available, else 0."""
    if not _finnhub_client:
        return {"signal_strength": 0.0, "source": "none"}
        
    try:
        # Get News Sentiment
        news = _finnhub_client.news_sentiment(ticker)
        
        # news contains 'buzz' (article volume) and 'sentiment'
        # sectorAverageBullishPercent, bullishPercent
        bull_pct = news.get("sentiment", {}).get("bullishPercent", 0.5)
        sector_bull_pct = news.get("sentiment", {}).get("sectorAverageBullishPercent", 0.5)
        
        # Scale to [-1, 1]
        news_signal = (bull_pct - 0.5) * 2.0
        
        # Get Social Sentiment (Reddit + Twitter)
        # Fetching last 7 days
        today = datetime.now().strftime("%Y-%m-%d")
        last_week = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        
        social = _finnhub_client.stock_social_sentiment(ticker, _from=last_week, to=today)
        
        reddit = social.get("reddit", [])
        twitter = social.get("twitter", [])
        
        # Aggregate social metrics
        sm_bull = sum(r.get("positiveMention", 0) for r in reddit) + sum(t.get("positiveMention", 0) for t in twitter)
        sm_bear = sum(r.get("negativeMention", 0) for r in reddit) + sum(t.get("negativeMention", 0) for t in twitter)
        sm_total = max(sm_bull + sm_bear, 1)
        
        social_signal = ((sm_bull - sm_bear) / sm_total)
        
        # Composite Signal (70% News AI, 30% Social Retail)
        composite = (news_signal * 0.7) + (social_signal * 0.3)
        
        return {
            "signal_strength": round(float(composite), 4),
            "news_bull_pct": bull_pct,
            "social_mentions": sm_total,
            "source": "finnhub"
        }
    except Exception as e:
        logger.warning(f"[{ticker}] Finnhub sentiment failed: {e}")
        return {"signal_strength": 0.0, "source": "error"}

# --- 7-Layer Intelligence Integration (Fear/Greed Replacement) ---

def calculate_fear_greed(ticker: str) -> object:
    """Calculate Fear/Greed score based on the latest 7-Layer Telemetry."""
    from aethelark_trade.db import get_db
    
    class Result:
        score = 50
        rating = "NEUTRAL"
        trend = "FLAT"
        buy_count = 0
        sell_count = 0
        synthesis = "No recent radar telemetry found."
        nue = 0.0

    res = Result()
    db = get_db()
    try:
        # Get latest snapshot
        row = db.execute(
            "SELECT nue_score, verdict_label, synthesis, buy_count, sell_count FROM telemetry_snapshots WHERE ticker = ? ORDER BY snapshot_time DESC LIMIT 1",
            (ticker.upper(),)
        ).fetchone()
        
        if row:
            res.nue = row["nue_score"] / 100.0  # database stores it scaled * 100
            res.rating = row["verdict_label"]
            res.synthesis = row["synthesis"]
            res.buy_count = row["buy_count"]
            res.sell_count = row["sell_count"]
            
            # Map NUE (-1.0 to 1.0) to Score (0 to 100)
            # 0.0 NUE = 50 Score
            res.score = int((res.nue + 1.0) * 50)
            res.score = max(0, min(100, res.score))
            
    except Exception as e:
        logger.warning(f"Failed to fetch Fear/Greed for {ticker}: {e}")
    finally:
        db.close()
        
    return res

def generate_narrative(fg, ticker: str) -> str:
    """Return the Radar's 7-layer synthesis as the narrative."""
    return getattr(fg, "synthesis", "Awaiting radar scan...")

def get_gauge_context(fg) -> str:
    """Return a descriptive label for the gauge activity."""
    if not hasattr(fg, "nue"):
        return "Initial Scan Pending"
        
    if fg.nue > 0.4: return "High Conviction Inflow"
    if fg.nue > 0.15: return "Moderate Accumulation"
    if fg.nue < -0.4: return "High Conviction Outflow"
    if fg.nue < -0.15: return "Moderate Distribution"
    return "Neutral System Noise"
