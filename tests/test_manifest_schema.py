"""The manifest generator must satisfy Space-Eagle's real loader.

Slice 4 was built to the schema in ROADMAP.md (`name` / `command` /
`tools = [...]`). The Module Bus actually requires `key` / `binary` / `output`
and an array-of-tables `[[tools]]` with `argv`. A manifest in the old shape is
rejected at manifest.py:183 with "no 'key'" and the module silently ceases to
exist -- which is exactly what happened to a3d.toml in the boot log.

These tests parse our generated TOML with Space-Eagle's own loader when it is
present, so the contract cannot drift again.
"""
import shutil
import tomllib
from pathlib import Path

import pytest

from aethelark_trade.engine.manifest import (
    EXPOSED_TOOLS,
    render_manifest,
    write_manifest,
)

SPACE_EAGLE = Path.home() / "Projects" / "Space-Eagle"
VALID_TYPES = {"STRING", "INTEGER", "NUMBER", "BOOLEAN", "ARRAY", "OBJECT"}
RESERVED_PARAM = "confirm_token"


@pytest.fixture(scope="module")
def data():
    return tomllib.loads(render_manifest())


# --------------------------------------------------- structural requirements
def test_declares_key_not_name(data):
    """manifest.py:181-183 reads raw['key'] and raises without it."""
    assert data["key"] == "atrade"
    assert "name" not in data


def test_declares_binary_not_command(data):
    """manifest.py:185-187 reads raw['binary']."""
    assert data["binary"] == "atrade"
    assert "command" not in data


def test_output_is_json(data):
    assert data["output"] == "json"


def test_tools_is_an_array_of_tables(data):
    """`tools = ["analyze", ...]` parses as a list of strings and blows up in
    _parse_tool, which expects a dict per entry."""
    assert isinstance(data["tools"], list)
    assert all(isinstance(t, dict) for t in data["tools"])
    assert [t["name"] for t in data["tools"]] == list(EXPOSED_TOOLS)


def test_every_tool_has_argv_and_description(data):
    for tool in data["tools"]:
        assert tool["argv"], f"{tool['name']} has no argv"
        assert tool["argv"][0] == tool["name"]
        assert "--json" in tool["argv"]
        assert tool["description"].strip()


def test_params_are_nested_under_their_own_tool(data):
    """Each tool's params must ride on that tool's table, not a stray
    top-level [tools.params.x] that attaches to whichever entry came last."""
    by_name = {t["name"]: t for t in data["tools"]}
    assert set(by_name["analyze"].get("params", {})) == {"ticker"}
    assert set(by_name["compare"].get("params", {})) == {"ticker_a", "ticker_b"}
    assert by_name["leaderboard"].get("params", {}) == {}
    assert by_name["portfolio"].get("params", {}) == {}


def test_param_types_are_from_the_accepted_set(data):
    for tool in data["tools"]:
        for pname, spec in (tool.get("params") or {}).items():
            assert spec["type"] in VALID_TYPES, f"{tool['name']}.{pname}"


def test_no_tool_declares_the_reserved_confirm_param(data):
    for tool in data["tools"]:
        assert RESERVED_PARAM not in (tool.get("params") or {})


def test_every_argv_placeholder_has_a_declared_param(data):
    for tool in data["tools"]:
        placeholders = {a.strip("{}") for a in tool["argv"] if a.startswith("{")}
        assert placeholders == set(tool.get("params") or {}), tool["name"]


# ------------------------------------------- the real loader, when available
@pytest.mark.skipif(not SPACE_EAGLE.exists(), reason="Space-Eagle not installed")
def test_space_eagle_actually_loads_our_manifest(tmp_path):
    """The decisive test: parse with the Module Bus's own code."""
    import sys
    sys.path.insert(0, str(SPACE_EAGLE))
    try:
        from core.module_bus.manifest import load_manifest
    except ImportError:
        pytest.skip("Space-Eagle module_bus not importable")
    finally:
        pass

    target = write_manifest(tmp_path / "atrade.toml")
    manifest = load_manifest(target)

    assert manifest.key == "atrade"
    assert manifest.binary == "atrade"
    assert manifest.output == "json"
    assert len(manifest.tools) == len(EXPOSED_TOOLS)
    assert {t.name for t in manifest.tools} == set(EXPOSED_TOOLS)


@pytest.mark.skipif(not SPACE_EAGLE.exists(), reason="Space-Eagle not installed")
def test_tools_get_module_qualified_names(tmp_path):
    """Names reach the model as `atrade_analyze`; a bare `portfolio` would
    collide with core tools in main.py's flat namespace."""
    import sys
    sys.path.insert(0, str(SPACE_EAGLE))
    try:
        from core.module_bus.manifest import load_manifest
    except ImportError:
        pytest.skip("Space-Eagle module_bus not importable")

    manifest = load_manifest(write_manifest(tmp_path / "atrade.toml"))
    assert {t.qualified_name for t in manifest.tools} == {
        f"atrade_{name}" for name in EXPOSED_TOOLS
    }
    # the collision the qualification exists to prevent
    assert "atrade_watchlist" in {t.qualified_name for t in manifest.tools}


@pytest.mark.skipif(not SPACE_EAGLE.exists(), reason="Space-Eagle not installed")
def test_declarations_build_without_error(tmp_path):
    """Each tool must produce a Gemini function declaration."""
    import sys
    sys.path.insert(0, str(SPACE_EAGLE))
    try:
        from core.module_bus.manifest import load_manifest
    except ImportError:
        pytest.skip("Space-Eagle module_bus not importable")

    manifest = load_manifest(write_manifest(tmp_path / "atrade.toml"))
    for tool in manifest.tools:
        decl = tool.declaration()
        assert decl["name"] == tool.qualified_name
        assert decl["parameters"]["type"] == "OBJECT"


def test_install_never_silently_writes_an_unloadable_file(tmp_path):
    """write_manifest must refuse to leave a file the bus would reject."""
    target = write_manifest(tmp_path / "atrade.toml")
    parsed = tomllib.loads(target.read_text())
    assert parsed.get("key") and parsed.get("binary")
