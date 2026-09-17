"""Layer 4 sector relativity tests: sample length invariance and unmapped ETF handling."""
import math
from aethelark_trade.engine.layers.sector_relativity import score_sector_relativity


def test_tiled_excess_return_score_is_invariant_to_sample_length():
    """Tiling one fixed excess-return pattern to lengths 25, 50, 100, 250, 500
    must yield consistent scores, not scale with sqrt(n)."""
    # A repeating 5-day cycle with a realistic daily excess return and dispersion
    pattern_excess = [-0.010, +0.012, -0.007, +0.011, -0.001]

    scores = []
    for n in (25, 50, 100, 250, 500):
        stock_closes = [100.0]
        sector_closes = [100.0]
        for i in range(n):
            ex = pattern_excess[i % len(pattern_excess)]
            sector_closes.append(sector_closes[-1] * 1.0005)
            stock_closes.append(stock_closes[-1] * (1.0005 + ex))

        result = score_sector_relativity(stock_closes, sector_closes, sector_etf="XLK")
        assert result.available is True
        scores.append(result.score)

    # Holding the excess-return distribution fixed, scores must agree within a small tolerance (<= 2 points),
    # not swing across a 38-point spread.
    assert max(scores) - min(scores) <= 2, f"Scores spread across sample lengths: {scores}"


def test_unmapped_sector_etf_is_unavailable():
    """An unmapped ticker must report unavailable rather than silently benchmarking vs SPY."""
    result = score_sector_relativity([100.0] * 30, [100.0] * 30, sector_etf="")
    assert result.available is False
    assert "no sector etf" in result.summary.lower()

    result_none = score_sector_relativity([100.0] * 30, [100.0] * 30, sector_etf=None)
    assert result_none.available is False
    assert "no sector etf" in result_none.summary.lower()
