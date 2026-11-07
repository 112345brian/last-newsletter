__arbor__ = {"ring": "core"}

from last_newsletter_core.entities import Cadence, Digest, EmailMessage, Theme, digest_slug
from last_newsletter_core.ports import (
    DigestPublisher,
    DigestRepository,
    EmailSource,
    RelevanceWeigher,
    Summarizer,
)

__all__ = [
    "Cadence",
    "Digest",
    "DigestPublisher",
    "DigestRepository",
    "EmailMessage",
    "EmailSource",
    "RelevanceWeigher",
    "Summarizer",
    "Theme",
    "digest_slug",
]
