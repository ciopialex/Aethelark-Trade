"""`atrade` — the on-demand Aethelark-Trade intelligence CLI."""

import json as jsonlib
import logging
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from aethelark_trade.engine.dossier import LAYER_TITLES
from aethelark_trade.engine.scoring import LAYER_WEIGHTS

app = typer.Typer(
    help="Aethelark-Trade — on-demand 7-layer equity intelligence.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

# yfinance prints its own 404s straight to stderr for delisted proxies (SILI.L
# among them). Those are expected -- the layer degrades around a dead symbol --
# so they must not drown the scorecard.
for _noisy in ("yfinance", "peewee", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)

VERDICT_STYLE = {
    "BULLISH": "bold green",
    "ACCUMULATE": "green",
    "NEUTRAL": "yellow",
    "CAUTION": "dark_orange",
    "BEARISH": "bold red",
}


def _score_style(score: int, available: bool) -> str:
    if not available:
        return "dim"
    if score >= 75:
        return "green"
    if score >= 55:
        return "cyan"
    if score >= 45:
        return "yellow"
    return "red"


def render_scorecard(result) -> None:
    """Print the rich terminal scorecard."""
    verdict_style = VERDICT_STYLE.get(result.verdict, "white")

    header = (
        f"[bold white]{result.ticker}[/bold white]   "
        f"[{verdict_style}]{result.composite_score}/100 · {result.verdict}[/{verdict_style}]\n"
        f"[dim]Asymmetry {result.asymmetry:.1f} : 1   ·   "
        f"Invalidation {result.invalidation_level}   ·   "
        f"Coverage {result.coverage:.0%}[/dim]"
    )
    console.print(Panel(header, border_style=verdict_style, expand=False))

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Layer", style="white", no_wrap=True)
    table.add_column("Wt", justify="right", style="dim")
    table.add_column("Score", justify="right")
    table.add_column("Reading", style="dim")

    for name, layer in result.layers.items():
        style = _score_style(layer.score, layer.available)
        table.add_row(
            LAYER_TITLES.get(name, name),
            f"{LAYER_WEIGHTS.get(name, 0):.0%}",
            f"[{style}]{layer.score if layer.available else '—'}[/{style}]",
            layer.summary,
        )
    console.print(table)

    lf = result.liar_filter
    if lf.status == "DIVERGENCE":
        console.print(
            Panel(
                f"[bold]⚠  LIAR FILTER: {result.ticker} DIVERGENCE[/bold]\n{lf.detail}",
                border_style="dark_orange",
                expand=False,
            )
        )
    else:
        console.print(f"[green]✓[/green] Liar Filter: [green]CLEAN[/green] — {lf.detail}")

    if result.dossier_path:
        console.print(f"[dim]Dossier → {result.dossier_path}[/dim]")
    if result.errors:
        console.print(f"[dim]{len(result.errors)} upstream layer(s) degraded; "
                      f"run with --json to inspect `errors`.[/dim]")


@app.callback()
def main() -> None:
    """Aethelark-Trade — on-demand 7-layer equity intelligence.

    Present so Typer keeps subcommand dispatch even when only one command is
    registered; without it `atrade analyze NVDA` collapses to `atrade NVDA`.
    """


@app.command()
def analyze(
    ticker: str = typer.Argument(..., help="Ticker symbol, e.g. NVDA"),
    json: bool = typer.Option(False, "--json", help="Emit the machine-readable scorecard."),
    report: bool = typer.Option(False, "--report", help="Also write a Markdown report and say where it went."),
):
    """Score a ticker across all 7 layers and run the Liar Filter."""
    from aethelark_trade.engine.engine import evaluate_7layers

    result = evaluate_7layers(ticker, write_dossier=report)

    if json:
        from aethelark_trade.engine.fetchers import with_quote
        typer.echo(jsonlib.dumps(
            with_quote(result.to_dict(), result.ticker), indent=2, default=str))
    else:
        render_scorecard(result)


def _humanise_age(seconds: float | None) -> str:
    """Freshness the model can say out loud, not a raw timestamp."""
    if seconds is None:
        return "unknown"
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m ago"
    if seconds < 86400:
        return f"{seconds / 3600:.0f}h ago"
    return f"{seconds / 86400:.0f}d ago"


def render_comparison(cmp) -> None:
    """Print the head-to-head verdict table."""
    if cmp.winner:
        headline = (
            f"[bold green]{cmp.winner}[/bold green] wins by "
            f"[bold]{cmp.margin}[/bold] points"
        )
    else:
        headline = "[yellow]Dead heat[/yellow]"

    console.print(
        Panel(
            f"[bold white]{cmp.ticker_a}[/bold white] {cmp.composite_a}/100   vs   "
            f"[bold white]{cmp.ticker_b}[/bold white] {cmp.composite_b}/100\n"
            f"{headline}   [dim]· layers won {cmp.layers_won_a}–{cmp.layers_won_b}[/dim]",
            border_style="cyan",
            expand=False,
        )
    )

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Layer", no_wrap=True)
    table.add_column("Wt", justify="right", style="dim")
    table.add_column(cmp.ticker_a, justify="right")
    table.add_column(cmp.ticker_b, justify="right")
    table.add_column("Δ", justify="right")
    table.add_column("Edge", no_wrap=True)

    for d in cmp.layer_diffs:
        if d.delta is None:
            delta_cell, edge = "[dim]n/a[/dim]", "[dim]—[/dim]"
        elif d.delta > 0:
            delta_cell, edge = f"[green]+{d.delta}[/green]", f"[green]{cmp.ticker_a}[/green]"
        elif d.delta < 0:
            delta_cell, edge = f"[red]{d.delta}[/red]", f"[red]{cmp.ticker_b}[/red]"
        else:
            delta_cell, edge = "0", "[dim]tie[/dim]"

        table.add_row(
            LAYER_TITLES.get(d.layer, d.layer),
            f"{LAYER_WEIGHTS.get(d.layer, 0):.0%}",
            "—" if d.score_a is None else str(d.score_a),
            "—" if d.score_b is None else str(d.score_b),
            delta_cell,
            edge,
        )
    console.print(table)


@app.command()
def compare(
    ticker_a: str = typer.Argument(..., help="First ticker"),
    ticker_b: str = typer.Argument(..., help="Second ticker"),
    json: bool = typer.Option(False, "--json", help="Emit the machine-readable diff."),
):
    """Head-to-head 7-layer relative asymmetry between two tickers."""
    from aethelark_trade.engine.comparison import compare_results
    from aethelark_trade.engine.engine import evaluate_7layers

    a = evaluate_7layers(ticker_a, write_dossier=False)
    b = evaluate_7layers(ticker_b, write_dossier=False)
    result = compare_results(a, b)

    if json:
        from aethelark_trade.engine.fetchers import with_quote
        typer.echo(jsonlib.dumps(
            with_quote(result.to_dict(), result.ticker_a), indent=2, default=str))
    else:
        render_comparison(result)


@app.command()
def leaderboard(
    limit: int = typer.Option(10, "--limit", help="How many names to show."),
    universe: str = typer.Option("sp500", "--universe",
                                 help="sp500, nasdaq100, all, or cached."),
    sector: Optional[str] = typer.Option(None, "--sector", "-s",
                                 help="Filter by sector: tech, healthcare, pharma, financials, energy, industrials, staples, discretionary."),
    refresh: int = typer.Option(0, "--refresh",
                                help="Score this many un-cached names before ranking."),
    json: bool = typer.Option(False, "--json", help="Emit machine-readable rankings."),
):
    """Rank the universe by relative asymmetry: quality + cheapness + insider buying."""
    from aethelark_trade.engine.engine import evaluate_7layers
    from aethelark_trade.engine.leaderboard import rank_leaderboard
    from aethelark_trade.engine.store import (
        cached_tickers,
        load_entries,
        stale_model_count,
    )
    from aethelark_trade.ticker_registry import (
        NASDAQ100_TICKERS,
        SP500_TOP100,
        TICKER_TO_SECTOR_ETF,
        get_all_tracked_tickers,
    )

    SECTOR_MAP = {
        "tech": "XLK",
        "technology": "XLK",
        "healthcare": "XLV",
        "health": "XLV",
        "pharma": "XLV",
        "pharmaceuticals": "XLV",
        "biotech": "XLV",
        "financials": "XLF",
        "finance": "XLF",
        "banks": "XLF",
        "energy": "XLE",
        "oil": "XLE",
        "industrials": "XLI",
        "consumer": "XLY",
        "discretionary": "XLY",
        "staples": "XLP",
        "utilities": "XLU",
        "realestate": "XLRE",
    }

    universes = {
        "sp500": SP500_TOP100,
        "nasdaq100": NASDAQ100_TICKERS,
        "all": get_all_tracked_tickers(),
    }

    target_etf = SECTOR_MAP.get(sector.lower().strip()) if sector else None

    if refresh > 0:
        if universe == "cached":
            raise typer.BadParameter("--refresh needs a real universe, not 'cached'")
        pool = universes.get(universe)
        if pool is None:
            raise typer.BadParameter(f"unknown universe '{universe}'")
        if target_etf:
            pool = [t for t in pool if TICKER_TO_SECTOR_ETF.get(t) == target_etf]
        already = set(cached_tickers())
        todo = [t for t in pool if t not in already][:refresh]
        for i, t in enumerate(todo, start=1):
            console.print(f"[dim]scoring {t} ({i}/{len(todo)})…[/dim]")
            try:
                evaluate_7layers(t, write_dossier=False)
            except Exception as exc:
                console.print(f"[red]  {t} failed: {type(exc).__name__}[/red]")

    entries = load_entries()
    if universe != "cached":
        pool_set = set(universes.get(universe, []))
        if pool_set:
            entries = [e for e in entries if e.ticker in pool_set]

    if target_etf:
        entries = [e for e in entries if TICKER_TO_SECTOR_ETF.get(e.ticker) == target_etf]

    ranked = rank_leaderboard(entries, limit=limit)
    superseded = stale_model_count()

    if json:
        # SHIP_1.0 A7. This ranks what has already been analysed on this
        # machine; it surveys nothing. Reporting {"universe": "sp500",
        # "count": 8} said the opposite — a person hears "I looked at the
        # S&P 500 and these came out on top" — and an empty result came back
        # as a plain success, which reads as "nothing looks good."
        #
        # The top company's quote also used to be spread across the top level
        # so the island could draw a card. That is the falsification named in
        # spec 15.4: a question about a list must not put a card on screen for
        # a subject the question was not about. No card.
        ages = [r.age_seconds for r in ranked if r.age_seconds is not None]
        stalest_days = round(max(ages) / 86400.0, 1) if ages else None

        scope = f"the {universe} universe" if universe != "cached" else "the cache"
        if sector:
            scope += f", {sector} only"

        if ranked:
            noun = "company" if len(ranked) == 1 else "companies"
            summary = (f"Ranked {len(ranked)} {noun} already analysed on this "
                       f"machine. This is not a survey of {scope}.")
            if stalest_days is not None:
                summary += f" The oldest reading is {stalest_days} days old."
        else:
            summary = ("Nothing here has been analysed yet, so there is nothing "
                       "to rank. Name a company and I will analyse it.")
        if superseded:
            summary += (f" {superseded} further score(s) were computed by a "
                        f"superseded scoring model and were withheld rather "
                        f"than ranked.")

        typer.echo(jsonlib.dumps(
            {"universe_requested": universe,
             "sector_filter": sector,
             "surveyed_the_universe": False,
             "ranked": len(ranked),
             "scorecards_available": len(entries),
             "superseded_scorecards": superseded,
             "stalest_days": stalest_days,
             "summary": summary,
             "rankings": [r.__dict__ for r in ranked]},
            indent=2, default=str,
        ))
        return

    if not ranked:
        if superseded:
            console.print(
                f"[yellow]No rankable scorecards.[/yellow] "
                f"{superseded} cached score(s) were computed by a superseded "
                f"scoring model and are being withheld rather than ranked.\n"
                f"[dim]Rescore them with: atrade leaderboard --refresh {superseded}[/dim]"
            )
        else:
            console.print(
                "[yellow]No cached scorecards for this universe.[/yellow]\n"
                "[dim]Populate it with: atrade leaderboard --refresh 20[/dim]"
            )
        return

    table = Table(title=f"Relative Asymmetry — {universe}", header_style="bold",
                  box=None, pad_edge=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Ticker", style="bold")
    table.add_column("Asym", justify="right")
    table.add_column("Comp", justify="right")
    table.add_column("Quality", justify="right")
    table.add_column("Insider", justify="right")
    table.add_column("FCF Yld", justify="right")
    table.add_column("Age", style="dim")

    for r in ranked:
        table.add_row(
            str(r.rank), r.ticker, f"{r.asymmetry:.1f}", str(r.composite),
            "—" if r.quality is None else str(r.quality),
            "—" if r.insider is None else str(r.insider),
            "—" if r.fcf_yield_pct is None else f"{r.fcf_yield_pct:.2f}%",
            _humanise_age(r.age_seconds),
        )
    console.print(table)
    if superseded:
        console.print(
            f"[dim]{superseded} scorecard(s) withheld — computed by a superseded "
            f"scoring model. Rescore with --refresh.[/dim]"
        )


@app.command("sync-bulk")
def sync_bulk(
    keep_zip: bool = typer.Option(False, "--keep-zip", help="Keep the downloaded archive."),
    zip_path: str = typer.Option("", "--from-zip",
                                 help="Ingest an already-downloaded archive."),
):
    """Hydrate local XBRL fundamentals from the SEC companyfacts archive."""
    import tempfile
    from pathlib import Path

    from aethelark_trade.engine.bulk import (
        COMPANYFACTS_ZIP_URL,
        DEFAULT_PARQUET,
        download_companyfacts_zip,
        ingest_companyfacts_zip,
    )

    if zip_path:
        archive = Path(zip_path)
        if not archive.exists():
            raise typer.BadParameter(f"no such archive: {archive}")
    else:
        archive = Path(tempfile.gettempdir()) / "aethelark_companyfacts.zip"
        console.print(f"[dim]Downloading {COMPANYFACTS_ZIP_URL}…[/dim]")
        with console.status("[cyan]streaming archive…") as status:
            def progress(written, total):
                if total:
                    status.update(
                        f"[cyan]streaming archive… {written / 1e6:,.0f}/{total / 1e6:,.0f} MB"
                    )
                else:
                    status.update(f"[cyan]streaming archive… {written / 1e6:,.0f} MB")
            download_companyfacts_zip(archive, progress=progress)
        console.print(f"[green]✓[/green] Downloaded {archive.stat().st_size / 1e6:,.0f} MB")

    with console.status("[cyan]flattening into Parquet…"):
        stats = ingest_companyfacts_zip(archive, DEFAULT_PARQUET)

    console.print(
        f"[green]✓[/green] Ingested [bold]{stats['companies']:,}[/bold] companies / "
        f"[bold]{stats['facts']:,}[/bold] annual facts in "
        f"[bold]{stats['elapsed_seconds']:.2f}s[/bold]\n"
        f"[dim]{stats['parquet_path']} ({stats['bytes'] / 1e6:,.1f} MB)[/dim]"
    )

    if not zip_path and not keep_zip:
        archive.unlink(missing_ok=True)


def island_default() -> str:
    """Where the host looks for this module's island events. Host-resolved via
    tempfile.gettempdir(), so it must not be hardcoded to /tmp."""
    import tempfile
    from pathlib import Path as _Path

    return str(_Path(tempfile.gettempdir()) / "atrade_dynamic_island.json")


@app.command()
def listen(
    interval: float = typer.Option(30.0, "--interval",
                                   help="Seconds between feed polls (30 = 0.033 req/s)."),
    forms: str = typer.Option("4,8-K", "--forms", help="Comma-separated form types."),
    cycles: int = typer.Option(0, "--cycles", help="Stop after N polls (0 = forever)."),
    all_tickers: bool = typer.Option(False, "--all",
                                     help="Do not restrict to the tracked universe."),
    island_file: str = typer.Option(str(island_default()), "--island-file",
                                    help="Path to Dynamic Island JSON file."),
):
    """Featherweight SEC event listener emitting Dynamic Island JSON."""
    from aethelark_trade.engine import events as island
    from aethelark_trade.engine.sec_stream import stream
    from aethelark_trade.engine.watch import EventWatcher

    form_types = tuple(f.strip() for f in forms.split(",") if f.strip())
    watcher = EventWatcher(restrict_to_universe=not all_tickers)

    console.print(
        f"[dim]Listening: forms={','.join(form_types)} every {interval:.0f}s "
        f"({len(form_types) / interval:.3f} req/s). Ctrl-C to stop.[/dim]",
        style="dim",
    )

    try:
        for filing in stream(form_types=form_types, interval=interval,
                             max_cycles=cycles or None):
            payloads = watcher.handle(filing)
            if not payloads:
                continue
            # If two events land together, prioritize before writing.
            # Ascending sort ensures the highest-priority event is written last (latest wins).
            payloads.sort(key=island.event_priority)
            for payload in payloads:
                typer.echo(jsonlib.dumps(payload))
                island.write_dynamic_island_event(payload, dest=island_file)
    except KeyboardInterrupt:
        console.print("\n[dim]Listener stopped.[/dim]")


@app.command()
def insider(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    days: int = typer.Option(180, "--days", help="Lookback window."),
    json: bool = typer.Option(False, "--json", help="Emit machine-readable ledger."),
):
    """Latest SEC Form 4 and Form 144 insider transaction ledger."""
    from datetime import date, timedelta

    from aethelark_trade.engine import fetchers
    from aethelark_trade.engine.engine import SECClientContext

    cutoff = date.today() - timedelta(days=days)

    with SECClientContext() as client:
        transactions = fetchers.fetch_insider_transactions(client, ticker)
        try:
            notices = fetchers.fetch_form144_filings(client, ticker)
        except Exception:
            notices = []

    rows = [t for t in transactions
            if (t.transaction_date or t.filing_date) >= cutoff]
    rows.sort(key=lambda t: t.transaction_date or t.filing_date, reverse=True)

    if json:
        # Flatten here, shape there. This function knows the SEC objects;
        # `insider_ledger_view` knows what a payload has to fit inside, and
        # being pure dict-to-dict is what lets a real 182-filing ledger be a
        # test fixture instead of a live SEC call.
        flat = [
            {
                "date": str(t.transaction_date or t.filing_date),
                "insider": t.insider_name,
                "title": t.insider_title,
                "code": t.transaction_code,
                "signal": t.signal,
                "shares": t.shares,
                "price": t.price_per_share,
                "value": t.total_value,
                "shares_owned_after": t.shares_owned_after,
                "is_10b5_1": t.is_10b5_1,
                "accession": t.accession_number,
            }
            for t in rows
        ]
        typer.echo(jsonlib.dumps(
            fetchers.insider_ledger_view(flat, ticker, days, len(notices)),
            indent=2, default=str))
        return

    if not rows:
        console.print(f"[yellow]No Form 4 activity for {ticker.upper()} "
                      f"in the last {days} days.[/yellow]")
        return

    table = Table(title=f"{ticker.upper()} — Insider Ledger ({days}d)",
                  header_style="bold", box=None, pad_edge=False)
    table.add_column("Date", no_wrap=True)
    table.add_column("Insider")
    table.add_column("Role", style="dim")
    table.add_column("Code", justify="center")
    table.add_column("Shares", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Value", justify="right")
    table.add_column("Plan", justify="center", style="dim")

    for t in rows[:40]:
        colour = {"BULLISH": "green", "BEARISH": "red"}.get(t.signal, "white")
        table.add_row(
            str(t.transaction_date or t.filing_date),
            t.insider_name[:26],
            (t.insider_title or "")[:18],
            f"[{colour}]{t.transaction_code}[/{colour}]",
            f"{t.shares:,.0f}",
            "—" if not t.price_per_share else f"${t.price_per_share:,.2f}",
            "—" if t.total_value is None else f"${t.total_value:,.0f}",
            "10b5-1" if t.is_10b5_1 else "",
        )
    console.print(table)
    if notices:
        console.print(f"[dim]{len(notices)} Form 144 proposed-sale notice(s) on file.[/dim]")



def _readable(exc: Exception) -> str:
    """What the eagle is told when a command fails.

    Gemini 2.5 Flash reads this in the middle of a spoken turn, so it carries
    the next action and never a class name: "QuoteUnavailable: ..." spends the
    model's attention on a Python identifier that means nothing to it, and
    "KeyError: 'currentTradingPeriod'" -- which this replaced -- was read aloud
    to a user on 2026-09-04.

    Errors this codebase raises deliberately already say what to do next, so
    their own words are used. Anything else is a failure nobody anticipated, and
    the honest thing is to say so plainly rather than forward an internal.
    """
    from aethelark_trade.engine.fetchers import QuoteUnavailable

    if isinstance(exc, QuoteUnavailable):
        return str(exc)
    detail = str(exc).strip()
    return (f"That did not work and the reason is not one this module "
            f"recognises{': ' + detail if detail else ''}. Tell the user it "
            f"failed rather than trying a different tool.")


@app.command()
def portfolio(
    json: bool = typer.Option(False, "--json", help="Emit machine-readable account."),
):
    """Alpaca account equity, buying power and open positions."""
    from aethelark_trade.engine import fetchers

    try:
        data = fetchers.fetch_alpaca_portfolio()
    except Exception as exc:
        if json:
            typer.echo(jsonlib.dumps({"error": _readable(exc)}))
        else:
            console.print(f"[red]Portfolio unavailable:[/red] {exc}")
        raise typer.Exit(code=1)

    if json:
        typer.echo(jsonlib.dumps(data, indent=2, default=str))
        return

    mode = "paper" if data["paper"] else "live"
    console.print(Panel(
        f"[bold]Equity[/bold] ${data['equity']:,.2f}   "
        f"[bold]Cash[/bold] ${data['cash']:,.2f}   "
        f"[bold]Buying Power[/bold] ${data['buying_power']:,.2f}\n"
        f"[dim]{len(data['positions'])} open position(s) · {mode} account[/dim]",
        border_style="cyan", expand=False,
    ))

    if not data["positions"]:
        return

    table = Table(header_style="bold", box=None, pad_edge=False)
    table.add_column("Symbol")
    for col in ("Qty", "Entry", "Value", "P/L", "P/L %"):
        table.add_column(col, justify="right")
    for p in data["positions"]:
        colour = "green" if p["unrealized_pl"] >= 0 else "red"
        table.add_row(
            p["symbol"], f"{p['qty']:,.0f}", f"${p['avg_entry_price']:,.2f}",
            f"${p['market_value']:,.2f}",
            f"[{colour}]${p['unrealized_pl']:,.2f}[/{colour}]",
            f"[{colour}]{p['unrealized_plpc'] * 100:+.2f}%[/{colour}]",
        )
    console.print(table)


@app.command()
def quote(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    json: bool = typer.Option(False, "--json", help="Machine-readable quote."),
):
    """Current price and today's move. The fast path."""
    from aethelark_trade.engine import fetchers

    try:
        # The card that renders this needs its chart in the same payload.
        data = fetchers.quote_with_series(ticker)
    except Exception as exc:
        if json:
            typer.echo(jsonlib.dumps({"error": _readable(exc)}))
        else:
            console.print(f"[red]No quote for {ticker.upper()}:[/red] {exc}")
        raise typer.Exit(code=1)

    if json:
        typer.echo(jsonlib.dumps(data, indent=2))
        return

    up = data["change_pct"] >= 0
    colour = "green" if up else "red"
    arrow = "▲" if up else "▼"
    console.print(Panel(
        f"[bold white]{data['ticker']}[/bold white]  "
        f"[bold]${data['price']:,.2f}[/bold]   "
        f"[{colour}]{arrow} {data['change']:+,.2f} ({data['change_pct']:+.2f}%)[/{colour}]",
        border_style=colour, expand=False,
    ))


@app.command()
def governance(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    json: bool = typer.Option(False, "--json", help="Machine-readable signal."),
):
    """Is the CEO getting paid more than shareholders are making?"""
    from aethelark_trade.engine import fetchers
    from aethelark_trade.engine.engine import SECClientContext

    with SECClientContext() as client:
        signal = fetchers.fetch_governance(client, ticker)

    if json:
        typer.echo(jsonlib.dumps(
            {"ticker": ticker.upper(), **signal.to_dict()}, indent=2, default=str))
        return

    if not signal.available:
        console.print(f"[yellow]{ticker.upper()}:[/yellow] {signal.sentence}")
        return

    border = "dark_orange" if signal.bearish else "green"
    lines = [signal.sentence]
    if signal.ceo_name:
        lines.append(f"[dim]CEO: {signal.ceo_name}[/dim]")
    if signal.pay_change_pct is not None and signal.tsr_change_pct is not None:
        lines.append(
            f"[dim]Pay {signal.pay_change_pct:+.1f}%  ·  "
            f"Shareholder return {signal.tsr_change_pct:+.1f}%[/dim]"
        )
    console.print(Panel("\n".join(lines),
                        title=f"[bold]{ticker.upper()} — Governance[/bold]",
                        border_style=border, expand=False))


@app.command()
def owners(
    ticker: str = typer.Argument(..., help="Ticker symbol, e.g. NVDA"),
    json: bool = typer.Option(False, "--json", help="Machine-readable holders."),
):
    """Who holds five percent or more, and which of them are activists."""
    from aethelark_trade.owners import who_owns
    from aethelark_trade.storage import load_schedule13_filings

    answer = who_owns(ticker, load_schedule13_filings(ticker, limit=60))

    if json:
        typer.echo(jsonlib.dumps(answer, indent=2, default=str))
        return

    console.print(f"[bold]{answer['ticker']}[/bold] — {answer['summary']}")
    if not answer["holders"]:
        return

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Holder")
    table.add_column("Stake", justify="right")
    table.add_column("Shares", justify="right")
    table.add_column("Stance")
    table.add_column("Filed")
    for h in answer["holders"]:
        # A percentage the filing did not carry is a dash, not a zero.
        stake = f"{h['percent']}%" if h["percent"] is not None else "—"
        shares = f"{h['shares']:,}" if h["shares"] else "—"
        stance = ("[yellow]activist[/yellow]" if h["stance"] == "activist"
                  else "[dim]passive[/dim]")
        table.add_row(h["name"], stake, shares, stance, h["filed"])
    console.print(table)


@app.command()
def watch(ticker: str = typer.Argument(..., help="Ticker to follow"),
          json: bool = typer.Option(False, "--json")):
    """Add a ticker to your watchlist."""
    from aethelark_trade.engine import fetchers
    from aethelark_trade.engine.favorites import add_favorite

    # SHIP_1.0 B4. A symbol nobody checked used to be written straight in, and
    # then sat there permanently, priceless and nameless, costing every later
    # `watchlist` call a failed lookup. Resolving first is the whole fix.
    #
    # The refusal is QuoteUnavailable's own sentence, not a restatement of it:
    # that message already names the next action for the small model that reads
    # it, and two wordings for one failure is one wording too many.
    try:
        fetchers.fetch_quote(ticker)
    except fetchers.QuoteUnavailable as exc:
        if json:
            typer.echo(jsonlib.dumps(
                {"ticker": ticker.upper(), "added": False, "error": str(exc)}))
        else:
            console.print(f"[bold red]Not following {ticker.upper()}:[/bold red] {exc}")
        raise typer.Exit(code=1)

    added = add_favorite(ticker)
    if json:
        typer.echo(jsonlib.dumps({"ticker": ticker.upper(), "added": added}))
    elif added:
        console.print(f"[green]✓[/green] Following [bold]{ticker.upper()}[/bold]")
    else:
        console.print(f"[dim]{ticker.upper()} is already on your watchlist.[/dim]")


@app.command()
def unwatch(ticker: str = typer.Argument(..., help="Ticker to drop"),
            json: bool = typer.Option(False, "--json")):
    """Remove a ticker from your watchlist."""
    from aethelark_trade.engine.favorites import remove_favorite

    removed = remove_favorite(ticker)
    if json:
        typer.echo(jsonlib.dumps({"ticker": ticker.upper(), "removed": removed}))
    elif removed:
        console.print(f"[green]✓[/green] Stopped following [bold]{ticker.upper()}[/bold]")
    else:
        console.print(f"[dim]{ticker.upper()} was not on your watchlist.[/dim]")


@app.command()
def watchlist(json: bool = typer.Option(False, "--json")):
    """Show the tickers you follow, with live prices."""
    from aethelark_trade.engine import fetchers
    from aethelark_trade.engine.favorites import list_favorites

    rows = list_favorites()
    if not rows:
        if json:
            typer.echo(jsonlib.dumps({"count": 0, "tickers": []}))
        else:
            console.print("[yellow]Your watchlist is empty.[/yellow]\n"
                          "[dim]Add one with: atrade watch NVDA[/dim]")
        return

    quotes = []
    for symbol in rows:
        try:
            quotes.append(fetchers.fetch_quote(symbol))
        except Exception:
            quotes.append({"ticker": symbol, "price": None,
                           "change": None, "change_pct": None})

    if json:
        typer.echo(jsonlib.dumps({"count": len(quotes), "tickers": quotes},
                                 indent=2, default=str))
        return

    table = Table(title="Watchlist", header_style="bold", box=None, pad_edge=False)
    table.add_column("Ticker", style="bold")
    table.add_column("Price", justify="right")
    table.add_column("Today", justify="right")
    for q in quotes:
        if q["price"] is None:
            table.add_row(q["ticker"], "—", "—")
            continue
        colour = "green" if q["change_pct"] >= 0 else "red"
        table.add_row(q["ticker"], f"${q['price']:,.2f}",
                      f"[{colour}]{q['change_pct']:+.2f}%[/{colour}]")
    console.print(table)


@app.command("register")
def register_module(
    path: str = typer.Option("", "--path",
                             help="Override the modules directory."),
    json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """Install the Space-Eagle Module Bus socket for atrade.

    Copies the shipped manifest and its Dynamic Island assets. It does NOT
    re-render the manifest: the rendered form carries no [island] section, so
    regenerating over an existing install silently deletes the card
    configuration. See engine/register.py.
    """
    from aethelark_trade.engine.register import (
        RegistrationError, register, registration_summary,
    )

    try:
        target = register(path or None)
    except RegistrationError as exc:
        if json:
            console.print_json(jsonlib.dumps({"ok": False, "error": str(exc)}))
        else:
            console.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(1)

    tools, cards = registration_summary(target)
    if json:
        console.print_json(jsonlib.dumps({
            "ok": True, "manifest": str(target),
            "tools": tools, "island_cards": cards,
        }))
        return
    console.print(
        f"[green]✓[/green] Module registered at [bold]{target}[/bold]\n"
        f"[dim]{len(tools)} tools: {', '.join(tools)}[/dim]\n"
        f"[dim]{cards} island cards installed[/dim]"
    )


if __name__ == "__main__":
    app()
