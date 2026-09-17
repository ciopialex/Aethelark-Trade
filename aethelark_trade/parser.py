"""Form 4 XML parser using lxml."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, List

from lxml import etree
import logging

from aethelark_trade.narrative import NarrativeGenerator

# Transaction code semantic classification
# Each code has: name, signal type, emoji, and plain English explanation
TRANSACTION_CODES = {
    "P": {
        "name": "Purchase",
        "signal": "BULLISH",
        "emoji": "🟢",
        "explanation": "Voluntary open-market buy. Insider is betting their own money.",
    },
    "S": {
        "name": "Sale",
        "signal": "BEARISH",
        "emoji": "🔴",
        "explanation": "Open-market sale. Could be profit-taking, diversification, or concern.",
    },
    "M": {
        "name": "Option Exercise",
        "signal": "DILUTION",
        "emoji": "⚠️",
        "explanation": "Converting stock options into shares. Often a neutral administrative move, but can create selling pressure (dilution).",
    },
    "O": {
        "name": "Out-of-Money Exercise",
        "signal": "NEUTRAL",
        "emoji": "🔄",
        "explanation": "Exercise of out-of-the-money derivative security.",
    },
    "X": {
        "name": "Derivative Exercise",
        "signal": "NEUTRAL",
        "emoji": "🔄",
        "explanation": "Exercise or conversion of derivative security (not 16b-3).",
    },
    "V": {
        "name": "Early Report",
        "signal": "NEUTRAL",
        "emoji": "📝",
        "explanation": "Voluntary early reporting of a transaction.",
    },
    "H": {
        "name": "Cancellation",
        "signal": "NEUTRAL",
        "emoji": "❌",
        "explanation": "Expiration or cancellation of derivative security with value received.",
    },
    "C": {
        "name": "Conversion",
        "signal": "NEUTRAL",
        "emoji": "⚪",
        "explanation": "Security conversion. Neutral until paired with a sale.",
    },
    "A": {
        "name": "Award/Grant",
        "signal": "COMPENSATION",
        "emoji": "🎁",
        "explanation": "Compensation grant. Not a voluntary purchase - don't treat as bullish.",
    },
    "F": {
        "name": "Tax Withholding",
        "signal": "TAX",
        "emoji": "📋",
        "explanation": "Shares withheld for taxes on grants/exercises. NOT a sale decision.",
    },
    "G": {
        "name": "Gift",
        "signal": "NEUTRAL",
        "emoji": "🎀",
        "explanation": "Gift of shares. No market signal.",
    },
    "D": {
        "name": "Disposition to Issuer",
        "signal": "NEUTRAL",
        "emoji": "↩️",
        "explanation": "Return to company. Often part of compensation clawback or buyback.",
    },
    "E": {
        "name": "Expiration",
        "signal": "NEUTRAL",
        "emoji": "⏰",
        "explanation": "Option/derivative expired. No market action.",
    },
    "I": {
        "name": "Discretionary",
        "signal": "NEUTRAL",
        "emoji": "📊",
        "explanation": "Discretionary transaction reported by Rule 16b-3.",
    },
    "L": {
        "name": "Small Acquisition",
        "signal": "NEUTRAL",
        "emoji": "📌",
        "explanation": "Small acquisition under Rule 16a-6.",
    },
    "W": {
        "name": "Inheritance",
        "signal": "NEUTRAL",
        "emoji": "📜",
        "explanation": "Acquired or disposed by will or estate.",
    },
    "Z": {
        "name": "Trust Deposit",
        "signal": "NEUTRAL",
        "emoji": "🏦",
        "explanation": "Deposit into voting trust.",
    },
    "J": {
        "name": "Other",
        "signal": "NEUTRAL",
        "emoji": "❓",
        "explanation": "Other acquisition or disposition.",
    },
    "K": {
        "name": "Equity Swap",
        "signal": "NEUTRAL",
        "emoji": "🔄",
        "explanation": "Equity swap transaction.",
    },
    "U": {
        "name": "Tender",
        "signal": "BEARISH",
        "emoji": "🔴",
        "explanation": "Tender of shares in change of control.",
    },
}

def get_transaction_signal(code: str) -> str:
    """Get the trading signal for a transaction code."""
    info = TRANSACTION_CODES.get(code, {})
    return info.get("signal", "NEUTRAL")

def get_transaction_emoji(code: str) -> str:
    """Get the emoji indicator for a transaction code."""
    info = TRANSACTION_CODES.get(code, {})
    return info.get("emoji", "❓")

def get_transaction_name(code: str) -> str:
    """Get the human-readable name for a transaction code."""
    info = TRANSACTION_CODES.get(code, {})
    return info.get("name", "Unknown")

@dataclass
class InsiderTransaction:
    """Represents a single insider transaction from Form 4."""
    
    # Filing metadata
    filing_date: date
    accession_number: str
    
    # Issuer info
    issuer_name: str
    issuer_ticker: str
    issuer_cik: str
    
    # Insider info
    insider_name: str
    insider_cik: str
    insider_title: str
    is_director: bool
    is_officer: bool
    is_ten_percent_owner: bool
    is_other: bool
    is_ceo: bool = False
    is_cfo: bool = False
    filing_time: str = "12:00:00" # Default, updated by collector
    # SEC <aff10b5One> affirmative-defence checkbox: the trade was executed
    # under a Rule 10b5-1 plan adopted before the insider held the information,
    # so they had no discretion over its timing.
    is_10b5_1: bool = False
    
    # Transaction details
    transaction_date: date | None = None
    transaction_code: str = ""
    transaction_code_meaning: str = ""
    acquired_disposed: str = "" # "A" or "D"
    shares: float = 0.0
    price_per_share: float | None = None
    shares_owned_after: float = 0.0
    ownership_nature: str = "" # "D" (direct) or "I" (indirect)
    
    # Additional context
    footnotes: List[str] = field(default_factory=list)
    
    # Computed fields
    total_value: float | None = field(init=False)
    is_buy: bool = field(init=False)
    is_sell: bool = field(init=False)
    signal: str = field(init=False)  # BULLISH, BEARISH, DILUTION, NEUTRAL, TAX, COMPENSATION
    role_weight: float = field(init=False)
    is_friday_night: bool = field(init=False)
    readable_sentence: str = field(init=False)
    
    def __post_init__(self):
        if self.price_per_share is not None and self.shares:
            self.total_value = round(self.price_per_share * self.shares, 2)
        else:
            self.total_value = None
        
        # Identify the Player
        title_lower = self.insider_title.lower()
        if "cfo" in title_lower or "financial officer" in title_lower:
            self.is_cfo = True
            self.role_weight = 3.0 # The Math Guy
        elif "ceo" in title_lower or "executive officer" in title_lower:
            self.is_ceo = True
            self.role_weight = 2.0 # The Cheerleader
        else:
            self.role_weight = 1.0 # The Board/Noise
            
        # Detect Friday Night Cowardice (Filed after 4PM on Friday)
        from datetime import datetime
        try:
            # Check if filing_date is Friday (weekday 4)
            is_friday = self.filing_date.weekday() == 4
            hour = int(self.filing_time.split(":")[0])
            self.is_friday_night = is_friday and hour >= 16
        except Exception:
            self.is_friday_night = False

        # Get signal from transaction code classification
        self.signal = get_transaction_signal(self.transaction_code)
        
        # P = voluntary purchase (bullish)
        self.is_buy = self.transaction_code == "P"
        
        # S = open-market sale (bearish)
        self.is_sell = self.transaction_code == "S"
        
        # Generate narrative
        self.readable_sentence = NarrativeGenerator.generate(self, self.footnotes)

def parse_form4_xml(
    xml_content: str,
    filing_date: date,
    accession_number: str,
) -> list[InsiderTransaction]:
    """Parse Form 4 XML and extract all transactions."""
    
    try:
        # Check if content is bytes or string
        if isinstance(xml_content, str):
            xml_bytes = xml_content.encode("utf-8")
        else:
            xml_bytes = xml_content
            
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as e:
        raise ValueError(f"Invalid XML: {e}")
    
    # Helper to safely get text
    def _get_text(element: Any, xpath: str) -> str:
        if element is None:
            return ""
        results = element.xpath(xpath)
        if not results:
            return ""
        return str(results[0]).strip()
    
    # Helper to safely get float
    def _get_float(element: Any, xpath: str) -> float | None:
        text = _get_text(element, xpath)
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    # Helper to parse date
    def _parse_date(date_str: str) -> date | None:
        if not date_str:
            return None
        try:
            return date.fromisoformat(date_str)
        except ValueError:
            return None

    # Get issuer info
    issuer_name = _get_text(root, ".//issuer/issuerName/text()")
    issuer_ticker = _get_text(root, ".//issuer/issuerTradingSymbol/text()").upper()
    issuer_cik = _get_text(root, ".//issuer/issuerCik/text()")
    
    # Strip namespaces to simplify XPath queries
    for elem in root.iter():
        if isinstance(elem.tag, str) and '}' in elem.tag:
            elem.tag = elem.tag.split('}', 1)[1]
            
    # Get issuer info
    issuer_name = _get_text(root, ".//issuer/issuerName/text()")
    issuer_ticker = _get_text(root, ".//issuer/issuerTradingSymbol/text()").upper()
    issuer_cik = _get_text(root, ".//issuer/issuerCik/text()")

    # SEC Rule 10b5-1(c) affirmative-defence checkbox. Document-level: it
    # applies to every transaction reported on the form.
    _aff = _get_text(root, ".//aff10b5One/text()").strip().lower()
    is_10b5_1 = _aff in ("1", "true")
    
    # Get reporting owner info
    owner = root.find(".//reportingOwner")
    if owner is None:
        return []
    
    insider_name = _get_text(owner, ".//reportingOwnerId/rptOwnerName/text()")
    insider_cik = _get_text(owner, ".//reportingOwnerId/rptOwnerCik/text()")
    
    # Get relationship
    relationship = owner.find(".//reportingOwnerRelationship")

    def _xml_bool(xpath: str) -> bool:
        """xsd:boolean permits both "1"/"0" and "true"/"false".

        Filer agents disagree: Broadridge emits digits, DFIN (Alphabet, Meta,
        Apple) emits words. Comparing against "1" alone silently reported every
        DFIN-filed insider as neither officer nor director.
        """
        if relationship is None:
            return False
        return _get_text(relationship, xpath).strip().lower() in ("1", "true")

    is_director = _xml_bool(".//isDirector/text()")
    is_officer = _xml_bool(".//isOfficer/text()")
    is_ten_percent = _xml_bool(".//isTenPercentOwner/text()")
    is_other = _get_text(relationship, ".//isOther/text()") == "1" if relationship is not None else False
    officer_title = _get_text(relationship, ".//officerTitle/text()") if relationship is not None else ""
    
    # Determine title
    if officer_title:
        insider_title = officer_title
    elif is_director:
        insider_title = "Director"
    elif is_ten_percent:
        insider_title = "10% Owner"
    elif is_other:
        insider_title = "Other"
    else:
        insider_title = "Unknown"
    
    # ---------------------------------------------------------
    # Footnote Extraction
    # ---------------------------------------------------------
    footnotes_map = {}
    # Iterate over all elements to find <footnote>
    for elem in root.iter():
        if elem.tag is not None and elem.tag.endswith("footnote") and elem.get("id"):
            fn_id = elem.get("id")
            fn_text = (elem.text or "").strip()
            if fn_id and fn_text:
                footnotes_map[fn_id] = fn_text
                
    transactions = []
    
    # Helper to extract footnotes from a transaction element
    def get_footnotes_for_tx(tx_element):
        refs = []
        for child in tx_element.iter():
            fn_id = child.get("footnoteId")
            if fn_id and fn_id in footnotes_map:
                if fn_id not in refs:
                    refs.append(fn_id)
        return [footnotes_map[rid] for rid in refs]
    
    # Parse non-derivative transactions (Table I - common stock) using namespace-agnostic XPath
    for tx in root.xpath(".//*[local-name()='nonDerivativeTransaction']"):
        tx_date_str = _get_text(tx, ".//*[local-name()='transactionDate']/*[local-name()='value']/text()")
        tx_code = _get_text(tx, ".//*[local-name()='transactionCoding']/*[local-name()='transactionCode']/text()")
        acquired_disposed = _get_text(tx, ".//*[local-name()='transactionAmounts']/*[local-name()='transactionAcquiredDisposedCode']/*[local-name()='value']/text()")
        shares = _get_float(tx, ".//*[local-name()='transactionAmounts']/*[local-name()='transactionShares']/*[local-name()='value']/text()") or 0.0
        price = _get_float(tx, ".//*[local-name()='transactionAmounts']/*[local-name()='transactionPricePerShare']/*[local-name()='value']/text()")
        shares_after = _get_float(tx, ".//*[local-name()='postTransactionAmounts']/*[local-name()='sharesOwnedFollowingTransaction']/*[local-name()='value']/text()") or 0.0
        ownership = _get_text(tx, ".//*[local-name()='ownershipNature']/*[local-name()='directOrIndirectOwnership']/*[local-name()='value']/text()")
        
        tx_footnotes = get_footnotes_for_tx(tx)
        
        transactions.append(InsiderTransaction(
            filing_date=filing_date,
            accession_number=accession_number,
            issuer_name=issuer_name,
            issuer_ticker=issuer_ticker,
            issuer_cik=issuer_cik,
            insider_name=insider_name,
            insider_cik=insider_cik,
            insider_title=insider_title,
            is_10b5_1=is_10b5_1,
            is_director=is_director,
            is_officer=is_officer,
            is_ten_percent_owner=is_ten_percent,
            is_other=is_other,
            transaction_date=_parse_date(tx_date_str),
            transaction_code=tx_code,
            transaction_code_meaning=get_transaction_name(tx_code),
            acquired_disposed=acquired_disposed,
            shares=shares,
            price_per_share=price,
            shares_owned_after=shares_after,
            ownership_nature=ownership,
            footnotes=tx_footnotes
        ))
    
    # Parse derivative transactions (Table II - options, warrants, etc.)
    for tx in root.xpath(".//*[local-name()='derivativeTransaction']"):
        tx_date_str = _get_text(tx, ".//*[local-name()='transactionDate']/*[local-name()='value']/text()")
        tx_code = _get_text(tx, ".//*[local-name()='transactionCoding']/*[local-name()='transactionCode']/text()")
        shares = _get_float(tx, ".//*[local-name()='transactionAmounts']/*[local-name()='transactionShares']/*[local-name()='value']/text()") or 0.0
        acquired_disposed = _get_text(tx, ".//*[local-name()='transactionAmounts']/*[local-name()='transactionAcquiredDisposedCode']/*[local-name()='value']/text()")
        price = _get_float(tx, ".//*[local-name()='transactionAmounts']/*[local-name()='transactionPricePerShare']/*[local-name()='value']/text()")
        
        # For derivatives, get underlying shares if available
        underlying_shares = _get_float(tx, ".//*[local-name()='underlyingSecurity']/*[local-name()='underlyingSecurityShares']/*[local-name()='value']/text()")
        if underlying_shares:
            shares = underlying_shares
        
        shares_after = _get_float(tx, ".//*[local-name()='postTransactionAmounts']/*[local-name()='sharesOwnedFollowingTransaction']/*[local-name()='value']/text()") or 0.0
        ownership = _get_text(tx, ".//*[local-name()='ownershipNature']/*[local-name()='directOrIndirectOwnership']/*[local-name()='value']/text()")
        
        tx_footnotes = get_footnotes_for_tx(tx)
        
        transactions.append(InsiderTransaction(
            filing_date=filing_date,
            accession_number=accession_number,
            issuer_name=issuer_name,
            issuer_ticker=issuer_ticker,
            issuer_cik=issuer_cik,
            insider_name=insider_name,
            insider_cik=insider_cik,
            insider_title=insider_title,
            is_10b5_1=is_10b5_1,
            is_director=is_director,
            is_officer=is_officer,
            is_ten_percent_owner=is_ten_percent,
            is_other=is_other,
            transaction_date=_parse_date(tx_date_str),
            transaction_code=tx_code,
            transaction_code_meaning=get_transaction_name(tx_code),
            acquired_disposed=acquired_disposed,
            shares=shares,
            price_per_share=price,
            shares_owned_after=shares_after,
            ownership_nature=ownership,
            footnotes=tx_footnotes
        ))
    
    return transactions
