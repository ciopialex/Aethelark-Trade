"""SEC rate limiting must hold ACROSS processes, not just within one.

sec_client.RateLimiter paces requests using a class attribute, so its guarantee
stops at the process boundary -- its own docstring says "same process". Two
concurrent `atrade` invocations therefore each pace at ~7 req/s and collectively
issue ~14 req/s, over the SEC's hard 10 req/s ceiling. Measured: sustained
concurrent runs produced HTTP 429.

This is a realistic configuration, not a stress test: `atrade listen` is meant
to run continuously while `atrade analyze` and `atrade leaderboard --refresh`
are used interactively.

Zero mocks: these spawn real OS processes and measure real wall-clock spacing.
"""
import subprocess
import sys
import time
from pathlib import Path

import pytest

from aethelark_trade.engine.ratelimit import (
    SEC_MAX_REQUESTS_PER_SECOND,
    CrossProcessRateLimiter,
)

WORKER = """
import sys, time
sys.path.insert(0, {repo!r})
from aethelark_trade.engine.ratelimit import CrossProcessRateLimiter
limiter = CrossProcessRateLimiter(state_path={state!r}, min_interval={interval!r})
stamps = []
for _ in range({n}):
    limiter.acquire()
    stamps.append(time.time())
open({out!r}, "w").write("\\n".join(repr(s) for s in stamps))
"""

REPO = str(Path(__file__).resolve().parent.parent)


def test_single_process_spacing_is_enforced(tmp_path):
    limiter = CrossProcessRateLimiter(state_path=tmp_path / "rl", min_interval=0.05)
    start = time.time()
    for _ in range(5):
        limiter.acquire()
    assert time.time() - start >= 0.05 * 4


def test_documented_ceiling():
    assert SEC_MAX_REQUESTS_PER_SECOND == 10.0


def test_concurrent_processes_do_not_exceed_the_ceiling(tmp_path):
    """Four processes, 12 acquisitions each, one shared limiter state.

    Without cross-process coordination each would pace independently and the
    combined rate would be ~4x the per-process rate.
    """
    interval = 0.12          # ~8.3 req/s if honoured globally
    per_worker = 12
    workers = 4

    procs = []
    for i in range(workers):
        script = WORKER.format(
            repo=REPO, state=str(tmp_path / "rl"), interval=interval,
            n=per_worker, out=str(tmp_path / f"out{i}.txt"),
        )
        procs.append(subprocess.Popen([sys.executable, "-c", script]))
    for p in procs:
        assert p.wait(timeout=120) == 0

    stamps = []
    for i in range(workers):
        stamps += [float(line) for line in
                   (tmp_path / f"out{i}.txt").read_text().splitlines() if line]
    stamps.sort()
    assert len(stamps) == workers * per_worker

    # No one-second window may contain more than the ceiling allows.
    worst = 0
    for i, t in enumerate(stamps):
        j = i
        while j < len(stamps) and stamps[j] - t < 1.0:
            j += 1
        worst = max(worst, j - i)

    assert worst <= SEC_MAX_REQUESTS_PER_SECOND, (
        f"{worst} requests landed inside one second across {workers} processes"
    )


def test_minimum_spacing_holds_between_adjacent_cross_process_requests(tmp_path):
    interval = 0.10
    procs = []
    for i in range(3):
        script = WORKER.format(
            repo=REPO, state=str(tmp_path / "rl"), interval=interval,
            n=8, out=str(tmp_path / f"o{i}.txt"),
        )
        procs.append(subprocess.Popen([sys.executable, "-c", script]))
    for p in procs:
        assert p.wait(timeout=120) == 0

    stamps = sorted(
        float(line)
        for i in range(3)
        for line in (tmp_path / f"o{i}.txt").read_text().splitlines() if line
    )
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    # Allow a small scheduling tolerance, but the guarantee must broadly hold.
    assert min(gaps) >= interval * 0.7, f"smallest gap {min(gaps):.4f}s < {interval}s"


def test_state_file_is_created_under_the_given_path(tmp_path):
    limiter = CrossProcessRateLimiter(state_path=tmp_path / "nested" / "rl",
                                      min_interval=0.01)
    limiter.acquire()
    assert (tmp_path / "nested" / "rl").exists()


# --- integration with the existing SEC client -----------------------------
def test_sec_client_rate_limiter_is_cross_process():
    """Every SEC call site (sec_client, collector, daemon, atrade) goes through
    SECClient.rate_limiter, so the cross-process guarantee has to live there
    rather than in a parallel code path only the new engine uses."""
    from aethelark_trade.sec_client import SECClient

    client = SECClient()
    try:
        assert isinstance(client.rate_limiter.limiter(), CrossProcessRateLimiter)
    finally:
        client.close()


def test_sec_client_still_exposes_the_wait_interface():
    from aethelark_trade.sec_client import RateLimiter

    limiter = RateLimiter()
    start = time.time()
    limiter.wait()
    limiter.wait()
    assert time.time() - start >= 0.0
    assert hasattr(limiter, "wait")


def test_sec_client_min_interval_stays_inside_the_ceiling():
    from aethelark_trade.sec_client import MIN_REQUEST_INTERVAL

    assert 1.0 / MIN_REQUEST_INTERVAL < SEC_MAX_REQUESTS_PER_SECOND
