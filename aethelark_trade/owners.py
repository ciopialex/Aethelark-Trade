"""Who owns a company, from its Schedule 13D and 13G filings.

SHIP_1.0 C1. The parser, the storage and the collector were all built and wired;
nothing reached them, because no command existed. This turns the stored filings
into an answer.

It is a fact rather than a forecast -- who holds five percent or more, and which
of them told the SEC they intend to push for change. A 13D filer wants
something; a 13G filer is accumulating quietly. That distinction is the whole
value of the question and it is carried in the form type, not inferred.

Three things this module refuses to do, each of which would be easy:

  - **Show a filing nobody could read.** Measured 2026-09-05, 4 of 40 stored
    filings carry `Unknown Filer (Parsing Failed)` with zero shares. Listing
    those as holders states a falsehood. Dropping them silently overstates how
    complete the answer is. They are excluded and counted.
  - **Report a missing percentage as zero.** A filing that did not carry a
    percentage becomes `None`, not `0.0`. Zero means "owns none of it", which is
    a claim, and s15 exists to stop this codebase making claims it cannot back.
  - **Answer as of now.** Ownership filings are episodic; the newest 13G for a
    company can be two years old. The answer carries its own date so nobody
    reads stale holdings as current ones.
"""
from __future__ import annotations

from typing import Any, Iterable

#: What the parser writes into `filer_name` when it could not read the filing.
_UNREADABLE = "parsing failed"


def _is_unreadable(filing) -> bool:
    name = (getattr(filing, "filer_name", "") or "").strip()
    return not name or _UNREADABLE in name.lower()


def _percent(filing) -> float | None:
    """The stake, or None when the filing did not carry one.

    Zero is not the same as absent. A fund reported at 0.0% would be a fund that
    owns none of the company, which is not what a 13G filing means.
    """
    value = getattr(filing, "percent_of_class", None)
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def who_owns(ticker: str, filings: Iterable[Any]) -> dict:
    """The five-percent holders of one company, largest stake first."""
    filings = list(filings or [])

    unreadable = sum(1 for f in filings if _is_unreadable(f))
    readable = [f for f in filings if not _is_unreadable(f)]

    # One holder, one row. A fund files an amended 13G every time its stake
    # moves, so the same name appears repeatedly; the question is what it owns
    # now, which is its most recent filing.
    latest: dict[str, Any] = {}
    for filing in readable:
        name = filing.filer_name.strip()
        held = latest.get(name)
        if held is None or filing.filing_date > held.filing_date:
            latest[name] = filing

    holders = [{
        "name": f.filer_name.strip(),
        "percent": _percent(f),
        "shares": int(f.shares_owned) if getattr(f, "shares_owned", 0) else None,
        "stance": "activist" if f.is_activist else "passive",
        "form": f.form_type,
        "filed": f.filing_date.isoformat(),
    } for f in latest.values()]

    # Largest stake first; a holder with no percentage sorts last rather than
    # being treated as zero.
    holders.sort(key=lambda h: (h["percent"] is not None, h["percent"] or 0),
                 reverse=True)

    activists = sum(1 for h in holders if h["stance"] == "activist")
    dates = [f.filing_date for f in readable]
    latest_filing = max(dates).isoformat() if dates else None

    return {
        "ticker": ticker.upper(),
        "holders": holders,
        "activists": activists,
        "unreadable": unreadable,
        "latest_filing": latest_filing,
        "summary": _summary(ticker, holders, activists, unreadable, latest_filing),
    }


def _summary(ticker: str, holders: list, activists: int, unreadable: int,
             latest_filing: str | None) -> str:
    """One sentence, written for the small model that reads it aloud.

    Names the next action when there is nothing to report, because a model told
    only that a list is empty has to guess whether to retry, try another tool,
    or say so.
    """
    name = ticker.upper()
    if not holders:
        said = (f"No investor has filed a five percent stake in {name}. That is "
                f"not a gap in the data -- it means nobody crossed the "
                f"threshold that requires a filing. Say so; do not retry.")
        if unreadable:
            said += (f" {unreadable} filing(s) on record could not be read and "
                     f"are not included.")
        return said

    noun = "holder" if len(holders) == 1 else "holders"
    said = f"{len(holders)} five-percent {noun} on record for {name}"
    if activists:
        which = "is an activist" if activists == 1 else "are activists"
        said += f", of which {activists} {which} (filed 13D, wants change)"
    said += "."
    if latest_filing:
        said += f" The most recent filing is dated {latest_filing}."
    if unreadable:
        said += (f" {unreadable} further filing(s) could not be read and are "
                 f"not included.")
    return said
