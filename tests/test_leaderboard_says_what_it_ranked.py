"""SHIP_1.0 A7 — "what should I buy" stops claiming it surveyed a market.

Ranking only re-sorts companies already analysed on this machine. Measured
2026-09-03, live:

    {"universe": "sp500", "count": 8, "superseded_scorecards": 2,
     "rankings": [{"rank": 1, "ticker": "META",
                   "scored_at": "2026-08-23T14:35:24+00:00",
                   "age_seconds": 766932.09}]}

Three untruths in one answer. It names `sp500` while ranking eight companies;
the leader was scored 8.9 days earlier; and two scorecards computed under a
superseded scoring model were counted. All returned as a success, which a person
hears as "I looked at the market and nothing much stands out."

The payload also spread the top company's quote across the top level, so a
question about a *list* put a card for a single *subject* on the island — the
falsification named in spec 15.4.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ATRADE = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "atrade"

#: Keys the island binds a single-subject card to. A list answer carrying any
#: of these draws a card for a company the question was not about.
SUBJECT_KEYS = ("price", "company_name", "series", "change_pct", "previous_close",
                "day_high", "day_low", "market_cap", "volume")


@pytest.fixture(scope="module")
def payload():
    if not ATRADE.exists():
        pytest.skip("atrade is not installed")
    done = subprocess.run([str(ATRADE), "leaderboard", "--json"],
                          capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-400:]
    return json.loads(done.stdout)


def test_it_does_not_claim_a_universe_it_did_not_survey(payload):
    """It ranks what is cached. Naming `sp500` beside a count of 8 is the lie."""
    assert payload.get("surveyed_the_universe") is False, (
        "the answer must state plainly that it did not survey the universe")
    assert "universe_requested" in payload, (
        "the requested universe must be labelled as requested, not as covered")


def test_it_says_how_many_it_could_actually_rank(payload):
    assert "ranked" in payload
    assert payload["ranked"] == len(payload.get("rankings", []))
    assert "scorecards_available" in payload


def test_it_reports_how_old_the_readings_are(payload):
    """A leader scored nine days ago, presented undated, reads as today."""
    if payload.get("ranked"):
        assert "stalest_days" in payload
        assert isinstance(payload["stalest_days"], (int, float))


def test_the_answer_carries_a_sentence_a_person_can_hear(payload):
    """Ship 1.0: 'it says plainly what it can rank and how many that is.'"""
    summary = payload.get("summary", "")
    assert summary, "an empty ranking with no explanation reads as 'nothing looks good'"
    assert str(payload.get("ranked", 0)) in summary or "nothing" in summary.lower()


def test_a_list_answer_puts_no_subject_card_on_the_island(payload):
    """Spec 15.4. The top company's quote used to be spread across the top
    level, so asking what to buy drew a card for whichever name ranked first."""
    leaked = [k for k in SUBJECT_KEYS if k in payload]
    assert not leaked, f"a list answer carries single-subject card keys: {leaked}"
