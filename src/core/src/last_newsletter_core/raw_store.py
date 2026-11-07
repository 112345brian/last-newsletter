"""In-memory `RawMessageStore`: the core-owned fake that other packages can import in tests."""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from hashlib import sha256
from typing import TYPE_CHECKING

from last_newsletter_core.events import RawRef

if TYPE_CHECKING:
    from last_newsletter_core.entities import EmailMessage


class InMemoryRawMessageStore:
    def __init__(self) -> None:
        self._messages: dict[RawRef, EmailMessage] = {}

    def put(self, message: EmailMessage) -> RawRef:
        ref = RawRef("raw:" + sha256(message.message_id.encode()).hexdigest())
        self._messages[ref] = message
        return ref

    def get(self, ref: RawRef) -> EmailMessage | None:
        return self._messages.get(ref)
