"""Slice 4 -- Space-Eagle Module Bus socket manifest.

The schema here is the one core/module_bus/manifest.py actually parses, which
is NOT the one sketched in ROADMAP.md. The roadmap describes `name`/`command`/
`tools = [...]`; the loader requires top-level `key`, `binary` and `output`,
plus an array-of-tables `[[tools]]` carrying `argv`. A manifest in the roadmap
shape is rejected at manifest.py:183 and the module silently stops existing --
observed in the boot log as `a3d.toml ignored: no 'key'`.

Tool names reach the model module-qualified (`atrade_analyze`), because main.py
holds every tool in one flat namespace where a bare `portfolio` would collide.
"""

from pathlib import Path

#: Where the eagle will actually read it from.
#:
#: Space-Eagle's loader scans a modules directory with three globs and keeps the
#: first manifest per module key:
#:
#:     sorted(set(glob("*.toml") + glob("*/manifest.toml") + glob("*/*.toml")))
#:
#: Path sorting puts the directory entry first, so `atrade/manifest.toml` beats
#: `atrade.toml` at the root. Writing to the root meant that regenerating the
#: manifest changed nothing whenever an older copy existed in the directory --
#: measured 2026-09-05, when an added `owners` tool never reached the bus.
#: a3d and alaw both use the directory form; this was the odd one out.
DEFAULT_MANIFEST_PATH = (
    Path.home() / ".aethelark" / "modules" / "atrade" / "manifest.toml")

MODULE_KEY = "atrade"
MODULE_BINARY = "atrade"
MODULE_DESCRIPTION = (
    "Aethelark-Trade: 7-Layer Equity Intelligence & Relative Asymmetry Engine"
)
OUTPUT_MODE = "json"

# Types the loader accepts (manifest.py VALID_TYPES).
VALID_PARAM_TYPES = ("STRING", "INTEGER", "NUMBER", "BOOLEAN", "ARRAY", "OBJECT")

# Reserved by the bus for the confirmation handshake; declaring it raises.
RESERVED_PARAM = "confirm_token"

EXPOSED_TOOLS: tuple[str, ...] = (
    "quote", "analyze", "governance", "compare", "leaderboard",
    "insider", "watchlist", "watch", "unwatch", "portfolio", "owners",
)

TICKER_PARAM = {
    "type": "STRING",
    "description": "Stock ticker symbol (e.g. NVDA, AAPL, TSLA)",
    "required": True,
}

# Descriptions are written for a voice model choosing between ~45 tools from a
# spoken sentence, so each one carries the phrasings people actually say rather
# than the feature's name. The costly ones say so: routing "what's NVDA doing"
# to analyze instead of quote is the difference between a HUD and a spinner.
TOOL_SPECS: dict[str, dict] = {
    "quote": {
        "description": (
            "FAST current price and today's move for one company. Use this for "
            "'what's Nvidia doing', 'how's Tesla today', 'what's the price of "
            "Apple', 'is AMD up or down'. Prefer this over analyze whenever the "
            "question is only about price or today's move — it answers instantly."
        ),
        "argv": ["quote", "{ticker}", "--json"],
        "params": {"ticker": TICKER_PARAM},
    },
    "analyze": {
        "description": (
            "SLOW, thorough 7-layer verdict on whether a company is worth owning: "
            "fundamentals, insiders, sector alpha, news, supply chain. Use for "
            "'is Nvidia a good buy', 'tell me about Palantir', 'should I invest "
            "in Tesla', 'what do you think of AMD'. Do NOT use for a plain price "
            "question — use quote for that."
        ),
        "argv": ["analyze", "{ticker}", "--json"],
        "params": {"ticker": TICKER_PARAM},
    },
    "compare": {
        "description": (
            "Head-to-head 7-layer relative asymmetry between two companies. Use "
            "for 'X or Y', 'which is better', 'X versus Y'."
        ),
        "argv": ["compare", "{ticker_a}", "{ticker_b}", "--json"],
        "params": {
            "ticker_a": {"type": "STRING",
                         "description": "First ticker symbol", "required": True},
            "ticker_b": {"type": "STRING",
                         "description": "Second ticker symbol", "required": True},
        },
    },
    "owners": {
        "description": (
            "Who holds five percent or more of a company, and which of them "
            "are activists pushing for change rather than passive holders. "
            "From SEC Schedule 13D and 13G filings. Use for 'who owns Nvidia', "
            "'who are the big holders', 'is anyone activist in this', 'who has "
            "a stake'. This is who owns it, NOT whether to buy it -- use "
            "analyze for that."
        ),
        "argv": ["owners", "{ticker}", "--json"],
        "params": {"ticker": TICKER_PARAM},
    },
    "governance": {
        "description": (
            "Whether a company's CEO is paid in line with what shareholders "
            "actually earned, from the SEC proxy statement. Use for 'is the CEO "
            "overpaid', 'how much does Intel's CEO make', 'is management "
            "aligned', 'do they treat shareholders well', 'what about the boss'."
        ),
        "argv": ["governance", "{ticker}", "--json"],
        "params": {"ticker": TICKER_PARAM},
    },
    "watchlist": {
        "description": (
            "The user's own followed companies with live prices. Use for 'how's "
            "my watchlist', 'show my stocks', 'what am I following', 'how are my "
            "picks doing'. This is their personal list, not the whole market."
        ),
        "argv": ["watchlist", "--json"],
        "params": {},
    },
    "watch": {
        "description": (
            "Start following a company. Use for 'add Palantir to my watchlist', "
            "'follow Nvidia', 'keep an eye on ASML', 'track Tesla for me'."
        ),
        "argv": ["watch", "{ticker}", "--json"],
        "params": {"ticker": TICKER_PARAM},
    },
    "unwatch": {
        "description": (
            "Stop following a company. Use for 'remove Intel from my watchlist', "
            "'unfollow Tesla', 'stop tracking AMD', 'drop Qualcomm'."
        ),
        "argv": ["unwatch", "{ticker}", "--json"],
        "params": {"ticker": TICKER_PARAM},
    },
    "leaderboard": {
        "description": (
            "Rank companies by how attractive they look right now: quality, "
            "cheapness and insider buying combined. Use for 'what should I buy', "
            "'what looks good right now', 'best opportunities', 'any bargains', "
            "'where's the value'."
        ),
        "argv": ["leaderboard", "--json"],
        "params": {},
    },
    "insider": {
        "description": (
            "Latest SEC Form 4 and Form 144 insider transaction ledger for one "
            "company. Use for 'are insiders buying X', 'who is selling X'."
        ),
        "argv": ["insider", "{ticker}", "--json"],
        "params": {"ticker": dict(TICKER_PARAM,
                                  description="Stock ticker symbol")},
    },
    "portfolio": {
        "description": (
            "Live Alpaca account equity, cash, buying power and open positions. "
            "Use for 'how is my portfolio', 'what do I own', 'my positions'."
        ),
        "argv": ["portfolio", "--json"],
        "params": {},
    },
}

EMITTED_EVENTS: tuple[str, ...] = (
    "form4_whale_buy",
    "8k_material_event",
    "liar_filter_warning",
    "relative_outlier_leader",
    "scoring_progress",
)


class ManifestError(ValueError):
    """Raised rather than writing a file the Module Bus would reject."""


def _toml_string(value: str) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_array(values) -> str:
    return "[" + ", ".join(_toml_string(v) for v in values) + "]"


def _validate() -> None:
    """Fail loudly here rather than silently at the eagle's next boot."""
    for name in EXPOSED_TOOLS:
        spec = TOOL_SPECS.get(name)
        if spec is None:
            raise ManifestError(f"{name}: exposed but has no spec")

        argv = spec["argv"]
        if not argv or argv[0] != name:
            raise ManifestError(f"{name}: argv must start with the subcommand")

        params = spec.get("params") or {}
        if RESERVED_PARAM in params:
            raise ManifestError(
                f"{name}: {RESERVED_PARAM!r} is reserved by the bus")

        placeholders = {a.strip("{}") for a in argv if a.startswith("{")}
        if placeholders != set(params):
            raise ManifestError(
                f"{name}: argv placeholders {sorted(placeholders)} do not match "
                f"declared params {sorted(params)}")

        for pname, pspec in params.items():
            if pspec["type"] not in VALID_PARAM_TYPES:
                raise ManifestError(
                    f"{name}.{pname}: type {pspec['type']!r} not in "
                    f"{VALID_PARAM_TYPES}")


def render_manifest() -> str:
    """Render the manifest TOML in the Module Bus's schema."""
    _validate()

    lines = [
        "# Aethelark-Trade module socket for the Space-Eagle Module Bus.",
        "# Rendered from EXPOSED_TOOLS. This form carries NO [island] section:",
        "# do not write it over an installed manifest. See engine/register.py.",
        "#",
        "# Schema per Space-Eagle/core/module_bus/manifest.py:",
        "#   top level -> key, binary, description, output",
        "#   tools     -> [[tools]] array of tables with name/description/argv",
        "",
        f"key = {_toml_string(MODULE_KEY)}",
        f"binary = {_toml_string(MODULE_BINARY)}",
        f"description = {_toml_string(MODULE_DESCRIPTION)}",
        f"output = {_toml_string(OUTPUT_MODE)}",
        "",
    ]

    for name in EXPOSED_TOOLS:
        spec = TOOL_SPECS[name]
        lines += [
            "[[tools]]",
            f"name = {_toml_string(name)}",
            f"description = {_toml_string(spec['description'])}",
            f"argv = {_toml_array(spec['argv'])}",
        ]
        for pname, pspec in (spec.get("params") or {}).items():
            lines += [
                "",
                f"[tools.params.{pname}]",
                f"type = {_toml_string(pspec['type'])}",
                f"description = {_toml_string(pspec['description'])}",
                f"required = {'true' if pspec.get('required') else 'false'}",
            ]
        lines.append("")

    lines += [
        "# Dynamic Island events this module emits (docs/UI_STATES.md).",
        "[events]",
        f"emits = {_toml_array(EMITTED_EVENTS)}",
        f"listener = {_toml_string('atrade listen')}",
        "",
    ]

    return "\n".join(lines)


def write_manifest(path=None) -> Path:
    """Write the manifest, refusing to emit anything the bus would reject."""
    import tomllib

    body = render_manifest()

    # Parse our own output before it touches disk: a manifest that fails to
    # load takes the whole module offline with one confusing log line.
    parsed = tomllib.loads(body)
    if not parsed.get("key") or not parsed.get("binary"):
        raise ManifestError("generated manifest is missing key/binary")
    if len(parsed.get("tools") or ()) != len(EXPOSED_TOOLS):
        raise ManifestError("generated manifest lost tools during rendering")

    target = Path(path) if path else DEFAULT_MANIFEST_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target
