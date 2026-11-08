"""Build a ranked, continuity-aware digest over time: no I/O, no framework, no app-specific
concept beyond the type names (`EmailMessage`, `EmailSource`) that describe where items come
from -- a consumer outside the email/newsletter domain supplies its own `EmailSource` and
`Summarizer` and gets the same continuity and ranking behavior."""

from __future__ import annotations

__arbor__ = {"ring": "core"}

from ranked_digest.entities import Cadence, Digest, EmailMessage, Theme, digest_slug
from ranked_digest.ports import (
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
