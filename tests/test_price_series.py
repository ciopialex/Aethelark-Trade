"""Six ranges of price history, small enough to travel and honest enough to draw.

The Glance card carries range pills (1D … 5Y) and has to redraw the instant one
is clicked. The island cannot call back into a module — the Qt bridge exposes a
fixed set of slots — so either every range rides in the one payload, or the pill
click costs a round trip. It rides along.

That runs into the module bus ceiling: `MAX_OUTPUT_CHARS = 16000`, and a clipped
JSON document is not a JSON document, so an oversized payload is not truncated —
it is rejected outright.

Six raw ranges is roughly 19 KB, so they are downsampled. The bound comes from
the geometry rather than taste: the sparkline is ~400 px wide, so 1250 daily
closes for 5Y is three points per pixel and none of them are visible. ~100
points per range renders identically and fits six ranges in a few KB.

Downsampling has to keep the shape. Taking every Nth point drops the spike that
made the day interesting, and a chart that smooths away a crash is a chart that
lies, so this uses Largest-Triangle-Three-Buckets, which is the standard choice
for exactly this and preserves extremes.
"""
from __future__ import annotations

import json
import math
import sys
import types

import pytest

from aethelark_trade.engine import fetchers


# ── the downsampler ─────────────────────────────────────────────────────────

def test_a_short_series_is_left_alone():
    series = [1.0, 2.0, 3.0]
    assert fetchers.downsample(series, 100) == series


def test_downsampling_hits_the_budget():
    series = [float(i) for i in range(1250)]
    out = fetchers.downsample(series, 100)
    assert len(out) == 100


def test_the_ends_of_the_line_are_never_moved():
    """The first and last points are the open and the current price. A chart
    that redraws its own endpoints is showing a different day."""
    series = [float(i) * 1.7 for i in range(500)]
    out = fetchers.downsample(series, 60)

    assert out[0] == series[0]
    assert out[-1] == series[-1]


def test_a_spike_survives_the_downsample():
    """Every-Nth sampling would drop this and draw a flat, calm day."""
    series = [100.0] * 1000
    series[437] = 180.0                      # the thing the user needs to see

    out = fetchers.downsample(series, 100)

    assert max(out) == 180.0, "the downsampler smoothed away a 80% spike"


def test_a_crash_survives_too():
    series = [100.0] * 1000
    series[612] = 20.0
    assert min(fetchers.downsample(series, 100)) == 20.0


def test_downsampling_keeps_the_series_in_order():
    series = [float(i) for i in range(1000)]
    out = fetchers.downsample(series, 50)
    assert out == sorted(out), "the line would double back on itself"


@pytest.mark.parametrize("target", [2, 3, 10])
def test_tiny_budgets_still_produce_something_drawable(target):
    out = fetchers.downsample([float(i) for i in range(500)], target)
    assert len(out) == target
    assert out[0] == 0.0 and out[-1] == 499.0


# ── the six ranges ──────────────────────────────────────────────────────────

def _fake_yf(bars_per_call: int = 400):
    """A yfinance stand-in. Real network here would make the suite a weather
    report on whether the market API is up."""
    mod = types.ModuleType("yfinance")

    class _Frame:
        def __init__(self, values):
            self._v = values
            self.empty = not values

        def __contains__(self, key):
            return key == "Close"

        def __getitem__(self, key):
            return self

        def dropna(self):
            return self

        def tolist(self):
            return self._v

    class _Info:
        last_price = 214.72
        previous_close = 217.05
        day_high = 218.74
        day_low = 214.50
        last_volume = 98_545_600
        market_cap = 5_200_733_149_566

    class _Ticker:
        def __init__(self, sym):
            self.sym = sym
            self.fast_info = _Info()

        def history(self, period=None, interval=None, auto_adjust=True):
            return _Frame([100.0 + math.sin(i / 9.0) * 12 for i in range(bars_per_call)])

    mod.Ticker = _Ticker
    return mod


def test_all_six_ranges_come_back(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yf())
    series = fetchers.fetch_series("NVDA")
    assert list(series) == ["1D", "7D", "1M", "3M", "1Y", "5Y"]


def test_every_range_is_within_the_point_budget(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yf(2000))
    for label, points in fetchers.fetch_series("NVDA").items():
        assert 0 < len(points) <= fetchers.SERIES_POINTS, (
            f"{label} carries {len(points)} points")


def test_the_whole_payload_fits_through_the_module_bus(monkeypatch):
    """The constraint that decided the design. 16000 is the bus's ceiling, and
    the quote's own fields share the budget."""
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yf(2000))
    payload = json.dumps({"ticker": "NVDA", "price": 214.72,
                          "series": fetchers.fetch_series("NVDA")})

    assert len(payload) < 16000, f"payload is {len(payload)} chars"


def test_a_range_the_feed_cannot_serve_is_empty_not_an_explosion(monkeypatch):
    mod = types.ModuleType("yfinance")

    class _Ticker:
        def __init__(self, sym):
            pass

        def history(self, **_k):
            raise RuntimeError("delisted")

    mod.Ticker = _Ticker
    monkeypatch.setitem(sys.modules, "yfinance", mod)

    series = fetchers.fetch_series("NOPE")
    assert list(series) == ["1D", "7D", "1M", "3M", "1Y", "5Y"]
    assert all(v == [] for v in series.values())


def test_the_points_are_numbers(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yf())
    for points in fetchers.fetch_series("NVDA").values():
        assert all(isinstance(p, float) for p in points)


def test_one_day_is_asked_for_at_intraday_resolution(monkeypatch):
    """`_close_series` hardcodes interval="1d", which cannot express a single
    trading day — 1D drawn from daily bars is one point."""
    seen = []
    mod = types.ModuleType("yfinance")

    class _Ticker:
        def __init__(self, sym):
            pass

        def history(self, period=None, interval=None, auto_adjust=True):
            seen.append((period, interval))
            raise RuntimeError("stop here")

    mod.Ticker = _Ticker
    monkeypatch.setitem(sys.modules, "yfinance", mod)
    fetchers.fetch_series("NVDA")

    assert ("1d", "1m") in seen, f"1D was requested as {seen[:1]}"


def test_the_six_ranges_are_fetched_concurrently(monkeypatch):
    """Six independent HTTP requests. Run one after another they cost the sum
    of their latencies; run together they cost the slowest one. Measured
    against the live feed that is 1.54s versus roughly 0.3s, on top of a quote
    that already takes 2.7s — the difference between a chart being free and a
    chart being the reason the answer was late.
    """
    import threading
    import time as _time

    live = {"n": 0, "peak": 0}
    lock = threading.Lock()
    mod = types.ModuleType("yfinance")

    class _Frame:
        empty = False
        def __contains__(self, k): return k == "Close"
        def __getitem__(self, k): return self
        def dropna(self): return self
        def tolist(self): return [1.0, 2.0, 3.0]

    class _Ticker:
        def __init__(self, sym): pass
        def history(self, **_k):
            with lock:
                live["n"] += 1
                live["peak"] = max(live["peak"], live["n"])
            _time.sleep(0.10)
            with lock:
                live["n"] -= 1
            return _Frame()

    mod.Ticker = _Ticker
    monkeypatch.setitem(sys.modules, "yfinance", mod)

    started = _time.monotonic()
    fetchers.fetch_series("NVDA")
    elapsed = _time.monotonic() - started

    assert live["peak"] > 1, "the ranges were fetched one after another"
    assert elapsed < 0.40, (
        f"six 100ms calls took {elapsed:.2f}s — serial would be ~0.60s")


# ── the series has to reach the card ────────────────────────────────────────

def test_a_quote_carries_its_own_chart(monkeypatch):
    """The island cannot call back into a module — the Qt bridge exposes a
    fixed set of slots — so a range pill clicked inside the Glance card has to
    find its data already there or wait on a round trip."""
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yf())
    payload = fetchers.quote_with_series("NVDA")

    assert payload["ticker"] == "NVDA"
    assert list(payload["_series"]) == ["1D", "7D", "1M", "3M", "1Y", "5Y"]
    assert payload["price"] is not None


def test_the_chart_costs_nothing_the_quote_was_not_already_spending(monkeypatch):
    """Quote and series are independent lookups. Run one after the other the
    chart is time the user waits for; run together it hides inside a request
    that was happening anyway."""
    import threading
    import time as _time

    live = {"n": 0, "peak": 0}
    lock = threading.Lock()
    mod = types.ModuleType("yfinance")

    class _Frame:
        empty = False
        def __contains__(self, k): return k == "Close"
        def __getitem__(self, k): return self
        def dropna(self): return self
        def tolist(self): return [1.0, 2.0]

    class _Info:
        last_price = 100.0
        previous_close = 99.0
        day_high = 101.0
        day_low = 98.0
        last_volume = 1000
        market_cap = 5_000

    def _track():
        with lock:
            live["n"] += 1
            live["peak"] = max(live["peak"], live["n"])
        _time.sleep(0.10)
        with lock:
            live["n"] -= 1

    class _Ticker:
        def __init__(self, sym): pass
        @property
        def fast_info(self):
            _track()
            return _Info()
        def history(self, **_k):
            _track()
            return _Frame()

    mod.Ticker = _Ticker
    monkeypatch.setitem(sys.modules, "yfinance", mod)

    started = _time.monotonic()
    fetchers.quote_with_series("NVDA")
    elapsed = _time.monotonic() - started

    assert live["peak"] > 1, "quote and series were fetched one after another"
    assert elapsed < 0.40, f"seven 100ms lookups took {elapsed:.2f}s"


def test_the_card_payload_still_fits_the_bus(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yf(2000))
    assert len(json.dumps(fetchers.quote_with_series("NVDA"))) < 16000
