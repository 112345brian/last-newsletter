__arbor__ = {"ring": "adapters"}

from last_newsletter_adapter_storage.documents import RawStoreDocuments, to_document, to_email
from last_newsletter_adapter_storage.json_event_repository import JsonEventRepository
from last_newsletter_adapter_storage.json_repository import JsonDigestRepository
from last_newsletter_adapter_storage.processed_markers import ProcessedMarkers
from last_newsletter_adapter_storage.raw_message_store import (
    FileRawMessageStore,
    ListableRawMessageStore,
    RawStoreEmailSource,
)

__all__ = [
    "FileRawMessageStore",
    "JsonDigestRepository",
    "JsonEventRepository",
    "ListableRawMessageStore",
    "ProcessedMarkers",
    "RawStoreDocuments",
    "RawStoreEmailSource",
    "to_document",
    "to_email",
]
