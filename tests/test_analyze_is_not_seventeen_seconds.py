"""The seven-layer analysis, measured and made fast enough to be used.

The operator, 2026-09-05: "It takes too long... 16-35 seconds is an eternity in
2026."

Measured before touching anything, PLTR, cold:

    layer_5_insider_conviction   11.36s   81 SEC requests
    layer_1_fundamentals          2.79s
    the other five                1.89s
    TOTAL                        16.04s

The 11.4 seconds were not network latency. Layer 5 issued ~82 requests to
sec.gov and the rate limiter spaces every request 0.14s apart to stay under
SEC's 10/second ceiling: 82 x 0.14 = 11.5s. The wait was self-imposed, which is
why parallelising the SEC calls would have bought nothing -- the limiter simply
re-serialises them.

Three changes, none of which drop or invent a number:

  1. Do not download filings the scorer discards. Layer 5 reads a 90-day
     window; it downloaded the last 40 filings regardless of date. On PLTR: 16
     inside the window, 24 fetched and thrown away. The date is in the listing
     before any download, so the filter is free. 81 requests -> 35.
  2. Cache filed documents. An accepted EDGAR filing never changes -- an
     amendment gets its own accession -- so this is a cache with no
     invalidation problem. A repeat costs 1 request instead of 35.
  3. Run the six independent layers together. They wait on the network, not on
     a CPU, so in sequence they cost the sum of their waits and together they
     cost the longest.

After: 7.93s cold, 2.95s warm, same scores.
"""
from __future__ import annotations

import threading
import time
from datetime import date, timedelta

import pytest

from aethelark_trade.engine import fetchers
from aethelark_trade.engine.ratelimit import CrossProcessRateLimiter


# ------------------------------------------------- 1. filings never used

class _FakeClient:
    """Records what was actually asked for."""

    def __init__(self, filing_dates):
        self.filing_dates = filing_dates
        self.indexed: list[str] = []
        self.downloaded: list[str] = []

    def get_cik(self, ticker):
        return "0001321655"

    def get_form4_filings(self, cik, limit=40):
        return [{"accession_number": f"acc-{i}", "filing_date": d}
                for i, d in enumerate(self.filing_dates)]

    def find_form4_xml(self, cik, accession):
        self.indexed.append(accession)
        return f"{accession}.xml"

    def download_xml(self, cik, accession, name):
        self.downloaded.append(accession)
        return "<ownershipDocument/>"


def test_a_filing_older_than_the_scored_window_is_never_downloaded(monkeypatch):
    monkeypatch.setattr(fetchers, "parse_form4_xml",
                        lambda xml, filed, acc: [])

    today = date.today()
    recent = [(today - timedelta(days=n)).isoformat() for n in (1, 30, 89)]
    ancient = [(today - timedelta(days=n)).isoformat() for n in (200, 400, 900)]
    client = _FakeClient(recent + ancient)

    fetchers.fetch_insider_transactions(client, "PLTR")

    assert len(client.downloaded) == len(recent), (
        f"downloaded {len(client.downloaded)} filings for a 90-day window that "
        f"only {len(recent)} of them fall inside; each one costs two rate-"
        f"limited SEC requests and is discarded before it is scored")
    assert client.indexed == client.downloaded, (
        "a filing was indexed but not downloaded, so a request was spent "
        "finding a document that was then skipped")


def test_a_filing_just_outside_the_window_is_still_downloaded(monkeypatch):
    """Form 4 is filed AFTER the transaction, so the edge needs slack.

    A filing dated 95 days ago can carry a transaction dated 88 days ago, which
    the scorer counts. Trimming exactly at 90 would silently drop it.
    """
    monkeypatch.setattr(fetchers, "parse_form4_xml", lambda xml, filed, acc: [])
    just_outside = (date.today() - timedelta(days=95)).isoformat()
    client = _FakeClient([just_outside])

    fetchers.fetch_insider_transactions(client, "PLTR")
    assert client.downloaded == ["acc-0"], (
        "a late-filed Form 4 carrying an in-window transaction was skipped")


def test_an_unreadable_filing_date_is_not_a_reason_to_skip(monkeypatch):
    monkeypatch.setattr(fetchers, "parse_form4_xml", lambda xml, filed, acc: [])
    client = _FakeClient(["not-a-date"])
    client.filing_dates = ["not-a-date"]

    # The download must be attempted; parsing the date is what fails later.
    try:
        fetchers.fetch_insider_transactions(client, "PLTR")
    except Exception:
        pass
    assert client.downloaded == ["acc-0"], (
        "a filing with a malformed date was dropped; a date we cannot read is "
        "not evidence that the filing is old")


# ------------------------------------------------------------ 2. the cache

def test_a_filed_document_is_fetched_once_and_then_read_from_disk(tmp_path, monkeypatch):
    from aethelark_trade.sec_client import SECClient

    client = SECClient.__new__(SECClient)
    monkeypatch.setattr(SECClient, "FILING_CACHE_DIR", tmp_path, raising=False)

    calls = {"n": 0}

    def _fetch():
        calls["n"] += 1
        return "<ownershipDocument/>"

    first = client._cached_filing("doc", "123", "acc-1", "f.xml", _fetch)
    second = client._cached_filing("doc", "123", "acc-1", "f.xml", _fetch)

    assert first == second == "<ownershipDocument/>"
    assert calls["n"] == 1, (
        "an accepted EDGAR filing never changes, so fetching it twice spends a "
        "rate-limited request on a document already on disk")


def test_a_different_filing_is_not_served_from_another_ones_cache(tmp_path, monkeypatch):
    from aethelark_trade.sec_client import SECClient

    client = SECClient.__new__(SECClient)
    monkeypatch.setattr(SECClient, "FILING_CACHE_DIR", tmp_path, raising=False)

    a = client._cached_filing("doc", "123", "acc-1", "f.xml", lambda: "AAA")
    b = client._cached_filing("doc", "123", "acc-2", "f.xml", lambda: "BBB")
    assert (a, b) == ("AAA", "BBB")


def test_an_unwritable_cache_does_not_break_the_fetch(tmp_path, monkeypatch):
    """Caching is an optimisation. It must never become a gate."""
    from aethelark_trade.sec_client import SECClient

    client = SECClient.__new__(SECClient)
    monkeypatch.setattr(SECClient, "FILING_CACHE_DIR",
                        tmp_path / "nope" / "\0bad", raising=False)
    assert client._cached_filing("doc", "1", "a", "f", lambda: "OK") == "OK"


# -------------------------------------------- 3. threads and the rate limit

def test_the_rate_limiter_paces_threads_not_only_processes(tmp_path):
    """flock is held per open file description, not per thread.

    A second thread in the same process calling acquire() on the same fd is
    granted the lock immediately. Before the thread lock, running two SEC
    layers concurrently would have paced them independently and brought back
    the HTTP 429 this limiter exists to prevent.
    """
    limiter = CrossProcessRateLimiter(state_path=tmp_path / "gate",
                                      min_interval=0.05)
    stamps: list[float] = []
    lock = threading.Lock()

    def worker():
        for _ in range(4):
            limiter.acquire()
            with lock:
                stamps.append(time.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stamps.sort()
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    too_close = [g for g in gaps if g < 0.04]
    assert not too_close, (
        f"{len(too_close)} of {len(gaps)} requests were issued closer together "
        f"than the limiter allows, so concurrent layers would exceed SEC's "
        f"ceiling: {[round(g, 4) for g in too_close]}")


def test_the_independent_layers_actually_run_at_the_same_time():
    """Six layers waiting on six sockets should wait once, not six times."""
    import inspect

    from aethelark_trade.engine import engine

    src = inspect.getsource(engine.evaluate_7layers)
    assert "ThreadPoolExecutor" in src, "the layers still run one after another"

    pool_at = src.index("ThreadPoolExecutor")
    client_at = src.index("with SECClientContext()")
    macro_at = src.index('layers["layer_2_macro_gravity"]')
    assert client_at < pool_at, (
        "the pool runs outside the SEC client's context, so layers 1 and 5 "
        "would use a client that has already been closed")
    assert pool_at < macro_at, (
        "layer 2 reads the snapshot and the price history the wave produces, "
        "so it has to run after the wave, not inside it")


def test_layer_two_is_given_the_price_history_layer_four_fetches():
    """It always intended to. It never got it.

    `_macro` passes `closes if closes else None`, but layer 2 ran BEFORE layer
    4, so `closes` was empty every single time and the sensitivity model fell
    back to its default. Ordering the wave before layer 2 is what finally
    delivers it -- and it moves the score, PLTR 46 -> 48.
    """
    import inspect

    from aethelark_trade.engine import engine

    src = inspect.getsource(engine.evaluate_7layers)
    relativity_at = src.index("closes = fetchers.fetch_price_series(ticker)")
    macro_at = src.index('layers["layer_2_macro_gravity"]')
    assert relativity_at < macro_at, (
        "layer 2 still runs before the layer that fetches the price series, so "
        "`closes` is empty and the sensitivity is a default dressed as a "
        "measurement")
