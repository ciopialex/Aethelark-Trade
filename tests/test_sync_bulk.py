"""Slice 3 -- bulk companyfacts ingestion into Polars/Parquet.

The real archive is ~500MB of the same per-company JSON documents already in
tests/fixtures, so ingestion is exercised against a genuine zip built from
those verbatim SEC files.
"""
import json
import zipfile
from pathlib import Path

import pytest

from aethelark_trade.engine.bulk import (
    BULK_CONCEPTS,
    COMPANYFACTS_ZIP_URL,
    ingest_companyfacts_zip,
    load_snapshot_from_parquet,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def bulk_zip(tmp_path_factory):
    """A real companyfacts.zip in miniature: verbatim SEC JSON, zip-compressed
    with the CIK##########.json naming the live archive uses."""
    path = tmp_path_factory.mktemp("bulk") / "companyfacts.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for ticker, cik in (("NVDA", "0001045810"), ("INTC", "0000050863")):
            zf.writestr(f"CIK{cik}.json",
                        (FIXTURES / f"companyfacts_{ticker}.json").read_text())
    return path


@pytest.fixture(scope="module")
def parquet(bulk_zip, tmp_path_factory):
    out = tmp_path_factory.mktemp("out") / "companyfacts.parquet"
    ingest_companyfacts_zip(bulk_zip, out)
    return out


def test_archive_url_matches_the_documented_source():
    assert COMPANYFACTS_ZIP_URL.endswith("companyfacts.zip")
    assert "sec.gov" in COMPANYFACTS_ZIP_URL


def test_ingest_reports_what_it_loaded(bulk_zip, tmp_path):
    stats = ingest_companyfacts_zip(bulk_zip, tmp_path / "out.parquet")
    assert stats["companies"] == 2
    assert stats["facts"] > 0
    assert stats["elapsed_seconds"] >= 0


def test_ingest_writes_a_readable_parquet(parquet):
    import polars as pl
    frame = pl.read_parquet(parquet)
    assert frame.height > 0
    assert set(frame.columns) >= {"cik", "concept", "period_end", "val", "form", "fp"}


def test_only_the_concepts_layer_one_needs_are_kept(parquet):
    import polars as pl
    frame = pl.read_parquet(parquet)
    assert set(frame["concept"].unique()).issubset(set(BULK_CONCEPTS))


def test_both_companies_survive_the_round_trip(parquet):
    import polars as pl
    frame = pl.read_parquet(parquet)
    assert set(frame["cik"].unique()) == {"0001045810", "0000050863"}


def test_snapshot_from_parquet_matches_the_live_api_extraction(parquet):
    """The bulk path must produce the same Layer 1 numbers as the live
    companyfacts API, or fundamentals would silently change with the source."""
    from aethelark_trade.engine.layers.fundamentals import extract_fundamentals

    live = extract_fundamentals(
        json.loads((FIXTURES / "companyfacts_NVDA.json").read_text())
    )
    bulk = load_snapshot_from_parquet("0001045810", parquet)

    assert bulk.fiscal_year_end == live.fiscal_year_end
    assert bulk.revenue == pytest.approx(live.revenue)
    assert bulk.capex == pytest.approx(live.capex)
    assert bulk.gross_margin == pytest.approx(live.gross_margin)
    assert bulk.roic == pytest.approx(live.roic)


def test_unknown_cik_returns_an_empty_snapshot(parquet):
    assert load_snapshot_from_parquet("9999999999", parquet).revenue is None


def test_ingestion_is_fast(bulk_zip, tmp_path):
    """FACTS.md budgets <5s for the full archive; two companies must be
    a rounding error against that."""
    stats = ingest_companyfacts_zip(bulk_zip, tmp_path / "speed.parquet")
    assert stats["elapsed_seconds"] < 5.0


# --- memory-bounded ingestion -------------------------------------------
def test_batched_ingest_produces_identical_output(bulk_zip, tmp_path):
    """The full archive is 1.4GB across ~19k companies; accumulating every row
    before writing pushes RSS past 1.5GB. Batching must not change the result."""
    import polars as pl

    whole = tmp_path / "whole.parquet"
    batched = tmp_path / "batched.parquet"
    ingest_companyfacts_zip(bulk_zip, whole, batch_size=10_000_000)
    ingest_companyfacts_zip(bulk_zip, batched, batch_size=25)

    a = pl.read_parquet(whole).sort(["cik", "concept", "period_end"])
    b = pl.read_parquet(batched).sort(["cik", "concept", "period_end"])
    assert a.height == b.height
    assert a.equals(b)


def test_batched_ingest_reports_the_same_stats(bulk_zip, tmp_path):
    whole = ingest_companyfacts_zip(bulk_zip, tmp_path / "w.parquet",
                                    batch_size=10_000_000)
    batched = ingest_companyfacts_zip(bulk_zip, tmp_path / "b.parquet", batch_size=25)
    assert whole["companies"] == batched["companies"]
    assert whole["facts"] == batched["facts"]


def test_batched_snapshot_still_matches_the_live_api(bulk_zip, tmp_path):
    from aethelark_trade.engine.layers.fundamentals import extract_fundamentals

    out = tmp_path / "batched.parquet"
    ingest_companyfacts_zip(bulk_zip, out, batch_size=25)

    live = extract_fundamentals(
        json.loads((FIXTURES / "companyfacts_NVDA.json").read_text())
    )
    bulk = load_snapshot_from_parquet("0001045810", out)
    assert bulk.revenue == pytest.approx(live.revenue)
    assert bulk.capex == pytest.approx(live.capex)
