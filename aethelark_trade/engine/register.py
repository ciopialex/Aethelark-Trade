"""Install the module socket by COPYING the shipped manifest.

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

    # Cards with no template draw nothing, and the host logs nothing useful.
    # Checked before anything is written, so a failure leaves no half-installed
    # module behind. Every card is a stage of this one file.
    island = parsed.get("island") or {}
    if island.get("cards"):
        template = Path(str(island.get("template") or "template.html")).name
        if not (source / "island" / template).is_file():
            raise RegistrationError(
                f"manifest declares island cards but their template "
                f"{template!r} was not shipped")

    (target / "manifest.toml").write_text(body, encoding="utf-8")

    island_src = source / "island"
    if island_src.is_dir():
        island_dst = target / "island"
        island_dst.mkdir(exist_ok=True)
        for asset in sorted(island_src.iterdir()):
            if asset.is_file():
                shutil.copy2(asset, island_dst / asset.name)

    return target / "manifest.toml"


def registration_summary(manifest_path: Path) -> tuple[list[str], int]:
    """Tool names and island-card count of an installed manifest."""
    import tomllib

    parsed = tomllib.loads(Path(manifest_path).read_text(encoding="utf-8"))
    names = [t["name"] for t in (parsed.get("tools") or ())]
    cards = len((parsed.get("island") or {}).get("cards", {}))
    return names, cards
