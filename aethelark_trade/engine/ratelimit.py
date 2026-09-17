"""Cross-process SEC rate limiting.

sec_client.RateLimiter paces requests with a class attribute, so its guarantee
ends at the process boundary. That is not a theoretical gap: `atrade listen` is
designed to run continuously while `atrade analyze` and
`atrade leaderboard --refresh` are used interactively, and each process then
paces independently at ~7 req/s. Measured under concurrent runs: HTTP 429.

This limiter keeps the last-request timestamp in a small file guarded by an
advisory lock, so every process on the machine queues through the same gate.
"""

import errno
import os
import struct
import threading
import time
from pathlib import Path

# SEC's hard ceiling. Exceeding it returns HTTP 429 and risks an IP block.
SEC_MAX_REQUESTS_PER_SECOND = 10.0

# Pace at ~7 req/s, leaving headroom for clock jitter and in-flight retries.
DEFAULT_MIN_INTERVAL = 0.14

DEFAULT_STATE_PATH = Path.home() / ".aethelark" / "sec_ratelimit.lock"

_STAMP = struct.Struct("<d")


class CrossProcessRateLimiter:
    """Machine-wide minimum spacing between SEC requests."""

    def __init__(self, state_path=None, min_interval: float = DEFAULT_MIN_INTERVAL):
        self.min_interval = min_interval
        self.state_path = Path(state_path) if state_path else DEFAULT_STATE_PATH
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._fd: int | None = None
        # flock is held per open file description, not per thread, so a second
        # thread in THIS process calling acquire() on the same fd is granted the
        # lock immediately and both proceed. The file gate stops other
        # processes; only this stops our own threads. It matters from the
        # moment the layers run concurrently: without it two SEC layers pace
        # independently, which is how the 429 this class exists to prevent
        # comes back through a door nobody was watching.
        self._local = threading.Lock()

    def _open(self) -> int:
        if self._fd is None:
            self._fd = os.open(self.state_path, os.O_RDWR | os.O_CREAT, 0o644)
        return self._fd

    def acquire(self) -> None:
        """Block until it is safe to issue the next request.

        Serialised across threads as well as processes: see `_local`.
        """
        with self._local:
            self._acquire_locked()

    def _acquire_locked(self) -> None:
        try:
            import fcntl
        except ImportError:  # non-POSIX: degrade to in-process spacing
            self._sleep_local()
            return

        fd = self._open()
        while True:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                raw = os.read(fd, _STAMP.size)
                last = _STAMP.unpack(raw)[0] if len(raw) == _STAMP.size else 0.0

                now = time.time()
                wait = self.min_interval - (now - last)

                # A clock jump backwards would otherwise wedge every caller.
                if wait > self.min_interval:
                    wait = 0.0

                if wait <= 0:
                    os.lseek(fd, 0, os.SEEK_SET)
                    os.write(fd, _STAMP.pack(time.time()))
                    return
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)

            # Sleep OUTSIDE the lock so waiters do not serialise on each other.
            time.sleep(wait)

    _last_local = 0.0

    def _sleep_local(self) -> None:
        now = time.time()
        elapsed = now - CrossProcessRateLimiter._last_local
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        CrossProcessRateLimiter._last_local = time.time()

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError as exc:
                if exc.errno != errno.EBADF:
                    raise
            self._fd = None

    # Compatibility with sec_client.RateLimiter's interface.
    def wait(self) -> None:
        self.acquire()
