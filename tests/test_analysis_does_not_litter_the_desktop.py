"""SHIP_1.0 B1 — every analysis wrote a file to the user's Desktop, silently.

Measured 2026-09-05: nineteen `*_Aethelark_Report.md` files on the operator's
Desktop, eight of them written that evening by test runs and leaderboard calls
that nobody asked for a report from. The flag to skip it existed
(`write_dossier`) and defaulted to True, so every path that forgot to pass it
wrote a file.

A report is a thing a person asks for. It is not a side effect of asking what a
company is worth.
"""
from __future__ import annotations

import inspect

from aethelark_trade.engine import engine as engine_mod


def test_scoring_writes_no_report_unless_asked():
    """The default is the whole defect: every caller that forgets writes a file."""
    default = inspect.signature(engine_mod.evaluate_7layers).parameters["write_dossier"].default
    assert default is False, (
        "evaluate_7layers still writes a desktop report by default, so every "
        "caller that does not think about it litters the user's Desktop")


def test_the_flag_still_exists_for_whoever_does_want_one():
    assert "write_dossier" in inspect.signature(engine_mod.evaluate_7layers).parameters


def test_the_command_line_offers_a_report_rather_than_opting_out_of_one():
    """`--no-dossier` is the wrong shape: it makes the side effect the default."""
    from aethelark_trade.engine import cli as cli_mod

    params = inspect.signature(cli_mod.analyze).parameters
    assert "no_dossier" not in params, (
        "the flag still opts *out* of a file nobody asked for")
    assert "report" in params, (
        "there is no way to ask for a report, so the capability is simply gone")
    # Typer wraps a default in an OptionInfo, so the value is one level down.
    declared = params["report"].default
    assert getattr(declared, "default", declared) is False, (
        "the report flag exists but is on by default, which is the same defect "
        "wearing a different name")
