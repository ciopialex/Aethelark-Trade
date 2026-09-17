"""SEC EDGAR HTTP client with rate limiting and proper headers."""

import time
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("SECClient")

import httpx

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_FILING_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/index.json"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

from aethelark_trade.engine.useragent import sec_user_agent

#: SEC requires a declared, contactable UA. Set ATRADE_SEC_CONTACT to use your
#: own address instead of the project URL.
DEFAULT_USER_AGENT = sec_user_agent()
MIN_REQUEST_INTERVAL = 0.14  # 0.14s (~7 requests per second) - Safety Margin Velocity
MAX_RETRIES = 10
RETRY_BACKOFF = 2.0


class RateLimiter:
    """Rate limiter complying with SEC's 10 req/sec limit, MACHINE-WIDE.

    This used to pace on a class attribute, which only coordinates callers
    inside one process. That is not enough here: `atrade listen` is meant to
    run continuously while `atrade analyze` and `atrade leaderboard --refresh`
    are used interactively, and each process then paced independently at
    ~7 req/s. Measured under concurrent runs: HTTP 429, and a mutation test
    reproduces 36 requests inside a single second across four processes.

    Spacing is now held in a lock-guarded file shared by every process on the
    machine. The wait() interface is unchanged, so all existing call sites
    (collector, daemon, backfill, atrade) inherit the guarantee.
    """

    _shared = None

    def __init__(self, min_interval: float = MIN_REQUEST_INTERVAL):
        self.min_interval = min_interval

    def limiter(self):
        """The process-wide handle onto the machine-wide gate."""
        if (RateLimiter._shared is None
                or RateLimiter._shared.min_interval != self.min_interval):
            from aethelark_trade.engine.ratelimit import CrossProcessRateLimiter

            RateLimiter._shared = CrossProcessRateLimiter(
                min_interval=self.min_interval
            )
        return RateLimiter._shared

    def wait(self) -> None:
        self.limiter().acquire()


@dataclass
class SECClientConfig:
    user_agent: str = DEFAULT_USER_AGENT
    cache_dir: Path | None = None
    timeout: float = 30.0


class SECClientError(Exception):
    """Base exception for SEC client errors."""
    pass


class TickerNotFoundError(SECClientError):
    """Ticker symbol not found in SEC database."""
    pass


class RateLimitedError(SECClientError):
    """Request was rate limited by SEC."""
    pass


import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

AETHELARK_DIR = Path.home() / ".aethelark"
CIK_CACHE_PATH = AETHELARK_DIR / "cik_cache.json"

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
# ... (rest of constants)

class SECClient:
    """HTTP client for SEC EDGAR with rate limiting."""
    
    # In-memory cache for the current process
    _global_ticker_cache: dict[str, str] | None = None
    
    def __init__(self, config: SECClientConfig | None = None):
        self.config = config or SECClientConfig()
        self.rate_limiter = RateLimiter()
        self._client: httpx.Client | None = None
        self._submissions_cache: dict[str, dict] = {}

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                headers={"User-Agent": self.config.user_agent, "Accept-Encoding": "gzip, deflate"},
                timeout=self.config.timeout,
                follow_redirects=True,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _request(self, url: str) -> httpx.Response:
        """Rate-limited GET with retry on 429/5xx and SSL Jitter."""
        import ssl
        last_err = None
        for attempt in range(MAX_RETRIES):
            self.rate_limiter.wait()
            try:
                response = self.client.get(url)
                if response.status_code == 429:
                    wait = 12.0 * (attempt + 1)
                    logger.warning(f"⚠️ SEC 429 detected (Rate Limited). Performing heavy cooldown: {wait}s...")
                    time.sleep(wait)
                    continue
                if response.status_code >= 400:
                    logger.error(f"❌ SEC Error {response.status_code} for {url}")
                response.raise_for_status()
                return response
            except (httpx.ConnectError, ssl.SSLError, EOFError, ConnectionResetError) as e:
                last_err = e
                logger.warning(f"🔌 Network Impedance / SSL Jitter detected (Attempt {attempt+1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF * (attempt + 1))
            except httpx.HTTPStatusError as e:
                last_err = e
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF * (attempt + 1))
            except httpx.RequestError as e:
                last_err = e
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF * (attempt + 1))
        raise SECClientError(f"SEC request failed after {MAX_RETRIES} retries: {url}") from last_err

    def _load_ticker_cache(self) -> dict[str, str]:
        """Load and cache ticker to CIK mapping with disk persistence."""
        # 1. Try In-Memory first
        if SECClient._global_ticker_cache is not None:
            return SECClient._global_ticker_cache
            
        # 2. Try Disk Cache
        if CIK_CACHE_PATH.exists():
            try:
                # Only trust disk cache if it's less than 24h old
                if time.time() - CIK_CACHE_PATH.stat().st_mtime < 86400:
                    with open(CIK_CACHE_PATH, "r") as f:
                        cache = json.load(f)
                        SECClient._global_ticker_cache = cache
                        return cache
            except Exception:
                pass

        # 3. Fetch from SEC
        response = self._request(SEC_TICKERS_URL)
        data = response.json()
        
        cache = {}
        for entry in data.values():
            ticker = entry.get("ticker", "").upper()
            cik = entry.get("cik_str", "")
            if ticker and cik:
                cache[ticker] = str(cik).zfill(10)
        
        # 4. Save to Disk and Memory
        AETHELARK_DIR.mkdir(parents=True, exist_ok=True)
        with open(CIK_CACHE_PATH, "w") as f:
            json.dump(cache, f)
            
        SECClient._global_ticker_cache = cache
        return cache
    
    def get_cik(self, ticker: str) -> str:
        """Resolve ticker symbol to 10-digit CIK.

        The curated universe wins over SEC's own ticker file, which is wrong or
        silent for nine of the 503 tracked names — see `ticker_registry.
        _constituent_ciks` for the sweep and for why XOM in particular resolved
        to a registrant holding no annual filings at all.

        Outside the universe, SEC's file is all there is; a symbol written with
        a dot is retried with a hyphen, which is how SEC spells share classes
        (BRK.B is BRK-B there).
        """
        ticker = ticker.upper().strip()

        from aethelark_trade.ticker_registry import cik_for
        curated = cik_for(ticker)
        if curated:
            return curated

        cache = self._load_ticker_cache()
        for candidate in (ticker, ticker.replace(".", "-")):
            if candidate in cache:
                return cache[candidate]

        raise TickerNotFoundError(f"Ticker '{ticker}' not found in SEC database")
    
    def get_submissions(self, cik: str) -> dict:
        """Get company filings submission history.

        Cached per client: layer 5 wants the Form 4 list and layer 1 wants the
        SIC code, and both live in this one document. Fetching it twice for the
        same company in the same run is a request spent on nothing.
        """
        if cik in self._submissions_cache:
            return self._submissions_cache[cik]
        url = SEC_SUBMISSIONS_URL.format(cik=cik)
        payload = self._request(url).json()
        self._submissions_cache[cik] = payload
        return payload

    def get_sic(self, cik: str) -> int | None:
        """Standard Industrial Classification, or None if SEC does not say.

        6000-6799 is finance, insurance and real estate — the filers for whom a
        cash-flow margin is not a measure of the business (layer 1).
        """
        try:
            raw = self.get_submissions(cik).get("sic")
        except Exception:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    
    #: Where a filed document is kept once fetched. A filing that has been
    #: accepted by EDGAR never changes -- an amendment is a NEW accession with
    #: its own number -- so this is a cache with no invalidation problem and no
    #: staleness risk. It exists because the cost of a Form 4 is not bandwidth
    #: but the rate limiter: every request waits 0.14s behind the last one, and
    #: the prefetch means the same company is often analysed twice in a minute.
    FILING_CACHE_DIR = AETHELARK_DIR / "filing_cache"

    def _cached_filing(self, kind: str, cik: str, accession: str,
                       filename: str, fetch):
        """`fetch()`'s result, from disk when it has been fetched before."""
        import hashlib

        key = hashlib.sha256(
            f"{kind}|{cik}|{accession}|{filename}".encode()).hexdigest()[:32]
        path = self.FILING_CACHE_DIR / f"{key}.{kind}"
        try:
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                return json.loads(text) if kind == "index" else text
        except (OSError, ValueError):
            pass                      # an unreadable cache entry is not an error

        value = fetch()
        try:
            self.FILING_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            # Written via a temporary file in the same directory so a process
            # killed mid-write cannot leave a truncated entry to be read back
            # as a real filing.
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_text(
                json.dumps(value) if kind == "index" else value,
                encoding="utf-8")
            tmp.replace(path)
        except (OSError, TypeError, ValueError):
            pass                      # caching is an optimisation, never a gate
        return value

    def get_filing_index(self, cik: str, accession: str) -> dict:
        """Get filing directory index."""
        def _fetch():
            # Remove dashes from accession for URL
            accession_clean = accession.replace("-", "")
            url = SEC_FILING_INDEX_URL.format(
                cik=cik.lstrip("0"), accession=accession_clean)
            return self._request(url).json()

        return self._cached_filing("index", cik, accession, "", _fetch)
    
    def find_form4_xml(self, cik: str, accession: str) -> str | None:
        """Find the Form 4 XML file in a filing directory."""
        try:
            index = self.get_filing_index(cik, accession)
            directory = index.get("directory", {})
            items = directory.get("item", [])
            
            # Look for XML files that are likely the Form 4 document
            for item in items:
                name = item.get("name", "")
                # Form 4 XML files typically have these patterns
                if name.endswith(".xml") and not name.startswith("primary_doc"):
                    # Prefer files that look like form4 or ownership documents
                    lower_name = name.lower()
                    if ("form4" in lower_name or 
                        "ownership" in lower_name or 
                        "wf-" in lower_name or  # SEC's official XML
                        "wk-" in lower_name or  # Workiva
                        name.startswith("doc") or
                        "-form4" in lower_name):
                        return name
            
            # Fallback: return first XML file that's not a primary_doc
            for item in items:
                name = item.get("name", "")
                if name.endswith(".xml") and "primary_doc" not in name:
                    return name
            
            return None
        except SECClientError:
            return None
    
    def download_filing_text(self, cik: str, accession: str, filename: str) -> str:
        """Download filing content (HTML/XML/Text)."""
        def _fetch():
            accession_clean = accession.replace("-", "")
            url = (f"{SEC_ARCHIVES_BASE}/{cik.lstrip('0')}/"
                   f"{accession_clean}/{filename}")
            return self._request(url).text

        return self._cached_filing("doc", cik, accession, filename, _fetch)

    def download_xml(self, cik: str, accession: str, filename: str) -> str:
        """Deprecated alias for download_filing_text."""
        return self.download_filing_text(cik, accession, filename)
    
    def get_form4_filings(self, cik: str, limit: int = 50) -> list[dict]:
        """Get Form 4 and Form 4/A filings for a company."""
        submissions = self.get_submissions(cik)
        filings = submissions.get("filings", {}).get("recent", {})
        
        form_types = filings.get("form", [])
        accessions = filings.get("accessionNumber", [])
        filing_dates = filings.get("filingDate", [])
        primary_docs = filings.get("primaryDocument", [])
        
        form4_filings = []
        for i, form_type in enumerate(form_types):
            if form_type in ("4", "4/A"):
                form4_filings.append({
                    "form_type": form_type,
                    "accession_number": accessions[i],
                    "filing_date": filing_dates[i],
                    "primary_document": primary_docs[i],
                })
                if len(form4_filings) >= limit:
                    break
        
        return form4_filings

    def get_form144_filings(self, cik: str, limit: int = 50) -> list[dict]:
        """Get Form 144 filings for a company (planned insider sales)."""
        submissions = self.get_submissions(cik)
        filings = submissions.get("filings", {}).get("recent", {})
        
        form_types = filings.get("form", [])
        accessions = filings.get("accessionNumber", [])
        filing_dates = filings.get("filingDate", [])
        primary_docs = filings.get("primaryDocument", [])
        
        form144_filings = []
        for i, form_type in enumerate(form_types):
            if form_type == "144":
                form144_filings.append({
                    "form_type": form_type,
                    "accession_number": accessions[i],
                    "filing_date": filing_dates[i],
                    "primary_document": primary_docs[i],
                })
                if len(form144_filings) >= limit:
                    break
        
        return form144_filings

    def find_form144_xml(self, cik: str, accession: str) -> str | None:
        """Find the Form 144 XML file in a filing directory."""
        try:
            index = self.get_filing_index(cik, accession)
            directory = index.get("directory", {})
            items = directory.get("item", [])
            
            for item in items:
                name = item.get("name", "")
                if name.endswith(".xml") and not name.startswith("primary_doc"):
                    lower_name = name.lower()
                    if "form144" in lower_name or "144" in lower_name:
                        return name
            
            # Fallback: return first XML file
            for item in items:
                name = item.get("name", "")
                if name.endswith(".xml") and "primary_doc" not in name:
                    return name
            
            return None
        except SECClientError:
            return None

    def get_schedule13_filings(self, cik: str, limit: int = 20) -> list[dict]:
        """Get Schedule 13D/13G filings (5%+ beneficial ownership)."""
        submissions = self.get_submissions(cik)
        filings = submissions.get("filings", {}).get("recent", {})
        
        form_types = filings.get("form", [])
        accessions = filings.get("accessionNumber", [])
        filing_dates = filings.get("filingDate", [])
        primary_docs = filings.get("primaryDocument", [])
        
        schedule13_filings = []
        target_prefixes = ("SC 13D", "SC 13G")
        
        for i, form in enumerate(form_types):
            if any(form.startswith(prefix) for prefix in target_prefixes):
                if not primary_docs[i]:
                    continue
                schedule13_filings.append({
                    "form_type": form,
                    "accession_number": accessions[i],
                    "filing_date": filing_dates[i],
                    "primary_document": primary_docs[i],
                })
                if len(schedule13_filings) >= limit:
                    break
        
        return schedule13_filings

    def get_event_filings(self, cik: str, limit: int = 20) -> list[dict]:
        """Get 8-K filings (Material Events)."""
        submissions = self.get_submissions(cik)
        filings = submissions.get("filings", {}).get("recent", {})
        
        form_types = filings.get("form", [])
        accessions = filings.get("accessionNumber", [])
        filing_dates = filings.get("filingDate", [])
        primary_docs = filings.get("primaryDocument", [])
        items = filings.get("items", []) # 8-K items are often in this field in recent filings
        
        events = []
        for i, form in enumerate(form_types):
            if form == "8-K":
                events.append({
                    "form_type": form,
                    "accession_number": accessions[i],
                    "filing_date": filing_dates[i],
                    "primary_document": primary_docs[i],
                    "items": items[i] if i < len(items) else "", 
                })
                if len(events) >= limit:
                    break
        return events

    def get_proxy_filings(self, cik: str, limit: int = 5) -> list[dict]:
        """Get Proxy filings (DEF 14A, PRE 14A)."""
        submissions = self.get_submissions(cik)
        filings = submissions.get("filings", {}).get("recent", {})
        
        form_types = filings.get("form", [])
        accessions = filings.get("accessionNumber", [])
        filing_dates = filings.get("filingDate", [])
        primary_docs = filings.get("primaryDocument", [])
        
        proxies = []
        target_forms = ("DEF 14A", "PRE 14A")
        
        for i, form in enumerate(form_types):
            if form in target_forms:
                proxies.append({
                    "form_type": form,
                    "accession_number": accessions[i],
                    "filing_date": filing_dates[i],
                    "primary_document": primary_docs[i],
                })
                if len(proxies) >= limit:
                    break
        return proxies

    def get_merger_filings(self, cik: str, limit: int = 10) -> list[dict]:
        """Get M&A related filings (425, SC 13E3, etc)."""
        submissions = self.get_submissions(cik)
        filings = submissions.get("filings", {}).get("recent", {})
        
        form_types = filings.get("form", [])
        accessions = filings.get("accessionNumber", [])
        filing_dates = filings.get("filingDate", [])
        primary_docs = filings.get("primaryDocument", [])
        
        mergers = []
        # 425: Prospectuses and communications (M&A)
        # SC 13E3: Going private transaction
        # PREM14A / DEFM14A: Merger proxy statements
        target_prefixes = ("425", "SC 13E3", "PREM14A", "DEFM14A")
        
        for i, form in enumerate(form_types):
            if any(form.startswith(prefix) for prefix in target_prefixes):
                mergers.append({
                    "form_type": form,
                    "accession_number": accessions[i],
                    "filing_date": filing_dates[i],
                    "primary_document": primary_docs[i],
                })
                if len(mergers) >= limit:
                    break
        return mergers

    def find_schedule13_xml(self, cik: str, accession: str) -> str | None:
        """Find the Schedule 13D/13G XML file in a filing directory."""
        try:
            index = self.get_filing_index(cik, accession)
            directory = index.get("directory", {})
            items = directory.get("item", [])
            
            for item in items:
                name = item.get("name", "")
                if name.endswith(".xml") and "primary_doc" not in name:
                    lower_name = name.lower()
                    if "sc13" in lower_name or "13d" in lower_name or "13g" in lower_name:
                        return name
            
            # Fallback: return first XML file
            for item in items:
                name = item.get("name", "")
                if name.endswith(".xml") and "primary_doc" not in name:
                    return name
            
            return None
        except SECClientError:
            return None

    def find_ex991_html(self, cik: str, accession: str) -> str | None:
        """Find the EX-99.1 (Earnings Press Release) HTML file in a filing directory."""
        try:
            index = self.get_filing_index(cik, accession)
            directory = index.get("directory", {})
            items = directory.get("item", [])
            
            for item in items:
                name = item.get("name", "")
                if name.endswith(".htm") or name.endswith(".html"):
                    lower_name = name.lower()
                    if "ex99" in lower_name or "ex-99" in lower_name or "99_1" in lower_name:
                        return name
            return None
        except SECClientError:
            return None
