"""Layer 1 should prefer the local bulk table and fall back to the live API.

FACTS.md: the point of the weekly archive is 'zero live daytime API calls'.
"""
import json
import zipfile
from pathlib import Path

import pytest

from aethelark_trade.engine.bulk import ingest_companyfacts_zip
from aethelark_trade.engine.fetchers import load_fundamentals

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def parquet(tmp_path_factory):
    zip_path = tmp_path_factory.mktemp("z") / "cf.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("CIK0001045810.json",
                    (FIXTURES / "companyfacts_NVDA.json").read_text())
    out = tmp_path_factory.mktemp("p") / "cf.parquet"
    ingest_companyfacts_zip(zip_path, out)
    return out


def test_bulk_hit_avoids_the_network_entirely(parquet):
    def forbidden(*a, **kw):
        raise AssertionError("live SEC call made despite a bulk cache hit")

    snapshot, source = load_fundamentals(
        None, "NVDA", cik="0001045810", parquet_path=parquet, live_loader=forbidden
    )
    assert source == "bulk"
    assert snapshot.revenue == pytest.approx(215_938_000_000)


def test_a_bulk_miss_falls_back_to_the_live_api(parquet):
    live_payload = json.loads((FIXTURES / "companyfacts_INTC.json").read_text())
    calls = []

    def live_loader(client, ticker):
        calls.append(ticker)
        return live_payload

    snapshot, source = load_fundamentals(
        None, "INTC", cik="0000050863", parquet_path=parquet, live_loader=live_loader
    )
    assert source == "live"
    assert calls == ["INTC"]
    assert snapshot.revenue is not None


def test_missing_parquet_falls_back_without_error(tmp_path):
    live_payload = json.loads((FIXTURES / "companyfacts_NVDA.json").read_text())
    snapshot, source = load_fundamentals(
        None, "NVDA", cik="0001045810",
        parquet_path=tmp_path / "does_not_exist.parquet",
        live_loader=lambda c, t: live_payload,
    )
    assert source == "live"
    assert snapshot.revenue == pytest.approx(215_938_000_000)


def test_both_paths_agree(parquet):
    live_payload = json.loads((FIXTURES / "companyfacts_NVDA.json").read_text())
    bulk, _ = load_fundamentals(None, "NVDA", cik="0001045810",
                                parquet_path=parquet, live_loader=None)
    live, _ = load_fundamentals(None, "NVDA", cik="0001045810",
                                parquet_path=Path("/nonexistent.parquet"),
                                live_loader=lambda c, t: live_payload)
    assert bulk.revenue == live.revenue
    assert bulk.roic == pytest.approx(live.roic)
