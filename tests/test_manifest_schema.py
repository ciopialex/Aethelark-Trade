"""The manifest `atrade register` installs must satisfy Space-Eagle's real loader.

Slice 4 was built to the schema in ROADMAP.md (`name` / `command` /
`tools = [...]`). The Module Bus actually requires `key` / `binary` / `output`
and an array-of-tables `[[tools]]` with `argv`. A manifest in the old shape is
rejected with "no 'key'" and the module silently ceases to exist -- which is
exactly what happened to a3d.toml in the boot log.

These used to check a manifest RENDERED from a table of tools, which nothing
installed; the file that ships was checked by nobody on this side. They now
read the shipped file, and load what `register` installs with the bus's own
code when Space-Eagle is present, so the contract cannot drift again.
"""
import re
import sys
import tomllib
from pathlib import Path

import pytest

from aethelark_trade.engine import register as register_mod

SPACE_EAGLE = Path.home() / "Projects" / "Space-Eagle"
VALID_TYPES = {"STRING", "INTEGER", "NUMBER", "BOOLEAN", "ARRAY", "OBJECT"}
RESERVED_PARAM = "confirm_token"


@pytest.fixture(scope="module")
def data():
    src = register_mod.shipped_module_dir() / "manifest.toml"
    return tomllib.loads(src.read_text(encoding="utf-8"))


# --------------------------------------------------- structural requirements
def test_declares_key_not_name(data):
    """The loader reads raw['key'] and raises without it."""
    assert data["key"] == "atrade"
    assert "name" not in data


def test_declares_binary_not_command(data):
    assert data["binary"] == "atrade"
    assert "command" not in data


def test_output_is_json(data):
    assert data["output"] == "json"


def test_tools_is_an_array_of_tables(data):
    """`tools = ["analyze", ...]` parses as a list of strings and blows up in
    the loader, which expects a table per entry."""
    assert isinstance(data["tools"], list)
    assert all(isinstance(t, dict) for t in data["tools"])


def test_every_tool_is_a_command_the_binary_has(data):
    """The seam between the manifest and the binary. A tool whose argv names a
    command `atrade` does not have fails with a usage error, in front of the
    user, and every check on the manifest alone passes."""
    from typer.main import get_command

    from aethelark_trade.engine.cli import app

    commands = set(get_command(app).commands)
    missing = [t["name"] for t in data["tools"] if t["argv"][0] not in commands]
    assert not missing, f"argv names commands atrade does not have: {missing}"


def test_every_tool_answers_in_json_and_says_when_to_use_it(data):
    for tool in data["tools"]:
        assert "--json" in tool["argv"], tool["name"]
        assert tool["description"].strip(), tool["name"]


def test_param_types_are_from_the_accepted_set(data):
    for tool in data["tools"]:
        for pname, spec in (tool.get("params") or {}).items():
            assert spec["type"] in VALID_TYPES, f"{tool['name']}.{pname}"


def test_no_tool_declares_the_reserved_confirm_param(data):
    for tool in data["tools"]:
        assert RESERVED_PARAM not in (tool.get("params") or {})


def test_every_argv_placeholder_has_a_declared_param(data):
    """Including placeholders inside an element, like `--days={days}`."""
    for tool in data["tools"]:
        placeholders = set(re.findall(r"\{(\w+)\}", " ".join(tool["argv"])))
        assert placeholders == set(tool.get("params") or {}), tool["name"]


# ------------------------------------------- the real loader, when available
@pytest.fixture()
def installed(tmp_path):
    """What `atrade register` installs, loaded by the Module Bus's own code."""
    sys.path.insert(0, str(SPACE_EAGLE))
    try:
        from core.module_bus.manifest import load_manifest
    except ImportError:
        pytest.skip("Space-Eagle module_bus not importable")
    return load_manifest(register_mod.register(tmp_path))


@pytest.mark.skipif(not SPACE_EAGLE.exists(), reason="Space-Eagle not installed")
def test_space_eagle_actually_loads_what_register_installs(installed, data):
    """The decisive test. The loader validates the island too, so a card whose
    template did not travel with the manifest fails here."""
    assert installed.key == "atrade"
    assert installed.binary == "atrade"
    assert installed.output == "json"
    assert [t.name for t in installed.tools] == [t["name"] for t in data["tools"]]
    assert installed.island is not None and installed.island.cards


@pytest.mark.skipif(not SPACE_EAGLE.exists(), reason="Space-Eagle not installed")
def test_tools_get_module_qualified_names(installed):
    """Names reach the model as `atrade_analyze`; a bare `portfolio` would
    collide with the harness's own tools in one flat namespace."""
    assert all(t.qualified_name == f"atrade_{t.name}" for t in installed.tools)
    assert "atrade_watchlist" in {t.qualified_name for t in installed.tools}


@pytest.mark.skipif(not SPACE_EAGLE.exists(), reason="Space-Eagle not installed")
def test_declarations_build_without_error(installed):
    """Each tool must produce a Gemini function declaration."""
    for tool in installed.tools:
        decl = tool.declaration()
        assert decl["name"] == tool.qualified_name
        assert decl["parameters"]["type"] == "OBJECT"
