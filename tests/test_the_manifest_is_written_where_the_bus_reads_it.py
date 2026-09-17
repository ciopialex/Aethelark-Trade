"""`atrade install-module` wrote a manifest the eagle would never read.

Space-Eagle's loader scans a modules directory with three globs and keeps the
first manifest it finds per module key:

    sorted(set(dir.glob("*.toml") + dir.glob("*/manifest.toml") + dir.glob("*/*.toml")))

Path sorting puts the directory entry first, so with both files present:

    .aethelark/modules/atrade/manifest.toml     <- wins
    .aethelark/modules/atrade.toml              <- what install-module wrote

Measured 2026-09-05: after adding an `owners` tool and running `install-module`,
the bus still offered ten atrade tools and not eleven. The regenerated manifest
was being written to a path that loses, so the documented way to change what the
eagle can call did nothing at all.

The other two installed modules, a3d and alaw, both use `<key>/manifest.toml`.
This one was the odd one out.
"""
from __future__ import annotations

from pathlib import Path

from aethelark_trade.engine import manifest as manifest_mod


def test_the_default_path_is_the_one_the_loader_prefers():
    path = Path(manifest_mod.DEFAULT_MANIFEST_PATH)
    assert path.name == "manifest.toml", (
        f"install-module writes {path.name!r} at the modules root, which sorts "
        f"after <key>/manifest.toml and therefore loses to any older copy")
    assert path.parent.name == "atrade"


def test_writing_it_creates_the_directory(tmp_path):
    target = tmp_path / "modules" / "atrade" / "manifest.toml"
    written = manifest_mod.write_manifest(target)
    assert Path(written).exists(), "the module directory was not created"


def test_the_written_manifest_carries_every_exposed_tool(tmp_path):
    target = tmp_path / "modules" / "atrade" / "manifest.toml"
    text = Path(manifest_mod.write_manifest(target)).read_text()
    missing = [t for t in manifest_mod.EXPOSED_TOOLS
               if f'name = "{t}"' not in text]
    assert not missing, f"declared in EXPOSED_TOOLS but not written: {missing}"
