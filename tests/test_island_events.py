"""Slice 3 -- Dynamic Island event payloads, pinned to docs/UI_STATES.md."""
from datetime import date

import pytest

from aethelark_trade.engine.events import (
    eight_k_material_event,
    form4_whale_buy,
    liar_filter_warning,
    relative_outlier_leader,
    scoring_progress,
    should_emit_whale_buy,
    WHALE_BUY_THRESHOLD_USD,
)
from aethelark_trade.engine.sec_stream import POLL_INTERVAL_SECONDS, REQUESTS_PER_SECOND
from tests.test_liar_filter import tx

COMMON_KEYS = {"module", "event", "icon", "ticker", "title", "detail", "badge",
               "color", "duration_ms"}


# ------------------------------------------------------- rate limit contract
def test_thirty_second_poll_is_the_documented_load():
    """docs/FACTS.md: one request per 30s = 0.033 req/s, 0.33% of the ceiling."""
    assert POLL_INTERVAL_SECONDS == 30.0
    assert REQUESTS_PER_SECOND == pytest.approx(0.0333, abs=0.0005)


def test_stream_load_stays_far_inside_the_sec_ceiling():
    from aethelark_trade.engine.sec_stream import SEC_RATE_LIMIT
    forms = ("4", "8-K")
    assert len(forms) / POLL_INTERVAL_SECONDS < SEC_RATE_LIMIT * 0.01


# ------------------------------------------------------------ State A
def test_whale_buy_matches_the_documented_schema():
    payload = form4_whale_buy("NVDA", "CEO Jensen Huang", 12_500_000.0, score=88)
    assert set(payload) >= COMMON_KEYS
    assert payload["module"] == "trade"
    assert payload["event"] == "form4_whale_buy"
    assert payload["color"] == "#00FFA3"
    assert payload["duration_ms"] == 8000
    assert payload["icon"] == "🐋"
    assert payload["ticker"] == "NVDA"
    assert "$12.5M" in payload["badge"]
    assert "88" in payload["detail"]


def test_whale_buy_triggers_above_a_million_dollars():
    assert WHALE_BUY_THRESHOLD_USD == 1_000_000.0
    txs = [tx(title="Chief Executive Officer", code="P", shares=20_000,
              price=100.0, tx_date=date(2026, 8, 15))]      # $2.0M
    assert should_emit_whale_buy(txs, as_of=date(2026, 8, 19)) is True


def test_small_purchases_do_not_trigger_a_whale_alert():
    txs = [tx(title="Chief Executive Officer", code="P", shares=100,
              price=100.0, tx_date=date(2026, 8, 15))]      # $10k
    assert should_emit_whale_buy(txs, as_of=date(2026, 8, 19)) is False


def test_insider_selling_never_triggers_a_whale_buy():
    txs = [tx(title="Chief Executive Officer", code="S", shares=200_000,
              price=100.0, tx_date=date(2026, 8, 15))]
    assert should_emit_whale_buy(txs, as_of=date(2026, 8, 19)) is False


def test_option_exercises_never_trigger_a_whale_buy():
    """Guards the same $7B false positive the Liar Filter tests cover."""
    txs = [tx(title="Chief Executive Officer", code="M", shares=300_000_000,
              price=23.34, tx_date=date(2026, 8, 15))]
    assert should_emit_whale_buy(txs, as_of=date(2026, 8, 19)) is False


# ------------------------------------------------------------ State B
def test_eight_k_event_matches_the_documented_schema():
    payload = eight_k_material_event("INTC", "1.01",
                                     "Strategic Partnership Contract Verified")
    assert payload["event"] == "8k_material_event"
    assert payload["color"] == "#00E5FF"
    assert payload["duration_ms"] == 6000
    assert payload["icon"] == "📜"
    assert "1.01" in payload["detail"]


# ------------------------------------------------------------ State C
def test_liar_filter_warning_matches_the_documented_schema():
    payload = liar_filter_warning("META", 92.0, -18_200_000.0)
    assert payload["event"] == "liar_filter_warning"
    assert payload["color"] == "#FF9100"
    assert payload["duration_ms"] == 8000
    assert payload["icon"] == "⚠️"
    assert payload["badge"] == "Divergence"
    assert "92" in payload["detail"]
    assert "18.2" in payload["detail"]


# ------------------------------------------------------------ State D
def test_outlier_leader_matches_the_documented_schema():
    payload = relative_outlier_leader("QCOM", 91, rank=1, detail="32% ROIC")
    assert payload["event"] == "relative_outlier_leader"
    assert payload["color"] == "#D4AF37"
    assert payload["duration_ms"] == 6000
    assert payload["badge"] == "Rank #1"


# ------------------------------------------------------------ State E
def test_scoring_progress_matches_the_documented_schema():
    payload = scoring_progress("TSLA", "L1 Fundamentals • L5 Form 4")
    assert payload["event"] == "scoring_progress"
    assert payload["color"] == "#3B82F6"
    assert payload["duration_ms"] == 2000
    assert payload["badge"] == "Scoring"


def test_every_payload_is_json_serialisable():
    import json
    for payload in (
        form4_whale_buy("NVDA", "CEO", 12_500_000.0, 88),
        eight_k_material_event("INTC", "1.01", "x"),
        liar_filter_warning("META", 92.0, -18_200_000.0),
        relative_outlier_leader("QCOM", 91, 1, "x"),
        scoring_progress("TSLA", "x"),
    ):
        assert json.loads(json.dumps(payload))["module"] == "trade"


def test_write_dynamic_island_event_atomic(tmp_path):
    import json
    from aethelark_trade.engine.events import write_dynamic_island_event
    dest = tmp_path / "atrade_dynamic_island.json"
    payload = form4_whale_buy("NVDA", "CEO", 12_500_000.0, 88)
    write_dynamic_island_event(payload, dest=dest)
    assert dest.exists()
    data = json.loads(dest.read_text())
    assert data["ticker"] == "NVDA"
    assert data["event"] == "form4_whale_buy"


def test_event_priority_ordering():
    from aethelark_trade.engine.events import (
        eight_k_material_event,
        event_priority,
        form4_whale_buy,
        liar_filter_warning,
    )
    p_warn = liar_filter_warning("META", 90.0, -10_000_000.0)
    p_whale = form4_whale_buy("NVDA", "CEO", 5_000_000.0, 85)
    p_8k = eight_k_material_event("INTC", "1.01", "agreement")

    # Higher priority sort key should order: 8k < whale < warn
    assert event_priority(p_8k) < event_priority(p_whale) < event_priority(p_warn)

    # When sorted ascending, highest priority is last (latest wins on write)
    events = [p_whale, p_warn, p_8k]
    events.sort(key=event_priority)
    assert events[-1] == p_warn
