"""In-memory `DocumentStore`: the core-owned fake that other packages can import in tests."""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from hashlib import sha256
from typing import TYPE_CHECKING

from concert_tracker_core.events import RawRef

if TYPE_CHECKING:
    from concert_tracker_core.documents import SourceDocument


class InMemoryDocumentStore:
    def __init__(self) -> None:
        self._messages: dict[RawRef, SourceDocument] = {}

    def put(self, message: SourceDocument) -> RawRef:
        ref = RawRef("raw:" + sha256(message.message_id.encode()).hexdigest())
        self._messages[ref] = message
        return ref

    def get(self, ref: RawRef) -> SourceDocument | None:
        return self._messages.get(ref)
