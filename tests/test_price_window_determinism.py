"""The same ticker scored twice must give the same answer.

Observed in the eagle's boot log: TSLA analyzed twice, two seconds apart:

    epoch=10  layer_4 = 43   (-0.30 sigma, 123 sessions)
    epoch=11  layer_4 = 37   (-0.55 sigma, 125 sessions)

composite 53 -> 52 on identical inputs. The cause is an unpinned window:
`period="6mo"` returns however many sessions the provider feels like, so the
sample changes underneath the score. Pinning the tail to a fixed session count
makes the layer a pure function of the price history again.
"""
import pytest

from aethelark_trade.engine.fetchers import SESSION_WINDOW, pin_window
from aethelark_trade.engine.layers.sector_relativity import score_sector_relativity


def test_window_is_a_documented_session_count():
    assert isinstance(SESSION_WINDOW, int)
    assert SESSION_WINDOW >= 20


def test_pin_takes_the_most_recent_sessions():
    series = list(range(400))
    pinned = pin_window(series)
    assert len(pinned) == SESSION_WINDOW
    assert pinned[-1] == 399
    assert pinned[0] == 400 - SESSION_WINDOW


def test_pin_is_idempotent():
    series = list(range(400))
    assert pin_window(pin_window(series)) == pin_window(series)


def test_a_longer_upstream_response_yields_the_same_window():
    """The exact failure: provider returns 123 one call and 125 the next."""
    base = [100 + i * 0.5 for i in range(400)]
    short = base[-123:]
    long_ = base[-125:]
    assert pin_window(short) == pin_window(long_)


def test_short_history_is_passed_through_rather_than_padded():
    """A recent listing genuinely has less history; inventing bars would be
    worse than scoring on what exists."""
    series = [100.0] * 30
    assert pin_window(series) == series


def test_scores_match_across_differing_upstream_lengths():
    """End to end: the two responses that produced 43 and 37 must now agree."""
    stock = [100 * (1.0012 ** i) for i in range(400)]
    sector = [100 * (1.0009 ** i) for i in range(400)]

    a = score_sector_relativity(pin_window(stock[-123:]),
                                pin_window(sector[-123:]), sector_etf="XLY")
    b = score_sector_relativity(pin_window(stock[-125:]),
                                pin_window(sector[-125:]), sector_etf="XLY")
    assert a.score == b.score
    assert a.detail["sessions"] == b.detail["sessions"] == SESSION_WINDOW - 1


def test_reported_session_count_is_stable():
    stock = [100 * (1.001 ** i) for i in range(300)]
    sector = [100 * (1.0005 ** i) for i in range(300)]
    result = score_sector_relativity(pin_window(stock), pin_window(sector),
                                     sector_etf="XLK")
    assert result.detail["sessions"] == SESSION_WINDOW - 1
