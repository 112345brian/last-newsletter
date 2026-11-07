"""Shared atomic, private (0600) text-file write: temp file in the same directory + rename."""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import contextlib
import os
import tempfile
from pathlib import Path

from process_lock.file_lock import replace_with_retry


def write_text_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        replace_with_retry(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(tmp_name).unlink()
        raise
