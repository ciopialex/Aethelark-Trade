"""Guards on what a public checkout is allowed to contain.

This package was split out of a private repository that also held the
operator's standalone CLIs. The split was done by copying only the module's
import closure, so the private code is absent rather than ignored -- and these
tests are what keeps it absent.

They also cover the two things that are easy to carry across by accident: a
personal contact address baked into the SEC User-Agent, and a credential file.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

#: Files worth scanning. Excludes the virtualenv, git internals and caches.
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache",
             ".mypy_cache", "dist", "build", "node_modules"}
TEXT_SUFFIXES = {".py", ".toml", ".md", ".txt", ".cfg", ".ini", ".html",
                 ".css", ".js", ".json", ".yaml", ".yml", ".example"}


def _text_files():
    for path in REPO.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.resolve() == Path(__file__).resolve():
            continue        # this file quotes every pattern it searches for
        if path.is_file() and path.suffix in TEXT_SUFFIXES:
            yield path


# --------------------------------------------------------------- private code

PRIVATE_FILENAMES = (
    "cli.py", "aethelark_cli.py", "sec_streamer.py", "display.py",
    "summary.py", "collector.py", "daemon.py", "autopsy.py", "execution.py",
    "state_nexus.py", "harvester.py", "scout.py",
)


@pytest.mark.parametrize("name", PRIVATE_FILENAMES)
def test_no_private_cli_source_file_is_present(name):
    """`aethelark_trade/<name>` must not exist. engine/cli.py is unaffected:
    the check is scoped to the package root, where the private CLIs lived."""
    assert not (REPO / "aethelark_trade" / name).exists(), (
        f"aethelark_trade/{name} belongs to the private CLI and must not ship")


def test_only_atrade_is_installed_as_a_binary():
    import tomllib

    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert set(data["project"]["scripts"]) == {"atrade"}


# ------------------------------------------------------------------- secrets

#: Deliberately narrow: a bare mention of ALPACA_API_KEY is fine (the code reads
#: that variable), an assignment with a value after it is not.
SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)
    (?:api[_-]?key|secret[_-]?key|access[_-]?token|password)
    [ \t]*[=:][ \t]*
    ["']?[A-Za-z0-9/+_-]{16,}["']?
    """)
TOKEN_SHAPES = re.compile(r"(gh[pous]_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16})")


def test_no_secret_looking_assignment_anywhere():
    hits = []
    for path in _text_files():
        body = path.read_text(encoding="utf-8", errors="replace")
        for pattern in (SECRET_ASSIGNMENT, TOKEN_SHAPES):
            for match in pattern.finditer(body):
                # .env.example ships empty values on purpose.
                if path.name == ".env.example" and match.group(0).rstrip().endswith("="):
                    continue
                hits.append(f"{path.relative_to(REPO)}: {match.group(0)[:60]}")
    assert not hits, "possible credential committed:\n" + "\n".join(hits)


def test_no_credential_files_are_committed():
    bad = [p.relative_to(REPO) for p in REPO.rglob("*")
           if not any(part in SKIP_DIRS for part in p.parts) and p.is_file()
           and (p.name == ".env" or p.suffix in {".pem", ".key"}
                or "Keys" in p.name and p.suffix == ".txt")]
    assert not bad, f"credential files present: {bad}"


# -------------------------------------------------------------- personal data

PERSONAL = re.compile(r"(?i)(shennyonthebeat|7even\.tech|@gmail\.com)")


def test_no_personal_contact_is_baked_in():
    """SEC needs a contactable User-Agent, but not one specific person's.

    A hardcoded address means every installation's traffic identifies as the
    original author, and someone else's rate-limit abuse lands on their name.
    """
    hits = [f"{p.relative_to(REPO)}:{m.group(0)}"
            for p in _text_files()
            for m in [PERSONAL.search(p.read_text(encoding="utf-8", errors="replace"))]
            if m]
    assert not hits, "personal identifier in a public file:\n" + "\n".join(hits)


# ------------------------------------------------------------- SEC compliance

def test_the_user_agent_is_declared_and_contactable():
    from aethelark_trade.engine.useragent import sec_user_agent

    ua = sec_user_agent()
    assert "Aethelark-Trade" in ua, "UA must name the software"
    assert "(" in ua and ")" in ua, "UA must carry a contact in parentheses"


def test_the_user_agent_never_impersonates_a_browser():
    """SEC treats browser impersonation as a policy violation, not a trick."""
    from aethelark_trade.engine.useragent import sec_user_agent

    ua = sec_user_agent().lower()
    for forbidden in ("mozilla", "chrome", "safari", "applewebkit", "gecko"):
        assert forbidden not in ua, f"UA impersonates a browser: {forbidden!r}"


def test_an_operator_can_supply_their_own_contact(monkeypatch):
    from aethelark_trade.engine import useragent

    monkeypatch.setenv(useragent.CONTACT_ENV, "ops@example.org")
    assert "ops@example.org" in useragent.sec_user_agent()


def test_every_sec_caller_uses_the_shared_user_agent():
    """No module may re-declare its own literal UA string."""
    from aethelark_trade.engine import bulk, logos, sec_stream
    from aethelark_trade import sec_client
    from aethelark_trade.engine.useragent import sec_user_agent

    expected_contact = sec_user_agent().split("(")[-1]
    for module, attr in ((sec_client, "DEFAULT_USER_AGENT"),
                         (sec_stream, "USER_AGENT"),
                         (bulk, "USER_AGENT"),
                         (logos, "USER_AGENT")):
        ua = getattr(module, attr)
        assert "Aethelark-Trade" in ua, f"{module.__name__}.{attr} is off-pattern"
        assert expected_contact in ua, (
            f"{module.__name__}.{attr} does not use the shared contact")
