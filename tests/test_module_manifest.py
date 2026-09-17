"""Manifest basics: location, validity, coverage, idempotence.

The schema-shape assertions that used to live here encoded ROADMAP.md's
`name`/`command`/`tools = [...]` design, which the Module Bus rejects. They are
superseded by tests/test_manifest_schema.py, which validates against
Space-Eagle's own loader rather than against a document.
"""
import tomllib
from pathlib import Path

from aethelark_trade.engine.manifest import (
    DEFAULT_MANIFEST_PATH,
    EMITTED_EVENTS,
    EXPOSED_TOOLS,
    render_manifest,
    write_manifest,
)


def test_manifest_lands_where_the_loader_will_actually_read_it():
    """Not the documented path -- the winning one.

    This asserted `.aethelark/modules/atrade.toml` until 2026-09-05, which is
    where install-module wrote and where the eagle never looked. Space-Eagle's
    loader scans

        sorted(set(glob("*.toml") + glob("*/manifest.toml") + glob("*/*.toml")))

    and keeps the first manifest per module key. Path sorting puts the directory
    entry first, so an older `atrade/manifest.toml` beat every regeneration.
    Measured: an added `owners` tool never reached the bus.

    Same lesson as this file's docstring records for the schema assertions --
    validate against the loader, not against a document that describes it.
    """
    assert DEFAULT_MANIFEST_PATH == (
        Path.home() / ".aethelark" / "modules" / "atrade" / "manifest.toml")


def test_manifest_is_valid_toml():
    tomllib.loads(render_manifest())


def test_the_roadmap_tools_are_all_still_exposed():
    """ROADMAP Slice 4 named five. More have since been added for voice routing;
    none of the original five may quietly disappear."""
    assert set(EXPOSED_TOOLS) >= {
        "analyze", "compare", "leaderboard", "insider", "portfolio"
    }


def test_the_fast_price_path_is_exposed_separately_from_analyze():
    """Routing "what's NVDA doing" to analyze costs seconds instead of
    milliseconds, which is the whole difference between a HUD and a spinner."""
    assert "quote" in EXPOSED_TOOLS
    assert "analyze" in EXPOSED_TOOLS


def test_manifest_declares_the_ui_events_it_emits():
    data = tomllib.loads(render_manifest())
    assert set(data["events"]["emits"]) == set(EMITTED_EVENTS)
    assert set(EMITTED_EVENTS) == {
        "form4_whale_buy", "8k_material_event", "liar_filter_warning",
        "relative_outlier_leader", "scoring_progress",
    }


def test_write_manifest_creates_parent_directories(tmp_path):
    target = tmp_path / "nested" / "modules" / "atrade.toml"
    written = write_manifest(target)
    assert written.exists()
    assert tomllib.loads(written.read_text())["key"] == "atrade"


def test_rewriting_is_idempotent(tmp_path):
    target = tmp_path / "atrade.toml"
    write_manifest(target)
    first = target.read_text()
    write_manifest(target)
    assert target.read_text() == first
