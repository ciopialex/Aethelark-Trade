# Aethelark-Trade

Seven-layer equity intelligence over SEC filings and market data, exposed as a
single CLI — `atrade` — and as a module for the
[Space-Eagle](https://github.com/ciopialex/Project-Space-Eagle) Module Bus.

It answers questions like *is this company worth owning*, *are insiders
buying*, *is the CEO paid in line with what shareholders earned* — from primary
sources (SEC Form 4, Form 144, Schedule 13D/G, DEF 14A, XBRL company facts)
rather than from a vendor's summary of them.

## Install

```bash
uv pip install git+https://github.com/ciopialex/Aethelark-Trade
atrade register        # install the Space-Eagle module socket
```

`register` copies the module manifest and its Dynamic Island card assets into
`~/.aethelark/modules/atrade/`. It is a copy, never a regeneration — see
[CLAUDE.md](CLAUDE.md) for why that distinction matters.

Python 3.11+. No API key is needed for ten of the eleven tools.

## The eleven tools

Every one takes `--json` and prints a single JSON object on stdout.

| Command | What it answers |
|---|---|
| `atrade quote NVDA` | Current price and today's move. The fast path. |
| `atrade analyze NVDA` | Full 7-layer verdict, with the Liar Filter. |
| `atrade governance INTC` | Is CEO pay in line with shareholder return? |
| `atrade compare AMD NVDA` | Head-to-head relative asymmetry. |
| `atrade leaderboard` | Rank the universe: quality + cheapness + insider buying. |
| `atrade insider AMD --days 60` | Form 4 / Form 144 transaction ledger. |
| `atrade owners PLTR` | Who holds 5%+, and which of them are activists. |
| `atrade watchlist` | Your followed companies, with live prices. |
| `atrade watch TSLA` | Start following a company. |
| `atrade unwatch TSLA` | Stop following it. |
| `atrade portfolio` | Live account equity and open positions. Needs keys. |

Three more commands exist and are not exposed to the bus: `sync-bulk`
(hydrate local XBRL fundamentals from SEC's bulk archive, needs the `bulk`
extra), `listen` (SEC event stream), and `register`.

## The seven layers

Fundamentals · sector relativity · news velocity · macro · insider activity ·
geopolitics · supply chain. Each returns a score and a coverage figure, and a
layer that cannot be computed says so instead of scoring zero — `analyze`
reports which layers carried the verdict.

The **Liar Filter** cross-checks a company's stated numbers against what its
own filings imply, and flags the gaps.

## Configuration

Only `atrade portfolio` needs credentials:

```bash
uv pip install 'aethelark-trade[portfolio]'
cp .env.example .env     # then add your Alpaca keys
```

Paper-trading keys are fine and are what the default base URL selects. The
command only reads — it fetches account and positions, and places no orders.

## Rate limits — read this before pointing it at SEC

SEC allows **10 requests per second per IP** and requires a **declared,
contactable User-Agent**. Both are policy, not preference; exceeding the
first returns HTTP 429 and impersonating a browser is a violation.

This project paces itself with a **machine-wide** lock
(`~/.aethelark/sec_ratelimit.lock`), so several `atrade` processes running at
once still share one budget.

The User-Agent identifies the software and links back to this project. If you
are making sustained requests, declare yourself instead:

```bash
export ATRADE_SEC_CONTACT="you@example.com"
```

That way SEC's record of the traffic points at you rather than at this
repository. The module never impersonates a browser — that is a policy
violation, not a workaround.

## Development

```bash
git clone https://github.com/ciopialex/Aethelark-Trade
cd Aethelark-Trade
uv venv && uv pip install -e '.[dev]'
python -m pytest tests/ -q
```

## Not investment advice

This is a research tool. It reads public filings and market data and computes
scores from them. Those scores are opinions produced by code, they carry no
guarantee of accuracy or completeness, and nothing here is a recommendation to
buy or sell any security. Verify anything that matters against the filings
themselves.

## License

**Source-available, noncommercial.** [PolyForm Noncommercial 1.0.0](LICENSE).

This is not an open-source licence. The source is published so you can read it,
audit it, and verify what it sends to SEC — not so it can be resold.

- **Personal use, research, study, hobby projects** — permitted.
- **Charities, schools, public research, government** — permitted.
- **Any commercial use** — *not* granted here. That includes running it inside
  a business, or building a product or service on it. Contact the copyright
  holder for a commercial licence.
- **Attribution travels with the code.** If you pass on any part of it, you
  must pass on these terms and the `Required Notice` line with them. You may
  not present this work as your own.

Copyright 2026 Aethelark. All rights not expressly granted are reserved.
