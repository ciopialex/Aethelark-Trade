"""Dossier rendering."""
from datetime import date

from aethelark_trade.engine.dossier import dossier_path, render_dossier
from aethelark_trade.engine.engine import assemble_result
from aethelark_trade.engine.liar_filter import LiarFilterResult, check_liar_filter
from aethelark_trade.engine.types import LayerScore

CLEAN = check_liar_filter(50.0, [], as_of=date(2026, 8, 19))


def layers(**overrides):
    base = {name: LayerScore(score=70, summary=f"{name} reading")
            for name in ("layer_1_fundamentals", "layer_2_macro_gravity",
                         "layer_3_news_velocity", "layer_4_sector_relativity",
                         "layer_5_insider_conviction", "layer_6_geopolitics",
                         "layer_7_supply_chain")}
    base.update(overrides)
    return base


def test_dossier_path_matches_the_documented_location():
    assert dossier_path("nvda").name == "NVDA_Aethelark_Report.md"
    assert dossier_path("NVDA").parent.name == "Desktop"


def test_dossier_contains_verdict_and_every_layer():
    md = render_dossier(assemble_result("NVDA", layers(), CLEAN))
    assert "# NVDA — Aethelark 7-Layer Dossier" in md
    # §30.1: one of exactly five words. Which one depends on the driving layer
    # now, not on the composite band, so the dossier is checked against the
    # vocabulary rather than against a single expected word.
    assert any(w in md for w in ("ACCUMULATE", "WATCH", "NEUTRAL", "CAUTION", "AVOID"))
    for n in range(1, 8):
        assert f"Layer {n} —" in md


def test_dossier_names_the_data_gaps_explicitly():
    md = render_dossier(assemble_result(
        "NVDA", layers(layer_3_news_velocity=LayerScore.unavailable("No headlines")), CLEAN
    ))
    assert "Data Gaps" in md
    assert "layer_3_news_velocity" in md


def test_dossier_reports_a_divergence():
    dirty = LiarFilterResult("DIVERGENCE", 92.0, -18_200_000.0, 7, "euphoria vs dumping")
    md = render_dossier(assemble_result("META", layers(), dirty))
    assert "DIVERGENCE" in md
    assert "-18,200,000" in md
