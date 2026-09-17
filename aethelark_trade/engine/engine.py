"""The on-demand 7-layer evaluation engine.

assemble_result() is pure and holds the scorecard contract. evaluate_7layers()
adds the I/O: every fetch is isolated so one dead upstream degrades a single
layer to `unavailable` instead of failing the whole analysis.
"""

from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

from aethelark_trade.engine.liar_filter import LiarFilterResult, check_liar_filter
from aethelark_trade.engine.scoring import (
    LAYER_WEIGHTS,
    asymmetry_ratio,
    composite_score,
)
from aethelark_trade.engine.verdict import verdict_line
from aethelark_trade.engine.types import LayerScore
from aethelark_trade.sec_client import SECClient

LAYER_ORDER = tuple(LAYER_WEIGHTS)


@dataclass
class SevenLayerResult:
    ticker: str
    composite_score: int
    verdict: str
    reason: str
    asymmetry: float
    invalidation_level: str
    layers: dict[str, LayerScore]
    liar_filter: LiarFilterResult
    coverage: float
    generated_at: str
    dossier_path: str | None = None
    errors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Render the docs/UI_STATES.md section 2 dashboard scorecard."""
        return {
            "ticker": self.ticker,
            "composite_score": self.composite_score,
            "verdict": self.verdict,
            "reason": self.reason,
            "asymmetry_ratio": f"{self.asymmetry:.1f} : 1",
            "invalidation_level": self.invalidation_level,
            "layers": {
                name: {
                    "score": layer.score,
                    "summary": layer.summary,
                    "available": layer.available,
                    **({"detail": layer.detail} if layer.detail else {}),
                }
                for name, layer in self.layers.items()
            },
            "liar_filter_status": self.liar_filter.status,
            "liar_filter_detail": self.liar_filter.detail,
            "coverage": round(self.coverage, 3),
            "generated_at": self.generated_at,
            "dossier_path": self.dossier_path,
            **({"errors": self.errors} if self.errors else {}),
        }


def assemble_result(
    ticker: str,
    layers: dict[str, LayerScore],
    liar_filter: LiarFilterResult,
    ema25: float | None = None,
    dossier_path: str | None = None,
    errors: dict[str, str] | None = None,
) -> SevenLayerResult:
    """Fold scored layers into a verdict. Pure: no I/O, no clock beyond stamping."""
    # Narrow on the score itself, not on `available`. Both are equivalent given
    # the LayerScore invariant, but only this form is provable to a checker --
    # but only this form is verifiable by a static checker.
    scored: dict[str, float] = {
        name: float(layer.score)
        for name, layer in layers.items()
        if layer.score is not None
    }

    composite = composite_score(scored)
    ratio = asymmetry_ratio(composite, scored)

    # BEHAVIOR_SPEC §30.2: a verdict is never a score. The composite decides
    # ordering, not the word on the card — two companies with the same
    # composite may carry different verdicts. The reason names the layer that
    # moved it, and §30.7 requires that layer to be visible beside it.
    verdict_word, reason = verdict_line(scored, composite)

    covered = sum(LAYER_WEIGHTS[n] for n in scored if n in LAYER_WEIGHTS)
    coverage = covered / sum(LAYER_WEIGHTS.values())

    if ema25 is not None:
        invalidation = f"${ema25:,.2f} (25-EMA support)"
    else:
        invalidation = "Unavailable (no price history)"

    return SevenLayerResult(
        ticker=ticker.upper(),
        composite_score=composite,
        verdict=verdict_word,
        reason=reason,
        asymmetry=ratio,
        invalidation_level=invalidation,
        layers=layers,
        liar_filter=liar_filter,
        coverage=coverage,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        dossier_path=dossier_path,
        errors=errors or {},
    )


def _safe(errors: dict[str, str], layer: str, fn, unavailable_msg: str) -> LayerScore:
    """Run one layer's fetch+score, converting any failure into an honest gap."""
    try:
        return fn()
    except Exception as exc:
        # The class and the message go to `errors`, where a developer looks.
        errors[layer] = f"{type(exc).__name__}: {exc}"
        # The summary goes to the card and, through model_view, to the harness's
        # brain verbatim -- and that brain is Gemini 2.5 Flash mid-sentence.
        # "XBRL fundamentals unavailable (KeyError)" spends its attention on a
        # Python identifier that means nothing to it and that it may repeat to
        # the user. What is missing is worth saying; what the interpreter called
        # it is not.
        return LayerScore.unavailable(unavailable_msg)


def evaluate_7layers(
    ticker: str,
    as_of: date | None = None,
    # SHIP_1.0 B1. A report is a thing a person asks for, not a side
    # effect of asking what a company is worth. This defaulted to True,
    # so every caller that did not think about it wrote a file to the
    # user's Desktop -- nineteen of them had accumulated by 2026-09-05.
    write_dossier: bool = False,
    cache: bool = True,
) -> SevenLayerResult:
    """Score a ticker across all seven layers, synchronously, on demand."""
    from aethelark_trade.engine import fetchers
    from aethelark_trade.engine.layers.fundamentals import score_fundamentals
    from aethelark_trade.engine.layers.geopolitics import score_macro_regime
    from aethelark_trade.engine.layers.insider import score_insider_conviction
    from aethelark_trade.engine.layers.macro import (
        resolve_company_sensitivity,
        score_macro_gravity,
    )
    from aethelark_trade.engine.layers.news_velocity import score_news_velocity
    from aethelark_trade.engine.layers.sector_relativity import score_sector_relativity
    from aethelark_trade.engine.layers.supply_chain import score_supply_chain
    from aethelark_trade.ticker_registry import get_sector_etf

    ticker = ticker.upper().strip()
    as_of = as_of or date.today()
    errors: dict[str, str] = {}
    layers: dict[str, LayerScore] = {}

    snapshot = None
    sector_etf = get_sector_etf(ticker)
    closes: list[float] = []
    headlines: list = []
    transactions = []

    with SECClientContext() as client:
        def _fundamentals():
            nonlocal snapshot
            snapshot, source = fetchers.load_fundamentals(client, ticker)
            # What kind of filer this is decides whether cash-flow margin is a
            # measure of the business. The submissions document is cached on the
            # client and layer 5 asks for it too, so this costs no extra request.
            try:
                sic = client.get_sic(client.get_cik(ticker))
            except Exception:
                sic = None
            scored = score_fundamentals(
                snapshot, market_cap=fetchers.fetch_market_cap(ticker), sic=sic
            )
            return LayerScore(
                score=scored.score,
                summary=scored.summary,
                available=scored.available,
                detail={**scored.detail, "source": source},
            )

        def _insiders():
            nonlocal transactions
            transactions = fetchers.fetch_insider_transactions(client, ticker)
            return score_insider_conviction(transactions, as_of=as_of)

        def _news():
            nonlocal headlines
            headlines = fetchers.fetch_headlines(ticker)
            return score_news_velocity(headlines, now=datetime.now(timezone.utc))

        def _relativity():
            if not sector_etf:
                return LayerScore.unavailable(f"No sector ETF mapped for {ticker}")
            nonlocal closes
            closes = fetchers.fetch_price_series(ticker)
            return score_sector_relativity(
                closes, fetchers.fetch_price_series(sector_etf),
                sector_etf=sector_etf,
            )

        # Six of the seven layers depend on nothing but the ticker, and every
        # one of them is waiting on a network round trip rather than on a CPU.
        # Run in sequence they cost the SUM of their waits; run together they
        # cost the LONGEST. Measured 2026-09-05 before this change: 9.25s, of
        # which 5.30s was layer 5 alone sitting on the SEC rate limiter while
        # five idle layers queued behind it.
        #
        # Layer 2 is the exception and is NOT in the wave: it reads the
        # fundamentals snapshot layer 1 produces and the price history layer 4
        # produces, so it runs after them.
        #
        # Safe to thread only because `CrossProcessRateLimiter.acquire` now
        # takes a thread lock as well as its file lock. Without that, layers 1
        # and 5 would each pace independently and bring back the HTTP 429 the
        # limiter exists to prevent. The pool stays INSIDE this `with`, because
        # layers 1 and 5 hold `client` and it is closed on the way out.
        wave = {
            "layer_1_fundamentals": (
                _fundamentals, "XBRL fundamentals unavailable"),
            "layer_5_insider_conviction": (
                _insiders, "SEC Form 4 history unavailable"),
            "layer_3_news_velocity": (_news, "News feed unavailable"),
            "layer_4_sector_relativity": (
                _relativity,
                f"Price history vs {sector_etf or 'sector'} unavailable"),
            "layer_6_geopolitics": (
                lambda: score_macro_regime(fetchers.fetch_regime_proxies()),
                "Regime proxies unavailable"),
            "layer_7_supply_chain": (
                lambda: score_supply_chain(fetchers.build_supply_edges(ticker)),
                "Supply graph not yet mapped"),
        }
        with ThreadPoolExecutor(max_workers=len(wave),
                                thread_name_prefix="layer") as pool:
            running = {name: pool.submit(_safe, errors, name, fn, msg)
                       for name, (fn, msg) in wave.items()}
            for name, future in running.items():
                layers[name] = future.result()

    def _macro():
        d_to_e = None
        if snapshot and snapshot.equity and snapshot.equity > 0 and snapshot.long_term_debt:
            d_to_e = snapshot.long_term_debt / snapshot.equity
        sens = resolve_company_sensitivity(
            ticker,
            closes=closes if closes else None,
            sector_etf=sector_etf,
            debt_to_equity=d_to_e,
        )
        return score_macro_gravity(fetchers.fetch_macro_proxies(), sensitivity=sens)

    layers["layer_2_macro_gravity"] = _safe(
        errors, "layer_2_macro_gravity",
        _macro,
        "Macro proxies unavailable",
    )

    news_layer = layers["layer_3_news_velocity"]
    sentiment_pct = (
        float(news_layer.detail.get("sentiment_pct", 50.0))
        if news_layer.available else 50.0
    )
    liar = check_liar_filter(sentiment_pct, transactions, as_of=as_of)

    result = assemble_result(
        ticker=ticker,
        layers={name: layers[name] for name in LAYER_ORDER},
        liar_filter=liar,
        ema25=fetchers.ema(closes, 25) if closes else None,
        errors=errors,
    )

    if write_dossier:
        from aethelark_trade.engine.dossier import write_dossier as _write
        try:
            result.dossier_path = str(_write(result))
        except Exception as exc:
            errors["dossier"] = f"{type(exc).__name__}: {exc}"

    if cache:
        from aethelark_trade.engine.store import save_scorecard
        try:
            save_scorecard(result)
        except Exception as exc:
            errors["cache"] = f"{type(exc).__name__}: {exc}"

    return result


class SECClientContext:
    """SECClient context manager that is safe to enter even if construction fails."""

    def __enter__(self):
        self._client = SECClient()
        return self._client

    def __exit__(self, *exc):
        try:
            self._client.close()
        except Exception:
            pass
        return False
