"""SHIP_1.0 B4 — following a company accepted anything.

Measured 2026-09-05:

    $ atrade watch ZZZQXWNOPE --json
    {"ticker": "ZZZQXWNOPE", "added": true}     exit 0

The symbol was written straight to the watchlist without anyone asking whether
it exists. It then sits there permanently, priceless and nameless, and every
later `watchlist` call pays a failed lookup for it.

The refusal is read by Gemini 2.5 Flash, so it names the next action rather than
only reporting the rejection -- `fetch_quote`'s QuoteUnavailable already carries
that wording, so the resolution failure is passed through rather than restated.
"""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from aethelark_trade.engine import cli as engine_cli
from aethelark_trade.engine import fetchers


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def never_added(monkeypatch):
    """Records what would have been written, and writes nothing."""
    written: list[str] = []

    def _add(ticker):
        written.append(ticker)
        return True

    monkeypatch.setattr("aethelark_trade.engine.favorites.add_favorite", _add)
    return written


def test_a_symbol_that_does_not_resolve_is_not_added(runner, never_added, monkeypatch):
    def _no_such(_ticker):
        raise fetchers.QuoteUnavailable(
            "ZZZQXWNOPE is not a symbol the market feed knows.")

    monkeypatch.setattr(fetchers, "fetch_quote", _no_such)

    result = runner.invoke(engine_cli.app, ["watch", "ZZZQXWNOPE", "--json"])

    assert never_added == [], (
        f"a symbol nobody could price was written to the watchlist: {never_added}")
    assert result.exit_code != 0, "adding an unresolvable symbol reported success"


def test_the_refusal_says_what_to_do_next(runner, never_added, monkeypatch):
    sentence = ("ZZZQXWNOPE is not a symbol the market feed knows. If a company "
                "was named, call quote again with its ticker instead.")

    monkeypatch.setattr(
        fetchers, "fetch_quote",
        lambda _t: (_ for _ in ()).throw(fetchers.QuoteUnavailable(sentence)))

    result = runner.invoke(engine_cli.app, ["watch", "ZZZQXWNOPE", "--json"])
    body = json.loads(result.stdout)

    assert "error" in body, f"no error field for the model to read: {body}"
    assert "ZZZQXWNOPE" in body["error"]
    assert body.get("added") is False, "the payload must say plainly it was not added"


def test_a_real_symbol_is_still_added(runner, never_added, monkeypatch):
    monkeypatch.setattr(
        fetchers, "fetch_quote",
        lambda t: {"ticker": t.upper(), "price": 1.0, "company_name": "Real Co"})

    result = runner.invoke(engine_cli.app, ["watch", "AAPL", "--json"])

    assert result.exit_code == 0, result.stdout
    assert never_added == ["AAPL"], "a resolvable symbol was refused"
    assert json.loads(result.stdout)["added"] is True
