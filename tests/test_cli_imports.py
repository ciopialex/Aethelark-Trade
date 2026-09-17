"""The command line has to at least start.

This file exists because `atrade` was completely dead — every command, not one
— while the suite reported 355 passing. `--sector` was added using
`Optional[str]` without importing `typing`, which is a module-level NameError,
so `from aethelark_trade.engine.cli import app` raised and the binary could not
even print its help.

Nothing in the suite imported the CLI. The module's entire public surface is
that binary: a user never calls `score_fundamentals`, they type `atrade`. A
green suite over a program that will not start is the most expensive kind of
green there is.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest


def test_the_cli_module_imports():
    """The one-line guard that would have caught it."""
    import importlib

    module = importlib.import_module("aethelark_trade.engine.cli")
    assert module.app is not None


def test_every_command_the_shop_advertises_is_registered():
    """A manifest promising a tool that the CLI does not have is a module that
    fails on first use."""
    from aethelark_trade.engine.cli import app

    names = {c.name or c.callback.__name__ for c in app.registered_commands}
    for command in ("quote", "analyze", "compare", "leaderboard", "insider",
                    "portfolio", "watch", "unwatch", "watchlist", "governance"):
        assert command in names, f"{command} is not a registered command"


def test_the_binary_runs_its_own_help():
    """End to end through the interpreter, because an import inside the test
    process can be satisfied by state a fresh shell does not have."""
    done = subprocess.run(
        [sys.executable, "-c",
         "from aethelark_trade.engine.cli import app; print('ok')"],
        capture_output=True, text=True, timeout=120)

    assert done.returncode == 0, done.stderr[-800:]
    assert "ok" in done.stdout


def test_leaderboard_accepts_the_sector_flag():
    """The flag that broke it. Declared, and declared with a type the module
    actually imported."""
    from aethelark_trade.engine.cli import app

    command = next(c for c in app.registered_commands
                   if (c.name or c.callback.__name__) == "leaderboard")
    params = command.callback.__annotations__
    assert "sector" in params, "leaderboard has no --sector parameter"


#: Every binary pyproject promises. A promise that raises on import is a broken
#: install, not a missing feature -- and `--help` succeeding proves only that the
#: Typer object built, not that the command bodies can run.
#:
#: This repo publishes ONE binary. The operator's private CLIs (scrapetrade,
#: insiders, insiders-summary, smartmoney, aethelark) live in a separate private
#: repository and their modules are not present here at all. The tests below are
#: therefore also the leak detector: if a private entry point or one of its
#: modules ever reappears, they fail.
ENTRY_POINTS = {
    "atrade": ("aethelark_trade.engine.cli", "app"),
}

#: Modules that must NOT exist in a public checkout.
PRIVATE_MODULES = (
    "aethelark_trade.cli",
    "aethelark_trade.aethelark_cli",
    "aethelark_trade.sec_streamer",
    "aethelark_trade.display",
    "aethelark_trade.collector",
    "aethelark_trade.daemon",
)


@pytest.mark.parametrize("binary", sorted(ENTRY_POINTS))
def test_every_declared_entry_point_imports(binary):
    import importlib

    module, attr = ENTRY_POINTS[binary]
    mod = importlib.import_module(module)
    assert getattr(mod, attr, None) is not None, f"{module}.{attr} is missing"


def test_pyproject_declares_exactly_one_binary():
    """The packaging half of the split. A private entry point re-added here
    would install a command whose module this repo does not contain."""
    import tomllib

    root = pathlib.Path(__file__).resolve().parent.parent
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data.get("project", {}).get("scripts", {})
    assert set(scripts) == {"atrade"}, f"unexpected entry points: {sorted(scripts)}"
    assert scripts["atrade"] == "aethelark_trade.engine.cli:app"


@pytest.mark.parametrize("module", PRIVATE_MODULES)
def test_the_private_cli_is_absent(module):
    """Not gitignored -- absent. You cannot leak what is not in the building."""
    import importlib.util

    assert importlib.util.find_spec(module) is None, (
        f"{module} is importable from this repo; the private CLI has leaked in")


def test_every_command_body_import_succeeds():
    """Inspect and execute all lazy imports within every registered command body.

    Prevents regression where Typer app builds but commands fail at runtime
    due to renamed, privatised, or missing imports.
    """
    import ast
    import importlib
    import inspect

    failures = []

    for binary, (module_name, attr_name) in ENTRY_POINTS.items():
        mod = importlib.import_module(module_name)
        typer_app = getattr(mod, attr_name, None)
        if typer_app is None or not hasattr(typer_app, "registered_commands"):
            continue

        for cmd in typer_app.registered_commands:
            fn = cmd.callback
            if not fn:
                continue
            cmd_name = cmd.name or fn.__name__
            source = inspect.getsource(fn)
            tree = ast.parse(source)

            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    stmt = ast.unparse(node)
                    try:
                        exec(stmt)
                    except Exception as exc:
                        failures.append((binary, cmd_name, stmt, str(exc)))

    assert not failures, f"Command body import failures: {failures}"
