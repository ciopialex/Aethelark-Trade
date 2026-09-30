"""Cached scorecards must know which scoring model produced them.

Observed in the eagle's boot log: `atrade_leaderboard` ranked META third with
`insider: 0`, a value produced by the symmetric Layer 5 curve that no longer
exists. Under the three-tier model META scores 45. Six of nine cached names
carried pre-recalibration insider scores, so the ranking mixed two different
scoring models and presented the result as one.

A cache with no model identity cannot detect that. This adds one.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from aethelark_trade.engine.engine import assemble_result
from aethelark_trade.engine.liar_filter import check_liar_filter
from aethelark_trade.engine.scoring import SCORING_MODEL_VERSION
from aethelark_trade.engine.store import (
    load_entries,
    load_scorecard,
    save_scorecard,
    stale_model_count,
)
from aethelark_trade.engine.types import LayerScore

CLEAN = check_liar_filter(50.0, [], as_of=date(2026, 8, 20))
NAMES = ("layer_1_fundamentals", "layer_2_macro_gravity", "layer_3_news_velocity",
         "layer_4_sector_relativity", "layer_5_insider_conviction",
         "layer_6_geopolitics", "layer_7_supply_chain")


@pytest.fixture
def db(tmp_path):
    return tmp_path / "t.db"


def result(ticker, quality=80, insider=70):
    layers = {n: LayerScore(score=50, summary=n) for n in NAMES}
    layers["layer_1_fundamentals"] = LayerScore(score=quality, summary="f")
    layers["layer_5_insider_conviction"] = LayerScore(score=insider, summary="i")
    return assemble_result(ticker, layers, CLEAN)


def test_model_version_is_a_non_empty_identifier():
    assert isinstance(SCORING_MODEL_VERSION, str)
    assert SCORING_MODEL_VERSION.strip()


def test_saved_scorecards_record_the_model_version(db):
    save_scorecard(result("NVDA"), db_path=db)
    assert load_scorecard("NVDA", db_path=db)["model_version"] == SCORING_MODEL_VERSION


def test_entries_from_the_current_model_load(db):
    save_scorecard(result("NVDA"), db_path=db)
    assert [e.ticker for e in load_entries(db_path=db)] == ["NVDA"]


def test_entries_from_a_superseded_model_are_withheld(db):
    """The META case: a score computed by scoring math that no longer exists
    must not be ranked as though it were current."""
    save_scorecard(result("META", insider=0), db_path=db,
                   model_version="layer5-symmetric-v0")
    assert load_entries(db_path=db) == []


def test_superseded_entries_are_counted_not_silently_dropped(db):
    save_scorecard(result("META", insider=0), db_path=db,
                   model_version="layer5-symmetric-v0")
    save_scorecard(result("NVDA"), db_path=db)
    assert stale_model_count(db_path=db) == 1


def test_rescoring_under_the_current_model_revives_an_entry(db):
    save_scorecard(result("META", insider=0), db_path=db,
                   model_version="layer5-symmetric-v0")
    assert load_entries(db_path=db) == []
    save_scorecard(result("META", insider=45), db_path=db)
    entries = load_entries(db_path=db)
    assert [e.ticker for e in entries] == ["META"]
    assert entries[0].insider == 45


def test_entries_expose_their_age(db):
    save_scorecard(result("NVDA"), db_path=db)
    entry = load_entries(db_path=db)[0]
    assert entry.age_seconds is not None
    assert entry.age_seconds < 60


def test_age_reflects_an_old_scorecard(db):
    old = result("NVDA")
    old.generated_at = (datetime.now(timezone.utc)
                        - timedelta(hours=15)).isoformat(timespec="seconds")
    save_scorecard(old, db_path=db)
    age = load_entries(db_path=db)[0].age_seconds
    assert 14 * 3600 < age < 16 * 3600


def test_unparseable_timestamp_yields_unknown_age_not_a_crash(db):
    broken = result("NVDA")
    broken.generated_at = "not-a-timestamp"
    save_scorecard(broken, db_path=db)
    assert load_entries(db_path=db)[0].age_seconds is None
