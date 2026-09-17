"""SQLite database for Aethelark Trade telemetry persistence."""

import sqlite3
from pathlib import Path

AETHELARK_DIR = Path.home() / ".aethelark"
DB_PATH = AETHELARK_DIR / "aethelark.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    ticker TEXT PRIMARY KEY,
    name TEXT,
    sector TEXT,
    industry TEXT,
    circuit_role TEXT,
    added_at TEXT DEFAULT (datetime('now')),
    last_scanned TEXT
);

CREATE TABLE IF NOT EXISTS telemetry_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT UNIQUE NOT NULL,
    snapshot_time TEXT NOT NULL,
    nue_score REAL,
    earnings_modifier REAL,
    sector_gravity_base REAL,
    svi_vulnerability REAL,
    downside_probability INTEGER,
    verdict_label TEXT,
    buy_count INTEGER,
    sell_count INTEGER,
    net_purchase_ratio REAL DEFAULT 0.0,
    news_sentiment REAL DEFAULT 0.0,
    synthesis TEXT,
    layers_json TEXT,
    regime_probs_json TEXT,
    trust_weights_json TEXT,
    interaction_flags_json TEXT
);

CREATE TABLE IF NOT EXISTS regime_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES telemetry_snapshots(id),
    regime TEXT NOT NULL,
    probability REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS brier_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    prediction_time TEXT NOT NULL,
    predicted_regime TEXT,
    predicted_probability REAL,
    resolved_at TEXT,
    actual_regime TEXT,
    brier_score REAL
);

CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    event_time TEXT NOT NULL,
    event_type TEXT NOT NULL,
    headline TEXT,
    description TEXT,
    source TEXT,
    impact_score REAL DEFAULT 0.0,
    credibility_score REAL DEFAULT 0.0,
    raw_data TEXT
);

CREATE INDEX IF NOT EXISTS idx_snapshots_ticker ON telemetry_snapshots(ticker, snapshot_time DESC);
CREATE INDEX IF NOT EXISTS idx_regime_snapshot ON regime_history(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_events_ticker ON event_log(ticker, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_events_time ON event_log(event_time DESC);

CREATE TABLE IF NOT EXISTS simulation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    sim_start_date TEXT NOT NULL,
    sim_end_date TEXT NOT NULL,
    total_steps INTEGER DEFAULT 0,
    metrics_json TEXT,
    equity_curve_json TEXT,
    params_json TEXT
);

CREATE TABLE IF NOT EXISTS simulation_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES simulation_runs(id),
    sim_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    verdict_label TEXT,
    downside_probability INTEGER,
    net_purchase_ratio REAL,
    news_sentiment REAL,
    latent_health REAL,
    cascade_factor REAL,
    regime_probs_json TEXT,
    macro_bias REAL DEFAULT 0.0,
    price_at_prediction REAL,
    horizons_json TEXT
);

CREATE TABLE IF NOT EXISTS model_params (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    trigger TEXT NOT NULL,
    accumulation_buy_w REAL DEFAULT 0.5,
    accumulation_news_w REAL DEFAULT 0.2,
    accumulation_cascade_w REAL DEFAULT 0.2,
    accumulation_svi_w REAL DEFAULT 0.1,
    distribution_sell_w REAL DEFAULT 0.4,
    distribution_news_w REAL DEFAULT 0.2,
    distribution_cascade_w REAL DEFAULT 0.2,
    distribution_svi_w REAL DEFAULT 0.2,
    panic_sell_w REAL DEFAULT 0.4,
    panic_news_w REAL DEFAULT 0.2,
    panic_cascade_w REAL DEFAULT 0.2,
    panic_svi_w REAL DEFAULT 0.2,
    euphoria_buy_w REAL DEFAULT 0.4,
    euphoria_news_w REAL DEFAULT 0.3,
    euphoria_cascade_w REAL DEFAULT 0.2,
    euphoria_svi_w REAL DEFAULT 0.1,
    brier_score_at_creation REAL,
    sample_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS edge_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    sim_date TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    state_matrix_json TEXT NOT NULL,
    predicted_direction TEXT NOT NULL,
    actual_direction TEXT NOT NULL,
    return_pct REAL NOT NULL,
    is_failure INTEGER NOT NULL,
    error_magnitude REAL NOT NULL,
    auto_label TEXT
);

CREATE INDEX IF NOT EXISTS idx_sim_steps_run ON simulation_steps(run_id);
CREATE INDEX IF NOT EXISTS idx_sim_runs_ticker ON simulation_runs(ticker);
CREATE INDEX IF NOT EXISTS idx_model_params_time ON model_params(created_at DESC);

-- Phase 1: Database-First Ticker Profile Tables

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    adj_close REAL,
    UNIQUE(ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_price_ticker_date ON price_history(ticker, date DESC);

CREATE TABLE IF NOT EXISTS earnings_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    quarter_end TEXT NOT NULL,
    eps_actual REAL,
    eps_estimate REAL,
    surprise_pct REAL,
    revenue REAL,
    UNIQUE(ticker, quarter_end)
);
CREATE INDEX IF NOT EXISTS idx_earnings_ticker ON earnings_history(ticker, quarter_end DESC);

CREATE TABLE IF NOT EXISTS analyst_forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    firm TEXT,
    action TEXT,
    from_grade TEXT,
    to_grade TEXT,
    price_target REAL,
    UNIQUE(ticker, date, firm)
);
CREATE INDEX IF NOT EXISTS idx_analyst_ticker ON analyst_forecasts(ticker, date DESC);

CREATE TABLE IF NOT EXISTS institutional_holders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    holder_name TEXT NOT NULL,
    shares INTEGER,
    pct_held REAL,
    value REAL,
    snapshot_date TEXT NOT NULL,
    UNIQUE(ticker, holder_name, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_holders_ticker ON institutional_holders(ticker, snapshot_date DESC);

CREATE TABLE IF NOT EXISTS raw_materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    price_usd REAL,
    unit TEXT,
    source TEXT,
    UNIQUE(symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_materials_symbol ON raw_materials(symbol, date DESC);

CREATE TABLE IF NOT EXISTS macro_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    sp500_close REAL,
    nasdaq_close REAL,
    vix REAL,
    fed_funds_rate REAL,
    us10y_yield REAL,
    us3m_yield REAL,
    dxy REAL
);
CREATE INDEX IF NOT EXISTS idx_macro_date ON macro_snapshots(date DESC);

CREATE TABLE IF NOT EXISTS virtual_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    entry_time TEXT NOT NULL,
    exit_time TEXT,
    direction TEXT NOT NULL, -- 'LONG' or 'SHORT'
    entry_price REAL NOT NULL,
    exit_price REAL,
    quantity INTEGER NOT NULL,
    nue_at_entry REAL,
    status TEXT DEFAULT 'OPEN', -- 'OPEN', 'CLOSED'
    pnl_pct REAL
);

CREATE TABLE IF NOT EXISTS backfill_status (
    ticker TEXT NOT NULL,
    phase TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    last_updated TEXT,
    rows_fetched INTEGER DEFAULT 0,
    error_msg TEXT,
    PRIMARY KEY(ticker, phase)
);

-- Phase C: Replacing JSON Storage
CREATE TABLE IF NOT EXISTS insider_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    accession_number TEXT NOT NULL,
    transaction_date TEXT,
    transaction_code TEXT,
    acquired_disposed TEXT,
    shares REAL,
    price_per_share REAL,
    shares_owned_after REAL,
    ownership_nature TEXT,
    insider_name TEXT,
    insider_cik TEXT,
    insider_title TEXT,
    is_director BOOLEAN,
    is_officer BOOLEAN,
    is_ten_percent_owner BOOLEAN,
    is_other BOOLEAN,
    is_ceo BOOLEAN,
    is_cfo BOOLEAN,
    footnotes_json TEXT,
    UNIQUE(ticker, accession_number, transaction_code, shares, price_per_share)
);
CREATE INDEX IF NOT EXISTS idx_insider_tx_ticker ON insider_transactions(ticker, filing_date DESC);

CREATE TABLE IF NOT EXISTS form144_filings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    accession_number TEXT NOT NULL,
    seller_name TEXT,
    seller_title TEXT,
    shares_to_sell REAL,
    approximate_sale_date TEXT,
    is_10b5_1_plan BOOLEAN,
    UNIQUE(ticker, accession_number)
);
CREATE INDEX IF NOT EXISTS idx_form144_ticker ON form144_filings(ticker, filing_date DESC);

CREATE TABLE IF NOT EXISTS schedule13_filings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    accession_number TEXT NOT NULL,
    form_type TEXT,
    filer_name TEXT,
    shares_owned REAL,
    percent_of_class REAL,
    is_activist BOOLEAN,
    purpose TEXT,
    UNIQUE(ticker, accession_number)
);
CREATE INDEX IF NOT EXISTS idx_sched13_ticker ON schedule13_filings(ticker, filing_date DESC);

CREATE TABLE IF NOT EXISTS governance_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    accession_number TEXT NOT NULL,
    has_comp_table BOOLEAN,
    has_delinquency BOOLEAN,
    description TEXT,
    UNIQUE(ticker, accession_number)
);
CREATE INDEX IF NOT EXISTS idx_gov_ticker ON governance_signals(ticker, filing_date DESC);

CREATE TABLE IF NOT EXISTS supply_chain_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_ticker TEXT NOT NULL,
    target_ticker TEXT NOT NULL,
    relationship_type TEXT,
    weight REAL,
    period_end TEXT,
    source_accession TEXT,
    attested INTEGER DEFAULT 0,
    confidence REAL DEFAULT 1.0,
    metadata_json TEXT,
    UNIQUE(source_ticker, target_ticker, relationship_type, period_end)
);
CREATE INDEX IF NOT EXISTS idx_supply_source ON supply_chain_edges(source_ticker);

CREATE TABLE IF NOT EXISTS news_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    published TEXT NOT NULL,
    source TEXT,
    title TEXT,
    link TEXT NOT NULL,
    analysis_json TEXT,
    UNIQUE(ticker, link)
);
CREATE INDEX IF NOT EXISTS idx_news_ticker ON news_signals(ticker, published DESC);

-- Phase D: Paper Trading & Strategy Logging
CREATE TABLE IF NOT EXISTS live_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    order_id TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    entry_price REAL,
    entry_pulse REAL,
    entry_regime TEXT,
    take_profit_price REAL,
    stop_loss_price REAL,
    status TEXT NOT NULL,
    entered_at TEXT NOT NULL,
    closed_at TEXT,
    exit_price REAL,
    exit_reason TEXT,
    pnl REAL,
    trade_context TEXT,
    UNIQUE(order_id)
);
CREATE INDEX IF NOT EXISTS idx_live_trades_ticker ON live_trades(ticker, status);

-- Phase E: Full Decision Audit Log (every evaluation, not just trades)
CREATE TABLE IF NOT EXISTS decision_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ticker TEXT NOT NULL,
    pulse_score REAL,
    regime TEXT,
    l1_fund REAL,
    l2_macro REAL,
    l3_sent REAL,
    l4_sector REAL,
    l5_insider REAL,
    l6_geo REAL,
    l7_mat REAL,
    trust_w1 REAL, trust_w2 REAL, trust_w3 REAL,
    trust_w4 REAL, trust_w5 REAL, trust_w6 REAL, trust_w7 REAL,
    hard_blocked INTEGER DEFAULT 0,
    block_reasons TEXT,
    interaction_flags TEXT,
    size_scalar REAL,
    decision TEXT,
    price_at_eval REAL
);
CREATE INDEX IF NOT EXISTS idx_audit_ticker ON decision_audit(ticker, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_decision ON decision_audit(decision, timestamp DESC);

CREATE TABLE IF NOT EXISTS failed_trade_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    trade_id INTEGER NOT NULL,
    order_id TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    exit_date TEXT NOT NULL,
    pnl REAL NOT NULL,
    entry_telemetry_json TEXT NOT NULL,
    exit_telemetry_json TEXT NOT NULL,
    autopsy_synthesis TEXT,
    FOREIGN KEY(trade_id) REFERENCES live_trades(id)
);
CREATE INDEX IF NOT EXISTS idx_failed_trades ON failed_trade_logs(ticker, exit_date DESC);

-- PHASE 5: Neural Mesh & Kinetic Flow Modeling
CREATE TABLE IF NOT EXISTS adjacency_matrix (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_ticker TEXT NOT NULL,
    target_ticker TEXT NOT NULL,
    weight REAL NOT NULL,
    link_type TEXT NOT NULL, -- 'SUPPLIER', 'CUSTOMER', 'COMMODITY', 'HUMAN_OVERLAP', 'WHALE_OVERLAP'
    extracted_from TEXT,
    last_updated TEXT DEFAULT (datetime('now')),
    UNIQUE(source_ticker, target_ticker, link_type)
);
CREATE INDEX IF NOT EXISTS idx_adj_source ON adjacency_matrix(source_ticker);
CREATE INDEX IF NOT EXISTS idx_adj_target ON adjacency_matrix(target_ticker);

CREATE TABLE IF NOT EXISTS executive_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cik TEXT NOT NULL,
    name TEXT NOT NULL,
    ticker TEXT NOT NULL,
    role TEXT,
    joined_date TEXT,
    win_rate_score REAL DEFAULT 0.0,
    UNIQUE(cik, ticker)
);
CREATE INDEX IF NOT EXISTS idx_exec_cik ON executive_nodes(cik);

CREATE TABLE IF NOT EXISTS institutional_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    whale_id TEXT NOT NULL, -- 13F Filer CIK
    ticker TEXT NOT NULL,
    concentration_pct REAL NOT NULL, -- Portfolio %
    float_owned_pct REAL NOT NULL,   -- Market overlap trigger
    last_updated TEXT DEFAULT (datetime('now')),
    UNIQUE(whale_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_whale_id ON institutional_nodes(whale_id);
"""


def init_db():
    """Ensure the database and schema exist. Called once on startup."""
    AETHELARK_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    try:
        cur = conn.cursor()
        existing_cols = {r[1] for r in cur.execute("PRAGMA table_info(supply_chain_edges)").fetchall()}
        for col, ctype in [
            ("weight", "REAL"),
            ("period_end", "TEXT"),
            ("source_accession", "TEXT"),
            ("attested", "INTEGER DEFAULT 0"),
            ("confidence", "REAL DEFAULT 1.0"),
        ]:
            if col not in existing_cols:
                conn.execute(f"ALTER TABLE supply_chain_edges ADD COLUMN {col} {ctype}")
        conn.commit()
    except Exception:
        pass
    conn.close()

_SCHEMA_READY = False


def get_db() -> sqlite3.Connection:
    """Get a SQLite connection, creating the schema on first use.

    This used to say "assumes init_db was called" -- and nothing on the atrade
    path ever called it. Measured 2026-09-14 against a live install: the
    database held two tables, both created lazily elsewhere, and `atrade
    owners` died with `no such table: schedule13_filings` on every run. On a
    machine that has only ever pip-installed this module there is no other
    process to have created them at all.

    init_db() is CREATE TABLE IF NOT EXISTS throughout, so this is idempotent;
    the flag keeps it to one pass per process rather than one per connection.
    """
    global _SCHEMA_READY
    if not _SCHEMA_READY:
        init_db()
        _SCHEMA_READY = True

    conn = sqlite3.connect(str(DB_PATH), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
