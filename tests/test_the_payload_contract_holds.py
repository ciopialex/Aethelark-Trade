"""The key names this module emits are a public contract, and nothing owned it.

The host does not import this package. It runs the binary and reads JSON, and
`Space-Eagle/core/card_assembly.py` carries 51 hardcoded field-name literals
about that JSON. Rename a key here and nothing raises anywhere: the adapter
finds nothing, the card draws an em dash, and the only signal is a person
looking at a blank field. Four of ten consecutive commits in the host were that
one shape.

Worse, the split runs through the middle of a single file. `module/manifest.toml`
declares 27 field names in its island `shows` lists, and seven of them --
gov_label, gov_text, insider_net_usd, insider_trade_count, insider_latest,
compare_winner, compare_against -- are NOT produced by this module at all. They
are invented by the host's adapters from keys this module does emit (`net_usd`,
`filings`, `latest`, ...). So the manifest shipped here declares names only the
host can satisfy, and neither side can verify the whole contract alone.

This file owns the half that belongs here:

  * `module/payloads/*.json` are real captures from the binary, not
    hand-written samples. The host should render its templates against these
    instead of keeping its own copies, which go stale silently.
  * The tests below fail when a live payload stops matching its capture, which
    is where a rename actually originates.

Regenerate a capture deliberately, never to make a red test green:

    atrade <tool> --json > aethelark_trade/module/payloads/<tool>.json

and then go and fix the host's adapter in the same change.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PAYLOADS = REPO / "aethelark_trade" / "module" / "payloads"
MANIFEST = REPO / "aethelark_trade" / "module" / "manifest.toml"

#: Field names the island asks for that this module does not emit. They are
#: built by the host's adapters out of keys this module does emit. Listed here
#: so the gap is inspectable rather than folded into a passing test.
HOST_DERIVED = frozenset({
    "gov_label", "gov_text",
    "insider_net_usd", "insider_trade_count", "insider_latest",
    "compare_winner", "compare_against",
})

#: What the host builds each derived name from. If a key on the right is
#: renamed here, the name on the left stops appearing on the card.
DERIVED_FROM = {
    "insider_net_usd": ("insider", "net_usd"),
    "insider_trade_count": ("insider", "filings"),
    "insider_latest": ("insider", "latest"),
    "compare_winner": ("compare", "winner"),
    "gov_label": ("governance", "verdict"),
    "gov_text": ("governance", "sentence"),
}


def _captures() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(PAYLOADS.glob("*.json"))}


CAPTURES = _captures()


def test_captures_exist():
    assert CAPTURES, f"no payload captures in {PAYLOADS}"


@pytest.mark.parametrize("tool", sorted(CAPTURES))
def test_a_capture_is_a_json_object_with_keys(tool):
    assert isinstance(CAPTURES[tool], dict) and CAPTURES[tool], \
        f"{tool}.json is not a populated object"


# ------------------------------------------------- the manifest side of it

def _shows() -> set[str]:
    man = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    names: set[str] = set()
    for card in (man.get("island") or {}).get("cards", {}).values():
        names |= set(card.get("shows") or [])
    return names


def test_every_shows_name_is_either_ours_or_a_known_host_derivation():
    """A name that is neither is a field nobody can fill -- the em-dash bug."""
    ours: set[str] = set()
    for payload in CAPTURES.values():
        ours |= set(payload)

    unexplained = sorted(_shows() - ours - HOST_DERIVED)
    assert not unexplained, (
        f"island `shows` declares {unexplained}, which no captured payload "
        f"produces and which is not a documented host derivation. Either a "
        f"tool stopped emitting it, or the card asks for something that has "
        f"never existed.")


@pytest.mark.parametrize("derived,source", sorted(DERIVED_FROM.items()))
def test_the_source_key_behind_each_host_derived_name_still_exists(derived, source):
    """The half of the cross-repo contract this repo can actually enforce.

    The host builds `derived` from `tool.key`. If that key is renamed here, the
    host's adapter silently yields nothing and the card loses the field.
    """
    tool, key = source
    payload = CAPTURES.get(tool)
    if payload is None:
        pytest.skip(f"no capture for {tool}")
    assert key in payload, (
        f"'{key}' is gone from the {tool} payload, so the host can no longer "
        f"build '{derived}' and that field disappears from the island card")


def test_host_derived_names_are_not_quietly_emitted_by_us_too():
    """If this module ever starts emitting one of these itself, the adapter and
    the payload are both supplying it and the precedence is undefined."""
    for tool, payload in CAPTURES.items():
        clash = sorted(HOST_DERIVED & set(payload))
        assert not clash, (
            f"{tool} now emits {clash}, which the host also derives; decide "
            f"which one wins before shipping both")


# ------------------------------------------------------- drift at the source

@pytest.mark.network
@pytest.mark.parametrize("tool,argv", [
    ("quote", ["quote", "NVDA"]),
    ("governance", ["governance", "INTC"]),
    ("owners", ["owners", "PLTR"]),
])
def test_the_live_payload_still_has_the_captured_keys(tool, argv):
    """Runs the real binary. This is the test that catches a rename on the day
    it happens rather than when somebody notices a blank card."""
    captured = CAPTURES.get(tool)
    if captured is None:
        pytest.skip(f"no capture for {tool}")

    done = subprocess.run([sys.executable, "-m", "aethelark_trade.engine.cli",
                           *argv, "--json"],
                          capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        pytest.skip(f"{tool} did not run here: {done.stderr[-200:]}")
    try:
        live = json.loads(done.stdout)
    except ValueError:
        pytest.skip(f"{tool} did not return JSON")

    missing = sorted(set(captured) - set(live))
    assert not missing, (
        f"{tool} no longer emits {missing}. If that is deliberate, update "
        f"module/payloads/{tool}.json AND the host adapter that reads it.")
