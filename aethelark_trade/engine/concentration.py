"""Extraction of SEC 10-K customer-concentration disclosures (ASC 280-10-50-42).

Extracts ConcentrationRiskPercentage1 facts from XBRL instance documents,
distinguishing revenue vs accounts-receivable risks and separating specific
counterparties from aggregate customer disclosures.
"""
from dataclasses import dataclass
from datetime import date, datetime
import re
from xml.etree import ElementTree

AGGREGATE_PATTERNS = [
    re.compile(r"tenlargest", re.I),
    re.compile(r"fourlargest", re.I),
    re.compile(r"fivelargest", re.I),
    re.compile(r"threelargest", re.I),
    re.compile(r"twolargest", re.I),
    re.compile(r"largestcustomer", re.I),
    re.compile(r"topcustomer", re.I),
    re.compile(r"majorcustomersmember", re.I),
    re.compile(r"customerconcentrationriskmember", re.I),
]

GAAP_DIMENSION_MEMBERS = {
    "salesrevenuenetmember",
    "accountsreceivablemember",
    "customerconcentrationriskmember",
    "majorcustomersmember",
}


@dataclass(frozen=True)
class ConcentrationFact:
    counterparty_tag: str      # "crus:AppleIncMember"
    risk_type: str             # "revenue" | "receivable"
    pct: float                 # 0.91
    period_end: date
    accession: str


@dataclass(frozen=True)
class ExtractionResult:
    facts: list[ConcentrationFact]
    aggregate_concentration: float | None = None


def is_aggregate_member(member_tag: str) -> bool:
    """True if the member describes an aggregate pool rather than a single counterparty."""
    local = member_tag.split(":")[-1] if ":" in member_tag else member_tag
    return any(p.search(local) for p in AGGREGATE_PATTERNS)


def parse_concentration_facts(xml_content: str, accession: str = "") -> ExtractionResult:
    """Parse XBRL instance document for customer concentration disclosures."""
    if not xml_content or not xml_content.strip():
        return ExtractionResult(facts=[], aggregate_concentration=None)

    try:
        root = ElementTree.fromstring(xml_content)
    except ElementTree.ParseError:
        return ExtractionResult(facts=[], aggregate_concentration=None)

    # 1. Map contexts: contextRef -> (period_end_date, set_of_members)
    contexts: dict[str, tuple[date | None, set[str]]] = {}

    for elem in root.iter():
        tag_name = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag_name == "context":
            c_id = elem.attrib.get("id")
            if not c_id:
                continue

            period_end: date | None = None
            members: set[str] = set()

            for child in elem.iter():
                c_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if c_tag in ("endDate", "instant") and child.text:
                    try:
                        period_end = datetime.fromisoformat(child.text.strip()).date()
                    except ValueError:
                        pass
                elif c_tag == "explicitMember" and child.text:
                    members.add(child.text.strip())

            contexts[c_id] = (period_end, members)

    facts: list[ConcentrationFact] = []
    aggregate_conc: float | None = None

    # 2. Extract ConcentrationRiskPercentage1 elements
    for elem in root.iter():
        tag_name = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag_name == "ConcentrationRiskPercentage1":
            c_ref = elem.attrib.get("contextRef")
            if not c_ref or c_ref not in contexts:
                continue

            try:
                raw_val = float(elem.text.strip()) if elem.text else 0.0
            except ValueError:
                continue

            # Standardize percentage: 0.91 stays 0.91; 91.0 becomes 0.91
            pct = raw_val / 100.0 if raw_val > 1.0 else raw_val
            period_end, members = contexts[c_ref]
            if period_end is None:
                period_end = date.today()

            # Determine risk type: revenue vs receivable
            risk_type = "revenue"
            for m in members:
                m_lower = m.lower()
                if "accountsreceivable" in m_lower:
                    risk_type = "receivable"
                    break
                if "salesrevenue" in m_lower:
                    risk_type = "revenue"
                    break

            # Find the counterparty member
            counterparty_tag = None
            for m in members:
                m_local = m.split(":")[-1].lower() if ":" in m else m.lower()
                if m_local not in GAAP_DIMENSION_MEMBERS:
                    counterparty_tag = m
                    break

            if not counterparty_tag:
                continue

            if is_aggregate_member(counterparty_tag):
                if aggregate_conc is None or pct > aggregate_conc:
                    aggregate_conc = pct
            else:
                facts.append(
                    ConcentrationFact(
                        counterparty_tag=counterparty_tag,
                        risk_type=risk_type,
                        pct=pct,
                        period_end=period_end,
                        accession=accession,
                    )
                )

    return ExtractionResult(facts=facts, aggregate_concentration=aggregate_conc)
