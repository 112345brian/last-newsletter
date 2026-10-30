"""Boundary interfaces. Core defines these; adapter packages implement them.

Nothing in this file may import a concrete adapter — the dependency points
inward, from adapters toward these Protocols, never the other way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime

    from last_newsletter_core.entities import Digest, EmailMessage, Theme


class EmailSource(Protocol):
    """Fetches raw messages for a given window. Implemented by an adapter package."""

    def fetch_since(self, since: datetime) -> list[EmailMessage]: ...


class Summarizer(Protocol):
    """Turns a batch of messages into cross-source themes. Implemented by an adapter package."""

    def summarize(self, messages: list[EmailMessage]) -> list[Theme]: ...


class DigestPublisher(Protocol):
    """Renders a finished Digest somewhere a human will read it."""

    def publish(self, digest: Digest) -> None: ...


class DigestRepository(Protocol):
    """Persists digests and makes past ones retrievable, keyed by an opaque slug.

    The slug's format is the repository implementation's own business (a
    filename, a database id, whatever) — callers only ever get one back from
    `save` or `list_recent` and pass it back to `get`, never construct one.
    """

    def save(self, digest: Digest) -> str: ...

    def list_recent(self, limit: int = 20) -> list[tuple[str, Digest]]: ...

    def get(self, slug: str) -> Digest | None: ...
