"""Test atrade listen command atomic Dynamic Island writing and prioritization."""
import json
from unittest.mock import patch

from typer.testing import CliRunner

from aethelark_trade.engine.cli import app
from aethelark_trade.engine.events import (
    eight_k_material_event,
    form4_whale_buy,
)
from aethelark_trade.engine.sec_stream import FilingEvent

runner = CliRunner()


def test_listen_writes_dynamic_island_atomically_and_prioritizes(tmp_path):
    island_file = tmp_path / "atrade_dynamic_island.json"

    # Mock stream to yield one filing
    fake_filing = FilingEvent(
        form_type="8-K",
        company="Intel Corp",
        cik="0000050863",
        role="Issuer",
        accession="0000050863-26-000001",
        filed=None,
        updated="2026-08-19T10:00:00Z",
        link="",
    )

    # Mock watcher.handle to return two events landing together:
    # 8-K material event (prio 80) and Form 4 whale buy (prio 90)
    event_8k = eight_k_material_event("INTC", "1.01", "Strategic contract")
    event_whale = form4_whale_buy("NVDA", "CEO", 10_000_000.0, 90)

    with patch("aethelark_trade.engine.sec_stream.stream", return_value=[fake_filing]), \
         patch("aethelark_trade.engine.watch.EventWatcher.handle", return_value=[event_8k, event_whale]):

        result = runner.invoke(app, [
            "listen",
            "--cycles", "1",
            "--island-file", str(island_file),
        ])

        assert result.exit_code == 0
        # Verify stdout echo contains both payloads
        assert "8k_material_event" in result.stdout
        assert "form4_whale_buy" in result.stdout

        # Verify island file was written atomically and contains the higher-priority event (latest wins)
        assert island_file.exists()
        saved = json.loads(island_file.read_text(encoding="utf-8"))
        assert saved["event"] == "form4_whale_buy"
        assert saved["ticker"] == "NVDA"
