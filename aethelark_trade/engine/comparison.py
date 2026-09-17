"""Slice 2 -- head-to-head 7-layer comparison."""

from dataclasses import dataclass

from aethelark_trade.engine.scoring import LAYER_WEIGHTS


@dataclass(frozen=True)
class LayerDiff:
    layer: str
    score_a: int | None
    score_b: int | None
    delta: int | None
    winner: str | None
    summary_a: str
    summary_b: str


@dataclass(frozen=True)
class ComparisonResult:
    ticker_a: str
    ticker_b: str
    composite_a: int
    composite_b: int
    winner: str | None
    margin: int
    layer_diffs: list[LayerDiff]
    layers_won_a: int
    layers_won_b: int

    def to_dict(self) -> dict:
        return {
            "ticker_a": self.ticker_a,
            "ticker_b": self.ticker_b,
            "composite_a": self.composite_a,
            "composite_b": self.composite_b,
            "winner": self.winner,
            "margin": self.margin,
            "layers_won_a": self.layers_won_a,
            "layers_won_b": self.layers_won_b,
            "layers": [
                {
                    "layer": d.layer,
                    "weight": LAYER_WEIGHTS.get(d.layer),
                    "score_a": d.score_a,
                    "score_b": d.score_b,
                    "delta": d.delta,
                    "winner": d.winner,
                    "summary_a": d.summary_a,
                    "summary_b": d.summary_b,
                }
                for d in self.layer_diffs
            ],
        }


def compare_results(a, b) -> ComparisonResult:
    """Diff two scored tickers layer by layer.

    A layer only produces a winner when BOTH sides have data. Scoring a gap as
    a loss would reward whichever name happened to have better data coverage
    rather than better fundamentals.
    """
    diffs: list[LayerDiff] = []
    won_a = won_b = 0

    for layer in LAYER_WEIGHTS:
        la, lb = a.layers.get(layer), b.layers.get(layer)
        avail_a = la is not None and la.available
        avail_b = lb is not None and lb.available

        score_a = la.score if avail_a else None
        score_b = lb.score if avail_b else None

        if score_a is not None and score_b is not None:
            delta = score_a - score_b
            if delta > 0:
                winner, _ = a.ticker, won_a
                won_a += 1
            elif delta < 0:
                winner = b.ticker
                won_b += 1
            else:
                winner = None
        else:
            delta = None
            winner = None

        diffs.append(
            LayerDiff(
                layer=layer,
                score_a=score_a,
                score_b=score_b,
                delta=delta,
                winner=winner,
                summary_a=la.summary if la else "",
                summary_b=lb.summary if lb else "",
            )
        )

    if a.composite_score > b.composite_score:
        overall = a.ticker
    elif b.composite_score > a.composite_score:
        overall = b.ticker
    else:
        overall = None

    return ComparisonResult(
        ticker_a=a.ticker,
        ticker_b=b.ticker,
        composite_a=a.composite_score,
        composite_b=b.composite_score,
        winner=overall,
        margin=abs(a.composite_score - b.composite_score),
        layer_diffs=diffs,
        layers_won_a=won_a,
        layers_won_b=won_b,
    )
