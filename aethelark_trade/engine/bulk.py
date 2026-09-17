"""Slice 3 -- bulk XBRL fundamentals hydrator.

Downloads the SEC's companyfacts archive once and flattens it into Parquet, so
Layer 1 can be served for the whole market with zero live API calls. Only the
concepts Layer 1 actually resolves are kept, which turns a ~500MB archive of
deeply nested JSON into a narrow columnar table.
"""

import json
import logging
import time
import zipfile
from pathlib import Path

from aethelark_trade.engine.layers.fundamentals import (
    ANNUAL_FORMS,
    CONCEPTS,
    MIN_ANNUAL_DAYS,
    FundamentalSnapshot,
)

logger = logging.getLogger("aethelark.bulk")

COMPANYFACTS_ZIP_URL = (
    "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
)
from aethelark_trade.engine.useragent import require_sec_contact, sec_user_agent

USER_AGENT = sec_user_agent()

DEFAULT_PARQUET = Path.home() / ".aethelark" / "companyfacts.parquet"

# Flattening every us-gaap concept would produce hundreds of millions of rows;
# Layer 1 only ever resolves this set.
BULK_CONCEPTS: tuple[str, ...] = tuple(
    concept for aliases in CONCEPTS.values() for concept in aliases
)

_SCHEMA = {
    "cik": str, "entity_name": str, "concept": str, "unit": str,
    "period_start": str, "period_end": str, "fy": int, "fp": str,
    "form": str, "val": float, "filed": str,
}


def _flatten_company(payload: dict) -> list[dict]:
    """One company's JSON -> annual fact rows for the tracked concepts."""
    cik = str(payload.get("cik", "")).zfill(10)
    name = payload.get("entityName", "")
    facts = payload.get("facts", {})
    gaap = dict(facts.get("us-gaap", {}))
    for k, v in facts.get("ifrs-full", {}).items():
        gaap.setdefault(k, v)

    rows: list[dict] = []
    for concept in BULK_CONCEPTS:
        node = gaap.get(concept)
        if not node:
            continue
        for unit, entries in node.get("units", {}).items():
            for e in entries:
                if e.get("form") not in ANNUAL_FORMS or e.get("fp") != "FY":
                    continue
                rows.append({
                    "cik": cik,
                    "entity_name": name,
                    "concept": concept,
                    "unit": unit,
                    "period_start": e.get("start") or "",
                    "period_end": e.get("end") or "",
                    "fy": int(e.get("fy") or 0),
                    "fp": e.get("fp") or "",
                    "form": e.get("form") or "",
                    "val": float(e.get("val") or 0.0),
                    "filed": e.get("filed") or "",
                })
    return rows


# Rows held in memory before a part file is flushed. The real archive yields
# roughly two million annual fact rows; holding them all as Python dicts pushes
# RSS past 1.5GB, so parts are written incrementally and merged at the end.
DEFAULT_BATCH_SIZE = 250_000


def ingest_companyfacts_zip(zip_path, parquet_path,
                            batch_size: int = DEFAULT_BATCH_SIZE,
                            progress=None) -> dict:
    """Flatten a companyfacts archive into a Parquet table.

    Memory is bounded by ``batch_size`` regardless of archive size: batches are
    flushed to numbered part files, then streamed into the final table.
    """
    import shutil
    import tempfile

    import polars as pl

    zip_path, parquet_path = Path(zip_path), Path(parquet_path)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    parts_dir = Path(tempfile.mkdtemp(prefix="aethelark_bulk_"))
    rows: list[dict] = []
    companies = facts = part_index = 0

    def flush():
        nonlocal rows, part_index, facts
        if not rows:
            return
        pl.DataFrame(rows, schema=_SCHEMA).write_parquet(
            parts_dir / f"part_{part_index:05d}.parquet", compression="zstd"
        )
        facts += len(rows)
        part_index += 1
        rows = []

    try:
        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.namelist():
                if not member.endswith(".json"):
                    continue
                try:
                    payload = json.loads(archive.read(member))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    logger.debug("skipping unreadable member %s", member)
                    continue
                companies += 1
                rows.extend(_flatten_company(payload))
                if len(rows) >= batch_size:
                    flush()
                if progress and companies % 1000 == 0:
                    progress(companies, facts + len(rows))
        flush()

        if part_index == 0:
            pl.DataFrame(schema=_SCHEMA).write_parquet(parquet_path, compression="zstd")
        else:
            (
                pl.scan_parquet(str(parts_dir / "part_*.parquet"))
                .sink_parquet(parquet_path, compression="zstd")
            )
    finally:
        shutil.rmtree(parts_dir, ignore_errors=True)

    elapsed = time.perf_counter() - started
    return {
        "companies": companies,
        "facts": facts,
        "parquet_path": str(parquet_path),
        "elapsed_seconds": round(elapsed, 3),
        "bytes": parquet_path.stat().st_size,
    }


def download_companyfacts_zip(destination, progress=None) -> Path:
    """Stream the archive to disk. One request; no rate-limit pressure."""
    import httpx

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with httpx.stream("GET", COMPANYFACTS_ZIP_URL,
                      headers={"User-Agent": sec_user_agent()},
                      timeout=600.0, follow_redirects=True) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length", 0))
        written = 0
        with open(destination, "wb") as handle:
            for chunk in response.iter_bytes(chunk_size=1 << 20):
                handle.write(chunk)
                written += len(chunk)
                if progress:
                    progress(written, total)
    return destination


def _annual_series(frame, field: str) -> dict[str, float]:
    """Merge a field's alias chain period-by-period, earlier aliases winning.

    Mirrors fundamentals._resolve exactly: resolving whole-series-first would
    let a concept the filer abandoned years ago shadow the one they use today.
    """
    merged: dict[str, float] = {}
    for concept in reversed(CONCEPTS[field]):
        subset = frame.filter(frame["concept"] == concept)
        for row in subset.iter_rows(named=True):
            start, end = row["period_start"], row["period_end"]
            if not end:
                continue
            if start:
                from datetime import date as _date
                try:
                    span = (_date.fromisoformat(end) - _date.fromisoformat(start)).days
                except ValueError:
                    continue
                if span < MIN_ANNUAL_DAYS:
                    continue
            merged[end] = row["val"]
    return merged


def load_snapshot_from_parquet(cik: str, parquet_path=None) -> FundamentalSnapshot:
    """Build a Layer 1 snapshot for one CIK straight from the bulk table."""
    import polars as pl
    from datetime import date

    path = Path(parquet_path) if parquet_path else DEFAULT_PARQUET
    if not path.exists():
        return FundamentalSnapshot()

    cik = str(cik).zfill(10)
    frame = pl.read_parquet(path).filter(pl.col("cik") == cik)
    if frame.height == 0:
        return FundamentalSnapshot()

    resolved = {field: _annual_series(frame, field) for field in CONCEPTS}
    revenue_series = resolved["revenue"]
    if not revenue_series:
        return FundamentalSnapshot()

    periods = sorted(revenue_series)
    latest = periods[-1]
    prior = periods[-2] if len(periods) > 1 else None

    def at(field: str, period: str | None):
        return resolved[field].get(period) if period else None

    gp = at("gross_profit", latest)
    if gp is None and at("revenue", latest) is not None and at("cost_of_revenue", latest) is not None:
        gp = at("revenue", latest) - at("cost_of_revenue", latest)

    prior_gp = at("gross_profit", prior)
    if prior_gp is None and at("revenue", prior) is not None and at("cost_of_revenue", prior) is not None:
        prior_gp = at("revenue", prior) - at("cost_of_revenue", prior)

    return FundamentalSnapshot(
        fiscal_year_end=date.fromisoformat(latest),
        revenue=at("revenue", latest),
        gross_profit=gp,
        operating_income=at("operating_income", latest),
        cash_from_operations=at("cash_from_operations", latest),
        capex=at("capex", latest),
        equity=at("equity", latest),
        long_term_debt=at("long_term_debt", latest),
        prior_revenue=at("revenue", prior),
        prior_gross_profit=prior_gp,
    )
