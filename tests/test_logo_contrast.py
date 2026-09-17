"""A logo tile must never render its logo invisible.

Intel's mark is near-black. Drawn on the island's dark tile it disappears
entirely -- the slot reads as empty. Nike, Apple's own mark and a good share of
industrials have the same problem, and inverting the whole pill for them is
worse: the island stops looking like one object.

The fix is per-tile: measure the logo's own ink, then pick the tile behind it.
"""
import io
from pathlib import Path

import pytest

from aethelark_trade.engine.logos import (
    DARK_TILE,
    LIGHT_TILE,
    ink_luminance,
    tile_for,
)

LOGO_DIR = Path.home() / ".aethelark" / "logos"


def solid(rgba, size=64):
    from PIL import Image
    im = Image.new("RGBA", (size, size), rgba)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def with_transparent_margin(rgba, ink=20, size=64):
    """Ink in the middle, transparent everywhere else -- the real shape of a
    trimmed logo PNG."""
    from PIL import Image
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    patch = Image.new("RGBA", (ink, ink), rgba)
    im.paste(patch, ((size - ink) // 2, (size - ink) // 2))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_luminance_of_black_ink_is_low():
    assert ink_luminance(solid((0, 0, 0, 255))) < 0.1


def test_luminance_of_white_ink_is_high():
    assert ink_luminance(solid((255, 255, 255, 255))) > 0.9


def test_transparent_pixels_are_ignored():
    """A trimmed logo is mostly transparent. Counting those as black would
    make every logo look dark and flip every tile."""
    assert ink_luminance(with_transparent_margin((255, 255, 255, 255))) > 0.9


def test_a_fully_transparent_image_has_no_measurable_ink():
    assert ink_luminance(solid((0, 0, 0, 0))) is None


def test_dark_logo_gets_the_light_tile():
    assert tile_for(solid((17, 17, 17, 255))) == LIGHT_TILE


def test_light_logo_keeps_the_dark_tile():
    assert tile_for(solid((240, 240, 240, 255))) == DARK_TILE


def test_mid_tone_logo_keeps_the_dark_tile():
    """Most brand colours are mid-tone and read fine on dark; only genuinely
    near-black ink needs the swap."""
    assert tile_for(solid((0, 113, 197, 255))) == DARK_TILE      # Intel blue
    assert tile_for(solid((118, 185, 0, 255))) == DARK_TILE      # NVIDIA green


def test_unmeasurable_logo_falls_back_to_the_dark_tile():
    assert tile_for(solid((0, 0, 0, 0))) == DARK_TILE


def test_corrupt_bytes_do_not_raise():
    assert tile_for(b"not a png") == DARK_TILE
    assert ink_luminance(b"not a png") is None


@pytest.mark.skipif(not (LOGO_DIR / "INTC.png").exists(),
                    reason="logo harvest has not run")
def test_intel_is_detected_as_dark_on_the_real_asset():
    """The reported case, on the actual downloaded file."""
    assert tile_for((LOGO_DIR / "INTC.png").read_bytes()) == LIGHT_TILE


@pytest.mark.skipif(not (LOGO_DIR / "NVDA.png").exists(),
                    reason="logo harvest has not run")
def test_nvidia_keeps_the_dark_tile_on_the_real_asset():
    assert tile_for((LOGO_DIR / "NVDA.png").read_bytes()) == DARK_TILE
