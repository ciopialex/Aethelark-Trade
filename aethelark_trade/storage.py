"""SQLite storage wrapper (formerly JSON storage).

All storage now goes to the unified aethelark.db SQLite database.
Function signatures are maintained for backward compatibility.
"""

import json
from datetime import date
from typing import TypedDict, Optional

from aethelark_trade.parser import InsiderTransaction
from aethelark_trade.db import get_db, AETHELARK_DIR

DEFAULT_DATA_DIR = AETHELARK_DIR


def _parse_date(date_str: str | None) -> date | None:
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        return None


def filing_exists(ticker: str, accession_number: str) -> bool:
    """Check if a filing already exists in storage."""
    # We check if any transaction exists for this accession
    db = get_db()
    row = db.execute(
        "SELECT 1 FROM insider_transactions WHERE ticker = ? AND accession_number = ? LIMIT 1",
        (ticker.upper(), accession_number)
    ).fetchone()
    return row is not None


def save_transactions(transactions: list[InsiderTransaction]) -> int:
    """Save transactions to SQLite. Returns count of new rows saved."""
    saved_count = 0
    if not transactions:
        return 0
        
    db = get_db()
    for tx in transactions:
        try:
            db.execute(
                """INSERT OR IGNORE INTO insider_transactions (
                    ticker, filing_date, accession_number, transaction_date, 
                    transaction_code, acquired_disposed, shares, price_per_share, 
                    shares_owned_after, ownership_nature, insider_name, insider_cik, 
                    insider_title, is_director, is_officer, is_ten_percent_owner, 
                    is_other, is_ceo, is_cfo, footnotes_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    tx.issuer_ticker,
                    tx.filing_date.isoformat(),
                    tx.accession_number,
                    tx.transaction_date.isoformat() if tx.transaction_date else None,
                    tx.transaction_code,
                    tx.acquired_disposed,
                    tx.shares,
                    tx.price_per_share,
                    tx.shares_owned_after,
                    tx.ownership_nature,
                    tx.insider_name,
                    tx.insider_cik,
                    tx.insider_title,
                    tx.is_director,
                    tx.is_officer,
                    tx.is_ten_percent_owner,
                    tx.is_other,
                    tx.is_ceo,
                    tx.is_cfo,
                    json.dumps(tx.footnotes) if tx.footnotes else "[]"
                )
            )
            if db.execute("SELECT changes()").fetchone()[0] > 0:
                saved_count += 1
        except Exception:
            pass
            
    db.commit()
    return saved_count


class TransactionList(list):
    """List of transactions carrying data age metadata so readers never mistake
    stale filings for fresh ones."""
    def __init__(self, items=(), latest_filing_date: str | None = None,
                 latest_transaction_date: str | None = None,
                 age_days: float | None = None, is_stale: bool = False):
        super().__init__(items)
        self.latest_filing_date = latest_filing_date
        self.latest_transaction_date = latest_transaction_date
        self.age_days = age_days
        self.is_stale = is_stale


def get_insider_store_age(ticker: str | None = None) -> dict:
    """Return age metrics for stored insider transactions.

    Returns dict with:
      - 'count': int
      - 'latest_filing_date': str | None
      - 'latest_transaction_date': str | None
      - 'age_days': float | None
      - 'is_stale': bool (True if latest_filing_date > 7 days ago)
    """
    db = get_db()
    if ticker:
        row = db.execute(
            "SELECT COUNT(*) as cnt, MAX(filing_date) as max_f, MAX(transaction_date) as max_t "
            "FROM insider_transactions WHERE ticker = ?",
            (ticker.upper(),)
        ).fetchone()
    else:
        row = db.execute(
            "SELECT COUNT(*) as cnt, MAX(filing_date) as max_f, MAX(transaction_date) as max_t "
            "FROM insider_transactions"
        ).fetchone()

    cnt = row["cnt"] if row else 0
    max_f = row["max_f"] if row else None
    max_t = row["max_t"] if row else None

    age_days = None
    is_stale = False
    if max_f:
        try:
            latest_dt = date.fromisoformat(max_f)
            age_days = round((date.today() - latest_dt).total_seconds() / 86400.0, 1)
            is_stale = age_days > 7.0
        except Exception:
            pass

    return {
        "count": cnt,
        "latest_filing_date": max_f,
        "latest_transaction_date": max_t,
        "age_days": age_days,
        "is_stale": is_stale,
    }


def load_transactions(ticker: str, limit: int | None = None, data_dir=None) -> TransactionList:
    """Load transactions from SQLite, sorted by date (newest first)."""
    db = get_db()
    query = "SELECT * FROM insider_transactions WHERE ticker = ? ORDER BY filing_date DESC, id DESC"
    if limit:
        query += f" LIMIT {limit}"
        
    rows = db.execute(query, (ticker.upper(),)).fetchall()
    
    transactions = []
    for row in rows:
        try:
            # Reconstruct the InsiderTransaction
            tx = InsiderTransaction(
                filing_date=_parse_date(row["filing_date"]),
                accession_number=row["accession_number"],
                issuer_name="",  # We don't save issuer_name to DB
                issuer_ticker=row["ticker"],
                issuer_cik="",
                insider_name=row["insider_name"],
                insider_cik=row["insider_cik"],
                insider_title=row["insider_title"],
                is_director=bool(row["is_director"]),
                is_officer=bool(row["is_officer"]),
                is_ten_percent_owner=bool(row["is_ten_percent_owner"]),
                is_other=bool(row["is_other"]),
                is_ceo=bool(row["is_ceo"]),
                is_cfo=bool(row["is_cfo"]),
                transaction_date=_parse_date(row["transaction_date"]),
                transaction_code=row["transaction_code"],
                acquired_disposed=row["acquired_disposed"],
                shares=row["shares"],
                price_per_share=row["price_per_share"],
                shares_owned_after=row["shares_owned_after"],
                ownership_nature=row["ownership_nature"],
                footnotes=json.loads(row["footnotes_json"]) if row["footnotes_json"] else []
            )
            transactions.append(tx)
        except Exception:
            continue
            
    age_meta = get_insider_store_age(ticker)
    return TransactionList(
        transactions,
        latest_filing_date=age_meta["latest_filing_date"],
        latest_transaction_date=age_meta["latest_transaction_date"],
        age_days=age_meta["age_days"],
        is_stale=age_meta["is_stale"],
    )


def get_existing_accessions(ticker: str) -> set[str]:
    """Get set of accession numbers already in storage."""
    db = get_db()
    rows = db.execute(
        "SELECT DISTINCT accession_number FROM insider_transactions WHERE ticker = ?", 
        (ticker.upper(),)
    ).fetchall()
    return {r[0] for r in rows}


# Form 144 storage (planned sales)

def save_form144_filings(filings: list) -> int:
    """Save Form 144 filings to SQLite. Returns count saved."""
    from aethelark_trade.form144 import Form144Filing
    
    saved = 0
    if not filings:
        return 0
        
    db = get_db()
    for filing in filings:
        if not isinstance(filing, Form144Filing):
            continue
            
        try:
            db.execute(
                """INSERT OR IGNORE INTO form144_filings (
                    ticker, filing_date, accession_number, seller_name, 
                    seller_title, shares_to_sell, approximate_sale_date, is_10b5_1_plan
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    filing.issuer_ticker,
                    filing.filing_date.isoformat(),
                    filing.accession_number,
                    filing.seller_name,
                    filing.seller_title,
                    filing.shares_to_sell,
                    filing.approximate_sale_date.isoformat() if filing.approximate_sale_date else None,
                    filing.is_10b5_1_plan
                )
            )
            if db.execute("SELECT changes()").fetchone()[0] > 0:
                saved += 1
        except Exception:
            pass
            
    db.commit()
    return saved


def load_form144_filings(ticker: str, limit: int | None = None) -> list:
    """Load Form 144 filings from SQLite."""
    from aethelark_trade.form144 import Form144Filing
    
    db = get_db()
    query = "SELECT * FROM form144_filings WHERE ticker = ? ORDER BY filing_date DESC, id DESC"
    if limit:
        query += f" LIMIT {limit}"
        
    rows = db.execute(query, (ticker.upper(),)).fetchall()
    
    filings = []
    for row in rows:
        try:
            f = Form144Filing(
                filing_date=_parse_date(row["filing_date"]),
                accession_number=row["accession_number"],
                issuer_name="",
                issuer_ticker=row["ticker"],
                issuer_cik="",
                seller_name=row["seller_name"],
                seller_cik="",
                seller_title=row["seller_title"],
                seller_address="",
                is_director=False,
                is_officer=False,
                is_ten_percent_owner=False,
                is_affiliate=False,
                shares_to_sell=row["shares_to_sell"],
                security_class="",
                approximate_sale_date=_parse_date(row["approximate_sale_date"]),
                earliest_sale_date=None,
                broker_name=None,
                broker_address=None,
                is_10b5_1_plan=bool(row["is_10b5_1_plan"])
            )
            filings.append(f)
        except Exception:
            continue
            
    return filings


# Schedule 13D/13G storage (smart money / 5%+ owners)

def save_schedule13_filings(filings: list) -> int:
    """Save Schedule 13D/13G filings to SQLite. Returns count saved."""
    from aethelark_trade.schedule13 import Schedule13Filing
    
    saved = 0
    if not filings:
        return 0
        
    db = get_db()
    for filing in filings:
        if not isinstance(filing, Schedule13Filing):
            continue
            
        try:
            db.execute(
                """INSERT OR IGNORE INTO schedule13_filings (
                    ticker, filing_date, accession_number, form_type, 
                    filer_name, shares_owned, percent_of_class, is_activist, purpose
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    filing.issuer_ticker,
                    filing.filing_date.isoformat(),
                    filing.accession_number,
                    filing.form_type,
                    filing.filer_name,
                    filing.shares_owned,
                    filing.percent_of_class,
                    filing.is_activist,
                    filing.purpose
                )
            )
            if db.execute("SELECT changes()").fetchone()[0] > 0:
                saved += 1
        except Exception:
            pass
            
    db.commit()
    return saved


def load_schedule13_filings(ticker: str, limit: int | None = None) -> list:
    """Load Schedule 13D/13G filings from SQLite."""
    from aethelark_trade.schedule13 import Schedule13Filing
    
    db = get_db()
    query = "SELECT * FROM schedule13_filings WHERE ticker = ? ORDER BY filing_date DESC, id DESC"
    if limit:
        query += f" LIMIT {limit}"
        
    rows = db.execute(query, (ticker.upper(),)).fetchall()
    
    filings = []
    for row in rows:
        try:
            f = Schedule13Filing(
                filing_date=_parse_date(row["filing_date"]),
                accession_number=row["accession_number"],
                form_type=row["form_type"],
                issuer_name="",
                issuer_ticker=row["ticker"],
                issuer_cik="",
                issuer_cusip="",
                filer_name=row["filer_name"],
                filer_cik="",
                filer_address="",
                shares_owned=row["shares_owned"],
                percent_of_class=row["percent_of_class"],
                sole_voting_power=0.0,
                shared_voting_power=0.0,
                sole_dispositive_power=0.0,
                shared_dispositive_power=0.0,
                is_activist=bool(row["is_activist"]),
                purpose=row["purpose"] or ""
            )
            filings.append(f)
        except Exception:
            continue
            
    return filings


# Event Signals (8-K, M&A)

class EventSignal(TypedDict):
    filing_date: str # ISO format
    form_type: str
    accession_number: str
    primary_document: str
    headline: str
    description: str
    link: str
    details: Optional[str] # e.g. "Subject: Maxwell"

def save_event_signals(ticker: str, signals: list[EventSignal]) -> int:
    """Save event signals to SQLite's event_log table. Returns count saved."""
    saved_count = 0
    if not signals:
        return 0
        
    db = get_db()
    for s in signals:
        try:
            db.execute(
                """INSERT OR IGNORE INTO event_log (
                    ticker, event_time, event_type, headline, description, source, raw_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticker.upper(),
                    s["filing_date"],
                    s["form_type"],
                    s["headline"],
                    s["description"],
                    s["link"],
                    json.dumps(s)
                )
            )
            # SQLite doesn't have an easy UPSERT that returns row counts safely without extra work,
            # but we can check if it inserted:
            if db.execute("SELECT changes()").fetchone()[0] > 0:
                saved_count += 1
            else:
                # If ignored, it might be an update case, but we don't strictly need to update details here
                pass
        except Exception:
            pass
            
    db.commit()
    return saved_count

def load_event_signals(ticker: str, limit: int | None = None) -> list[EventSignal]:
    """Load event signals from SQLite."""
    db = get_db()
    query = "SELECT raw_data FROM event_log WHERE ticker = ? ORDER BY event_time DESC, id DESC"
    if limit:
        query += f" LIMIT {limit}"
        
    rows = db.execute(query, (ticker.upper(),)).fetchall()
    
    signals = []
    for row in rows:
        try:
            if row["raw_data"]:
                signals.append(json.loads(row["raw_data"]))
        except Exception:
            pass
            
    return signals


# Governance Signals (Proxy)

class GovernanceSignal(TypedDict):
    filing_date: str
    accession_number: str
    link: str
    has_comp_table: bool
    has_delinquency: bool
    description: str

def save_governance_signals(ticker: str, signals: list[GovernanceSignal]) -> int:
    """Save governance signals to SQLite. Returns count saved."""
    saved = 0
    if not signals:
        return 0
        
    db = get_db()
    for s in signals:
        try:
            db.execute(
                """INSERT OR IGNORE INTO governance_signals (
                    ticker, filing_date, accession_number, has_comp_table, has_delinquency, description
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    ticker.upper(),
                    s["filing_date"],
                    s["accession_number"],
                    s["has_comp_table"],
                    s["has_delinquency"],
                    s["description"]
                )
            )
            if db.execute("SELECT changes()").fetchone()[0] > 0:
                saved += 1
        except Exception:
            pass
            
    db.commit()
    return saved

def load_governance_signals(ticker: str, limit: int | None = None) -> list[GovernanceSignal]:
    """Load governance signals from SQLite."""
    db = get_db()
    query = "SELECT * FROM governance_signals WHERE ticker = ? ORDER BY filing_date DESC, id DESC"
    if limit:
        query += f" LIMIT {limit}"
        
    rows = db.execute(query, (ticker.upper(),)).fetchall()
    
    signals = []
    for row in rows:
        signals.append({
            "filing_date": row["filing_date"],
            "accession_number": row["accession_number"],
            "link": "",
            "has_comp_table": bool(row["has_comp_table"]),
            "has_delinquency": bool(row["has_delinquency"]),
            "description": row["description"]
        })
    return signals

# Supply Chain Graph Edges
def save_supply_chain_edges(ticker: str, edges: list) -> int:
    """Save supply chain edges to SQLite."""
    if not edges:
        return 0
        
    db = get_db()
    # Replace existing edges for this ticker
    db.execute("DELETE FROM supply_chain_edges WHERE source_ticker = ?", (ticker.upper(),))
    
    saved = 0
    for edge in edges:
        try:
            db.execute(
                """INSERT INTO supply_chain_edges (
                    source_ticker, target_ticker, relationship_type,
                    weight, period_end, source_accession, attested, confidence,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    edge.get("source", ticker.upper()),
                    edge.get("target", ""),
                    edge.get("type") or edge.get("relationship_type", "supplier"),
                    float(edge.get("weight", 1.0)),
                    str(edge.get("period_end", "")),
                    str(edge.get("source_accession", "")),
                    1 if edge.get("attested", False) else 0,
                    float(edge.get("confidence", 1.0)),
                    json.dumps(edge)
                )
            )
            saved += 1
        except Exception:
            pass
            
    db.commit()
    return saved

def load_supply_chain_edges(ticker: str) -> list | None:
    """Load supply chain edges from SQLite."""
    db = get_db()
    rows = db.execute(
        "SELECT metadata_json FROM supply_chain_edges WHERE source_ticker = ?", 
        (ticker.upper(),)
    ).fetchall()
    
    if not rows:
        return None
        
    edges = []
    for row in rows:
        try:
            edges.append(json.loads(row["metadata_json"]))
        except Exception:
            pass
    return edges

def get_consumers(ticker: str) -> list[str]:
    """Find all tickers that depend on this ticker as a supplier."""
    db = get_db()
    rows = db.execute(
        "SELECT source_ticker FROM supply_chain_edges WHERE target_ticker = ?", 
        (ticker.upper(),)
    ).fetchall()
    return [r[0] for r in rows]

# News Signals
class NewsSignal(TypedDict):
    published: str
    source: str
    title: str
    link: str
    analysis: dict

def save_news_signals(ticker: str, signals: list[NewsSignal]) -> int:
    """Save news signals to SQLite. Returns count saved."""
    saved = 0
    if not signals:
        return 0
        
    db = get_db()
    for s in signals:
        try:
            db.execute(
                """INSERT OR IGNORE INTO news_signals (
                    ticker, published, source, title, link, analysis_json
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    ticker.upper(),
                    s["published"],
                    s["source"],
                    s["title"],
                    s["link"],
                    json.dumps(s.get("analysis", {}))
                )
            )
            if db.execute("SELECT changes()").fetchone()[0] > 0:
                saved += 1
        except Exception:
            pass
            
    db.commit()
    return saved

def load_news_signals(ticker: str, limit: int | None = None) -> list[NewsSignal]:
    """Load news signals from SQLite."""
    db = get_db()
    query = "SELECT * FROM news_signals WHERE ticker = ? ORDER BY published DESC, id DESC"
    if limit:
        query += f" LIMIT {limit}"
        
    rows = db.execute(query, (ticker.upper(),)).fetchall()
    
    signals = []
    for row in rows:
        try:
            signals.append({
                "published": row["published"],
                "source": row["source"],
                "title": row["title"],
                "link": row["link"],
                "analysis": json.loads(row["analysis_json"]) if row["analysis_json"] else {}
            })
        except Exception:
            continue
    return signals

def load_circuit_role(ticker: str) -> str:
    """Fetch the thermodynamic circuit role for a ticker."""
    db = get_db()
    row = db.execute("SELECT circuit_role FROM watchlist WHERE ticker = ?", (ticker.upper(),)).fetchone()
    if row and row["circuit_role"]:
        return row["circuit_role"]
    return "Unknown / Neutral Component"
