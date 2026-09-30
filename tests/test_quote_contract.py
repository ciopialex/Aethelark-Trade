"""What `quote` promises, and where that promise is kept.

Three things went wrong at once when the four-stat grid was wired up, and each
one is pinned here.

`to_dict()` is a serialisation method. It is called by `store.py` on every
scorecard write, so anything it does happens once per row persisted — network
I/O belongs nowhere near it. It also grew a second `return` behind the first,
which made the whole block after it unreachable; `analyze --json` never carried
a single quote key despite the code being there to add them.

And a module's JSON is its public API. It is read by the Dynamic Island, by the
shop, and by a model doing arithmetic on it. `"5.2T"` is a rendering of a
number, not a number: it cannot be compared, summed, or charted without being
parsed back. AMS-1 §3 says stdout carries data; the client renders it.
"""
from __future__ import annotations

import ast
import inspect
import sys
import types
from datetime import date

import pytest

from aethelark_trade.engine.engine import assemble_result
from aethelark_trade.engine.liar_filter import check_liar_filter
from aethelark_trade.engine.types import LayerScore

CLEAN = check_liar_filter(50.0, [], as_of=date(2026, 8, 19))


LAYER_NAMES = (
    "layer_1_fundamentals", "layer_2_macro_gravity", "layer_3_news_velocity",
    "layer_4_sector_relativity", "layer_5_insider_conviction",
    "layer_6_geopolitics", "layer_7_supply_chain",
)


def _result():
    layers = {n: LayerScore(score=70, summary="x") for n in LAYER_NAMES}
    return assemble_result("NVDA", layers, CLEAN)


# ── to_dict stays a serialiser ──────────────────────────────────────────────

def test_to_dict_has_no_code_behind_its_return():
    """The defect itself: a second `return` cannot be reached past the first,
    so everything between them is decoration."""
    import aethelark_trade.engine.engine as engine

    src = inspect.getsource(engine)
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "to_dict")

    for i, stmt in enumerate(fn.body):
        if isinstance(stmt, ast.Return):
            unreachable = fn.body[i + 1:]
            assert not unreachable, (
                f"{len(unreachable)} statement(s) sit behind to_dict's first "
                f"return and never execute: "
                f"{[type(s).__name__ for s in unreachable]}")
            break


def test_serialising_a_scorecard_touches_no_network(monkeypatch):
    """store.py calls this on every write. A quote fetch hidden in here is one
    HTTP round trip per persisted row."""
    import aethelark_trade.engine.fetchers as fetchers

    def explode(*_a, **_k):
        raise AssertionError("to_dict reached out to the network")

    monkeypatch.setattr(fetchers, "fetch_quote", explode)
    payload = _result().to_dict()

    assert payload["ticker"] == "NVDA"


# ── the analyze payload actually carries the quote ──────────────────────────

QUOTE_KEYS = ("price", "previous_close", "change", "change_pct",
              "day_high", "day_low", "volume", "market_cap", "company_name")


def test_the_scorecard_can_be_given_market_context(monkeypatch):
    """The behaviour the dead block was reaching for, in a place that runs."""
    from aethelark_trade.engine import fetchers

    monkeypatch.setattr(fetchers, "fetch_quote", lambda t: {
        "ticker": t, "company_name": "NVIDIA Corp.", "price": 214.72,
        "previous_close": 217.05, "change": -2.33, "change_pct": -1.07,
        "day_high": 218.74, "day_low": 214.50,
        "volume": 98_500_000, "market_cap": 5_200_000_000_000,
    })

    enriched = fetchers.with_quote(_result().to_dict(), "NVDA")

    for key in QUOTE_KEYS:
        assert key in enriched, f"{key} never reached the scorecard"
    assert enriched["composite_score"] == _result().to_dict()["composite_score"]


def test_market_context_is_optional_not_fatal(monkeypatch):
    """A quote lookup that fails must not take the scorecard down with it."""
    from aethelark_trade.engine import fetchers

    def explode(_t):
        raise RuntimeError("yfinance is down")

    monkeypatch.setattr(fetchers, "fetch_quote", explode)
    payload = fetchers.with_quote(_result().to_dict(), "NVDA")

    assert payload["ticker"] == "NVDA"
    assert "price" not in payload


# ── the JSON carries data, not rendered text ────────────────────────────────

def _fake_yfinance(**fast):
    mod = types.ModuleType("yfinance")

    class _Info:
        pass

    info = _Info()
    for k, v in fast.items():
        setattr(info, k, v)

    class _Ticker:
        def __init__(self, sym):
            self.sym = sym
            self.fast_info = info

    mod.Ticker = _Ticker
    return mod


def test_a_quote_reports_numbers_the_client_can_do_arithmetic_on(monkeypatch):
    """`"5.2T"` cannot be compared against `"820.4B"`, summed, or charted. The
    module reports the number; formatting is the card's job."""
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance(
        last_price=214.72, previous_close=217.05, day_high=218.74,
        day_low=214.50, last_volume=98_500_000, market_cap=5_200_000_000_000))

    from aethelark_trade.engine.fetchers import fetch_quote
    q = fetch_quote("nvda")

    for key in ("day_high", "day_low", "volume", "market_cap"):
        assert isinstance(q[key], (int, float)), (
            f"{key} is {q[key]!r} — a rendered string, not a value")
    assert q["market_cap"] == 5_200_000_000_000
    assert q["ticker"] == "NVDA"


def test_a_stat_the_feed_withheld_comes_back_as_null_not_a_dash(monkeypatch):
    """`—` is a glyph the card chooses. In JSON the honest answer is null, so a
    consumer can tell 'absent' from 'a string that happens to be a dash'."""
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance(
        last_price=214.72, previous_close=217.05))

    from aethelark_trade.engine.fetchers import fetch_quote
    q = fetch_quote("NVDA")

    assert q["market_cap"] is None
    assert q["volume"] is None


def test_prices_are_rounded_and_counts_are_whole(monkeypatch):
    """Still data, just not noise. A feed that reports 218.74000549316406 is
    reporting 218.74 to a fifteenth decimal place nobody trades on, and a share
    count is a count."""
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance(
        last_price=214.72, previous_close=217.05,
        day_high=218.74000549316406, day_low=214.5,
        last_volume=98_545_600.0, market_cap=5_200_733_149_566.65))

    from aethelark_trade.engine.fetchers import fetch_quote
    q = fetch_quote("NVDA")

    assert q["day_high"] == 218.74
    assert q["day_low"] == 214.5
    assert q["volume"] == 98_545_600 and isinstance(q["volume"], int)
    assert q["market_cap"] == 5_200_733_149_566 and isinstance(q["market_cap"], int)
