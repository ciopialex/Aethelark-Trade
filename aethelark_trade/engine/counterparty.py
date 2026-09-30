"""Resolution of raw filer-namespaced XBRL customer tags to named companies and tickers."""
from dataclasses import dataclass
import re

CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

KNOWN_COUNTERPARTIES: dict[str, tuple[str, str | None, float]] = {
    # name -> (canonical_name, ticker, confidence)
    "apple": ("Apple Inc", "AAPL", 1.0),
    "apple inc": ("Apple Inc", "AAPL", 1.0),
    "microsoft": ("Microsoft Corp", "MSFT", 1.0),
    "amazon": ("Amazon.com Inc", "AMZN", 1.0),
    "google": ("Alphabet Inc", "GOOGL", 1.0),
    "alphabet": ("Alphabet Inc", "GOOGL", 1.0),
    "nvidia": ("NVIDIA Corp", "NVDA", 1.0),
    "intel": ("Intel Corp", "INTC", 1.0),
    "qualcomm": ("Qualcomm Inc", "QCOM", 1.0),
    "tsmc": ("Taiwan Semiconductor", "TSM", 1.0),
    "taiwan semiconductor": ("Taiwan Semiconductor", "TSM", 1.0),
    "super micro": ("Super Micro Computer", "SMCI", 1.0),
    "supermicro": ("Super Micro Computer", "SMCI", 1.0),
    "micron": ("Micron Technology", "MU", 1.0),
    "broadcom": ("Broadcom Inc", "AVGO", 1.0),
    "tesla": ("Tesla Inc", "TSLA", 1.0),
    "boeing": ("Boeing Co", "BA", 1.0),
    "general motors": ("General Motors Co", "GM", 1.0),
    "ford": ("Ford Motor Co", "F", 1.0),
    "eli lilly": ("Eli Lilly and Co", "LLY", 1.0),
    "mckesson": ("McKesson Corp", "MCK", 1.0),
    "cencora": ("Cencora Inc", "COR", 1.0),
    "cardinal health": ("Cardinal Health Inc", "CAH", 1.0),
    "spirit aerosystems": ("Spirit AeroSystems", "SPR", 1.0),
    "ge aerospace": ("GE Aerospace", "GE", 1.0),

    # Unlisted international leaders (retained as graph nodes without US ticker)
    "foxconn": ("Foxconn Technology Group", None, 0.9),
    "hon hai": ("Foxconn (Hon Hai Precision)", None, 0.9),
    "luxshare": ("Luxshare Precision Industry", None, 0.9),
    "samsung": ("Samsung Electronics", None, 0.9),
    "catl": ("Contemporary Amperex Technology (CATL)", None, 0.9),
    "byd": ("BYD Company", None, 0.85),
}


@dataclass(frozen=True)
class Counterparty:
    raw_tag: str
    name: str                  # "Apple Inc"
    ticker: str | None         # "AAPL", or None when not US-listed
    confidence: float          # 0.0-1.0


def split_camel_case(text: str) -> str:
    """Split CamelCase into separate words: 'AppleInc' -> 'Apple Inc'."""
    return CAMEL_RE.sub(" ", text).strip()


def normalize_tag_to_name(raw_tag: str) -> str:
    """Strip namespace and Member suffix, then split camel case."""
    # Strip namespace e.g. "crus:AppleIncMember" -> "AppleIncMember"
    local = raw_tag.split(":")[-1] if ":" in raw_tag else raw_tag
    # Strip Member suffix
    if local.endswith("Member"):
        local = local[:-6]
    return split_camel_case(local)


def resolve_counterparty(raw_tag: str) -> Counterparty:
    """Resolve a raw XBRL counterparty member to a canonical name and ticker."""
    name = normalize_tag_to_name(raw_tag)
    lookup_key = name.lower().strip()

    # Direct match in known catalog
    if lookup_key in KNOWN_COUNTERPARTIES:
        canonical, ticker, conf = KNOWN_COUNTERPARTIES[lookup_key]
        return Counterparty(raw_tag=raw_tag, name=canonical, ticker=ticker, confidence=conf)

    # Partial / substring match
    for key, (canonical, ticker, conf) in KNOWN_COUNTERPARTIES.items():
        if key in lookup_key or lookup_key in key:
            return Counterparty(raw_tag=raw_tag, name=canonical, ticker=ticker, confidence=conf * 0.9)

    # Fallback: check if tag represents generic customer label (e.g. CustomerA)
    if re.search(r"customer\s*[a-z0-9]", name, re.I):
        return Counterparty(raw_tag=raw_tag, name=name, ticker=None, confidence=0.2)

    # General unlisted counterparty
    return Counterparty(raw_tag=raw_tag, name=name, ticker=None, confidence=0.5)
