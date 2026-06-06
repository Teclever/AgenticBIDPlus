"""Cross-process file lock for the single path to Sonnet (WEBAPP_DESIGN §16.8).

The nightly Pass-2 phase and a web "Generate Summary" click both call ``summarize_bid``.
A POSIX ``flock`` on one lockfile under the runtime dir serialises them across processes
(the web server and the systemd-timer run are separate processes). The web endpoint takes
the lock NON-BLOCKING so it can return 409 "busy" instead of hanging while the nightly run
holds it; the nightly run takes it blocking.
"""

from __future__ import annotations

import contextlib
import fcntl
import os

import bidplus.config as config

SUMMARIZE_LOCK_PATH = config.RUNTIME_DIR / "summarize.lock"


class LockBusy(RuntimeError):
    """Raised when a non-blocking acquire fails because the lock is already held."""


@contextlib.contextmanager
def summarize_lock(blocking: bool = True):
    """Hold the global summarization lock for the duration of the ``with`` block.

    ``blocking=False`` raises :class:`LockBusy` immediately if another process holds it.
    """
    config.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(SUMMARIZE_LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o644)
    flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
    try:
        try:
            fcntl.flock(fd, flags)
        except (BlockingIOError, OSError) as e:
            raise LockBusy("summarization is busy (nightly run in progress)") from e
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
