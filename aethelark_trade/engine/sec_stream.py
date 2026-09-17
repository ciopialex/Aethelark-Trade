"""Slice 3 -- the featherweight SEC master ATOM stream.

The legacy aethelark_trade/sec_streamer.py polls every 5 seconds (0.2 req/s),
spoofs a Chrome User-Agent where the SEC requires a declared identity, requires
a running Redis, and extracts nothing but CIKs. This replaces it: one request
every 30 seconds against the master getcurrent feed -- 0.033 req/s, or 0.33% of
the SEC's 10 req/s ceiling -- with no broker dependency at all.

Per docs/FACTS.md the single master feed captures 100% of newly filed Form 4s
market-wide, so watchlist breadth costs nothing extra.
"""

import html
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from xml.etree import ElementTree

import httpx

logger = logging.getLogger("aethelark.sec_stream")

ATOM_BASE = "https://www.sec.gov/cgi-bin/browse-edgar"

# The SEC requires a real, contactable User-Agent. Impersonating a browser is
# both against their access policy and how streamers get an IP banned.
from aethelark_trade.engine.useragent import sec_user_agent

USER_AGENT = sec_user_agent()

POLL_INTERVAL_SECONDS = 30.0
REQUESTS_PER_SECOND = 1.0 / POLL_INTERVAL_SECONDS  # 0.033 req/s
SEC_RATE_LIMIT = 10.0

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

# "4 - Reservoir Media, Inc. (0001824403) (Issuer)"
TITLE_RE = re.compile(r"^(?P<form>.+?)\s+-\s+(?P<name>.+?)\s+\((?P<cik>\d{10})\)"
                      r"(?:\s+\((?P<role>[^)]+)\))?\s*$")
ACCESSION_RE = re.compile(r"accession-number=([\d-]+)")
FILED_RE = re.compile(r"Filed:</b>\s*(\d{4}-\d{2}-\d{2})")

# When one accession yields several entries, keep the one whose CIK is the
# company: that is the side that resolves to a tradeable ticker.
ROLE_PRIORITY = {"Issuer": 0, "Filer": 1, "Reporting": 2}


@dataclass(frozen=True)
class FilingEvent:
    form_type: str
    company: str
    cik: str
    role: str
    accession: str
    filed: date | None
    updated: str
    link: str


def feed_url(form_type: str = "4", count: int = 100) -> str:
    """Master getcurrent feed for one form type."""
    return (
        f"{ATOM_BASE}?action=getcurrent&type={form_type}&company=&dateb="
        f"&owner=include&count={count}&output=atom"
    )


def _text(entry, tag: str) -> str:
    node = entry.find(f"atom:{tag}", ATOM_NS)
    return (node.text or "").strip() if node is not None else ""


def parse_atom_feed(xml: str) -> list[FilingEvent]:
    """Parse the getcurrent ATOM feed into filing events.

    A malformed or empty payload yields no events rather than raising: the
    poller must survive an SEC maintenance window without dying.
    """
    if not xml or not xml.strip():
        return []
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return []

    events: list[FilingEvent] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        title = _text(entry, "title")
        match = TITLE_RE.match(title)
        if not match:
            continue

        summary = _text(entry, "summary")
        entry_id = _text(entry, "id")

        accession_match = ACCESSION_RE.search(entry_id)
        if not accession_match:
            continue

        filed = None
        filed_match = FILED_RE.search(html.unescape(summary))
        if filed_match:
            try:
                filed = date.fromisoformat(filed_match.group(1))
            except ValueError:
                filed = None

        link_node = entry.find("atom:link", ATOM_NS)
        link = link_node.get("href", "") if link_node is not None else ""

        events.append(
            FilingEvent(
                form_type=match.group("form").strip(),
                company=match.group("name").strip(),
                cik=match.group("cik"),
                role=(match.group("role") or "Filer").strip(),
                accession=accession_match.group(1),
                filed=filed,
                updated=_text(entry, "updated"),
                link=link,
            )
        )
    return events


def dedupe_filings(events: list[FilingEvent]) -> list[FilingEvent]:
    """Collapse each accession to a single event, preferring the issuer side."""
    best: dict[str, FilingEvent] = {}
    for event in events:
        current = best.get(event.accession)
        if current is None or ROLE_PRIORITY.get(event.role, 9) < ROLE_PRIORITY.get(
            current.role, 9
        ):
            best[event.accession] = event
    return list(best.values())


def issuer_ciks(events: list[FilingEvent]) -> list[str]:
    """CIKs of the company side only."""
    return [e.cik for e in events if e.role == "Issuer"]


def poll_once(client: httpx.Client, form_type: str = "4") -> list[FilingEvent]:
    """One feed request. Never raises; an outage returns no events."""
    try:
        response = client.get(
            feed_url(form_type),
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/atom+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=20.0,
        )
        if response.status_code != 200:
            logger.warning("SEC feed returned %s", response.status_code)
            return []
        return dedupe_filings(parse_atom_feed(response.text))
    except Exception as exc:
        logger.warning("SEC feed poll failed: %s", exc)
        return []


def stream(form_types=("4", "8-K"), interval: float = POLL_INTERVAL_SECONDS,
           max_cycles: int | None = None):
    """Yield newly-seen filing events, polling every ``interval`` seconds.

    Synchronous generator, no Redis, no event loop. One request per form type
    per cycle keeps load at len(form_types)/interval req/s.
    """
    seen: set[str] = set()
    cycles = 0
    with httpx.Client(follow_redirects=True) as client:
        while max_cycles is None or cycles < max_cycles:
            for form_type in form_types:
                for event in poll_once(client, form_type):
                    if event.accession in seen:
                        continue
                    seen.add(event.accession)
                    yield event

            # Unbounded growth over a multi-day run would leak; the feed only
            # ever exposes the most recent filings, so old keys cannot recur.
            if len(seen) > 20_000:
                seen.clear()

            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            time.sleep(interval)
