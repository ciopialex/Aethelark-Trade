"""
Deterministic parsers for SEC filings.
Extracts signals using Pattern Matching (Regex) and Structure Analysis (BeautifulSoup).
No AI/LLM dependencies.
"""

import re
from bs4 import BeautifulSoup

# Map 8-K Item codes to human-readable meanings
# Map 8-K Item codes to human-readable headlines (Trader Speak)
ITEM_MAP = {
    "1.01": "🤝 MATERIAL DEAL: Definitive Agreement",
    "1.03": "💀 BANKRUPTCY / RECEIVERSHIP",
    "2.01": "💰 ASSET DEAL: Acquisition/Disposition",
    "2.03": "💳 DEBT: Direct Financial Obligation",
    "2.04": "📉 DEBT CRISIS: Default/Acceleration",
    "3.01": "⚠️  DELISTING NOTICE",
    "4.01": "AUDITOR CHANGE",
    "4.02": "🚩 ACCOUNTING SCANDAL: Non-Reliance",
    "5.01": "👑 TAKEOVER: Change in Control",
    "5.02": "🚪 EXECUTIVE MOVES: Departure/Election",
    "7.01": "📢 REG FD DISCLOSURE",
    "8.01": "OTHER EVENTS",
}

def scan_8k_items(html_content: str) -> list[dict]:
    """
    Scans 8-K HTML/Text content for specific Item codes.
    Returns a list of found items with their descriptions.
    
    Returns format:
    [
        {"code": "5.02", "description": "Departure of Directors...", "snippet": "..."},
        ...
    ]
    """
    soup = BeautifulSoup(html_content, 'lxml')
    text = soup.get_text(" ", strip=True) # Normalize whitespace
    
    found_items = []
    
    # Regex to find "Item X.XX" case-insensitive
    # We look for "Item" followed by space/nbsp and the number
    # We use \b to ensure we don't match "Item 5.020" or something odd
    for code, desc in ITEM_MAP.items():
        # strict pattern: Item\s+Code
        pattern = f"Item\\s+{re.escape(code)}\\b"
        match = re.search(pattern, text, re.IGNORECASE)
        
        if match:
            # Extract a small snippet of text following the match for context
            start = match.end()
            snippet = text[start:start+200] + "..."
            found_items.append({
                "code": code,
                "description": desc,
                "snippet": snippet.strip()
            })
            
    return found_items

def extract_merger_target(html_content: str) -> str | None:
    """
    Extracts 'Subject Company' from Form 425 filings.
    """
    soup = BeautifulSoup(html_content, 'lxml')
    text = soup.get_text(" ", strip=True)
    
    # 425 Filings typically have "Subject Company: [Name]" at the top
    match = re.search(r"Subject\s+Company:?\s*(.+?)(?:\s+Commission|\s+File|\s*$)", text, re.IGNORECASE)
    if match:
        target = match.group(1).strip()
        # Cleanup: sometimes it grabs too much
        if len(target) > 50:
            target = target[:50] + "..."
        return target
    return None

def scan_proxy_signals(html_content: str) -> dict:
    """
    Scans Proxy Statement (DEF 14A) using two layers:
    1. iXBRL Extraction (exact numbers from legally mandated tags)
    2. Heuristic Text Scanning (qualitative signals via regex fallback)
    """
    import warnings
    from bs4 import XMLParsedAsHTMLWarning
    from aethelark_trade.xbrl import extract_proxy_xbrl

    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

    # Layer 1: Deterministic iXBRL extraction
    xbrl = extract_proxy_xbrl(html_content)

    # Layer 2: Heuristic text scanning for qualitative signals
    soup = BeautifulSoup(html_content, 'lxml')
    text = soup.get_text(" ", strip=True)

    signals = {
        "xbrl": xbrl,
        "has_crimes": False,
        "has_comp_table": not xbrl.is_empty,
        "compensation_snippet": "",
        "has_clawback": False,
        "clawback_snippet": "",
        "has_ownership_guidelines": False,
        "ownership_snippet": "",
    }

    # Fallback: regex comp table detection if XBRL is empty
    if xbrl.is_empty:
        comp_match = re.search(r"Summary\s+Compensation\s+Table", text, re.IGNORECASE)
        if comp_match:
            signals["has_comp_table"] = True
            start = comp_match.end()
            signals["compensation_snippet"] = text[start:start+300].strip() + "..."

    # Clawback Policy (qualitative, not in XBRL)
    claw_match = re.search(r"Clawback\s+Policy", text, re.IGNORECASE)
    if claw_match:
        signals["has_clawback"] = True
        start = claw_match.start()
        signals["clawback_snippet"] = text[start:start+250].strip() + "..."

    # Stock Ownership Guidelines (qualitative)
    own_match = re.search(r"(Stock\s+Ownership\s+Guidelines|Minimum\s+Stock\s+Holdings)", text, re.IGNORECASE)
    if own_match:
        signals["has_ownership_guidelines"] = True
        start = own_match.start()
        signals["ownership_snippet"] = text[start:start+300].strip() + "..."

    # Delinquent Section 16(a) Reports (red flag)
    crime_match = re.search(r"Delinquent\s+Section\s+16\(?a\)?\s+Reports", text, re.IGNORECASE)
    if crime_match:
        signals["has_crimes"] = True

    return signals

def scan_earnings_press_release(html_content: str) -> dict:
    """
    Scans EX-99.1 (Earnings Press Release) for bullish/bearish keywords.
    Returns a dictionary indicating if it was a 'beat' or 'miss' and a snippet.
    """
    soup = BeautifulSoup(html_content, 'lxml')
    text = soup.get_text(" ", strip=True)
    
    signals = {
        "is_beat": False,
        "is_miss": False,
        "earnings_snippet": ""
    }
    
    # Bullish keywords typical for earnings beats
    beat_pattern = r"(?i)\b(record revenue|exceed(s|ed)? (expectations|guidance)|beat (expectations|guidance)|all-time high|strong quarter|record results)\b"
    # Bearish keywords typical for misses
    miss_pattern = r"(?i)\b(missed (expectations|guidance)|fell short|lower than expected|disappointing quarter|decreased revenue|missed estimates)\b"
    
    beat_match = re.search(beat_pattern, text)
    miss_match = re.search(miss_pattern, text)
    
    if beat_match:
        signals["is_beat"] = True
        start = max(0, beat_match.start() - 50)
        signals["earnings_snippet"] = "... " + text[start:start+200].strip() + " ..."
    elif miss_match:
        signals["is_miss"] = True
        start = max(0, miss_match.start() - 50)
        signals["earnings_snippet"] = "... " + text[start:start+200].strip() + " ..."
        
    return signals
