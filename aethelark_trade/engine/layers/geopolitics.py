"""Layer 6 -- Macro Regime Stress.

Originally specified against GDELT GKG tone, but aethelark_trade.geo_pulse only
populates that via an async daemon that has never run, leaving the layer
permanently unavailable and 8% of every verdict blank.

Volatility and the Treasury curve are priced continuously and capture the same
thing the geopolitical layer was meant to: how much systemic stress the world
is pricing right now. An inverted 10Y-2Y curve is the market saying it expects
the front end to be cut, i.e. that something breaks first.
"""

import math

from aethelark_trade.engine.types import LayerScore

# A healthy expansion prices a modest upward slope. Zero is not neutral -- a
# flat curve is late-cycle, and inversion has preceded every modern recession.
CURVE_NEUTRAL_SPREAD = 0.5
CURVE_SCALE = 1.0

VIX_NEUTRAL = 18.0
VIX_SCALE = 10.0

# The curve is the regime signal; VIX is the acute-stress signal. Regime leads.
COMPONENT_WEIGHTS = {"curve": 0.55, "vix": 0.45}


class RegimeProxies:
    """Market-priced macro stress inputs. None means unfetchable."""

    __slots__ = ("vix", "yield_10y", "yield_2y")

    def __init__(self, vix=None, yield_10y=None, yield_2y=None):
        self.vix = vix
        self.yield_10y = yield_10y
        self.yield_2y = yield_2y

    def __repr__(self):
        return (
            f"RegimeProxies(vix={self.vix}, yield_10y={self.yield_10y}, "
            f"yield_2y={self.yield_2y})"
        )


def curve_spread(proxies: RegimeProxies) -> float | None:
    """10Y minus 2Y, in percentage points. Negative means inverted."""
    if proxies.yield_10y is None or proxies.yield_2y is None:
        return None
    return proxies.yield_10y - proxies.yield_2y


def _saturating(value: float, scale: float) -> float:
    return 50 + 50 * math.tanh(value / scale)


def score_macro_regime(proxies: RegimeProxies) -> LayerScore:
    """Score systemic stress from the curve and implied volatility."""
    parts: dict[str, float] = {}
    bits: list[str] = []

    spread = curve_spread(proxies)
    if spread is not None:
        parts["curve"] = _saturating(spread - CURVE_NEUTRAL_SPREAD, CURVE_SCALE)
        shape = "inverted" if spread < 0 else ("flat" if spread < 0.25 else "positive")
        bits.append(f"10Y-2Y {spread:+.2f}pp ({shape})")

    if proxies.vix is not None:
        parts["vix"] = _saturating(-(proxies.vix - VIX_NEUTRAL), VIX_SCALE)
        bits.append(f"VIX {proxies.vix:.1f}")

    if not parts:
        return LayerScore.unavailable("No regime proxies available")

    weight_total = sum(COMPONENT_WEIGHTS[k] for k in parts)
    score = sum(COMPONENT_WEIGHTS[k] * v for k, v in parts.items()) / weight_total
    score = max(0, min(100, round(score)))

    if score >= 70:
        label = "Benign regime"
    elif score >= 45:
        label = "Neutral regime"
    elif score >= 25:
        label = "Tightening regime"
    else:
        label = "Acute systemic stress"

    return LayerScore(
        score=score,
        summary=f"{label} • " + " • ".join(bits),
        detail={
            "vix": proxies.vix,
            "yield_10y": proxies.yield_10y,
            "yield_2y": proxies.yield_2y,
            "curve_spread": spread,
        },
    )
