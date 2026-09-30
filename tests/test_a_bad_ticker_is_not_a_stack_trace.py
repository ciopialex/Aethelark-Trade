"""A symbol that does not exist is an answer, not a crash.

Measured 2026-09-04 against the live feed:

    $ atrade quote ZZZQXWNOPE --json
    {"error": "KeyError: 'currentTradingPeriod'"}

`fetch_quote` reaches into `yfinance`'s `fast_info`, which for an unknown symbol
raises out of its own internals on a key that means nothing outside that library.
The CLI then wrapped it as `{type(exc).__name__}: {exc}` and handed it on.

Space-Eagle reads that string aloud. "KeyError currentTradingPeriod" is not
something a person can act on, and it is not even true in a useful sense -- the
symbol was wrong, and nothing about a trading period was the problem.

Two separate defects, so two separate guards:

  1. An unknown symbol is recognised as an unknown symbol.
  2. Nothing that escapes the fetch layer reaches a person as an exception,
     whatever it is. Guard 1 fixes the case we know about; guard 2 is what
     catches the next one, since yfinance's internals are not ours to predict.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from aethelark_trade.engine import fetchers

#: Tokens that mean an exception escaped instead of an answer.
LEAKS = ("Error:", "KeyError", "ValueError", "TypeError", "IndexError",
         "AttributeError", "Traceback", "currentTradingPeriod")

NONSENSE = "ZZZQXWNOPE"


def test_the_fetch_layer_names_the_symbol_not_a_library_internal():
    """Guard 1. An unknown symbol raises something that says so."""
    with pytest.raises(fetchers.QuoteUnavailable) as caught:
        fetchers.fetch_quote(NONSENSE)

    message = str(caught.value)
    assert NONSENSE in message, (
        f"the error does not name the symbol that was wrong: {message!r}")
    leaked = [token for token in LEAKS if token in message]
    assert not leaked, f"a library internal leaked into the message: {message!r}"


def test_a_bad_symbol_is_reported_as_a_sentence(monkeypatch):
    """Guard 2. Whatever escapes the feed, a person gets a sentence.

    Driven with an error the fetch layer has never seen, because guard 1 only
    covers the failure we already found. This is the one that holds when
    yfinance changes its internals again.
    """
    def _explode(_ticker):
        raise RuntimeError("some future yfinance internal: 'quoteSummaryStore'")

    monkeypatch.setattr(fetchers, "fetch_quote", _explode)

    with pytest.raises(fetchers.QuoteUnavailable) as caught:
        fetchers.quote_with_series(NONSENSE)

    message = str(caught.value)
    assert "quoteSummaryStore" not in message, (
        f"the library's own words reached the caller: {message!r}")
    assert NONSENSE in message


def test_the_command_line_hands_over_no_exception_text():
    """End to end: the JSON envelope the module bus reads carries a sentence."""
    proc = subprocess.run(
        [sys.executable, "-m", "aethelark_trade.engine.cli", "quote",
         NONSENSE, "--json"],
        capture_output=True, text=True, timeout=90)

    payload = proc.stdout.strip()
    assert payload, f"nothing on stdout; stderr was {proc.stderr[:300]!r}"

    body = json.loads(payload)
    error = str(body.get("error", ""))
    leaked = [token for token in LEAKS if token in error]
    assert not leaked, (
        f"the eagle would read this aloud: {error!r}")
    assert NONSENSE in error, f"the message does not say what was wrong: {error!r}"


def test_a_real_symbol_still_prices():
    """The guard must not swallow working quotes."""
    payload = fetchers.fetch_quote("AAPL")
    assert isinstance(payload.get("price"), (int, float))
    assert payload["price"] > 0
    assert payload["ticker"] == "AAPL"
