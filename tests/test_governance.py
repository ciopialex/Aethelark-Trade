"""Governance signal: CEO pay growth vs shareholder return.

aethelark_trade/xbrl.py already reads the SEC's Pay Versus Performance disclosure
(Item 402(v), mandatory since 2023) out of DEF 14A proxies, and
decode_governance_summary() turns it into a plain-English verdict. That output
is rich-console markup, which is unusable for --json and unspeakable by the
voice layer. This wraps it into structured data plus a clean sentence.
"""
import pytest

from aethelark_trade.engine.governance import (
    GovernanceSignal,
    VERDICTS,
    governance_signal,
    strip_markup,
)
from aethelark_trade.xbrl import CompYear, ProxyXBRL


def proxy(pay, tsr, name="Jane Doe"):
    """Build a real ProxyXBRL the way extract_proxy_xbrl would."""
    return ProxyXBRL(
        ceo_name=name,
        ceo_actually_paid=[CompYear(y, v) for y, v in pay],
        total_shareholder_return=[CompYear(y, v) for y, v in tsr],
        is_empty=False,
    )


def test_strip_markup_removes_rich_tags():
    assert strip_markup("[bold red]TOTAL DRAIN:[/bold red] pay rose") == \
        "TOTAL DRAIN: pay rose"


def test_strip_markup_leaves_plain_text_alone():
    assert strip_markup("CEO pay rose 219.8%") == "CEO pay rose 219.8%"


def test_empty_proxy_is_unavailable():
    result = governance_signal(ProxyXBRL())
    assert result.available is False
    assert result.verdict == "UNKNOWN"


def test_real_coca_cola_shape_reads_as_a_leak():
    """Measured from KO's 2026 DEF 14A: James Quincey's 'actually paid' went
    $19.3M (2023) -> $61.6M (2025) while shareholder return went 118 -> 148."""
    result = governance_signal(proxy(
        pay=[("2025", 61_649_669.0), ("2024", 40_592_982.0), ("2023", 19_275_773.0)],
        tsr=[("2025", 148.0), ("2024", 128.0), ("2023", 118.0)],
        name="James Quincey",
    ))
    assert result.available is True
    assert result.ceo_name == "James Quincey"
    assert result.pay_change_pct > 200
    assert result.tsr_change_pct == pytest.approx(25.4, abs=1.0)
    assert result.verdict in VERDICTS
    assert result.bearish is True


def test_real_nvidia_shape_reads_as_aligned():
    """Measured from NVDA's 2026 DEF 14A: Huang's pay fell while shareholder
    return went 470 -> 1445."""
    result = governance_signal(proxy(
        pay=[("2026", 162_180_936.0), ("2025", 344_188_027.0), ("2024", 234_132_305.0)],
        tsr=[("2026", 1445.67), ("2025", 1100.69), ("2024", 470.88)],
        name="Jen-Hsun Huang",
    ))
    assert result.pay_change_pct < 0
    assert result.tsr_change_pct > 200
    assert result.bearish is False


def test_sentence_is_speakable_and_carries_no_markup():
    """The voice layer reads this aloud; brackets are not pronounceable."""
    result = governance_signal(proxy(
        pay=[("2025", 61_649_669.0), ("2023", 19_275_773.0)],
        tsr=[("2025", 148.0), ("2023", 118.0)],
    ))
    assert "[" not in result.sentence and "]" not in result.sentence
    assert result.sentence.strip()


def test_signal_serialises_for_the_module_bus():
    payload = governance_signal(proxy(
        pay=[("2025", 61_649_669.0), ("2023", 19_275_773.0)],
        tsr=[("2025", 148.0), ("2023", 118.0)],
    )).to_dict()
    for key in ("available", "ceo_name", "verdict", "sentence",
                "pay_change_pct", "tsr_change_pct", "bearish"):
        assert key in payload


def test_missing_shareholder_return_is_unavailable_not_a_guess():
    result = governance_signal(proxy(
        pay=[("2025", 61_649_669.0), ("2023", 19_275_773.0)], tsr=[]))
    assert result.available is False


def test_verdicts_are_a_closed_set():
    assert "UNKNOWN" in VERDICTS
    assert len(VERDICTS) >= 5


# --------------------------------------------------- founder-mode false positive
def test_missing_total_comp_does_not_claim_founder_mode():
    """xbrl.decode_governance_summary defaults total_comp_latest to 0 when the
    ceo_total_comp series is absent, and 0 < 100000, so ANY company whose stock
    rose was declared 'FOUNDER MODE (Extreme Bullish) — CEO takes negligible
    salary'. Absence of evidence became the strongest bullish claim available.

    Founder mode is a positive assertion. It needs the number that supports it.
    """
    leaking = proxy(
        pay=[("2025", 61_649_669.0), ("2024", 40_592_982.0), ("2023", 19_275_773.0)],
        tsr=[("2025", 148.0), ("2024", 128.0), ("2023", 118.0)],
        name="James Quincey",
    )
    assert leaking.ceo_total_comp == []          # the field that failed to parse
    result = governance_signal(leaking)
    assert result.verdict != "FOUNDER MODE"
    assert result.bearish is True


def test_genuine_founder_mode_still_reads_as_founder_mode():
    """A real $1-salary CEO with the stock up must still be recognised."""
    founder = proxy(
        pay=[("2025", 1.0), ("2023", 1.0)],
        tsr=[("2025", 300.0), ("2023", 100.0)],
        name="Real Founder",
    )
    object.__setattr__(founder, "ceo_total_comp",
                       [CompYear("2025", 1.0), CompYear("2023", 1.0)])
    assert governance_signal(founder).verdict == "FOUNDER MODE"


def test_percentages_match_the_sentence_window():
    """decode_governance_summary compares against a 3-year lookback, not the
    full series. Measuring the whole series instead produced KO reading
    'pay rose 219.8%' in the sentence and '+1.9%' in the structured field --
    the same fact, two numbers, and no way for a reader to tell which is real."""
    ko = proxy(
        pay=[("2025", 61_649_669.0), ("2024", 40_592_982.0), ("2023", 19_275_773.0),
             ("2022", 54_495_284.0), ("2021", 60_511_538.0)],
        tsr=[("2025", 148.0), ("2024", 128.0), ("2023", 118.0),
             ("2022", 123.0), ("2021", 111.0)],
        name="James Quincey",
    )
    result = governance_signal(ko)
    assert "219.8%" in result.sentence
    assert result.pay_change_pct == pytest.approx(219.8, abs=0.5)
    assert result.tsr_change_pct == pytest.approx(25.4, abs=0.5)
