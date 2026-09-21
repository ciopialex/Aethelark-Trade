"""
Inline XBRL (iXBRL) Deterministic Extractor for SEC Filings.

Extracts machine-readable ECD (Executive Compensation Disclosure) data
directly from the legally mandated iXBRL tags embedded in proxy statements.
Zero regex. Zero guessing. Physics-grade accuracy.
"""

import re
import logging
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

logger = logging.getLogger("xbrl")


@dataclass
class CompYear:
    """A single year's compensation data point."""
    year: str
    amount: float | None


@dataclass
class ProxyXBRL:
    """Structured XBRL extraction from a DEF 14A proxy statement."""
    ceo_name: str | None = None
    ceo_total_comp: list[CompYear] = field(default_factory=list)
    ceo_actually_paid: list[CompYear] = field(default_factory=list)
    avg_exec_comp: list[CompYear] = field(default_factory=list)
    total_shareholder_return: list[CompYear] = field(default_factory=list)
    peer_group_tsr: list[CompYear] = field(default_factory=list)
    company_measure_name: str | None = None
    company_measure_values: list[CompYear] = field(default_factory=list)
    has_insider_trading_policy: bool | None = None
    is_empty: bool = True

    def decode_governance_summary(self) -> str:
        """
        Decodes the raw numbers into a plain-English trading signal.
        Compares CEO 'Actually Paid' growth vs Shareholder Return growth.
        """
        if self.is_empty or not self.ceo_actually_paid or not self.total_shareholder_return:
            return "[dim]Insufficient XBRL history to generate governance signal.[/dim]"

        # Get latest and oldest data points (up to 3 years for relevance)
        latest_pay = self.ceo_actually_paid[0].amount if self.ceo_actually_paid[0].amount is not None else 0
        latest_tsr = self.total_shareholder_return[0].amount
        
        # Look back up to 3 years for the delta
        lookback_idx = min(2, len(self.ceo_actually_paid) - 1, len(self.total_shareholder_return) - 1)
        if lookback_idx < 1:
            return "[dim]History too short for growth trend analysis.[/dim]"
            
        oldest_pay = self.ceo_actually_paid[lookback_idx].amount if self.ceo_actually_paid[lookback_idx].amount is not None else 0
        oldest_tsr = self.total_shareholder_return[lookback_idx].amount

        if oldest_tsr is None or latest_tsr is None:
             return "[dim]Incomplete TSR data in historical records.[/dim]"

        # Special Case: Founder Mode ($0 Salary)
        # If latest total comp is very low / nil while stock is up.
        #
        # The `has_total_comp` guard matters: this used to default to 0 when the
        # ceo_total_comp series failed to extract, and 0 < 100000, so any company
        # with a rising stock and one unparsed field was declared "Extreme
        # Bullish - CEO takes negligible salary". Absence of evidence became the
        # strongest claim in the set. Founder mode is a positive assertion and
        # needs the number that supports it.
        has_total_comp = bool(self.ceo_total_comp) and self.ceo_total_comp[0].amount is not None
        total_comp_latest = self.ceo_total_comp[0].amount if has_total_comp else 0
        if has_total_comp and total_comp_latest < 100000 and latest_tsr > oldest_tsr:
            return "🚀 [bold green]FOUNDER MODE (Extreme Bullish):[/bold green] CEO takes negligible salary while creating massive shareholder value. Total alignment."

        # Calculate % changes.
        #
        # The denominator is an ABSOLUTE value, and that is the whole point.
        # SEC's "Compensation Actually Paid" is a mark-to-market measure that
        # includes the change in fair value of unvested equity, so it is
        # legitimately NEGATIVE in a year the stock fell. Dividing a negative
        # numerator by a negative denominator flips the sign of the result.
        #
        # Measured on INTC 2026-09-21: pay went from -$78.5M to -$82.2M, which
        # is a 4.7% DECREASE. The signed denominator returned +4.7%, which trips
        # the `tsr_change < 0 and pay_change > 0` branch below and published
        # "CEO pay rose 4.7% ... Management is looting the ship" -- naming a real
        # executive -- about a year in which their pay fell.
        #
        # engine/governance.py:_pct_change already divides by abs(oldest), so the
        # structured `pay_change_pct` field was correct while the sentence the
        # user actually hears was not. They must not be allowed to disagree.
        pay_change = (latest_pay - oldest_pay) / (abs(oldest_pay) if oldest_pay != 0 else 1)
        tsr_change = (latest_tsr - oldest_tsr) / (abs(oldest_tsr) if oldest_tsr != 0 else 1)

        # Peer Check
        peer_latest = self.peer_group_tsr[0].amount if self.peer_group_tsr else None
        peer_oldest = self.peer_group_tsr[lookback_idx].amount if len(self.peer_group_tsr) > lookback_idx else None
        peer_outperforming = False
        if peer_latest and peer_oldest:
            peer_change = (peer_latest - peer_oldest) / (abs(peer_oldest) if peer_oldest != 0 else 1)
            if peer_change > tsr_change:
                peer_outperforming = True

        # Deciding the Phrase
        if tsr_change < 0 and pay_change > 0:
            return f"💀 [bold red]TOTAL DRAIN (Extreme Bearish):[/bold red] CEO pay rose {abs(pay_change):.1%}, but stock fell {abs(tsr_change):.1%}. Management is looting the ship."
        
        if tsr_change < 0 and pay_change < tsr_change:
            return "🫡 [bold cyan]SHARED PAIN (Respect):[/bold cyan] Stock is down, but management took an even larger haircut than you. Rational leadership."

        if peer_outperforming and tsr_change > 0:
            return f"🌊 [bold yellow]RISING TIDE SKEPTICISM (Neutral):[/bold yellow] Stock is up {tsr_change:.1%}, but the Peer Group did better. Management is coasting on a broad market rally."

        if tsr_change > pay_change * 1.5:
            return f"🔥 [bold green]ALIGNED PERFORMANCE (Bullish):[/bold green] Stock growth ({tsr_change:.1%}) significantly outpaces pay growth ({pay_change:.1%}). Highly efficient."
        
        if pay_change > tsr_change * 2 and tsr_change > 0:
            return f"🚩 [bold orange3]THE LEAK (Bearish):[/bold orange3] CEO pay rose {pay_change:.1%}—doubling the actual return to you ({tsr_change:.1%}). Value is leaking to the top."

        if abs(tsr_change - pay_change) < 0.2:
            return "⚖️ [bold white]INEFFICIENT GROWTH (Neutral):[/bold white] Pay and performance are moving in lockstep. Standard corporate 'Participation Trophy'."

        return "[dim]Governance trend is stable but unsignalized.[/dim]"


def _parse_value(tag) -> float | None:
    """Extract numeric value from an ix:nonfraction tag, applying scale and sign."""
    if tag.get("xsi:nil") == "true":
        return None

    raw = tag.get_text(strip=True)
    if not raw:
        return None

    raw = raw.replace(",", "").replace("$", "").replace(" ", "")
    if not raw:
        return None

    try:
        value = float(raw)
    except ValueError:
        return None

    scale = tag.get("scale")
    if scale:
        try:
            value *= 10 ** int(scale)
        except ValueError:
            pass

    if tag.get("sign") == "-":
        value = -abs(value)

    return value


def _extract_year(context_ref: str) -> str | None:
    """Extract the fiscal year from a contextRef like 'From2024-09-29to2025-09-27'."""
    if not context_ref:
        return None

    match = re.search(r"to(\d{4})", context_ref)
    if match:
        return match.group(1)

    match = re.search(r"From(\d{4})", context_ref)
    if match:
        return match.group(1)

    match = re.search(r"(\d{4})", context_ref)
    if match:
        return match.group(1)

    return None


def extract_proxy_xbrl(html: str) -> ProxyXBRL:
    """
    Extract all ECD (Executive Compensation Disclosure) iXBRL data from
    a DEF 14A proxy statement HTML string.
    """
    soup = BeautifulSoup(html, "lxml")
    result = ProxyXBRL()

    # 1. Map contexts to years
    context_map: dict[str, str] = {}
    contexts = soup.find_all(["xbrli:context", "context"])
    for ctx in contexts:
        ctx_id = ctx.get("id")
        if not ctx_id:
            continue
        
        # Look for period/endDate or period/instant
        end_date = ctx.find(["xbrli:enddate", "enddate", "xbrli:instant", "instant"])
        if end_date:
            year = _extract_year(end_date.get_text())
            if year:
                context_map[ctx_id] = year
    
    # 2. Extract tags
    nonfrac = soup.find_all(["ix:nonfraction", "nonfraction"])
    nonnumeric = soup.find_all(["ix:nonnumeric", "nonnumeric"])

    def _get_year_for_tag(tag) -> str | None:
        ctx_ref = tag.get("contextref")
        if not ctx_ref:
            return None
        # Try direct extraction from ref string first (AAPL style)
        yr = _extract_year(ctx_ref)
        if yr:
            return yr
        # Fallback to context map (TSLA style)
        return context_map.get(ctx_ref)

    ecd_nonfrac: dict[str, list] = {}
    for tag in nonfrac:
        name = tag.get("name", "")
        if name.startswith("ecd:"):
            key = name.split(":")[-1]
            ecd_nonfrac.setdefault(key, []).append(tag)

    ecd_nonnumeric: dict[str, list] = {}
    for tag in nonnumeric:
        name = tag.get("name", "")
        if name.startswith("ecd:"):
            key = name.split(":")[-1]
            ecd_nonnumeric.setdefault(key, []).append(tag)

    # Helper to collect with context resolution
    def _collect_with_resolution(tags: list) -> list[CompYear]:
        res: dict[str, CompYear] = {}
        for tag in tags:
            year = _get_year_for_tag(tag)
            if not year or year in res:
                continue
            res[year] = CompYear(year=year, amount=_parse_value(tag))
        return sorted(res.values(), key=lambda c: c.year, reverse=True)

    # CEO Name
    peo_names = ecd_nonnumeric.get("PeoName", [])
    for tag in peo_names:
        text = tag.get_text(strip=True)
        if text:
            result.ceo_name = text
            break

    # Extract Datasets
    result.ceo_total_comp = _collect_with_resolution(ecd_nonfrac.get("PeoTotalCompAmt", []))
    result.ceo_actually_paid = _collect_with_resolution(ecd_nonfrac.get("PeoActuallyPaidCompAmt", []))
    result.avg_exec_comp = _collect_with_resolution(ecd_nonfrac.get("NonPeoNeoAvgTotalCompAmt", []))
    result.total_shareholder_return = _collect_with_resolution(ecd_nonfrac.get("TotalShareholderRtnAmt", []))
    result.peer_group_tsr = _collect_with_resolution(ecd_nonfrac.get("PeerGroupTotalShareholderRtnAmt", []))

    # Insider Trading Policy Flag
    policy_flags = ecd_nonnumeric.get("InsiderTrdPoliciesProcAdoptedFlag", [])
    for tag in policy_flags:
        text = tag.get_text(strip=True).lower()
        if "true" in text:
            result.has_insider_trading_policy = True
            break
        elif "false" in text:
            result.has_insider_trading_policy = False
            break

    # Determine if we actually found anything
    has_data = (
        result.ceo_name
        or result.ceo_total_comp
        or result.ceo_actually_paid
        or result.avg_exec_comp
        or result.total_shareholder_return
    )
    result.is_empty = not has_data

    return result
