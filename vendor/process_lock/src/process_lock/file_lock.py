"""One cross-platform, cross-process exclusive file lock.

Several places need "only one process (and thread) at a time may run this
read-modify-write span": the browser scrapers' digest persistence, the tracker's
pending-questions and applied-state files, the Workday session registry, and the
browser-profile allocation registry. They used to each carry their own copy of the
msvcrt/fcntl split, with different (and mostly implicit) answers to "what if the
lock is never released?". This is the one copy, and the answer is an argument:

``timeout_s``
    How long to wait for the lock. ``None`` waits forever (only for a holder that
    is known to finish, like a small JSON rewrite with no I/O inside it).
``on_timeout``
    ``"raise"`` (default): a wedged holder is an error, raised as
    :class:`TimeoutError` so the caller can back off and retry or fail loudly.
    ``"proceed"``: log a warning and run the body WITHOUT the lock. Only for
    best-effort observability state that must never be what breaks real work
    (``jobsearch.scrapers.browser_registry``); a lost update there is a stale
    hint, not lost data. It also covers a lock file that cannot be opened.

Utility module: any layer may import it. The OS-level lock is ``filelock`` (``flock`` on POSIX, ``msvcrt`` on
Windows); the rename retry is ``tenacity``. This module keeps only the policy above.
"""
from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Literal

from filelock import FileLock, Timeout
from tenacity import retry_if_exception_type, stop_after_attempt, wait_incrementing, Retrying

_LOGGER = logging.getLogger("process_lock.file_lock")

_POLL_S = 0.05

_REPLACE_ATTEMPTS = 8
_REPLACE_BACKOFF_S = 0.02


def replace_with_retry(src: str | os.PathLike, dst: str | os.PathLike) -> None:
    """``os.replace``, retried briefly on ``PermissionError``.

    On Windows a replace onto a file that another process has open (a reader
    mid-``read_text``, or a second writer replacing at that instant) fails with
    ``[WinError 5] Access is denied`` instead of waiting. That is transient (the
    other handle is held for milliseconds), so back off and try again; POSIX never
    raises it here. The last attempt's error propagates."""
    for attempt in Retrying(
        retry=retry_if_exception_type(PermissionError),
        stop=stop_after_attempt(_REPLACE_ATTEMPTS),
        wait=wait_incrementing(start=_REPLACE_BACKOFF_S, increment=_REPLACE_BACKOFF_S),
        reraise=True,
    ):
        with attempt:
            os.replace(src, dst)


@contextmanager
def cross_process_file_lock(
    lock_path: Path | str,
    *,
    timeout_s: float | None,
    on_timeout: Literal["raise", "proceed"] = "raise",
    thread_lock: threading.Lock | None = None,
    label: str = "file",
) -> Iterator[None]:
    """Hold an exclusive lock on ``lock_path`` (created, with its parent, if
    missing) for the ``with`` body, against other processes AND, when
    ``thread_lock`` is given, other threads of this process (taken first, and
    waited on without a bound: threads of one process are not the wedged-holder
    risk this timeout is for).

    See the module docstring for ``timeout_s`` / ``on_timeout``. ``label`` names
    the lock in the timeout error and warnings."""
    lock_path = Path(lock_path)
    with thread_lock if thread_lock is not None else nullcontext():
        lock: FileLock | None = None
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.touch(exist_ok=True)
            lock = FileLock(lock_path, timeout=-1 if timeout_s is None else timeout_s, poll_interval=_POLL_S)
        except OSError as exc:
            if on_timeout == "raise":
                raise
            _LOGGER.warning("%s lock: could not open %s (%s) -- proceeding unlocked", label, lock_path, exc)
        locked = False
        try:
            if lock is not None:
                try:
                    lock.acquire()
                    locked = True
                except Timeout:
                    if on_timeout == "raise":
                        raise TimeoutError(
                            f"{label} lock held >{timeout_s:g}s by another process -- "
                            f"check for a wedged run ({lock_path})"
                        ) from None
                    _LOGGER.warning(
                        "%s lock: %s not acquired within %gs -- proceeding unlocked", label, lock_path, timeout_s,
                    )
                except OSError as exc:  # not contention: this filesystem cannot lock
                    if on_timeout == "raise":
                        raise
                    _LOGGER.warning("%s lock: could not lock %s (%s) -- proceeding unlocked", label, lock_path, exc)
            yield
        finally:
            if locked:
                lock.release()
