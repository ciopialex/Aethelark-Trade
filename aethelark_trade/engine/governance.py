"""Governance signal — is the CEO getting paid more than you are?

Thin structural wrapper around aethelark_trade/xbrl.py, which already reads the
SEC's Pay Versus Performance disclosure (Item 402(v), mandatory since 2023) out
of DEF 14A proxies and decodes it into a plain-English verdict. That decoder is
the asset; this only adds what the CLI and the voice layer need:

  * markup stripped, because the voice layer reads the sentence aloud and
    "open bracket bold red" is not pronounceable
  * the underlying percentages exposed, so --json consumers and the HUD can
    render rather than parse prose

Deliberately no new opinion about compensation. The judgement lives in
xbrl.decode_governance_summary() where it was written.
"""

import re
from dataclasses import dataclass, field

from aethelark_trade.xbrl import ProxyXBRL

# Closed set, matching the phrasings decode_governance_summary() emits.
#
# It did not match. Measured 2026-09-21: xbrl.py emits SHARED PAIN, RISING TIDE
# SKEPTICISM and INEFFICIENT GROWTH, none of which were listed, so `_classify`
# returned UNKNOWN for them -- INTC among them -- and the card drew no
# governance label for a company whose reading was perfectly clear. FAIR
# EXCHANGE was listed and is emitted by nothing.
#
# tests/test_governance_verdicts_are_a_closed_set.py reads the phrases straight
# out of xbrl.py and fails if the two drift apart again.
VERDICTS = (
    "FOUNDER MODE",
    "ALIGNED PERFORMANCE",
    "SHARED PAIN",
    "RISING TIDE SKEPTICISM",
    "INEFFICIENT GROWTH",
    "THE LEAK",
    "TOTAL DRAIN",
    "UNKNOWN",
)

# Verdicts that argue against owning the stock. SHARED PAIN is deliberately not
# here: management taking a bigger haircut than shareholders is an argument for
# trusting them, not against owning the company.
BEARISH_VERDICTS = ("THE LEAK", "TOTAL DRAIN")

_MARKUP = re.compile(r"\[/?[^\]]{0,40}\]")


def strip_markup(text: str) -> str:
    """Remove rich console tags. The HUD and the voice layer both need prose."""
    return _MARKUP.sub("", text or "").strip()


@dataclass(frozen=True)
class GovernanceSignal:
    available: bool
    verdict: str
    sentence: str
    ceo_name: str | None = None
    pay_change_pct: float | None = None
    tsr_change_pct: float | None = None
    bearish: bool = False
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "verdict": self.verdict,
            "sentence": self.sentence,
            "ceo_name": self.ceo_name,
            "pay_change_pct": self.pay_change_pct,
            "tsr_change_pct": self.tsr_change_pct,
            "bearish": self.bearish,
            **({"detail": self.detail} if self.detail else {}),
        }


# decode_governance_summary compares the latest year against index 2 -- a
# three-year window, not the whole disclosure. These percentages must use the
# same window or the card contradicts its own sentence.
LOOKBACK_INDEX = 2


def _pct_change(series) -> tuple[float | None, float | None, float | None]:
    """(change_pct, latest, oldest) over the same window the decoder uses."""
    values = [c.amount for c in series if c.amount is not None]
    if len(values) < 2:
        return None, None, None
    latest = values[0]
    oldest = values[min(LOOKBACK_INDEX, len(values) - 1)]
    if not oldest:
        return None, latest, oldest
    return (latest - oldest) / abs(oldest) * 100.0, latest, oldest


def _classify(sentence: str) -> str:
    upper = sentence.upper()
    for verdict in VERDICTS:
        if verdict in upper:
            return verdict
    return "UNKNOWN"


def governance_signal(proxy: ProxyXBRL) -> GovernanceSignal:
    """Structured pay-versus-performance signal for one company."""
    raw = proxy.decode_governance_summary()
    sentence = strip_markup(raw)

    usable = (
        not proxy.is_empty
        and bool(proxy.ceo_actually_paid)
        and bool(proxy.total_shareholder_return)
    )
    if not usable:
        return GovernanceSignal(
            available=False,
            verdict="UNKNOWN",
            sentence="No pay-versus-performance disclosure found in the latest proxy.",
        )

    pay_pct, pay_now, pay_then = _pct_change(proxy.ceo_actually_paid)
    tsr_pct, tsr_now, tsr_then = _pct_change(proxy.total_shareholder_return)
    verdict = _classify(sentence)

    return GovernanceSignal(
        available=True,
        verdict=verdict,
        sentence=sentence,
        ceo_name=proxy.ceo_name,
        pay_change_pct=None if pay_pct is None else round(pay_pct, 1),
        tsr_change_pct=None if tsr_pct is None else round(tsr_pct, 1),
        bearish=verdict in BEARISH_VERDICTS,
        detail={
            "ceo_pay_latest": pay_now,
            "ceo_pay_earliest": pay_then,
            "shareholder_return_latest": tsr_now,
            "shareholder_return_earliest": tsr_then,
            "years": [c.year for c in proxy.ceo_actually_paid],
        },
    )
