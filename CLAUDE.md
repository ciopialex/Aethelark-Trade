# Working in Aethelark-Trade

This is the Aethelark-Trade module for the Space-Eagle Module Bus. It exposes
one binary, `atrade`, and eleven tools the eagle calls with `--json`.

## Read the code. This file does not tell you what works.

    .venv/bin/pytest tests/ -q       # what passes
    atrade --help                    # what commands exist
    atrade quote NVDA --json         # what a payload really contains

Read the keys that come back before believing any description of them.

## Facts that are not derivable from the source

None of this can be recovered by reading the code. The first section is
external policy and getting it wrong has consequences beyond this repo.

### The SEC will rate-limit or ban your IP if you get this wrong

- **10 requests per second, per IP.** Over it returns HTTP 429. SEC policy,
  not a tunable.
- **A declared, contactable User-Agent is required.** Impersonating a browser
  is a violation, not a trick. Every SEC caller builds its UA from
  `engine/useragent.py:sec_user_agent()` — do not re-declare a literal string
  in a new module; `tests/test_this_repo_is_publishable.py` fails if you do.
  The default contact is the project URL; operators may set `ATRADE_SEC_CONTACT`.
- **The rate limiter is strictly machine-wide.** `engine/ratelimit.py`
  holds an `flock` on `~/.aethelark/sec_ratelimit.lock` to guarantee compliance
  across multiple concurrent `atrade` processes. Never move this lock into process memory.

### Registration copies the manifest. It does not regenerate it.

`atrade register` copies `aethelark_trade/module/manifest.toml` and
`module/island/` into `~/.aethelark/modules/atrade/`. Edit the manifest by hand.
The bus reads `~/.aethelark/modules` and keeps the first manifest per key,
preferring `<key>/manifest.toml` over `<key>.toml` (a sorted-glob rule).

### The rest

- **`portfolio` needs your own Alpaca keys.** See `.env.example`, and install
  `pip install 'aethelark-trade[portfolio]'`. Without them that one tool
  raises; the other ten are unaffected. It only reads — `get_account()` and
  `get_all_positions()`, no orders.
- **No `FINNHUB_API_KEY` is required.** Absent one, Layer 3 scores tone with
  the keyless lexicon rather than the vendor signal (`engine/layers/news_velocity.py`).
- **`polars` is an extra, not a dependency.** Only `atrade sync-bulk` imports
  it inside the function body. The core eleven tools do not require it.
- **Banks report no gross profit.** Accounting metrics adapt accordingly.
- **`constituents.csv` ships inside the package** at
  `aethelark_trade/data/constituents.csv`. Local overrides take precedence.
- **The curated universe resolves tracked names via CIK mapping** in `constituents.csv`.

### Layer Coverage & Graceful Normalization

- **Honest Absence:** If a data source has no telemetry (e.g. unmapped supply chain dependencies or quiet news cycles), the layer honestly returns absence (`"No supply-chain dependencies mapped"`) rather than synthetic zeroes or placeholder scores.
- **Dynamic Renormalization:** Composite scores reweight dynamically across the actively populated layers.
- **Human Spoken Synthesis:** `engine/speech.py` translates scorecard summaries into conversational natural language. Telemetry jargon must never reach the voice layer (`tests/test_it_talks_like_a_person.py`).

### Governance Arithmetic Integrity

- **Mark-to-Market Executive Pay:** SEC "Compensation Actually Paid" can be negative in down years. Percent change calculations strictly divide by `abs(oldest)` to preserve sign correctness.
- **Verdicts:** Only emit classified verdicts verified by `tests/test_governance_does_not_libel_anyone.py`.

### Logos

`aethelark_trade/module/island/logos.json` carries all 507 names (503
constituents plus 4 ETFs/extras), harvested 2026-09-21, 2.46 MB. It shipped
with 22 -- ModuleShop's showcase list -- so 96% of the universe drew a
monogram. Rebuild with `engine/logos.py:harvest()` then re-encode; it needs the
`logos` extra (Pillow, numpy) and no API key.

Space-Eagle reads this file (`island_logos` in `aethelark_web.py`) and merges
it over the few logos `web/pill.html` ships with.
## Apple Human Interface Guidelines (HIG) Mandate

**All cards in `aethelark_trade/module/island/` must strictly conform to Apple HIG:**
- **Concentric Geometry (`ContainerRelativeShape`):** Range pills (`.range`), delta badges, and scorecards must satisfy $R_{\text{inner}} = \max(0, R_{\text{outer}} - P)$.
- **Tabular Numerals:** Apply `font-variant-numeric: tabular-nums` to all stock quotes, dollar values, percentage changes, and scores to prevent character jitter during streaming updates.
- **Dark Mode Materials:** Pitch-black background, 1px specular upper highlight, muted secondary typography.

## Active Architectural Blueprints
- **Opus 5.5 Master Mission Briefing & Physics Doctrine:** `../Space-Eagle/docs/OPUS_MISSION_BRIEFING.md`

