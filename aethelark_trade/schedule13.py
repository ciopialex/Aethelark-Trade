"""Schedule 13D/13G (Beneficial Ownership) parser.

13D/13G filings are required when investors acquire 5%+ of a company's stock.
- 13D = ACTIVIST investor (intends to influence the company)
- 13G = PASSIVE investor (just holding, no control intent)

This is "smart money" tracking - hedge funds, activist investors, institutions.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import List

from lxml import etree


@dataclass 
class Schedule13Filing:
    """Represents a Schedule 13D or 13G beneficial ownership filing."""
    
    # Filing metadata
    filing_date: date
    accession_number: str
    form_type: str  # "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"
    
    # Subject company
    issuer_name: str
    issuer_ticker: str
    issuer_cik: str
    issuer_cusip: str
    
    # Beneficial owner
    filer_name: str
    filer_cik: str
    filer_address: str
    
    # Ownership details
    shares_owned: float
    percent_of_class: float  # e.g., 5.2 = 5.2%
    sole_voting_power: float
    shared_voting_power: float
    sole_dispositive_power: float
    shared_dispositive_power: float
    
    # Intent and type
    is_activist: bool  # 13D = True, 13G = False
    purpose: str  # Purpose of transaction (Item 4 in 13D)
    
    # Computed fields
    signal: str = field(init=False)
    
    def __post_init__(self):
        if self.is_activist:
            self.signal = "ACTIVIST"  # 13D - wants change
        else:
            self.signal = "ACCUMULATION"  # 13G - passive but accumulating


def parse_schedule13_xml(
    xml_content: str,
    filing_date: date,
    accession_number: str,
    form_type: str,
) -> Schedule13Filing | None:
    """Parse Schedule 13D/13G XML filing."""
    try:
        if isinstance(xml_content, str):
            xml_bytes = xml_content.encode("utf-8")
        else:
            xml_bytes = xml_content
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError:
        return None
    
    def _get_text(element, xpath: str) -> str:
        if element is None:
            return ""
        results = element.xpath(xpath)
        if not results:
            return ""
        return str(results[0]).strip()
    
    def _get_float(element, xpath: str) -> float:
        text = _get_text(element, xpath)
        if not text:
            return 0.0
        try:
            return float(text.replace(",", "").replace("%", ""))
        except ValueError:
            return 0.0
    
    # Strip namespaces
    for elem in root.iter():
        if isinstance(elem.tag, str) and '}' in elem.tag:
            elem.tag = elem.tag.split('}', 1)[1]
    
    # Subject company (issuer)
    issuer_name = _get_text(root, ".//issuerName/text()") or _get_text(root, ".//subjectCompany/issuerName/text()")
    issuer_ticker = _get_text(root, ".//issuerTradingSymbol/text()") or _get_text(root, ".//subjectCompany/issuerTradingSymbol/text()")
    issuer_cik = _get_text(root, ".//issuerCik/text()") or _get_text(root, ".//subjectCompany/issuerCik/text()")
    issuer_cusip = _get_text(root, ".//cusip/text()")
    
    # Filer (beneficial owner)
    filer_name = _get_text(root, ".//filedBy/filerName/text()") or _get_text(root, ".//reportingOwnerName/text()")
    filer_cik = _get_text(root, ".//filedBy/filerCik/text()") or _get_text(root, ".//reportingOwnerCik/text()")
    
    # Address
    street = _get_text(root, ".//filedBy/filerAddress/street1/text()")
    city = _get_text(root, ".//filedBy/filerAddress/city/text()")
    state = _get_text(root, ".//filedBy/filerAddress/stateOrCountry/text()")
    filer_address = f"{street}, {city}, {state}".strip(", ")
    
    # Ownership amounts
    shares = _get_float(root, ".//shrsOrPrnAmt/sshPrnamt/text()") or _get_float(root, ".//aggregateAmountOwned/text()")
    percent = _get_float(root, ".//percentOfClass/text()") or _get_float(root, ".//pctOfClass/text()")
    
    # Voting and dispositive power
    sole_vote = _get_float(root, ".//votingPower/sole/text()")
    shared_vote = _get_float(root, ".//votingPower/shared/text()")
    sole_disp = _get_float(root, ".//dispositivePower/sole/text()")
    shared_disp = _get_float(root, ".//dispositivePower/shared/text()")
    
    # Purpose (important for 13D - activist intent)
    purpose = _get_text(root, ".//purposeOfTransaction/text()") or ""
    if not purpose:
        purpose = _get_text(root, ".//item4/text()") or ""
    
    # Determine activist vs passive
    is_activist = "13D" in form_type.upper()
    
    return Schedule13Filing(
        filing_date=filing_date,
        accession_number=accession_number,
        form_type=form_type,
        issuer_name=issuer_name,
        issuer_ticker=issuer_ticker.upper() if issuer_ticker else "",
        issuer_cik=issuer_cik,
        issuer_cusip=issuer_cusip,
        filer_name=filer_name,
        filer_cik=filer_cik,
        filer_address=filer_address,
        shares_owned=shares,
        percent_of_class=percent,
        sole_voting_power=sole_vote,
        shared_voting_power=shared_vote,
        sole_dispositive_power=sole_disp,
        shared_dispositive_power=shared_disp,
        is_activist=is_activist,
        purpose=purpose[:500] if purpose else "",  # Truncate long purposes
    )


def parse_schedule13_html(
    html_content: str | bytes,
    filing_date: date,
    accession_number: str,
    form_type: str,
) -> Schedule13Filing | None:
    """Parse Schedule 13D/13G HTML/Text filing using regex fallback."""
    import re
    import html
    
    if isinstance(html_content, bytes):
        text = html_content.decode("utf-8", errors="ignore")
    else:
        text = html_content
    
    # 1. Unescape HTML entities (&nbsp; -> space, etc.)
    text = html.unescape(text)
    
    # 2. Strip HTML tags
    # Replace <br> and variants with newline
    text = re.sub(r'<(br|BR|Br|div|p|P|DIV)[^>]*>', '\n', text)
    # Remove other tags
    clean_text = re.sub(r'<[^>]+>', ' ', text)
    # Collapse multiple spaces
    clean_text = re.sub(r'\s+', ' ', clean_text)
    
    # 1. Subject Company (Issuer)
    # Often in header or "NAME OF ISSUER"
    issuer_name = "Unknown Issuer"
    issuer_ticker = ""
    issuer_cusip = ""
    
    name_match = re.search(r'COMPANY CONFORMED NAME:\s+([^\n\r]+)', text)  # Use original text for header
    if name_match:
        issuer_name = name_match.group(1).strip()
    
    # 2. Filer Name
    # "NAME OF REPORTING PERSONS"
    # Can be "Names of Reporting Persons" or "Name of Reporting Person"
    filer_name = "Unknown Filer"
    
    # Regex explanations:
    # Names? of Reporting Persons? : Handle plural/singular
    # [A-Z0-9][A-Za-z0-9\s\.,&]{2,} : Capture the name (Start with Cap, allow lower, length 3+)
    
    # Attempt 1: Look for name followed by IRS line or Check Box
    # "Names... Elon Musk ... Check the appropriate box"
    # We use a non-greedy match until we hit a known footer like "Check" or "I.R.S"
    
    # Clean text has removed IRS line in some cases? No, unescape keeps text.
    # But clean_text replaces tags with spaces.
    
    # Attempt 0: Look for "ABOVE PERSON" label directly (most reliable for IRS lines)
    # Use permissible capture to handle unicode dashes/spaces
    irs_name_pattern = r'ABOVE PERSON\s*(?:\([^\)]+\))?\s+([A-Z0-9].+?)\s+(?:Check|I\.R\.S\.|SSN|IDENTIFICATION|SEC USE ONLY)'
    report_person_match = re.search(irs_name_pattern, clean_text, re.IGNORECASE | re.DOTALL)
    
    if not report_person_match:
        # Combined fix: Negative lookahead, extended chars, distance limit, AND explicitly skip IRS label
        # Added [\.:]? to allow "Names of Reporting Persons." (with period)
        name_pattern = r'Names? of Reporting Persons?[\.:]?(?:.{1,200}?ABOVE PERSON.*?)?\s+(?!(?:I\.R\.S\.|S\.S\.))([A-Z0-9].+?)\s+(?:Check|I\.R\.S\.|SSN|IDENTIFICATION|SEC USE ONLY)'
        report_person_match = re.search(name_pattern, clean_text, re.IGNORECASE | re.DOTALL)
    
    if not report_person_match:
         # Fallback: Just grab the next few words after "Reporting Persons" if they look like a name
         # Ignore single character '1.' or similar
         # Ignore single character '1.' or similar
         name_pattern_simple = r'Names? of Reporting Persons?[\.:]?(?:.{1,200}?ABOVE PERSON.*?)?\s+(?!(?:I\.R\.S\.|S\.S\.))([A-Z0-9][A-Za-z0-9\s\.,&-\(\)]{3,50}?)'
         report_person_match = re.search(name_pattern_simple, clean_text, re.IGNORECASE)

    if report_person_match:
        possible_name = report_person_match.group(1).strip()
        # Cleanup: Remove leading "1." and trailing junk (like IRS numbers captured by mistake)
        possible_name = re.sub(r'^\d+[\.\)]\s*', '', possible_name)
        # Split at " - 123" pattern (IRS ID suffix)
        possible_name = re.split(r'\s+[-–—]\s+\d', possible_name)[0]
        # Strip trailing digits, dots, parens, hyphens, AND OPEN PARENS (e.g. "Inc. (")
        possible_name = re.sub(r'[\s\d\.\)\-\(]+$', '', possible_name)
        filer_name = possible_name[:50].strip()
    
    # 3. Ownership Amount
    # "AGGREGATE AMOUNT BENEFICIALLY OWNED"
    shares = 0.0
    # Try generic pattern
    shares_match = re.search(r'AGGREGATE AMOUNT BENEFICIALLY OWNED\D{1,100}?([\d,]+)', clean_text, re.IGNORECASE)
    if shares_match:
        try:
            shares = float(shares_match.group(1).replace(",", ""))
        except ValueError:
            pass
            
    # 4. Percent
    # "PERCENT OF CLASS REPRESENTED"
    percent = 0.0
    # Require % at the end to avoid matching Row Numbers like "(9)"
    percent_match = re.search(r'PERCENT OF CLASS REPRESENTED[\s\S]{1,80}?([\d\.]+)(?:%| percent)', clean_text, re.IGNORECASE)
    if percent_match:
        try:
            percent = float(percent_match.group(1))
        except ValueError:
            pass

            
    # If we found nothing useful, abort
    if shares == 0 and percent == 0 and filer_name == "Unknown Filer":
        return None
        
    return Schedule13Filing(
        filing_date=filing_date,
        accession_number=accession_number,
        form_type=form_type,
        issuer_name=issuer_name,
        issuer_ticker=issuer_ticker,
        issuer_cik="",
        issuer_cusip=issuer_cusip,
        filer_name=filer_name,
        filer_cik="",
        filer_address="",
        shares_owned=shares,
        percent_of_class=percent,
        sole_voting_power=0.0,
        shared_voting_power=0.0,
        sole_dispositive_power=0.0,
        shared_dispositive_power=0.0,
        is_activist="13D" in form_type.upper(),
        purpose="",
    )

