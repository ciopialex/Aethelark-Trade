"""Which company a ticker means.

SEC's own `company_tickers.json` is the obvious source and it is wrong or
silent for nine of the 503 tracked names. Swept 2026-09-04:

  XOM     maps to 2115436, "ExxonMobil Holdings Corp" — a successor registrant
          created by an 8-K12B filed 2026-07-01. It holds the ticker and 29
          filings, none of them annual. Every 10-K ExxonMobil has ever filed
          is under 34088, which SEC now lists with no ticker at all. The
          engine fetched the successor, found no annual facts, and reported
          "No XBRL fundamentals available" for one of the largest filers in
          the United States.

  AVB BK CTRA SATS EA EQR    absent from SEC's file entirely.
  BRK.B BF.B                 spelled BRK-B and BF-B there.

`constituents.csv` carries a CIK column and is right about all nine, so for a
tracked name the curated file decides. These tests do not touch the network.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from aethelark_trade.ticker_registry import cik_for

REPO = Path(__file__).resolve().parent.parent


def test_exxon_resolves_to_the_registrant_that_has_the_filings():
    """34088 has 8,327 annual facts and scores 69. 2115436 has none."""
    assert cik_for("XOM") == "0000034088"


@pytest.mark.parametrize("ticker,cik", [
    ("AVB", "0000915912"), ("BK", "0001390777"), ("CTRA", "0000858470"),
    ("SATS", "0001415404"), ("EA", "0000712515"), ("EQR", "0000906107"),
])
def test_names_sec_omits_from_its_ticker_file_still_resolve(ticker, cik):
    assert cik_for(ticker) == cik


@pytest.mark.parametrize("ticker,cik", [
    ("BRK.B", "0001067983"), ("BF.B", "0000014693"),
])
def test_share_classes_written_with_a_dot_resolve(ticker, cik):
    assert cik_for(ticker) == cik


def test_every_tracked_name_carries_a_cik():
    """The curated file is only authoritative if it is complete. A blank CIK
    silently falls through to the SEC file this exists to correct."""
    from aethelark_trade.ticker_registry import _constituents_paths

    seed = next((c for c in _constituents_paths() if c.exists()), None)
    assert seed is not None, "constituents.csv is not shipped anywhere on the search path"
    rows = list(csv.DictReader(open(seed, encoding="utf-8")))
    assert len(rows) > 400, f"universe looks truncated: {len(rows)} rows"
    missing = [r["Symbol"] for r in rows if not (r.get("CIK") or "").strip().isdigit()]
    assert not missing, f"tracked names with no CIK: {missing}"


def test_ciks_are_ten_digits():
    """SEC's submissions and companyfacts URLs are zero-padded to ten."""
    for t in ("XOM", "MSFT", "JPM"):
        assert len(cik_for(t)) == 10, cik_for(t)


def test_a_name_outside_the_universe_is_not_invented():
    assert cik_for("NOSUCHTICKER") is None
    assert cik_for("") is None


def test_the_curated_map_does_not_disagree_with_the_name_map():
    """Both are read from the same file; if one drifts the other should say so."""
    from aethelark_trade.ticker_registry import _load_constituents, _constituent_ciks
    names, ciks = _load_constituents(), _constituent_ciks()
    assert set(ciks) == set(names), (
        f"symbols known to one map and not the other: "
        f"{set(ciks) ^ set(names)}")
