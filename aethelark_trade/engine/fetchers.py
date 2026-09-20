"""Live data adapters for the seven layers.

Every function here returns a best-effort value or raises; engine.py catches
per-layer so a dead upstream costs one layer, never the whole analysis.

SEC traffic goes through aethelark_trade.sec_client.SECClient, whose shared
RateLimiter enforces a 0.14s floor between requests (~7 req/s), inside the
SEC's 10 req/s ceiling.
"""

import logging
from pathlib import Path
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from aethelark_trade.engine.layers.macro import MacroProxies
from aethelark_trade.engine.layers.news_velocity import Headline
from aethelark_trade.engine.layers.supply_chain import SupplyEdge
from aethelark_trade.parser import parse_form4_xml
from aethelark_trade.sec_client import SECClient

logger = logging.getLogger("aethelark.fetchers")

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

MACRO_TICKERS = {
    "yield_10y": "^TNX",
    "vix": "^VIX",
    "dollar_index": "DX-Y.NYB",
    "copper": "HG=F",
}


def fetch_companyfacts(client: SECClient, ticker: str) -> dict:
    """Full XBRL fact set for a ticker (one SEC request after CIK resolution)."""
    cik = client.get_cik(ticker)
    return client._request(COMPANYFACTS_URL.format(cik=cik)).json()


#: Days of Form 4 history the insider layer actually scores. Mirrors
#: `layers.insider.LOOKBACK_DAYS`; imported lazily below so this module keeps
#: no import-time dependency on the layers package.
_INSIDER_LOOKBACK_DAYS = 90

#: Filed after the transaction, so a filing just outside the window can still
#: carry a transaction inside it. Form 4 is due within two business days; ten
#: days is generous enough to cover late and amended filings.
_FILING_GRACE_DAYS = 10


def fetch_insider_transactions(client: SECClient, ticker: str, limit: int = 40) -> list:
    """Parse the recent Form 4 filings into InsiderTransaction objects.

    Only filings the scorer can actually use are downloaded. Each filing costs
    TWO SEC requests -- one to find the XML inside it, one to fetch it -- and
    the rate limiter paces every request 0.14s apart, so the download loop is
    the entire cost of this layer. Measured 2026-09-05 on PLTR: 40 filings
    fetched, 16 inside the 90-day window the scorer reads, 24 downloaded and
    discarded. 81 SEC requests, 11.4 seconds, most of it spent on data that was
    thrown away before it was scored.

    The filing date is already in the listing, before any download, so this
    filter costs nothing. `limit` still bounds the listing, because a company
    with heavy insider activity can file more inside 90 days than anyone needs.
    """
    cik = client.get_cik(ticker)
    cutoff = date.today() - timedelta(
        days=_INSIDER_LOOKBACK_DAYS + _FILING_GRACE_DAYS)

    transactions = []
    for filing in client.get_form4_filings(cik, limit=limit):
        accession = filing["accession_number"]
        try:
            if date.fromisoformat(filing["filing_date"]) < cutoff:
                continue
        except (TypeError, ValueError):
            pass            # an unreadable date is not a reason to skip it
        try:
            xml_name = client.find_form4_xml(cik, accession)
            if not xml_name:
                continue
            xml = client.download_xml(cik, accession, xml_name)
            filed = date.fromisoformat(filing["filing_date"])
            transactions.extend(parse_form4_xml(xml, filed, accession))
        except Exception as exc:  # one malformed filing must not sink the layer
            logger.debug("Form 4 %s unparseable: %s", accession, exc)
    return transactions


# Sessions the relativity layer scores over. Pinned rather than derived from a
# period string: providers return a variable number of bars for the same
# request, which made the same ticker score 43 one call and 37 the next.
SESSION_WINDOW = 120

# Fetched wider than SESSION_WINDOW so the tail is always full.
PRICE_PERIOD = "1y"


def pin_window(series: list[float], window: int = SESSION_WINDOW) -> list[float]:
    """The most recent `window` observations, or all of them if fewer exist.

    Short histories are passed through rather than padded: a recent listing
    has less data available; padding would alter the z-score.
    """
    if len(series) <= window:
        return list(series)
    return list(series[-window:])


#: Points kept per range when a series is drawn. The sparkline is ~400px wide,
#: so 5Y at daily resolution is 1250 points — three per pixel, none of them
#: visible. 100 renders identically and lets all six ranges share one payload
#: without passing the module bus's 16000-character ceiling.
#:
#: Corrected 2026-09-08: this used to say the JSON is "not truncated but
#: rejected". It is truncated, silently, mid-structure, with a character count
#: appended — and the model answers from the fragment. Believing overflow fails
#: loudly is how a payload goes uncapped for months: you assume you would have
#: heard about it. See docs/MODULE_CONTRACT.md in Space-Eagle.
SERIES_POINTS = 100

#: How many sales the model is shown by name. Everything is COUNTED — the
#: totals below are computed over the whole ledger — and this is only how many
#: get named individually.
#:
#: Measured 2026-09-07 on AMD over 180 days: 182 filings, 47,586 characters,
#: against a 16,000 ceiling that clips mid-structure. 121 filings were cut. The
#: model answered from the 61 that survived and reported $45M of selling
#: against a true $118M, naming two mid-level executives and never the CEO,
#: whose own sales were entirely on the far side of the cut. Every figure in
#: that answer was true. The omission was the lie.
#:
#: Ranking is what fixes it. Twelve rows is roughly 1,300 characters, so a busy
#: ledger and a quiet one both fit, and the largest sale is present because it
#: is the largest — not because of where a byte offset happened to fall.
TOP_SALES = 12

#: Form 4 transaction codes, in the words a person would use. `S` and `P` are
#: the only two that are somebody deciding to sell or buy on the open market;
#: the rest are vesting machinery and are counted, not named. Conflating them
#: is how "insiders dumped $80M" gets written about a tax withholding.
_SALE, _PURCHASE = "S", "P"
_CODE_NAMES = {
    "M": "exercises",
    "F": "tax_withheld",
    "A": "grants",
    "G": "gifts",
}


def _usd(row: dict) -> float:
    """The absolute dollar value of one filing, or 0 when it carried none."""
    try:
        return abs(float(row.get("value") or 0.0))
    except (TypeError, ValueError):
        return 0.0


def insider_ledger_view(rows: list[dict], ticker: str, days: int,
                        form144_notices: int = 0) -> dict:
    """The insider ledger as a payload that fits the bus.

    `rows` are the flattened filings, newest first. Pure: no network, no SEC
    client, no clock.

    Two audiences, one payload, and they need opposite things. The card can
    page through hundreds of rows; a voice model cannot read them and the bus
    will cut them mid-object on the way to it. So the model gets totals over
    EVERYTHING plus the sales that matter most, and the full ledger travels
    underscored — `_transactions` — which Space-Eagle's `model_view` strips
    from the model's copy and keeps whole for the screen. Same mechanism the
    six chart ranges already use.

    The totals are the point. A capped list is a sample and says so; an
    aggregate computed over the whole ledger is simply true, however few rows
    are named beside it.
    """
    sales = [r for r in rows if r.get("code") == _SALE]
    buys = [r for r in rows if r.get("code") == _PURCHASE]

    other: dict[str, int] = {}
    for row in rows:
        code = row.get("code")
        if code in (_SALE, _PURCHASE):
            continue
        other[_CODE_NAMES.get(code, f"code_{code}")] = (
            other.get(_CODE_NAMES.get(code, f"code_{code}"), 0) + 1)

    def named(row: dict) -> dict:
        """One filing, reduced to what decides whether it matters.

        `is_10b5_1` stays: a sale scheduled months ago under a plan and a sale
        somebody chose to make this week are different facts, and dropping the
        flag would let the model present one as the other.
        """
        code = row.get("code")
        return {
            "date": row.get("date"),
            "insider": row.get("insider"),
            "title": row.get("title"),
            # The word, not the letter. `top_sales` is all one code and could
            # imply it, but `latest` is whatever happened most recently, and a
            # model handed {"code": "F"} has no way to know that is a tax
            # withholding rather than somebody selling.
            "action": ("sold" if code == _SALE else
                       "bought" if code == _PURCHASE else
                       _CODE_NAMES.get(code, f"code_{code}")),
            "usd": round(_usd(row), 2),
            "is_10b5_1": row.get("is_10b5_1"),
        }

    sold_usd = round(sum(_usd(r) for r in sales), 2)
    bought_usd = round(sum(_usd(r) for r in buys), 2)

    return {
        "ticker": ticker.upper(),
        "lookback_days": days,
        "filings": len(rows),
        "sold": {"count": len(sales), "usd": sold_usd},
        "bought": {"count": len(buys), "usd": bought_usd},
        "net_usd": round(bought_usd - sold_usd, 2),
        "other": other,
        # Sales are capped; purchases never are. An insider BUYING is the rare
        # signal and there are seldom more than a handful — dropping one to
        # save a hundred characters would throw away the reason to look.
        "top_sales": [named(r) for r in
                      sorted(sales, key=_usd, reverse=True)[:TOP_SALES]],
        "buys": [named(r) for r in sorted(buys, key=_usd, reverse=True)],
        "latest": named(rows[0]) if rows else None,
        "form144_notices": form144_notices,
        "_transactions": rows,
    }


#: The six range pills, and what each one has to ask the feed for. 1D is
#: intraday: drawn from daily bars a single trading day is one point.
SERIES_RANGES: dict[str, tuple[str, str]] = {
    "1D": ("1d", "1m"),
    "7D": ("7d", "15m"),
    "1M": ("1mo", "1d"),
    "3M": ("3mo", "1d"),
    "1Y": ("1y", "1d"),
    "5Y": ("5y", "1wk"),
}


def downsample(series: list[float], target: int = SERIES_POINTS) -> list[float]:
    """`series` reduced to `target` points, keeping the shape.

    Largest-Triangle-Three-Buckets. Taking every Nth point is cheaper and
    wrong: it drops whichever samples happen to fall between strides, so the
    one bar where a stock fell twenty percent disappears and the card draws a
    calm afternoon. LTTB walks bucket by bucket and keeps, from each, the point
    forming the largest triangle with the last point kept and the mean of the
    next bucket — which is the point furthest from the line its neighbours
    would otherwise draw, so peaks and troughs are exactly what survives.

    First and last are always kept: they are the open and the current price.
    """
    n = len(series)
    if target >= n or target < 3:
        if target < 3 and n > target >= 2:
            return [series[0], series[-1]][:target]
        return list(series)

    kept = [series[0]]
    step = (n - 2) / (target - 2)
    previous = 0

    for i in range(target - 2):
        lo = int(math.floor((i + 1) * step)) + 1
        hi = min(int(math.floor((i + 2) * step)) + 1, n - 1)
        nxt_lo = hi
        nxt_hi = min(int(math.floor((i + 3) * step)) + 1, n)
        if nxt_hi <= nxt_lo:
            nxt_lo, nxt_hi = n - 1, n
        avg_x = (nxt_lo + nxt_hi - 1) / 2.0
        avg_y = sum(series[nxt_lo:nxt_hi]) / (nxt_hi - nxt_lo)

        best, best_area = lo, -1.0
        for j in range(lo, max(hi, lo + 1)):
            area = abs((previous - avg_x) * (series[j] - series[previous])
                       - (previous - j) * (avg_y - series[previous])) / 2.0
            if area > best_area:
                best_area, best = area, j
        kept.append(series[best])
        previous = best

    kept.append(series[-1])
    return kept


def fetch_series(symbol: str,
                 points: int = SERIES_POINTS) -> dict[str, list[float]]:
    """Close prices for every range pill, downsampled to fit one payload.

    A range the feed cannot serve comes back empty rather than missing: the
    card draws six pills either way, and one that is absent from the payload
    is indistinguishable from a bug.
    """
    def _one(item):
        label, (period, interval) = item
        try:
            closes = _close_series(symbol, period=period, interval=interval)
        except Exception:
            closes = []
        return label, [round(v, 4) for v in downsample(closes, points)]

    # Six independent HTTP requests. Serially they cost the sum of their
    # latencies (1.54s measured); together they cost the slowest one, on top
    # of a quote that already takes 2.7s. Threads rather than processes
    # because every one of them is waiting on a socket, not on a CPU.
    with ThreadPoolExecutor(max_workers=len(SERIES_RANGES)) as pool:
        fetched = dict(pool.map(_one, SERIES_RANGES.items()))

    # Rebuilt in declaration order: the card draws its pills left to right,
    # and completion order is whatever the network decided.
    return {label: fetched.get(label, []) for label in SERIES_RANGES}


def _close_series(symbol: str, period: str = PRICE_PERIOD,
                  interval: str = "1d") -> list[float]:
    import yfinance as yf

    frame = yf.Ticker(symbol).history(period=period, interval=interval,
                                      auto_adjust=True)
    if frame is None or frame.empty or "Close" not in frame:
        return []
    return [float(v) for v in frame["Close"].dropna().tolist()]


def fetch_price_series(symbol: str, period: str = PRICE_PERIOD) -> list[float]:
    """Close series pinned to a fixed session count, so scores are repeatable."""
    return pin_window(_close_series(symbol, period))


def fetch_macro_proxies() -> MacroProxies:
    """Resolve the macro proxies, tolerating individual symbol failures."""
    values: dict[str, float | None] = {}
    changes: dict[str, float | None] = {}
    for name, symbol in MACRO_TICKERS.items():
        try:
            closes = _close_series(symbol, period="3mo")
            values[name] = closes[-1] if closes else None
            if len(closes) >= 22 and closes[-22]:
                changes[name] = (closes[-1] - closes[-22]) / closes[-22] * 100.0
            else:
                changes[name] = None
        except Exception as exc:
            logger.debug("macro proxy %s failed: %s", symbol, exc)
            values[name] = changes[name] = None

    return MacroProxies(
        yield_10y=values.get("yield_10y"),
        vix=values.get("vix"),
        dollar_index=values.get("dollar_index"),
        copper_change_pct=changes.get("copper"),
    )


def fetch_headlines(ticker: str, limit: int = 20) -> list[Headline]:
    """Keyless corporate/press headlines via aethelark_trade.news."""
    from aethelark_trade.news import NewsClient

    out: list[Headline] = []
    with NewsClient() as news:
        for item in news.fetch_google_news(ticker, limit=limit):
            published = item.get("published")
            when = None
            if published:
                try:
                    when = datetime.fromisoformat(published)
                except ValueError:
                    when = None
            if when is None:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            out.append(
                Headline(
                    title=item.get("title", ""),
                    published=when,
                    source=item.get("source", ""),
                )
            )
    return out


def fetch_supply_edges(ticker: str) -> list[SupplyEdge]:
    """Read the commercial supply graph out of the local database."""
    from aethelark_trade.db import get_db
    from aethelark_trade.engine.layers.supply_chain import SupplyEdge

    db = get_db()
    try:
        cur = db.cursor()
        cols = {r[1] for r in cur.execute("PRAGMA table_info(supply_chain_edges)").fetchall()}
        if "weight" in cols:
            rows = db.execute(
                "SELECT target_ticker, relationship_type, weight, attested, confidence, period_end "
                "FROM supply_chain_edges WHERE source_ticker = ?",
                (ticker.upper(),),
            ).fetchall()
            return [
                SupplyEdge(
                    counterparty=r[0],
                    relationship_type=r[1] or "supplier",
                    weight=float(r[2]) if r[2] is not None else 1.0,
                    health=0.5,
                    attested=bool(r[3]) if r[3] is not None else False,
                    confidence=float(r[4]) if r[4] is not None else 1.0,
                    period_end=str(r[5] or ""),
                )
                for r in rows
            ]
        else:
            rows = db.execute(
                "SELECT target_ticker, relationship_type FROM supply_chain_edges "
                "WHERE source_ticker = ?",
                (ticker.upper(),),
            ).fetchall()
            return [
                SupplyEdge(counterparty=r[0], relationship_type=r[1] or "supplier", health=0.5)
                for r in rows
            ]
    except Exception as exc:
        logger.debug("supply chain read failed: %s", exc)
        return []
    finally:
        db.close()


def ema(series: list[float], span: int = 25) -> float | None:
    """Exponential moving average of the tail of a close series."""
    if len(series) < span:
        return None
    k = 2.0 / (span + 1.0)
    value = sum(series[:span]) / span
    for price in series[span:]:
        value = price * k + value * (1 - k)
    return value


# --- Layer 6 -------------------------------------------------------------
REGIME_TICKERS = {
    "vix": "^VIX",
    "yield_10y": "^TNX",
    # 2-Year yield futures. ^UST2YR is not a valid Yahoo symbol; ^IRX (13-week)
    # is the fallback front-end proxy when the futures series is unavailable.
    "yield_2y": "2YY=F",
    "yield_2y_fallback": "^IRX",
}


def fetch_regime_proxies():
    """Resolve VIX and both curve legs, tolerating individual failures."""
    from aethelark_trade.engine.layers.geopolitics import RegimeProxies

    def last(symbol):
        try:
            closes = _close_series(symbol, period="3mo")
            return closes[-1] if closes else None
        except Exception as exc:
            logger.debug("regime proxy %s failed: %s", symbol, exc)
            return None

    two_year = last(REGIME_TICKERS["yield_2y"])
    if two_year is None:
        two_year = last(REGIME_TICKERS["yield_2y_fallback"])

    return RegimeProxies(
        vix=last(REGIME_TICKERS["vix"]),
        yield_10y=last(REGIME_TICKERS["yield_10y"]),
        yield_2y=two_year,
    )


# --- Layer 7 -------------------------------------------------------------
# Critical single-name suppliers that a buyer cannot substitute inside a cycle.
# A fab slot is not fungible; a copper contract is.
SECTOR_CRITICAL_SUPPLIER = {"XLK": "TSM"}
INDUSTRY_CRITICAL_SUPPLIER = {"Semiconductors": "TSM", "Consumer Electronics": "TSM"}

SUPPLIER_CRITICALITY = 2.0
INPUT_CRITICALITY = 1.0
MAX_INPUT_EDGES = 3
MOMENTUM_PERIOD = "3mo"

# ticker_registry maps silicon to SILI.L, which Yahoo no longer quotes. Skipping
# it up front avoids two guaranteed-404 round trips on every semiconductor name.
DEAD_COMMODITY_SYMBOLS = {"SILI.L"}


def _momentum_pct(symbol: str) -> float | None:
    """Percentage change across the momentum window."""
    closes = _close_series(symbol, period=MOMENTUM_PERIOD)
    if len(closes) < 2 or not closes[0]:
        return None
    return (closes[-1] - closes[0]) / closes[0] * 100.0


def build_supply_edges(ticker: str) -> list[SupplyEdge]:
    """Construct the dependency graph from mapped commercial disclosures.

    If a company has no mapped dependencies, returns an empty list so Layer 7
    honestly reports absence rather than synthesized price momentum.
    """
    return fetch_supply_edges(ticker)


def fetch_market_cap(ticker: str) -> float | None:
    """Market capitalisation via yfinance fast_info."""
    import yfinance as yf

    try:
        value = yf.Ticker(ticker).fast_info.market_cap
        return float(value) if value else None
    except Exception as exc:
        logger.debug("market cap for %s failed: %s", ticker, exc)
        return None


def fetch_form144_filings(client: SECClient, ticker: str, limit: int = 10) -> list:
    """Parse recent Form 144 proposed-sale notices."""
    from aethelark_trade.form144 import parse_form144_xml

    cik = client.get_cik(ticker)
    out = []
    for filing in client.get_form144_filings(cik, limit=limit):
        accession = filing["accession_number"]
        try:
            xml_name = client.find_form144_xml(cik, accession)
            if not xml_name:
                continue
            xml = client.download_xml(cik, accession, xml_name)
            filed = date.fromisoformat(filing["filing_date"])
            parsed = parse_form144_xml(xml, filed, accession)
            if parsed:
                out.append(parsed)
        except Exception as exc:
            logger.debug("Form 144 %s unparseable: %s", accession, exc)
    return out


#: Where an installed copy looks for Alpaca credentials.
ALPACA_ENV_PATH = Path.home() / ".aethelark" / ".env"


def fetch_alpaca_portfolio() -> dict:
    """Account equity, buying power and open positions from Alpaca.

    Credentials come from the environment, or from ~/.aethelark/.env.

    A bare `load_dotenv()` searches upward from the *calling file*, which found
    a .env at the repository root while this package was an editable install
    inside that repository, and finds nothing once it is installed properly --
    it climbs out through site-packages. Measured 2026-09-20: the same command
    returned an account from a source checkout and "ALPACA_API_KEY not set"
    from a pip install on the same machine, with the same .env on disk.

    So the file is looked for where a user's configuration lives rather than
    wherever the code happens to be unpacked. A real environment variable still
    wins, and the old upward search is kept as a fallback for a checkout.
    """
    import os

    from dotenv import load_dotenv

    if not (os.environ.get("ALPACA_API_KEY") and os.environ.get("ALPACA_SECRET_KEY")):
        if ALPACA_ENV_PATH.is_file():
            load_dotenv(ALPACA_ENV_PATH)
        else:
            load_dotenv()

    key = os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError(
            f"ALPACA_API_KEY / ALPACA_SECRET_KEY not set. Put them in the "
            f"environment or in {ALPACA_ENV_PATH}")

    from alpaca.trading.client import TradingClient

    paper = "paper" in (os.environ.get("ALPACA_BASE_URL") or "").lower()
    client = TradingClient(key, secret, paper=paper)

    # alpaca-py types these as unions (TradeAccount | dict, Position | str) that
    # the SDK does not actually return for these calls. Asserting the shape here
    # avoids a per-field ignore on each access below.
    account = client.get_account()
    positions = client.get_all_positions()

    return {
        "account_number": getattr(account, "account_number", None),
        "paper": paper,
        "equity": float(account.equity or 0),                    # type: ignore[union-attr]
        "cash": float(account.cash or 0),                        # type: ignore[union-attr]
        "buying_power": float(account.buying_power or 0),        # type: ignore[union-attr]
        "portfolio_value": float(account.portfolio_value or 0),  # type: ignore[union-attr]
        "positions": [
            {
                # p is a Position; alpaca-py's stub widens it to Position | str.
                "symbol": p.symbol,          # type: ignore[union-attr]
                "qty": float(p.qty),                              # type: ignore[union-attr]
                "avg_entry_price": float(p.avg_entry_price),      # type: ignore[union-attr]
                "market_value": float(p.market_value or 0),       # type: ignore[union-attr]
                "unrealized_pl": float(p.unrealized_pl or 0),     # type: ignore[union-attr]
                "unrealized_plpc": float(p.unrealized_plpc or 0), # type: ignore[union-attr]
            }
            for p in positions
        ],
    }


def load_fundamentals(client, ticker: str, cik: str | None = None,
                      parquet_path=None, live_loader=None):
    """Layer 1 snapshot, preferring the local bulk table over the network.

    Returns (snapshot, source) where source is "bulk" or "live". The weekly
    companyfacts archive exists so that scoring a name during market hours
    costs zero SEC requests; the live API is only touched for CIKs the archive
    does not cover (recent registrants, or a stale cache).
    """
    from aethelark_trade.engine.bulk import load_snapshot_from_parquet
    from aethelark_trade.engine.layers.fundamentals import extract_fundamentals

    if cik is None and client is not None:
        cik = client.get_cik(ticker)

    if cik:
        try:
            snapshot = load_snapshot_from_parquet(cik, parquet_path)
            if snapshot.revenue is not None and snapshot.roic is not None:
                return snapshot, "bulk"
        except Exception as exc:
            logger.debug("bulk lookup for %s failed: %s", ticker, exc)

    loader = live_loader or fetch_companyfacts
    return extract_fundamentals(loader(client, ticker)), "live"


def fetch_governance(client: SECClient, ticker: str):
    """Latest DEF 14A pay-versus-performance signal for a ticker."""
    from aethelark_trade.engine.governance import governance_signal
    from aethelark_trade.xbrl import ProxyXBRL, extract_proxy_xbrl

    cik = client.get_cik(ticker)
    proxies = client.get_proxy_filings(cik, limit=2)
    if not proxies:
        return governance_signal(ProxyXBRL())

    for filing in proxies:
        accession = filing["accession_number"]
        try:
            index = client.get_filing_index(cik, accession)
            document = None
            for item in index.get("directory", {}).get("item", []):
                name = item.get("name", "")
                if name.endswith((".htm", ".html")) and "index" not in name.lower():
                    document = name
                    break
            if not document:
                continue
            html = client.download_filing_text(cik, accession, document)
            signal = governance_signal(extract_proxy_xbrl(html))
            if signal.available:
                return signal
        except Exception as exc:
            logger.debug("proxy %s unreadable: %s", accession, exc)

    return governance_signal(ProxyXBRL())


from aethelark_trade.ticker_registry import COMPANY_NAMES, company_name


def _number(value) -> float | None:
    """A finite number, or None. yfinance hands back None, NaN and 0 for
    "I don't know" depending on the field, and a consumer has to be able to
    tell an absent market cap from a zero one."""
    if value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n != n or n in (float("inf"), float("-inf")):   # NaN / inf
        return None
    return n or None


def _price(value) -> float | None:
    n = _number(value)
    return round(n, 2) if n is not None else None


def _count(value) -> int | None:
    n = _number(value)
    return int(n) if n is not None else None


class QuoteUnavailable(Exception):
    """No price for this symbol, said in words a person can act on.

    `yfinance` reports an unknown symbol by raising out of its own internals --
    measured 2026-09-04, `ZZZQXWNOPE` produced `KeyError: currentTradingPeriod`.
    That names a key inside someone else's library, is not true in any useful
    sense (the symbol was wrong; nothing about a trading period was), and the
    eagle reads it aloud. Anything that escapes this module arrives as one of
    these instead, with the symbol in it.
    """


def fetch_quote(ticker: str) -> dict:
    """Price, range, volume and market stats. The fast path.

    Everything here is a NUMBER. A module's JSON is its public API — the
    Dynamic Island reads it, the shop reads it, and a model doing arithmetic on
    it reads it — and "5.2T" cannot be compared against "820.4B", summed, or
    charted without being parsed back into the thing it was already. Rendering
    is the card's job (AMS-1 §3); a field the feed withheld is null, not a dash.
    """
    import yfinance as yf

    sym = ticker.upper().strip()
    # Every read below can raise from inside yfinance, and what it raises is
    # not ours to predict: the failure mode for an unknown symbol has been a
    # KeyError on a key this code never names. Catching broadly here is the
    # point -- the caller is told which symbol failed, not which library did.
    try:
        info = yf.Ticker(sym).fast_info
        price = float(getattr(info, "last_price", 0.0) or 0.0)
        previous = float(getattr(info, "previous_close", price) or price)
    except Exception as exc:
        raise QuoteUnavailable(
            f"{sym} is not a symbol the market feed knows. If a company was "
            f"named, call quote again with its ticker instead (Apple is AAPL). "
            f"If the ticker was already right, the feed is unreachable and "
            f"retrying will not help.") from exc
    change = price - previous

    return {
        "ticker": sym,
        "company_name": company_name(sym),
        "price": round(price, 2),
        "previous_close": round(previous, 2),
        "change": round(change, 2),
        "change_pct": round(change / previous * 100, 2) if previous else 0.0,
        # Prices to the cent, counts as counts. Still data — just without the
        # fifteen decimal places of float noise nobody trades on.
        "day_high": _price(getattr(info, "day_high", None)),
        "day_low": _price(getattr(info, "day_low", None)),
        "volume": _count(getattr(info, "last_volume", None)),
        "market_cap": _count(getattr(info, "market_cap", None)),
    }


def quote_with_series(symbol: str) -> dict:
    """A quote and its six chart ranges, fetched together.

    The Glance card's range pills have to redraw the moment they are clicked,
    and the island has no way to ask for more data — the Qt bridge exposes a
    fixed set of slots, so anything the card needs has to arrive with it.

    Both lookups are independent and both are waiting on sockets, so they run
    at the same time: measured against the live feed, the quote is the long
    pole and the whole chart hides inside it.
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        quote_future = pool.submit(fetch_quote, symbol)
        series_future = pool.submit(fetch_series, symbol)
        try:
            payload = quote_future.result()
        except QuoteUnavailable:
            raise
        except Exception as exc:
            # The quote layer is expected to raise QuoteUnavailable. Anything
            # else escaping it is a failure nobody has seen yet, and it must
            # still not reach a person as an exception.
            raise QuoteUnavailable(
                f"{symbol.upper().strip()} is not a symbol the market feed "
                f"knows. If a company was named, call quote again with its "
                f"ticker instead (Apple is AAPL). If the ticker was already "
                f"right, the feed is unreachable and retrying will not help."
            ) from exc
        try:
            # Underscored so Space-Eagle's module bus keeps it out of the
            # model's copy. Measured 2026-09-05: the six ranges were 4,312
            # of a quote's 4,542 characters -- 487 numbers sent to a voice
            # model that cannot read a line graph. The island draws it.
            payload["_series"] = series_future.result()
        except Exception:
            # A chart that did not arrive is an empty chart, not a failed
            # quote: the price is the answer and it is already in hand.
            payload["_series"] = {label: [] for label in SERIES_RANGES}
    return payload


#: What a scorecard borrows from the quote when it is handed to a UI.
QUOTE_CONTEXT_KEYS = ("price", "previous_close", "change", "change_pct",
                      "day_high", "day_low", "volume", "market_cap",
                      "company_name", "_series")


def with_quote(payload: dict, ticker: str) -> dict:
    """`payload` plus live market context, or `payload` unchanged.

    Lives here rather than in `SevenLayerResult.to_dict()` because that method
    is called by `store.py` on every scorecard written to the database, and a
    serialiser must not reach for the network. Callers that are already doing
    I/O — the CLI, answering a request — ask for this explicitly.

    A quote that cannot be fetched is not an error: the scorecard is the
    answer, and the price is decoration on it.
    """
    enriched = dict(payload)
    try:
        quote = quote_with_series(ticker)
    except Exception:
        return enriched
    if not isinstance(quote, dict):
        return enriched
    for key in QUOTE_CONTEXT_KEYS:
        if key in quote:
            enriched[key] = quote[key]
    return enriched
