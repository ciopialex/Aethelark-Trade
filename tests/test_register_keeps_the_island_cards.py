"""Registering the module must not cost it its Dynamic Island cards.

`render_manifest()` builds the manifest from `EXPOSED_TOOLS` and emits no
`[island]` section. The manifest the bus loads carries eight `[island]` tables
that exist in no code path — card sizes, `shows` field lists, transitions. So
the old regenerate-on-install behaviour deleted the card configuration every
time it ran, and the module went on answering questions with a blank card.

`atrade register` copies the shipped manifest instead. These tests hold that
line: they fail if anyone rewires registration back to the renderer.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from aethelark_trade.engine import manifest as manifest_mod
from aethelark_trade.engine import register as register_mod


def _shipped() -> dict:
    src = register_mod.shipped_module_dir() / "manifest.toml"
    return tomllib.loads(src.read_text(encoding="utf-8"))


def test_the_shipped_manifest_actually_has_island_cards():
    cards = (_shipped().get("island") or {}).get("cards", {})
    assert cards, "shipped manifest has no island cards to preserve"


def test_the_renderer_does_not_produce_them():
    """The reason registration copies rather than renders, stated as a test."""
    rendered = tomllib.loads(manifest_mod.render_manifest())
    assert not rendered.get("island"), (
        "render_manifest() now emits an [island] section — if it is complete, "
        "registration could render again; until then copying is the only way "
        "the cards survive")


def test_register_installs_every_island_card(tmp_path):
    target = register_mod.register(tmp_path)
    installed = tomllib.loads(Path(target).read_text(encoding="utf-8"))

    shipped_cards = (_shipped().get("island") or {}).get("cards", {})
    installed_cards = (installed.get("island") or {}).get("cards", {})
    assert installed_cards.keys() == shipped_cards.keys()
    for name, card in shipped_cards.items():
        assert installed_cards[name] == card, f"island card {name} changed"


def test_register_copies_the_card_files_next_to_the_manifest(tmp_path):
    target = Path(register_mod.register(tmp_path))
    cards = (_shipped().get("island") or {}).get("cards", {})
    for card in cards.values():
        name = card.get("file")
        if name:
            asset = target.parent / "island" / name
            assert asset.is_file(), f"card file {name} was not installed"
            assert asset.stat().st_size > 0


def test_register_installs_exactly_the_exposed_tools(tmp_path):
    target = register_mod.register(tmp_path)
    names, cards = register_mod.registration_summary(target)
    assert names == list(manifest_mod.EXPOSED_TOOLS)
    assert cards == len((_shipped().get("island") or {}).get("cards", {}))


def test_register_is_idempotent_and_keeps_the_cards(tmp_path):
    """Running it twice is the case that used to lose the island."""
    first = Path(register_mod.register(tmp_path))
    before = first.read_text(encoding="utf-8")
    second = Path(register_mod.register(tmp_path))
    assert second == first
    assert second.read_text(encoding="utf-8") == before


def test_register_writes_where_the_bus_reads(tmp_path):
    """<key>/manifest.toml wins the loader's sorted glob; <key>.toml loses."""
    target = Path(register_mod.register(tmp_path))
    assert target.name == "manifest.toml"
    assert target.parent.name == "atrade"


def test_a_manifest_naming_a_missing_card_is_refused(tmp_path, monkeypatch):
    """Ship a card file or fail loudly — never install a blank card."""
    broken = tmp_path / "pkg"
    (broken / "island").mkdir(parents=True)
    src = register_mod.shipped_module_dir() / "manifest.toml"
    (broken / "manifest.toml").write_text(src.read_text(encoding="utf-8"),
                                          encoding="utf-8")
    # island/ deliberately left empty
    monkeypatch.setattr(register_mod, "shipped_module_dir", lambda: broken)

    with pytest.raises(register_mod.RegistrationError, match="island card"):
        register_mod.register(tmp_path / "modules")
