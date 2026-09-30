"""A layer's name is written down in four places, and nothing held them equal.

    engine/scoring.py   LAYER_WEIGHTS + NON_COMPOSITE_LAYERS   the maths
    engine/dossier.py   LAYER_TITLES                           the report
    engine/speech.py    _SPEAKERS                              the voice
    engine/engine.py    the keys it actually emits             the payload

Measured 2026-09-22: LAYER_WEIGHTS was covered by five test files, LAYER_TITLES
and _SPEAKERS by none. They agreed, but by luck rather than by construction --
nothing would have failed if they stopped agreeing.

That is not hypothetical here. `engine/governance.py:VERDICTS` called itself a
closed set matching what `xbrl.py` emits, drifted from it, and three real
verdicts silently classified as UNKNOWN until someone went looking. This is the
same shape one level up: add an eighth layer, forget `_SPEAKERS`, and the voice
quietly stops mentioning it while every other surface reports it.

A missing name is not a crash. It is a layer the user is never told about.
"""
from __future__ import annotations

import pytest

from aethelark_trade.engine.dossier import LAYER_TITLES
from aethelark_trade.engine.scoring import LAYER_WEIGHTS, NON_COMPOSITE_LAYERS
from aethelark_trade.engine.speech import _ORDER, _SPEAKERS

#: Every layer the engine knows about: scored ones plus the ones deliberately
#: kept out of the composite.
ALL_LAYERS = frozenset(LAYER_WEIGHTS) | frozenset(NON_COMPOSITE_LAYERS)


def test_there_are_layers_to_check():
    assert ALL_LAYERS, "no layers declared at all"


def test_every_layer_has_a_title():
    missing = sorted(ALL_LAYERS - set(LAYER_TITLES))
    assert not missing, (
        f"{missing} are weighted but have no entry in LAYER_TITLES, so the "
        f"dossier prints a raw key like 'layer_8_foo' as a heading")


def test_every_title_belongs_to_a_real_layer():
    orphans = sorted(set(LAYER_TITLES) - ALL_LAYERS)
    assert not orphans, (
        f"LAYER_TITLES names {orphans}, which no weight and no non-composite "
        f"entry mentions -- a heading for a layer that cannot be produced")


def test_every_layer_can_be_spoken():
    missing = sorted(ALL_LAYERS - set(_SPEAKERS))
    assert not missing, (
        f"{missing} have no phrase in speech._SPEAKERS, so the voice omits "
        f"them entirely while the card and the dossier both show them")


def test_every_speaker_belongs_to_a_real_layer():
    orphans = sorted(set(_SPEAKERS) - ALL_LAYERS)
    assert not orphans, f"speech._SPEAKERS has phrases for unknown layers: {orphans}"


def test_the_spoken_order_covers_every_composite_layer():
    """_ORDER decides what actually reaches the sentence. A layer absent from
    it has a phrase written and never used, which is harder to notice than
    having no phrase at all."""
    missing = sorted(set(LAYER_WEIGHTS) - set(_ORDER))
    assert not missing, (
        f"{missing} are weighted into the composite but never spoken, because "
        f"speech._ORDER does not list them")


def test_the_spoken_order_has_no_duplicates_and_no_strangers():
    assert len(_ORDER) == len(set(_ORDER)), f"speech._ORDER repeats a layer: {_ORDER}"
    strangers = sorted(set(_ORDER) - ALL_LAYERS)
    assert not strangers, f"speech._ORDER lists unknown layers: {strangers}"


def test_the_composite_weights_still_sum_to_one():
    """Not a naming check, but the same class: a number stated in one place
    and relied on in another. Renormalisation hides a drifted total."""
    total = sum(LAYER_WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9, f"LAYER_WEIGHTS sum to {total}, not 1.0"


def test_no_layer_is_both_weighted_and_excluded():
    both = sorted(set(LAYER_WEIGHTS) & set(NON_COMPOSITE_LAYERS))
    assert not both, (
        f"{both} carry a composite weight and are also listed as "
        f"non-composite; composite_score() would silently drop the weight")


@pytest.mark.parametrize("layer", sorted(ALL_LAYERS))
def test_each_layer_is_complete_across_all_four_sites(layer):
    """One failure naming one layer, rather than four set-difference dumps."""
    assert layer in LAYER_TITLES, f"{layer}: no title"
    assert layer in _SPEAKERS, f"{layer}: no spoken phrase"
    assert layer in LAYER_WEIGHTS or layer in NON_COMPOSITE_LAYERS, \
        f"{layer}: neither weighted nor explicitly excluded"
