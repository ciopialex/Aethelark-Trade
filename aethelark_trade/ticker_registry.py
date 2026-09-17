"""Canonical ticker registry for S&P 500 and NASDAQ-100.

Single source of truth for tracked tickers, sector ETF mappings,
and raw material dependencies.
"""
import csv
import json
from pathlib import Path

# --- NASDAQ-100 Tickers (as of March 2026) ---
NASDAQ100_TICKERS = [
    "AAPL", "ABNB", "ADBE", "ADI", "ADP", "ADSK", "AEP", "AMAT", "AMD",
    "AMGN", "AMZN", "ANSS", "ARM", "ASML", "AVGO", "AZN", "BIIB", "BKNG",
    "BKR", "CCEP", "CDNS", "CDW", "CEG", "CHTR", "CMCSA", "COST", "CPRT",
    "CRWD", "CSCO", "CSGP", "CTAS", "CTSH", "DASH", "DDOG", "DLTR", "DXCM",
    "EA", "EXC", "FANG", "FAST", "FTNT", "GEHC", "GFS", "GILD", "GOOG",
    "GOOGL", "HON", "IDXX", "ILMN", "INTC", "INTU", "ISRG", "KDP", "KHC",
    "KLAC", "LIN", "LRCX", "LULU", "MAR", "MCHP", "MDB", "MDLZ", "MELI",
    "META", "MNST", "MRVL", "MSFT", "MU", "NFLX", "NVDA", "NXPI", "ODFL",
    "ON", "ORLY", "PANW", "PAYX", "PCAR", "PDD", "PEP", "PLTR", "PYPL",
    "QCOM", "REGN", "ROP", "ROST", "SBUX", "SMCI", "SNPS", "TEAM", "TMUS",
    "TSLA", "TTD", "TTWO", "TXN", "VRSK", "VRTX", "WBD", "WDAY", "XEL",
    "ZS",
]

# --- S&P 500 top 100 (largest by market cap, covers ~70% of index weight) ---
SP500_TOP100 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "BRK.B",
    "LLY", "AVGO", "JPM", "TSLA", "UNH", "XOM", "V", "MA", "PG", "JNJ",
    "COST", "HD", "MRK", "ABBV", "WMT", "NFLX", "BAC", "CRM", "CVX",
    "AMD", "KO", "PEP", "LIN", "TMO", "ORCL", "ADBE", "ACN", "MCD",
    "ABT", "WFC", "PM", "CSCO", "DHR", "IBM", "TXN", "GE", "ISRG",
    "INTU", "CAT", "QCOM", "VZ", "AXP", "AMGN", "NOW", "CMCSA", "BKNG",
    "PFE", "T", "MS", "GS", "SPGI", "LOW", "BLK", "NEE", "RTX",
    "UNP", "COP", "HON", "ETN", "DE", "PLD", "AMAT", "VRTX", "C",
    "ADP", "BA", "SYK", "MDLZ", "PANW", "SBUX", "ADI", "LRCX", "BMY",
    "MMC", "GILD", "REGN", "CB", "SCHW", "MU", "KLAC", "SO", "DUK",
    "CI", "ZTS", "SNPS", "SLB", "CME", "PGR", "BDX", "ICE", "FI",
    "CDNS", "MCK", "MO", "EOG", "EL", "WM", "MSI", "HUM", "APH",
    "MCO", "NOC", "USB", "TGT",
]

# --- Sector ETF Mapping ---
TICKER_TO_SECTOR_ETF = {
    # Technology (XLK)
    "AAPL": "XLK", "MSFT": "XLK", "NVDA": "XLK", "AVGO": "XLK", "CSCO": "XLK",
    "ADBE": "XLK", "CRM": "XLK", "ACN": "XLK", "ORCL": "XLK", "IBM": "XLK",
    "TXN": "XLK", "INTU": "XLK", "AMD": "XLK", "QCOM": "XLK", "AMAT": "XLK",
    "ADI": "XLK", "LRCX": "XLK", "KLAC": "XLK", "SNPS": "XLK", "CDNS": "XLK",
    "MRVL": "XLK", "MU": "XLK", "INTC": "XLK", "NXPI": "XLK", "ON": "XLK",
    "MCHP": "XLK", "FTNT": "XLK", "PANW": "XLK", "NOW": "XLK", "MSI": "XLK",
    "PLTR": "XLK", "CRWD": "XLK", "ZS": "XLK", "DDOG": "XLK", "TTD": "XLK",
    "TEAM": "XLK", "WDAY": "XLK", "MDB": "XLK", "ARM": "XLK", "SMCI": "XLK",
    "GFS": "XLK", "ASML": "XLK", "ANSS": "XLK", "ADSK": "XLK", "CDW": "XLK",
    "CTSH": "XLK",

    # Consumer Discretionary (XLY)
    "AMZN": "XLY", "TSLA": "XLY", "HD": "XLY", "MCD": "XLY", "NKE": "XLY",
    "LOW": "XLY", "BKNG": "XLY", "SBUX": "XLY", "TGT": "XLY", "ROST": "XLY",
    "ORLY": "XLY", "MAR": "XLY", "LULU": "XLY", "ABNB": "XLY", "DASH": "XLY",
    "CPRT": "XLY", "DLTR": "XLY", "PCAR": "XLY", "TTWO": "XLY", "EA": "XLY",

    # Communication Services (XLC)
    "META": "XLC", "GOOGL": "XLC", "GOOG": "XLC", "NFLX": "XLC", "CMCSA": "XLC",
    "T": "XLC", "VZ": "XLC", "TMUS": "XLC", "CHTR": "XLC", "WBD": "XLC",
    "PDD": "XLC", "MELI": "XLC",

    # Healthcare (XLV)
    "UNH": "XLV", "LLY": "XLV", "JNJ": "XLV", "MRK": "XLV", "ABBV": "XLV",
    "ABT": "XLV", "TMO": "XLV", "PFE": "XLV", "DHR": "XLV", "ISRG": "XLV",
    "AMGN": "XLV", "VRTX": "XLV", "SYK": "XLV", "BMY": "XLV", "GILD": "XLV",
    "REGN": "XLV", "CI": "XLV", "ZTS": "XLV", "BDX": "XLV", "HUM": "XLV",
    "IDXX": "XLV", "ILMN": "XLV", "DXCM": "XLV", "GEHC": "XLV", "BIIB": "XLV",
    "AZN": "XLV", "MCK": "XLV",

    # Financials (XLF)
    "JPM": "XLF", "BAC": "XLF", "WFC": "XLF", "GS": "XLF", "MS": "XLF",
    "V": "XLF", "MA": "XLF", "BLK": "XLF", "AXP": "XLF", "SPGI": "XLF",
    "C": "XLF", "SCHW": "XLF", "CB": "XLF", "MMC": "XLF", "CME": "XLF",
    "PGR": "XLF", "ICE": "XLF", "FI": "XLF", "MCO": "XLF", "USB": "XLF",
    "PYPL": "XLF",

    # Energy (XLE)
    "XOM": "XLE", "CVX": "XLE", "COP": "XLE", "SLB": "XLE", "EOG": "XLE",
    "BKR": "XLE", "FANG": "XLE",

    # Industrials (XLI)
    "GE": "XLI", "CAT": "XLI", "RTX": "XLI", "UNP": "XLI", "HON": "XLI",
    "BA": "XLI", "DE": "XLI", "ETN": "XLI", "NOC": "XLI", "WM": "XLI",
    "FAST": "XLI", "CTAS": "XLI", "ODFL": "XLI", "PAYX": "XLI", "VRSK": "XLI",
    "ROP": "XLI", "APH": "XLI",

    # Consumer Staples (XLP)
    "PG": "XLP", "KO": "XLP", "PEP": "XLP", "COST": "XLP", "WMT": "XLP",
    "PM": "XLP", "MDLZ": "XLP", "MO": "XLP", "EL": "XLP", "MNST": "XLP",
    "KDP": "XLP", "KHC": "XLP",

    # Utilities (XLU)
    "NEE": "XLU", "SO": "XLU", "DUK": "XLU", "AEP": "XLU", "EXC": "XLU",
    "XEL": "XLU", "CEG": "XLU",

    # Real Estate (XLRE)
    "PLD": "XLRE",

    # Materials (XLB)
    "LIN": "XLB", "CCEP": "XLB",
}

# --- Raw Material Dependencies per Ticker ---
TICKER_TO_MATERIALS = {
    # Semiconductors (heavy material dependency)
    "NVDA": ["silicon", "gallium", "germanium", "copper", "gold", "palladium", "neon"],
    "AMD": ["silicon", "gallium", "germanium", "copper", "gold", "neon"],
    "INTC": ["silicon", "gallium", "germanium", "copper", "gold", "neon", "cobalt"],
    "TSLA": ["lithium", "cobalt", "nickel", "copper", "steel", "aluminum", "silicon", "rare_earths"],
    "AVGO": ["silicon", "gallium", "germanium", "copper", "gold"],
    "QCOM": ["silicon", "gallium", "copper", "gold"],
    "TXN": ["silicon", "copper", "gold"],
    "MU": ["silicon", "copper", "gold", "neon"],
    "MRVL": ["silicon", "copper", "gold"],
    "NXPI": ["silicon", "copper", "gold"],
    "ON": ["silicon", "copper"],
    "MCHP": ["silicon", "copper"],
    "AMAT": ["silicon", "tungsten", "cobalt"],
    "LRCX": ["silicon", "tungsten"],
    "KLAC": ["silicon"],
    "ASML": ["silicon", "tin", "rare_earths"],
    "ARM": ["silicon"],
    "GFS": ["silicon", "gallium", "copper", "neon"],
    "SMCI": ["silicon", "copper", "steel", "aluminum"],
    "ADI": ["silicon", "copper", "gold"],

    # Automotive / EV
    "AAPL": ["lithium", "cobalt", "rare_earths", "aluminum", "copper", "gold", "silicon"],

    # Energy
    "XOM": ["oil", "natural_gas", "steel"],
    "CVX": ["oil", "natural_gas", "steel"],
    "COP": ["oil", "natural_gas"],
    "SLB": ["steel", "oil"],

    # Industrials
    "CAT": ["steel", "copper", "aluminum", "iron_ore"],
    "BA": ["aluminum", "titanium", "steel", "copper", "lithium"],
    "DE": ["steel", "iron_ore", "copper"],
    "GE": ["steel", "nickel", "titanium", "rare_earths"],
    "RTX": ["titanium", "steel", "aluminum", "rare_earths"],
    "HON": ["steel", "copper", "rare_earths"],
}

# --- Commodity Ticker Mapping (yfinance symbols) ---
COMMODITY_TICKERS = {
    "copper": "HG=F",
    "gold": "GC=F",
    "silver": "SI=F",
    "platinum": "PL=F",
    "palladium": "PA=F",
    "oil": "CL=F",
    "natural_gas": "NG=F",
    "aluminum": "ALI=F",
    "steel": "SLX",       # Steel ETF proxy
    "lithium": "LIT",     # Lithium ETF proxy
    "uranium": "URA",     # Uranium ETF proxy
    "rare_earths": "REMX", # Rare Earth ETF proxy
    "iron_ore": "VALE",   # Iron ore proxy via Vale
    "silicon": "SILI.L",  # Silicon proxy (limited)
    "cobalt": "LIT",      # Cobalt proxy via Lithium ETF
    "nickel": "JJN",      # Nickel ETN proxy
    "titanium": "TIE",    # Titanium Metals proxy
    "tungsten": "REMX",   # Tungsten proxy via Rare Earth ETF
    "tin": "JJT",         # Tin ETN proxy
}

# --- Macro Indicator Tickers ---
MACRO_TICKERS = {
    "sp500": "^GSPC",
    "nasdaq": "^IXIC",
    "vix": "^VIX",
    "us10y": "^TNX",
    "us3m": "^IRX",
    "dxy": "DX-Y.NYB",
}


# --- Granular Industry Mapping (The R32 Matrix) ---
TICKER_TO_INDUSTRY = {
    "MSFT": "Software - Infrastructure", "ORCL": "Software - Infrastructure", "PLTR": "Software - Infrastructure",
    "PANW": "Software - Infrastructure", "CRWD": "Software - Infrastructure", "FTNT": "Software - Infrastructure",
    "ADBE": "Software - Infrastructure", "SNPS": "Software - Infrastructure", "CDNS": "Software - Infrastructure",
    "ANSS": "Software - Infrastructure", "ADSK": "Software - Infrastructure", "TEAM": "Software - Infrastructure",
    "WDAY": "Software - Infrastructure",
    
    "NVDA": "Semiconductors", "AVGO": "Semiconductors", "TSM": "Semiconductors", "AMD": "Semiconductors",
    "MU": "Semiconductors", "INTC": "Semiconductors", "TXN": "Semiconductors", "QCOM": "Semiconductors",
    "ADI": "Semiconductors", "MCHP": "Semiconductors", "MRVL": "Semiconductors", "ON": "Semiconductors",
    "NXPI": "Semiconductors", "STM": "Semiconductors", "GFS": "Semiconductors",
    
    "AAPL": "Consumer Electronics",
    
    "DELL": "Computer Hardware", "ANET": "Computer Hardware", "WDC": "Computer Hardware",
    "HPQ": "Computer Hardware", "STX": "Computer Hardware", "SMCI": "Computer Hardware",
    "NTAP": "Computer Hardware", "HPE": "Computer Hardware",
    
    "GOOGL": "Internet Content & Information", "GOOG": "Internet Content & Information",
    "META": "Internet Content & Information", "BABA": "Internet Content & Information",
    "PDD": "Internet Content & Information", "BIDU": "Internet Content & Information",
    "TCEHY": "Internet Content & Information", "SNAP": "Internet Content & Information",
    
    "TSLA": "Auto Manufacturers", "TM": "Auto Manufacturers", "GM": "Auto Manufacturers",
    "F": "Auto Manufacturers", "HMC": "Auto Manufacturers", "STLA": "Auto Manufacturers",
    "RIVN": "Auto Manufacturers", "LCID": "Auto Manufacturers",
    
    "CSCO": "Communication Equipment", "MSI": "Communication Equipment", "CIEN": "Communication Equipment",
    "LITE": "Communication Equipment", "ZBRA": "Communication Equipment", "ERIC": "Communication Equipment",
    "NOK": "Communication Equipment",
    
    "APH": "Electronic Components", "GLW": "Electronic Components", "TEL": "Electronic Components",
    "JBL": "Electronic Components", "CLS": "Electronic Components", "KEYS": "Electronic Components",
    "TDY": "Electronic Components",
    
    "CRM": "Software - Application", "NOW": "Software - Application", "INTU": "Software - Application",
    "SAP": "Software - Application", "SHOP": "Software - Application", "UBER": "Software - Application",
    "DASH": "Software - Application", "ABNB": "Software - Application",
}

# --- Industry to Raw Material Mapping (Structural Cost-Push) ---
INDUSTRY_TO_MATERIALS = {
    "Auto Manufacturers": ["lithium", "steel", "aluminum"],
    "Semiconductors": ["silicon", "gold", "neon"],
    "Computer Hardware": ["copper", "silver", "plastic"],
    "Electronic Components": ["copper", "silver"],
    "Energy": ["oil", "gas"],
    "Airlines": ["oil"],
    "Drug Manufacturers - General": ["chemicals"]
}

def get_all_tracked_tickers() -> list[str]:
    """Return deduplicated union of NASDAQ-100 and S&P 500 top 100."""
    return sorted(set(NASDAQ100_TICKERS + SP500_TOP100))


def get_sector_etf(ticker: str) -> str | None:
    """Look up the sector ETF for a ticker."""
    return TICKER_TO_SECTOR_ETF.get(ticker.upper())


def get_industry(ticker: str) -> str | None:
    """Look up the granular industry for a ticker."""
    return TICKER_TO_INDUSTRY.get(ticker.upper())


def get_material_deps(ticker: str) -> list[str]:
    """Get raw material dependencies for a ticker."""
    return TICKER_TO_MATERIALS.get(ticker.upper(), [])


def get_commodity_ticker(material: str) -> str | None:
    """Get the yfinance ticker for a commodity/material."""
    return COMMODITY_TICKERS.get(material.lower())


# Fast path known names
COMPANY_NAMES = {
    "TSLA": "Tesla Inc.",
    "NVDA": "NVIDIA Corp.",
    "PLTR": "Palantir Technologies Inc.",
    "INTC": "Intel Corporation",
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "AMZN": "Amazon.com Inc.",
    "GOOGL": "Alphabet Inc.",
    "GOOG": "Alphabet Inc.",
    "META": "Meta Platforms Inc.",
    "AMD": "Advanced Micro Devices",
    "COIN": "Coinbase Global Inc.",
    "MSTR": "MicroStrategy Inc.",
    "NFLX": "Netflix Inc.",
    "BABA": "Alibaba Group",
    "QCOM": "Qualcomm Inc.",
    "ARM": "Arm Holdings plc",
    "AVGO": "Broadcom Inc.",
    "ASML": "ASML Holding N.V.",
    "CRUS": "Cirrus Logic Inc.",
}

_CONSTITUENTS_CACHE: dict[str, str] | None = None
_CIK_CACHE: dict[str, str] | None = None
_NAME_LOOKUP_CACHE: dict[str, str | None] = {}


_CONSTITUENT_CIK_CACHE: dict[str, str] | None = None


# constituents.csv ships inside the package (aethelark_trade/data/) so that a
# plain `pip install` has it. The two paths below it are the source-checkout and
# working-directory fallbacks that existed before packaging, kept so a developer
# copy still overrides the shipped seed.
def _constituents_paths():
    return (
        Path(__file__).resolve().parent / "data" / "constituents.csv",
        Path(__file__).resolve().parent.parent / "constituents.csv",
        Path("constituents.csv"),
    )


def _constituent_ciks() -> dict[str, str]:
    """Symbol -> 10-digit CIK, from the curated universe file.

    SEC's own `company_tickers.json` is authoritative for most of the market and
    wrong or silent for a measurable slice of it. Swept across all 503 names on
    2026-09-04:

      XOM    resolves to 2115436, "ExxonMobil Holdings Corp" — a successor
             registrant created by the 8-K12B filed 2026-07-01. It carries the
             ticker and 29 filings, none of them annual. Every 10-K ExxonMobil
             has ever filed sits under 34088, which now lists no ticker at all.
      6 more (AVB, BK, CTRA, SATS, EA, EQR) are absent from SEC's file entirely.
      2 more (BRK.B, BF.B) are spelled BRK-B and BF-B there.

    All nine are correct in `constituents.csv`, which carries a CIK column for
    every row. So for a name in the tracked universe the curated file wins.

    The XOM case will invert eventually: once the holding company files its
    first 10-K, 2115436 becomes the right answer and 34088 goes stale. That is a
    data update to constituents.csv, not a code change — but it is a real
    expiry, so it is written down here rather than left to be rediscovered.
    """
    global _CONSTITUENT_CIK_CACHE
    if _CONSTITUENT_CIK_CACHE is not None:
        return _CONSTITUENT_CIK_CACHE

    _CONSTITUENT_CIK_CACHE = {}
    for p in _constituents_paths():
        if not p.exists():
            continue
        try:
            with open(p, encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    sym = (row.get("Symbol") or "").strip().upper()
                    cik = (row.get("CIK") or "").strip()
                    if sym and cik.isdigit():
                        _CONSTITUENT_CIK_CACHE[sym] = cik.zfill(10)
            break
        except Exception:
            pass
    return _CONSTITUENT_CIK_CACHE


def cik_for(symbol: str) -> str | None:
    """The curated CIK for a tracked name, or None if it is not one."""
    return _constituent_ciks().get((symbol or "").strip().upper())


def _load_constituents() -> dict[str, str]:
    global _CONSTITUENTS_CACHE
    if _CONSTITUENTS_CACHE is not None:
        return _CONSTITUENTS_CACHE

    _CONSTITUENTS_CACHE = {}
    csv_paths = list(_constituents_paths())
    for p in csv_paths:
        if p.exists():
            try:
                with open(p, mode="r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        sym = row.get("Symbol", "").strip().upper()
                        sec = row.get("Security", "").strip()
                        if sym and sec:
                            _CONSTITUENTS_CACHE[sym] = sec
                break
            except Exception:
                pass
    return _CONSTITUENTS_CACHE


def _load_cik_cache() -> dict[str, str]:
    global _CIK_CACHE
    if _CIK_CACHE is not None:
        return _CIK_CACHE

    _CIK_CACHE = {}
    p = Path.home() / ".aethelark" / "cik_cache.json"
    if p.exists():
        try:
            with open(p, mode="r", encoding="utf-8") as f:
                _CIK_CACHE = json.load(f)
        except Exception:
            pass
    return _CIK_CACHE


def company_name(ticker: str) -> str | None:
    """Resolve a company's legally attested name without fabrication.

    Waterfall:
      1. Known catalog (COMPANY_NAMES)
      2. S&P 500 constituents (constituents.csv)
      3. Local SEC companyfacts Parquet via CIK
      4. Returns None when unresolvable (never invents '<TICKER> Corporation').
    """
    if not ticker or not isinstance(ticker, str):
        return None

    sym = ticker.upper().strip()
    if sym in _NAME_LOOKUP_CACHE:
        return _NAME_LOOKUP_CACHE[sym]

    # 1. Known table
    if sym in COMPANY_NAMES:
        _NAME_LOOKUP_CACHE[sym] = COMPANY_NAMES[sym]
        return COMPANY_NAMES[sym]

    # 2. constituents.csv
    constituents = _load_constituents()
    if sym in constituents:
        _NAME_LOOKUP_CACHE[sym] = constituents[sym]
        return constituents[sym]

    # 3. SEC companyfacts parquet
    ciks = _load_cik_cache()
    cik = ciks.get(sym)
    if cik:
        parquet_path = Path.home() / ".aethelark" / "companyfacts.parquet"
        if parquet_path.exists():
            try:
                import polars as pl
                df = (
                    pl.scan_parquet(parquet_path)
                    .filter(pl.col("cik") == str(cik))
                    .select("entity_name")
                    .limit(1)
                    .collect()
                )
                if len(df) > 0:
                    raw_name = df["entity_name"][0]
                    if raw_name:
                        name = raw_name.strip()
                        _NAME_LOOKUP_CACHE[sym] = name
                        return name
            except Exception:
                pass

    _NAME_LOOKUP_CACHE[sym] = None
    return None

