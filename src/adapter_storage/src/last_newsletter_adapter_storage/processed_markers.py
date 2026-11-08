"""Which raw messages the `process` stage has finished with, as one small JSON file.

A ref is marked only after its batch ingested without an extraction failure, so a failed batch
is retried on the next run. Ingest itself is idempotent, so re-processing is always safe; the
markers only save the work. A missing or unreadable file means "nothing processed yet".
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

import json
from typing import TYPE_CHECKING

from last_newsletter_adapter_storage.atomic_file import write_text_atomic
from last_newsletter_core.events import RawRef

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


class ProcessedMarkers:
    def __init__(self, path: Path) -> None:
        self._path = path

    def processed(self) -> set[RawRef]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return {RawRef(ref) for ref in data["processed"] if isinstance(ref, str)}
        except (OSError, ValueError, KeyError, TypeError):
            return set()

    def mark(self, refs: Iterable[RawRef]) -> None:
        merged = sorted(self.processed() | set(refs))
        write_text_atomic(self._path, json.dumps({"schema": 1, "processed": merged}))
