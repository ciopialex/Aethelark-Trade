"""Install the module socket by COPYING the shipped manifest, never by
re-rendering it.

`manifest.render_manifest()` builds its TOML from `EXPOSED_TOOLS` and emits no
`[island]` section at all. The manifest the bus actually loads carries eight
`[island]` tables describing the Dynamic Island cards, and none of them are
derivable from code — they are hand-tuned sizes, `shows` field lists and card
transitions. Rendering over an installed manifest therefore deletes the whole
card configuration silently, and the module keeps working well enough that
nobody notices until an answer comes back with no card.

Measured 2026-09-14 on the manifest shipped here:

    render_manifest()          116 lines,   0 [island] tables
    aethelark_trade/module/    268 lines,   8 [island] tables

So registration is a file copy. `render_manifest()` is still the schema's
executable specification and the tests still check it, but nothing wires it to
a path that already exists.

The bus scans `~/.aethelark/modules` before its own bundled directory and keeps
the first manifest per key, preferring `<key>/manifest.toml` over `<key>.toml`
(the sorted-glob rule in Space-Eagle's loader). That is the path written here.
"""

from __future__ import annotations

import shutil
from pathlib import Path

MODULE_KEY = "atrade"
DEFAULT_MODULES_DIR = Path.home() / ".aethelark" / "modules"


class RegistrationError(RuntimeError):
    """Raised rather than leaving a half-installed module socket behind."""


def shipped_module_dir() -> Path:
    """The `module/` payload as installed, wheel or editable checkout alike."""
    from importlib.resources import files

    path = Path(str(files("aethelark_trade") / "module"))
    if not (path / "manifest.toml").is_file():
        raise RegistrationError(
            f"packaged manifest missing at {path / 'manifest.toml'} — the wheel "
            f"was built without aethelark_trade/module (check the build config)")
    return path


def register(modules_dir: Path | str | None = None) -> Path:
    """Copy the shipped manifest and island assets into the modules directory.

    Returns the manifest path the bus will load. Existing files are replaced;
    the copy is verified before it is reported as installed.
    """
    import tomllib

    source = shipped_module_dir()
    target_dir = Path(modules_dir) if modules_dir else DEFAULT_MODULES_DIR
    target = target_dir / MODULE_KEY
    target.mkdir(parents=True, exist_ok=True)

    manifest_src = source / "manifest.toml"
    body = manifest_src.read_text(encoding="utf-8")

    # Parse before writing: a manifest that fails to load takes the module
    # offline with one confusing log line at the eagle's next boot.
    parsed = tomllib.loads(body)
    if not parsed.get("key") or not parsed.get("binary"):
        raise RegistrationError("shipped manifest is missing key/binary")
    tools = parsed.get("tools") or ()
    if not tools:
        raise RegistrationError("shipped manifest declares no tools")

    (target / "manifest.toml").write_text(body, encoding="utf-8")

    island_src = source / "island"
    copied_assets: list[str] = []
    if island_src.is_dir():
        island_dst = target / "island"
        island_dst.mkdir(exist_ok=True)
        for asset in sorted(island_src.iterdir()):
            if asset.is_file():
                shutil.copy2(asset, island_dst / asset.name)
                copied_assets.append(asset.name)

    # Every card file the manifest names must exist next to it, or the host
    # draws an empty card and logs nothing useful.
    for card in (parsed.get("island") or {}).get("cards", {}).values():
        name = card.get("file")
        if name and not (target / "island" / name).is_file():
            raise RegistrationError(
                f"manifest names island card {name!r} but it was not shipped")

    return target / "manifest.toml"


def registration_summary(manifest_path: Path) -> tuple[list[str], int]:
    """Tool names and island-card count of an installed manifest."""
    import tomllib

    parsed = tomllib.loads(Path(manifest_path).read_text(encoding="utf-8"))
    names = [t["name"] for t in (parsed.get("tools") or ())]
    cards = len((parsed.get("island") or {}).get("cards", {}))
    return names, cards
