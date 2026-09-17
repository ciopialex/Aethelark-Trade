"""Slice 3 -- filing events to Dynamic Island payloads.

The master feed carries every Form 4 filed market-wide, roughly 40-100 per
poll. Fetching the XML for all of them would cost several requests per second
and defeat the point of a featherweight listener, so filings are filtered down
to the tracked universe *before* any document is fetched: one cheap CIK lookup
against an in-memory map, then a request only for names we actually score.
"""

import logging
from datetime import date

from aethelark_trade.engine.events import (
    eight_k_material_event,
    form4_whale_buy,
    should_emit_whale_buy,
)
from aethelark_trade.engine.sec_stream import FilingEvent
from aethelark_trade.parser import parse_form4_xml

logger = logging.getLogger("aethelark.watch")

# docs/UI_STATES.md State B fires on material agreements and acquisitions only.
MATERIAL_8K_ITEMS = ("1.01", "2.01")


def _default_loader(client):
    def load(cik: str, accession: str, form_type: str) -> str:
        if form_type.startswith("8-K"):
            index = client.get_filing_index(cik, accession)
            for item in index.get("directory", {}).get("item", []):
                name = item.get("name", "")
                if name.endswith((".htm", ".html")) and "index" not in name:
                    return client.download_filing_text(cik, accession, name)
            return ""
        xml_name = client.find_form4_xml(cik, accession)
        return client.download_xml(cik, accession, xml_name) if xml_name else ""

    return load


class EventWatcher:
    """Stateful filter turning filings into HUD payloads."""

    def __init__(self, cik_map=None, loader=None, client=None, as_of=None,
                 restrict_to_universe: bool = True, universe=None):
        self._client = client
        self._loader = loader
        self._cik_map = cik_map
        self._as_of = as_of or date.today()
        self.restrict_to_universe = restrict_to_universe
        self._universe = universe
        self._acted: set[str] = set()

    # -- lazily-built collaborators, so construction never touches the network
    @property
    def cik_map(self) -> dict[str, str]:
        if self._cik_map is None:
            self._cik_map = {
                cik: ticker
                for ticker, cik in self._sec_client()._load_ticker_cache().items()
            }
        return self._cik_map

    @property
    def universe(self) -> set[str]:
        if self._universe is None:
            from aethelark_trade.ticker_registry import get_all_tracked_tickers

            self._universe = set(get_all_tracked_tickers())
        return self._universe

    def _sec_client(self):
        if self._client is None:
            from aethelark_trade.sec_client import SECClient

            self._client = SECClient()
        return self._client

    @property
    def loader(self):
        if self._loader is None:
            self._loader = _default_loader(self._sec_client())
        return self._loader

    # -- main entry point
    def handle(self, filing: FilingEvent) -> list[dict]:
        """Payloads this filing should raise. Empty is the normal case."""
        # The Reporting-person row mirrors the Issuer row under the same
        # accession; only the issuer side carries a tradeable ticker.
        if filing.role != "Issuer":
            return []

        ticker = self.cik_map.get(filing.cik)
        if not ticker:
            return []

        if self.restrict_to_universe and ticker not in self.universe:
            return []

        if filing.accession in self._acted:
            return []
        self._acted.add(filing.accession)

        try:
            document = self.loader(filing.cik, filing.accession, filing.form_type)
        except Exception as exc:
            logger.debug("could not load %s: %s", filing.accession, exc)
            return []

        if not document:
            return []

        if filing.form_type.startswith("8-K"):
            return self._handle_8k(ticker, document)
        if filing.form_type == "4":
            return self._handle_form4(ticker, filing, document)
        return []

    def _handle_form4(self, ticker, filing, xml) -> list[dict]:
        try:
            transactions = parse_form4_xml(
                xml, filing.filed or self._as_of, filing.accession
            )
        except Exception as exc:
            logger.debug("unparseable Form 4 %s: %s", filing.accession, exc)
            return []

        if not should_emit_whale_buy(transactions, as_of=self._as_of):
            return []

        # Bind the value once so both the sum and the max operate on a list the
        # checker knows is free of None -- the filter above guarantees it, but
        # only this form lets a tool verify that.
        buys = [(t, t.total_value) for t in transactions
                if t.transaction_code == "P" and t.total_value is not None]
        total = sum(value for _, value in buys)
        lead = max(buys, key=lambda pair: pair[1])[0]
        who = f"{lead.insider_title or 'Insider'} {lead.insider_name}".strip()

        return [form4_whale_buy(ticker, who, total, score=self._score_hint(ticker))]

    def _handle_8k(self, ticker, document) -> list[dict]:
        from aethelark_trade.parsers import scan_8k_items

        try:
            items = scan_8k_items(document)
        except Exception as exc:
            logger.debug("8-K scan failed for %s: %s", ticker, exc)
            return []

        payloads = []
        for item in items:
            code = str(item.get("code", ""))
            if code not in MATERIAL_8K_ITEMS:
                continue
            payloads.append(
                eight_k_material_event(
                    ticker, code,
                    item.get("description") or "Material event disclosed",
                )
            )
        return payloads

    def _score_hint(self, ticker: str) -> int:
        """Last cached composite for the card, if we have ever scored it."""
        try:
            from aethelark_trade.engine.store import load_scorecard

            cached = load_scorecard(ticker)
            return int(cached["composite_score"]) if cached else 0
        except Exception:
            return 0
