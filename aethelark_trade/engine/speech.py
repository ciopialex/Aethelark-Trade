"""Turning a scorecard into something a person would actually say.

Every layer already produces a `summary`, and every one of them is telemetry:

    -0.7σ alpha vs XLK (-0.08%/day excess over 119 sessions)
    Routine liquidation • -$660.7M net selling • 14 discretionary / 6 on 10b5-1
    No classifiable news sentiment

Those are right for the card, where a dense line in a small box is the point.
They are wrong for a voice, which is the product: nobody asks a friend about a
company and gets back a sigma against a sector ETF.

Two rules shape everything here.

**Absence has to sound like absence.** Measured across NVDA, JPM, KO and AMT,
a typical company is missing two of its layers -- so "I don't know" is this
engine's most frequently spoken sentence, and `No classifiable news sentiment`
reads as a broken sensor rather than a quiet week. Each layer carries its own
phrasing for having nothing, in the same voice as having something.

**Numbers get rounded to what a person says.** `0.7106808435754708` is
"about 71%". Precision the speaker cannot justify is not precision.

Nothing here scores anything or changes a verdict. It reads the `detail` dicts
the layers already emit and writes sentences. A layer that changes its numbers
changes its sentence for free; a layer that adds a field is simply not spoken
until someone teaches it a phrase.
"""

from __future__ import annotations

# Sessions per calendar month, for turning a window into a human duration.
_SESSIONS_PER_MONTH = 21


def _months(sessions) -> str:
    """119 sessions -> 'about six months'."""
    try:
        n = round(float(sessions) / _SESSIONS_PER_MONTH)
    except (TypeError, ValueError):
        return "the recent past"
    words = {1: "a month", 2: "two months", 3: "three months", 4: "four months",
             5: "five months", 6: "six months", 9: "nine months", 12: "a year"}
    if n in words:
        return f"about {words[n]}" if n != 1 else "about a month"
    return f"about {n} months"


def _usd(value) -> str:
    """660665685.48 -> '$661 million'. Spoken scale, not accounting precision."""
    try:
        v = abs(float(value))
    except (TypeError, ValueError):
        return "an unclear amount"
    if v >= 1e12:
        return f"${v / 1e12:.1f} trillion"
    if v >= 1e9:
        return f"${v / 1e9:.1f} billion"
    if v >= 1e6:
        return f"${v / 1e6:.0f} million"
    if v >= 1e3:
        return f"${v / 1e3:.0f} thousand"
    return f"${v:,.0f}"


def _pct(value, digits: int = 0) -> str:
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "an unclear share"


def _num(value, digits: int = 1):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------- per layer

def _say_fundamentals(d: dict, available: bool) -> str:
    if not available:
        return "I couldn't get a clean read on their financials."

    gm, fcf, roic = d.get("gross_margin"), d.get("fcf_margin"), d.get("roic")
    delta = _num(d.get("gross_margin_delta_pp"))
    bits: list[str] = []

    if gm is not None:
        bits.append(f"gross margins around {_pct(gm)}")
    if fcf is not None:
        bits.append(f"and they keep about {_pct(fcf)} of revenue as free cash")

    if not bits and roic is not None:
        # Banks and REITs report no gross profit, so the usual margin figures
        # are absent by accounting rather than by failure. Saying "no data"
        # would be wrong; saying nothing would be worse.
        return (f"The usual margin figures don't really apply to a business "
                f"like this one, but it's earning {_pct(roic)} on the capital "
                f"it employs.")

    sentence = "Financially, " + ", ".join(bits) + "."
    if roic is not None:
        quality = ("excellent" if roic > 0.30 else
                   "solid" if roic > 0.15 else
                   "modest" if roic > 0.07 else "thin")
        sentence += f" Returns on capital are {quality}, about {_pct(roic)}."
    if delta is not None and abs(delta) >= 1.0:
        way = "up" if delta > 0 else "down"
        sentence += f" Margins are {way} roughly {abs(delta):.0f} points on last year."
    return sentence


def _say_macro(d: dict, available: bool) -> str:
    if not available:
        return "I couldn't read the wider market backdrop."
    y, vix = _num(d.get("yield_10y")), _num(d.get("vix"))
    sensitivity = d.get("rate_sensitivity")
    parts = []
    if y is not None:
        parts.append(f"the ten-year sits at {y:.1f}%")
    if vix is not None:
        mood = "calm" if vix < 18 else "jumpy" if vix < 28 else "frightened"
        parts.append(f"and the market's {mood}")
    if not parts:
        return "The wider backdrop is unremarkable right now."
    tail = ""
    try:
        if sensitivity is not None and float(sensitivity) > 0.7:
            tail = " This one tends to move with rates, so that matters more than usual."
    except (TypeError, ValueError):
        pass
    return "On the backdrop, " + ", ".join(parts) + "." + tail


def _say_news(d: dict, available: bool) -> str:
    if not available:
        return "There's been nothing much in the news about them lately."
    count = d.get("headline_count")
    tone = _num(d.get("weighted_tone"), 3)
    age = _num(d.get("freshest_age_hours"))
    if not count:
        return "There's been nothing much in the news about them lately."
    if tone is None or abs(tone) < 0.15:
        mood = "and the tone is pretty even"
    elif tone > 0:
        mood = "and the coverage leans positive"
    else:
        mood = "and the coverage leans negative"
    when = ""
    if age is not None:
        when = " just in the last few hours" if age < 6 else \
               " in the last day or so" if age < 36 else ""
    return f"There are {int(count)} stories about them{when}, {mood}."


def _say_sector(d: dict, available: bool) -> str:
    if not available:
        return "I don't have a good sector benchmark to compare this one against."
    z, etf = _num(d.get("alpha_z"), 2), d.get("sector_etf")
    window = _months(d.get("sessions"))
    peers = f"the rest of {etf}" if etf else "its sector"
    if z is None:
        return f"Against {peers}, it's been roughly in line over {window}."
    if z > 1.0:
        return f"It's been clearly outrunning {peers} over {window}."
    if z > 0.25:
        return f"It's been a bit ahead of {peers} over {window}."
    if z < -1.0:
        return f"It's been lagging {peers} noticeably over {window}."
    if z < -0.25:
        return f"It's been trailing {peers} slightly over {window}."
    return f"It's been moving more or less with {peers} over {window}."


def _say_insider(d: dict, available: bool) -> str:
    if not available:
        return "No insiders have traded in the open market recently."
    tier = (d.get("tier") or "").upper()
    bought, sold = d.get("bought_usd") or 0, d.get("sold_usd") or 0
    planned, disc = d.get("planned_trade_count") or 0, d.get("discretionary_trade_count") or 0

    if tier == "ACCUMULATION":
        s = f"Insiders have actually been buying — about {_usd(bought)}."
        return s + " That's unusual, and it's the kind of thing worth paying attention to."
    if tier == "ABNORMAL_DISTRIBUTION":
        s = f"Insiders have been selling heavily, around {_usd(sold)}"
        if disc:
            s += f", and {disc} of those were discretionary rather than scheduled"
        return s + ". That's the part I'd want to understand."
    s = f"Insiders sold about {_usd(sold)}"
    if planned:
        s += f", though {planned} of those were pre-scheduled plans"
    return s + " — it reads as routine rather than anyone heading for the exit."


def _say_supply(d: dict, available: bool) -> str:
    if not available:
        return "I couldn't map who they depend on commercially."
    count = d.get("edge_count")
    weakest = d.get("weakest_link")
    conc = d.get("max_concentration")
    try:
        if conc is not None and float(conc) >= 0.20:
            return (f"A big chunk of their business — around {_pct(conc)} — "
                    f"runs through {weakest or 'a single counterparty'}.")
    except (TypeError, ValueError):
        pass
    return f"Their supply relationships look unremarkable across {count or 'a few'} mapped links."


def _say_geopolitics(d: dict, available: bool) -> str:
    if not available:
        return "Nothing geopolitical is obviously bearing on them."
    return "There's a geopolitical factor in play worth keeping in mind."


_SPEAKERS = {
    "layer_1_fundamentals": _say_fundamentals,
    "layer_2_macro_gravity": _say_macro,
    "layer_3_news_velocity": _say_news,
    "layer_4_sector_relativity": _say_sector,
    "layer_5_insider_conviction": _say_insider,
    "layer_6_geopolitics": _say_geopolitics,
    "layer_7_supply_chain": _say_supply,
}

#: Spoken in this order. Money first, then the people closest to the business,
#: then context -- which is how someone actually answers the question.
_ORDER = ("layer_1_fundamentals", "layer_5_insider_conviction",
          "layer_4_sector_relativity", "layer_3_news_velocity",
          "layer_7_supply_chain", "layer_2_macro_gravity")


def say_layer(name: str, layer: dict) -> str:
    """One layer as a sentence, whether or not it has data."""
    speaker = _SPEAKERS.get(name)
    if speaker is None:
        return ""
    if not isinstance(layer, dict):
        return ""
    return speaker(layer.get("detail") or {}, bool(layer.get("available")))


_VERDICT_OPENERS = {
    "ACCUMULATE": "It looks genuinely interesting.",
    "WATCH": "It's worth watching rather than acting on.",
    "AVOID": "I'd be careful with this one.",
}


def say_coverage(coverage) -> str:
    """Own the gaps out loud. Absence is this engine's commonest answer."""
    try:
        c = float(coverage)
    except (TypeError, ValueError):
        return ""
    if c >= 0.95:
        return ""
    if c >= 0.75:
        return "There are one or two things I couldn't check, so take it as a partial read."
    if c >= 0.5:
        return ("A fair bit of what I normally look at is missing here, so I'd hold "
                "this loosely.")
    return ("I'm missing most of what I'd normally look at, so honestly I wouldn't "
            "lean on this one.")


def spoken_answer(result: dict) -> str:
    """The whole scorecard as something a friend would say back to you."""
    if not isinstance(result, dict):
        return ""

    name = result.get("company_name") or result.get("ticker") or "this company"
    verdict = (result.get("verdict") or "").upper()
    reason = (result.get("reason") or "").strip()

    opener = _VERDICT_OPENERS.get(verdict, "Here's how it looks.")
    lines = [f"{name} — {opener}"]
    if reason:
        # The layers write reasons as clause fragments ("the business prints
        # cash"), which read as a typo once they follow a full stop.
        lines.append(reason[0].upper() + reason[1:].rstrip(".") + ".")

    layers = result.get("layers") or {}
    for key in _ORDER:
        layer = layers.get(key)
        if layer is None:
            continue
        sentence = say_layer(key, layer)
        if sentence:
            lines.append(sentence)

    liar = (result.get("liar_filter_status") or "").upper()
    if liar == "DIVERGENCE":
        detail = (result.get("liar_filter_detail") or "").strip()
        lines.append("One thing doesn't add up: " + (detail or
                     "their stated numbers don't match what the filings imply."))

    note = say_coverage(result.get("coverage"))
    if note:
        lines.append(note)

    return " ".join(lines)
