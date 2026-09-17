"""Test Task 3: LLY and PM gain ROIC, and 20-F filers (ASML, ARM) resolve fundamentals."""
import pytest
from aethelark_trade.engine.engine import SECClientContext
from aethelark_trade.engine.fetchers import load_fundamentals
from aethelark_trade.engine.layers.fundamentals import score_fundamentals


def test_lly_and_pm_gain_roic():
    """LLY lacks OperatingIncomeLoss (reports pre-tax continuing operations).
    PM has negative equity and LongTermDebt filed under LongTermDebtAndCapitalLeaseObligations.
    Both must gain ROIC."""
    with SECClientContext() as client:
        snap_lly, _ = load_fundamentals(client, "LLY")
        assert snap_lly.revenue is not None
        assert snap_lly.roic is not None and snap_lly.roic > 0
        score_lly = score_fundamentals(snap_lly)
        assert score_lly.available is True
        assert "ROIC" in score_lly.summary

        snap_pm, _ = load_fundamentals(client, "PM")
        assert snap_pm.revenue is not None
        assert snap_pm.roic is not None and snap_pm.roic > 0
        score_pm = score_fundamentals(snap_pm)
        assert score_pm.available is True
        assert "ROIC" in score_pm.summary


def test_foreign_filers_resolve_fundamentals():
    """ASML and ARM file form 20-F. They must return fundamentals rather than
    'No XBRL fundamentals available'."""
    with SECClientContext() as client:
        snap_asml, _ = load_fundamentals(client, "ASML")
        assert snap_asml.revenue is not None and snap_asml.revenue > 0
        score_asml = score_fundamentals(snap_asml)
        assert score_asml.available is True
        assert score_asml.score is not None

        snap_arm, _ = load_fundamentals(client, "ARM")
        assert snap_arm.revenue is not None and snap_arm.revenue > 0
        score_arm = score_fundamentals(snap_arm)
        assert score_arm.available is True
        assert score_arm.score is not None
