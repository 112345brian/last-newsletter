"""Mail <-> event-ledger documents.

The event ledger (vendored `concert_tracker_core`) knows one input type, `SourceDocument`; mail is
one source of them. `EmailMessage` and `SourceDocument` carry the same six facts, so the mapping is
a field copy, kept in this one place so nothing else has to know both types.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

from typing import TYPE_CHECKING

from concert_tracker_core.documents import SourceDocument

from ranked_digest.entities import EmailMessage

if TYPE_CHECKING:
    from concert_tracker_core.events import RawRef

    from last_newsletter_adapter_storage.raw_message_store import ListableRawMessageStore


def to_document(message: EmailMessage) -> SourceDocument:
    return SourceDocument(
        message_id=message.message_id,
        sender=message.sender,
        subject=message.subject,
        received_at=message.received_at,
        body_text=message.body_text,
        source_label=message.source_label,
    )


def to_email(document: SourceDocument) -> EmailMessage:
    return EmailMessage(
        message_id=document.message_id,
        sender=document.sender,
        subject=document.subject,
        received_at=document.received_at,
        body_text=document.body_text,
        source_label=document.source_label,
    )


class RawStoreDocuments:
    """The ledger's `DocumentStore` port over the raw email store, so an event's mention can be
    traced back to the stored mail."""

    def __init__(self, store: ListableRawMessageStore) -> None:
        self._store = store

    def put(self, message: SourceDocument) -> RawRef:
        return self._store.put(to_email(message))

    def get(self, ref: RawRef) -> SourceDocument | None:
        email = self._store.get(ref)
        return None if email is None else to_document(email)
