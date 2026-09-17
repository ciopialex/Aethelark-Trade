"""Ticker logo harvesting for the Dynamic Island.

Two hard problems with company logos, and one of them is solved for us:

1. *Which company is this ticker?* Most logo providers key on a domain, so you
   need a ticker -> domain map you have to maintain. FinancialModelingPrep's
   image-stock endpoint keys on the **ticker itself**, so that problem vanishes.
2. *Is it there?* Coverage is never complete -- recent listings, dual-class
   lines and foreign issuers miss. Every consumer keeps a monogram fallback.

Logos are trademarks. Using them to identify the company they belong to is how
every finance app works, but that is a decision to make consciously rather than
one to inherit from a helper function.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("aethelark.logos")

LOGO_URL = "https://financialmodelingprep.com/image-stock/{ticker}.png"
from aethelark_trade.engine.useragent import sec_user_agent

USER_AGENT = sec_user_agent("logo fetch")

LOGO_DIR = Path.home() / ".aethelark" / "logos"

# The island renders marks at 32px; 64 covers HiDPI without carrying 250px
# source art for 600 names.
TARGET_PX = 64

# Anything smaller is an error page or a spacer, not artwork.
MIN_BYTES = 400

# GICS sector -> monogram tint, used when no logo exists. Hues are pulled from
# the island's own state palette so a fallback never looks foreign to the HUD.
SECTOR_TINT = {
    "Information Technology": "#3B82F6",
    "Communication Services": "#4B9BFF",
    "Consumer Discretionary": "#FF9100",
    "Consumer Staples": "#FF5A5A",
    "Health Care": "#00E5FF",
    "Financials": "#00FFA3",
    "Industrials": "#C8C8D0",
    "Energy": "#FFC24B",
    "Materials": "#B98CFF",
    "Real Estate": "#8FD9A8",
    "Utilities": "#D4AF37",
}
DEFAULT_TINT = "#C8C8D0"


@dataclass(frozen=True)
class Constituent:
    ticker: str
    name: str
    sector: str
    cik: str


def read_constituents(path) -> list[Constituent]:
    """Parse the S&P constituents CSV (Symbol, Security, GICS Sector, …, CIK).

    Carries the sector and CIK too: the sector drives the fallback tint, and
    the CIK removes an SEC round trip we currently make per ticker.
    """
    import csv

    out: list[Constituent] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            symbol = (row.get("Symbol") or "").strip().upper()
            if not symbol:
                continue
            out.append(Constituent(
                ticker=symbol,
                name=(row.get("Security") or "").strip(),
                sector=(row.get("GICS Sector") or "").strip(),
                cik=str(row.get("CIK") or "").strip().zfill(10),
            ))
    return out


def monogram(ticker: str) -> str:
    """Two glyphs, the way the island draws a missing logo."""
    cleaned = "".join(c for c in ticker.upper() if c.isalnum())
    return (cleaned[:2] or "?").ljust(2, "·")


def tint_for(sector: str) -> str:
    return SECTOR_TINT.get(sector, DEFAULT_TINT)


def normalise(raw: bytes, size: int = TARGET_PX) -> bytes:
    """Square, trim transparent margins, downscale, re-encode as PNG.

    Sources arrive between 100px and 250px with inconsistent padding. Trimming
    to the ink and re-padding to a common box is what stops a row of marks from
    looking like it was assembled by hand.
    """
    import io

    from PIL import Image

    im = Image.open(io.BytesIO(raw)).convert("RGBA")

    bbox = im.getbbox()
    if bbox:
        im = im.crop(bbox)

    side = max(im.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2))

    canvas = canvas.resize((size, size), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def fetch_logo(client, ticker: str) -> bytes | None:
    """One logo, or None when the provider has no artwork for this ticker."""
    try:
        response = client.get(LOGO_URL.format(ticker=ticker))
    except Exception as exc:
        logger.debug("logo fetch failed for %s: %s", ticker, exc)
        return None

    if response.status_code != 200 or len(response.content) < MIN_BYTES:
        return None
    if not response.headers.get("content-type", "").startswith("image"):
        return None
    return response.content


def harvest(tickers, out_dir=None, size: int = TARGET_PX, progress=None) -> dict:
    """Download and normalise logos for `tickers`. Returns a summary."""
    import httpx

    out_dir = Path(out_dir) if out_dir else LOGO_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    saved = missing = skipped = 0
    total_bytes = 0
    absent: list[str] = []

    with httpx.Client(headers={"User-Agent": USER_AGENT},
                      timeout=20.0, follow_redirects=True) as client:
        for i, ticker in enumerate(tickers, start=1):
            target = out_dir / f"{ticker}.png"
            if target.exists():
                skipped += 1
                total_bytes += target.stat().st_size
                continue

            raw = fetch_logo(client, ticker)
            if raw is None:
                missing += 1
                absent.append(ticker)
            else:
                try:
                    data = normalise(raw, size)
                except Exception as exc:
                    logger.debug("normalise failed for %s: %s", ticker, exc)
                    missing += 1
                    absent.append(ticker)
                else:
                    target.write_bytes(data)
                    saved += 1
                    total_bytes += len(data)

            if progress:
                progress(i, len(tickers), ticker)

    return {
        "saved": saved,
        "skipped": skipped,
        "missing": missing,
        "absent": absent,
        "dir": str(out_dir),
        "bytes": total_bytes,
    }


# --- tile contrast --------------------------------------------------------
# The island's default logo tile. Most brand marks are mid-tone or bright and
# sit on it fine.
DARK_TILE = "dark"

# Used only for near-black ink. Inverting the whole pill instead would break
# the island's read as a single object; only the 34px tile changes.
LIGHT_TILE = "light"

# Below this mean luminance the ink is dark enough to vanish on the dark tile.
# Set low deliberately: Intel's near-black wordmark must flip, NVIDIA's green
# and Intel's own blue must not.
DARK_INK_THRESHOLD = 0.22

# Pixels fainter than this are the transparent surround of a trimmed logo, not
# ink. Counting them would drag every measurement toward black.
ALPHA_FLOOR = 40


def ink_luminance(png_bytes: bytes) -> float | None:
    """Mean perceptual luminance of a logo's actual ink, in 0..1.

    Transparent pixels are excluded: a trimmed logo is mostly empty, and
    averaging that emptiness in would report every mark as dark.
    Returns None when there is no measurable ink.
    """
    import io

    try:
        from PIL import Image

        im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    except Exception:
        return None

    import numpy as np

    pixels = np.asarray(im, dtype=np.float32)
    alpha = pixels[..., 3]
    ink = alpha >= ALPHA_FLOOR
    if not ink.any():
        return None

    # Rec. 601 luma — cheap and close enough for a threshold decision.
    luma = (0.299 * pixels[..., 0]
            + 0.587 * pixels[..., 1]
            + 0.114 * pixels[..., 2]) / 255.0
    return float(luma[ink].mean())


def tile_for(png_bytes: bytes) -> str:
    """Which tile background keeps this logo visible."""
    luminance = ink_luminance(png_bytes)
    if luminance is None:
        return DARK_TILE
    return LIGHT_TILE if luminance < DARK_INK_THRESHOLD else DARK_TILE


def build_manifest(logo_dir=None) -> dict:
    """{ticker: {"tile": …, "luminance": …}} for every harvested logo.

    Computed once at harvest time so the HUD never measures pixels on its
    paint path.
    """
    import json

    logo_dir = Path(logo_dir) if logo_dir else LOGO_DIR
    manifest: dict[str, dict] = {}

    for path in sorted(logo_dir.glob("*.png")):
        raw = path.read_bytes()
        luminance = ink_luminance(raw)
        manifest[path.stem] = {
            "tile": tile_for(raw),
            "luminance": None if luminance is None else round(luminance, 4),
        }

    (logo_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest
