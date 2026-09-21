# Working in Aethelark-Trade

This is the Aethelark-Trade module for the Space-Eagle Module Bus. It exposes
one binary, `atrade`, and eleven tools the eagle calls with `--json`.

## Read the code. This file does not tell you what works.

    python3 -m pytest tests/ -q      # what passes
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
  The default contact is the project URL. An operator sets `ATRADE_SEC_CONTACT`
  to their own address. It used to be one hardcoded personal email, which is
  correct for one machine and wrong the moment somebody else installs it:
  their traffic then identifies as the author, and their rate-limit abuse
  lands on the author's name.
- **The rate limiter is machine-wide, deliberately.** `engine/ratelimit.py`
  holds an `flock` on `~/.aethelark/sec_ratelimit.lock`. The code shows you
  the lock; it cannot tell you why. It used to pace on a class attribute, so
  the guarantee stopped at the process boundary — and running two atrade
  processes at once is a normal configuration, not a stress test. Four
  concurrent processes peaked at 36 requests in a one-second window and 429s
  were observed. After the change: 3 live processes, 7.55 req/s, smallest gap
  0.140 s, no 429s. Do not "simplify" this back into the process.

### Registration copies the manifest. It does not regenerate it.

`atrade register` copies `aethelark_trade/module/manifest.toml` and
`module/island/` into `~/.aethelark/modules/atrade/`.

It must never call `manifest.render_manifest()` against an installed path.
The renderer builds its TOML from `EXPOSED_TOOLS` and emits **no `[island]`
section**; the shipped manifest carries **eight `[island]` tables** — card
sizes, `shows` field lists, transitions — that exist nowhere in code. Measured
2026-09-14: rendered 116 lines / 0 island tables, shipped 268 / 8. The old
`install-module` command regenerated on every run and silently deleted the
card configuration, and the module kept answering with a blank card.

`render_manifest()` still exists as the schema's executable spec and the
tests' fixture. `tests/test_register_keeps_the_island_cards.py` fails if
anyone rewires registration back to it.

The bus scans `~/.aethelark/modules` **before** its own bundled directory and
keeps the first manifest per key, preferring `<key>/manifest.toml` over
`<key>.toml` (a sorted-glob rule). Writing the other spelling installs a
manifest the eagle will never read — that has happened once already.

### The rest

- **`portfolio` needs your own Alpaca keys.** See `.env.example`, and install
  `pip install 'aethelark-trade[portfolio]'`. Without them that one tool
  raises; the other ten are unaffected. It only reads — `get_account()` and
  `get_all_positions()`, no orders.
- **No `FINNHUB_API_KEY` is required.** Absent one, Layer 3 scores tone with
  the keyless lexicon rather than the vendor signal.
  `engine/layers/news_velocity.py` says so at the top of the file.
- **`polars` is an extra, not a dependency.** Only `atrade sync-bulk` imports
  it, and only inside the function body. Nothing among the eleven tools
  touches it.
- **Banks report no gross profit.** A layer that ranks on it will rank
  financials as though they were failing. This is accounting, not a bug.
- **`constituents.csv` ships inside the package** at
  `aethelark_trade/data/constituents.csv`, because `pip install` has no repo
  root to read. `ticker_registry._constituents_paths()` prefers a checkout or
  cwd copy over the shipped seed, so a local override still wins.
- **The curated universe beats SEC's own file for nine names.** Swept
  2026-09-04: `company_tickers.json` resolves XOM to a successor registrant
  with no annual filings, and omits six names outright. `constituents.csv`
  carries a CIK column and wins for tracked names. The XOM case will invert
  once the holding company files its first 10-K — a data update, not a code
  change, but a real expiry.

### Layer 7 has no data source here, and the "7 layers" claim is thin

Measured 2026-09-21 across NVDA, JPM, KO and AMT: coverage came back 0.76 every
time, and it was always the same two layers missing. `0.24 + 0.10 + 0.16 + 0.26`
is exactly the weight of layers 1, 2, 4 and 5.

- **Layer 7 never fires for anyone.** It scores `supply_chain_edges`, and
  nothing in this module writes that table -- the loader was a collector in the
  private repository. So 11% of the composite is renormalised away on every
  query.
- **Layer 3 fires about a quarter of the time**, because there is no
  `FINNHUB_API_KEY` and the keyless lexicon often finds nothing classifiable.
- **Layer 4 is absent for REITs** -- no sector ETF is mapped for them.
- **Layer 1 degrades to bare ROIC for banks AND REITs**, not just banks.

`engine/concentration.py` and `engine/counterparty.py` are the XBRL extractors
that would feed layer 7, plus `sec_client.get_annual_filings()` and
`find_xbrl_instance()`. They work -- measured on NVDA's 10-K, 14 facts -- but
wiring them is not enough, for two reasons found by measurement:

1. **Filers anonymise the counterparty.** NVDA discloses "CustomerOneMember
   25%", not a name. `counterparty.py` can only resolve named ones.
2. **`health` is uncomputable without a name.** Layer 7 scores momentum-derived
   health; there is no share price for "Customer One". Every edge would carry
   `health=0.5` and the layer would return exactly 50 for everyone -- a
   constant at 11% weight, which is worse than honest absence because it fakes
   coverage.

Also: 6 of 12 sampled companies disclose nothing at all, and the facts that do
come back mix geographic and credit-risk members with customer ones (PG reads
100%, JPM 95% -- both artefacts). Any future loader has to filter by member
type first. Until then the layer reporting "No supply-chain dependencies
mapped" is the correct behaviour, not a bug to paper over.

### The voice is generated, not the summaries

`engine/speech.py` turns a scorecard into something a person would say, and
`analyze --json` carries it as `spoken`. The layer `summary` fields stay dense
because the card wants them dense.

Absence is the most-used sentence this engine has -- two layers missing on a
typical company -- so every layer carries its own phrasing for having nothing.
"No classifiable news sentiment" reads as a broken sensor; "there's been
nothing much in the news about them lately" does not.
`tests/test_it_talks_like_a_person.py` fails if telemetry reaches the voice.

### Governance makes a claim about a named person

`decode_governance_summary()` can return "Management is looting the ship"
attached to a real CEO's name, so the arithmetic under it gets a higher bar
than the rest of the engine.

It was wrong. SEC's "Compensation Actually Paid" is mark-to-market and is
legitimately negative in a down year. `xbrl.py` divided the percent change by
the *signed* denominator, and a negative over a negative flips the sign.
Measured on INTC 2026-09-21: pay went -$78.5M -> -$82.2M, a 4.7% CUT, reported
as +4.7%, which tripped the looting branch. `governance.py:_pct_change` had
always used `abs(oldest)`, so the JSON field said -4.7 while the spoken
sentence said "rose". Both now divide by an absolute value.

`VERDICTS` also called itself a closed set and was not one: SHARED PAIN,
RISING TIDE SKEPTICISM and INEFFICIENT GROWTH were emitted and unlisted, so
they classified as UNKNOWN and the card drew no governance label. FAIR EXCHANGE
was listed and emitted by nothing.
`tests/test_governance_does_not_libel_anyone.py` holds both.

### Logos

`aethelark_trade/module/island/logos.json` carries all 507 names (503
constituents plus 4 ETFs/extras), harvested 2026-09-21, 2.46 MB. It shipped
with 22 -- ModuleShop's showcase list -- so 96% of the universe drew a
monogram. Rebuild with `engine/logos.py:harvest()` then re-encode; it needs the
`logos` extra (Pillow, numpy) and no API key.

Note that **Space-Eagle's `web/pill.html` inlines its own `_logos` object and
does not read this file.** Until the harness reads the module's copy, shipping
a complete bundle here changes nothing on screen.

## Dangling citations are expected

`engine/layers/macro.py`, `engine/layers/fundamentals.py` and
`engine/layers/supply_chain.py` open with comments correcting a `docs/FACTS.md`
that is not in this repo, and `engine/manifest.py` says its schema is "NOT the
one sketched in ROADMAP.md". Those documents do not exist here and are not
coming. The comments were left alone deliberately: the code had to carry a
correction to its documentation, which tells you which of the two was wrong.
Treat them as a note that a claim once had a written source. Do not recreate
the document.
