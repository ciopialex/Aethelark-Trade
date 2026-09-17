"""Five-percent ownership for `atrade owners`, fetched when the cache is cold.

`who_owns()` reads Schedule 13D/13G filings out of the local store. In the
repository this module was split from, that store was filled by a separate
long-running collector, so the read-only path was all the CLI needed.

Standalone there is no collector, and the failure is silent and confident: an
empty table is indistinguishable from a company nobody has filed against, and
`who_owns` says so in as many words -- "nobody crossed the threshold that
requires a filing... do not retry". Measured 2026-09-17 on a clean install,
that is what `atrade owners PLTR` returned, for a company with multiple 13G
filers. The host reads that answer out loud.

So a cold cache fetches. The distinction this module exists to preserve is
between *no filings exist* and *we have not looked*, and only one of those is
a fact about the company.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

logger = logging.getLogger("aethelark.ownership")

#: How many 13D/G filings to pull on a cold fetch. Holders file an amended 13G
#: whenever a stake moves, so recent history repeats the same names; `who_owns`
#: keeps each filer's most recent filing and discards the rest.
FETCH_LIMIT = 20

#: A cached answer older than this is refetched. Schedule 13 filings are event
#: driven and rarely move week to week.
CACHE_TTL_DAYS = 7


def _parse_filing(client, cik: str, meta: dict):
    """One filing to a Schedule13Filing, XML first, HTML second, else None."""
    from aethelark_trade.schedule13 import (
        parse_schedule13_html, parse_schedule13_xml,
    )

    try:
        filed = date.fromisoformat(meta["filing_date"])
    except (KeyError, TypeError, ValueError):
        return None

    accession, form_type = meta.get("accession_number"), meta.get("form_type", "")
    if not accession:
        return None

    try:
        xml_name = client.find_schedule13_xml(cik, accession)
        if xml_name:
            body = client.download_xml(cik, accession, xml_name)
            parsed = parse_schedule13_xml(body, filed, accession, form_type)
            if parsed:
                return parsed

        primary = meta.get("primary_document")
        if primary:
            body = client.download_xml(cik, accession, primary)
            return parse_schedule13_html(body, filed, accession, form_type)
    except Exception as exc:
        # One unparseable filing must not sink the answer. It is counted as
        # `unreadable` by who_owns rather than silently dropped.
        logger.debug("Schedule 13 %s unparseable: %s", accession, exc)
    return None


def _is_stale(filings) -> bool:
    if not filings:
        return True
    newest = max((getattr(f, "filing_date", None) for f in filings
                  if getattr(f, "filing_date", None)), default=None)
    if newest is None:
        return True
    fetched = getattr(filings[0], "fetched_at", None)
    if fetched is None:
        return False            # present and readable: trust the store
    try:
        age = datetime.now() - datetime.fromisoformat(str(fetched))
    except (TypeError, ValueError):
        return False
    return age > timedelta(days=CACHE_TTL_DAYS)


def fetch_schedule13(ticker: str, limit: int = FETCH_LIMIT) -> int:
    """Pull this company's 13D/G filings into the local store. Returns the
    number of filings stored."""
    from aethelark_trade.engine.engine import SECClientContext
    from aethelark_trade.storage import save_schedule13_filings

    ticker = (ticker or "").strip().upper()
    parsed_filings = []

    with SECClientContext() as client:
        cik = client.get_cik(ticker)
        for meta in client.get_schedule13_filings(cik, limit=limit):
            parsed = _parse_filing(client, cik, meta)
            if parsed is not None:
                # The XML does not always carry the issuer's ticker, and the
                # store is keyed on it.
                parsed.issuer_ticker = ticker
                parsed_filings.append(parsed)

    if parsed_filings:
        save_schedule13_filings(parsed_filings)
    return len(parsed_filings)


def owners_of(ticker: str, refresh: bool = False, limit: int = 60) -> dict:
    """`who_owns` over the local store, fetching first if it has nothing."""
    from aethelark_trade.owners import who_owns
    from aethelark_trade.storage import load_schedule13_filings

    ticker = (ticker or "").strip().upper()
    filings = load_schedule13_filings(ticker, limit=limit)

    if refresh or _is_stale(filings):
        try:
            fetch_schedule13(ticker)
            filings = load_schedule13_filings(ticker, limit=limit)
        except Exception as exc:
            # A fetch that fails leaves whatever was cached. If that is
            # nothing, the caller is told the difference.
            logger.debug("Schedule 13 fetch failed for %s: %s", ticker, exc)
            if not filings:
                answer = who_owns(ticker, [])
                answer["summary"] = (
                    f"Could not reach SEC for {ticker}'s Schedule 13D/G "
                    f"filings, so this is unknown rather than empty. "
                    f"Say the lookup failed; do not say nobody holds five "
                    f"percent.")
                answer["lookup_failed"] = True
                return answer

    return who_owns(ticker, filings)
