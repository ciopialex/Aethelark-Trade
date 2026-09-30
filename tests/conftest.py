"""Shared collection rules.

Some tests read live SEC filings. SEC requires a contactable email in the
User-Agent and answers 403 without one, so those tests cannot pass on a machine
that has not configured a contact — and failing them there reports a
configuration gap as a broken build.

They are skipped instead, with a reason that says what to set. Configure one
and they run:

    atrade register --contact you@example.com
    # or
    export ATRADE_SEC_CONTACT="you@example.com"
"""
from __future__ import annotations

import pytest

#: Tests that reach data.sec.gov / www.sec.gov rather than a fixture.
_NEEDS_SEC = {
    "test_foreign_and_roic.py",
    "test_liar_filter_real_filings.py",
}


def pytest_collection_modifyitems(config, items):
    from aethelark_trade.engine.useragent import sec_contact

    if sec_contact() is not None:
        return

    skip = pytest.mark.skip(
        reason="no SEC contact configured (ATRADE_SEC_CONTACT or "
               "`atrade register --contact`); SEC answers 403 without one")
    for item in items:
        if item.path.name in _NEEDS_SEC or "network" in item.keywords:
            item.add_marker(skip)
