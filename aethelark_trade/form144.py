"""Form 144 (Notice of Proposed Sale of Securities) parser.

Form 144 is filed when insiders plan to sell restricted or control securities.
This is a STRONG BEARISH signal - it indicates planned future selling.

Since April 2023, Form 144 must be filed as structured XML to EDGAR.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import List

from lxml import etree


@dataclass
class Form144Filing:
    """Represents a Form 144 planned sale filing.
    
    Form 144 is filed when an insider intends to sell restricted securities.
    This is advance notice of a planned sale - a bearish signal.
    """
    
    # Filing metadata
    filing_date: date
    accession_number: str
    
    # Issuer info
    issuer_name: str
    issuer_ticker: str
    issuer_cik: str
    
    # Seller info
    seller_name: str
    seller_cik: str
    seller_title: str
    seller_address: str
    
    is_director: bool
    is_officer: bool
    is_ten_percent_owner: bool
    is_affiliate: bool
    
    # Planned sale details
    shares_to_sell: float
    security_class: str  # "Common Stock", etc.
    
    # Dates
    approximate_sale_date: date | None
    earliest_sale_date: date | None
    
    # Broker info (if available)
    broker_name: str | None
    broker_address: str | None
    
    # Is this under a 10b5-1 trading plan?
    is_10b5_1_plan: bool
    
    # Signal classification
    signal: str = field(init=False)
    
    def __post_init__(self):
        # Form 144 is always a bearish signal - planned selling
        self.signal = "BEARISH"


def parse_form144_xml(
    xml_content: str,
    filing_date: date,
    accession_number: str,
) -> Form144Filing | None:
    """Parse Form 144 XML and extract planned sale information.
    
    Returns None if parsing fails.
    """
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
    
    def _get_float(element, xpath: str) -> float | None:
        text = _get_text(element, xpath)
        if not text:
            return None
        try:
            return float(text.replace(",", ""))
        except ValueError:
            return None
    
    def _parse_date(date_str: str) -> date | None:
        if not date_str:
            return None
        try:
            return date.fromisoformat(date_str)
        except ValueError:
            return None
    
    # Strip namespaces
    for elem in root.iter():
        if isinstance(elem.tag, str) and '}' in elem.tag:
            elem.tag = elem.tag.split('}', 1)[1]
    
    # Extract issuer info
    issuer_name = _get_text(root, ".//issuerName/text()") or _get_text(root, ".//issuer/issuerName/text()")
    issuer_ticker = _get_text(root, ".//issuerTradingSymbol/text()") or _get_text(root, ".//issuer/issuerTradingSymbol/text()")
    issuer_cik = _get_text(root, ".//issuerCik/text()") or _get_text(root, ".//issuer/issuerCik/text()")
    
    # Extract seller/reporting person info
    seller_name = _get_text(root, ".//sellerName/text()") or _get_text(root, ".//reportingPersonName/text()")
    seller_cik = _get_text(root, ".//sellerCik/text()") or _get_text(root, ".//reportingPersonCik/text()")
    seller_title = _get_text(root, ".//sellerTitle/text()") or _get_text(root, ".//titleOfSecuritiesSold/text()")
    
    # Address
    street = _get_text(root, ".//sellerAddress/street1/text()")
    city = _get_text(root, ".//sellerAddress/city/text()")
    state = _get_text(root, ".//sellerAddress/stateOrCountry/text()")
    zip_code = _get_text(root, ".//sellerAddress/zipCode/text()")
    seller_address = f"{street}, {city}, {state} {zip_code}".strip(", ")
    
    # Relationship flags
    is_director = _get_text(root, ".//isDirector/text()") == "1"
    is_officer = _get_text(root, ".//isOfficer/text()") == "1"
    is_ten_percent = _get_text(root, ".//isTenPercentOwner/text()") == "1"
    is_affiliate = _get_text(root, ".//isAffiliate/text()") == "1"
    
    # Shares to sell
    shares_to_sell = _get_float(root, ".//amountOfSecuritiesToBeSold/text()") or 0.0
    if shares_to_sell == 0:
        shares_to_sell = _get_float(root, ".//numberOfSecuritiesSold/text()") or 0.0
    
    security_class = _get_text(root, ".//securityClass/text()") or _get_text(root, ".//titleOfSecuritiesSold/text()") or "Common Stock"
    
    # Sale dates
    approx_sale_date_str = _get_text(root, ".//approximateDateOfSale/text()")
    earliest_sale_date_str = _get_text(root, ".//dateOfEarliestSale/text()")
    
    # Broker info
    broker_name = _get_text(root, ".//brokerName/text()") or _get_text(root, ".//nameOfBroker/text()")
    broker_street = _get_text(root, ".//brokerAddress/street1/text()")
    broker_city = _get_text(root, ".//brokerAddress/city/text()")
    broker_address = f"{broker_street}, {broker_city}".strip(", ") if broker_street or broker_city else None
    
    # 10b5-1 plan flag
    is_10b5_1 = _get_text(root, ".//is10b51Plan/text()") == "1"
    
    return Form144Filing(
        filing_date=filing_date,
        accession_number=accession_number,
        issuer_name=issuer_name,
        issuer_ticker=issuer_ticker.upper() if issuer_ticker else "",
        issuer_cik=issuer_cik,
        seller_name=seller_name,
        seller_cik=seller_cik,
        seller_title=seller_title,
        seller_address=seller_address,
        is_director=is_director,
        is_officer=is_officer,
        is_ten_percent_owner=is_ten_percent,
        is_affiliate=is_affiliate,
        shares_to_sell=shares_to_sell,
        security_class=security_class,
        approximate_sale_date=_parse_date(approx_sale_date_str),
        earliest_sale_date=_parse_date(earliest_sale_date_str),
        broker_name=broker_name if broker_name else None,
        broker_address=broker_address,
        is_10b5_1_plan=is_10b5_1,
    )
