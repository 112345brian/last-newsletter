"""Composable noise filter over any EmailSource: drops messages any configured filter flags.

Follows the same shape as last_newsletter_adapter_publish.email_publisher.CompositePublisher --
wraps a Sequence of the port's own collaborators and implements the port itself, so it drops
into the composition root with no change to anything else that consumes EmailSource.

`MessageFilter` is sized to this composition, not to core.ports: it's an adapter-layer
detail in how an EmailSource is wired, not something BuildDigestUseCase or any other core
code ever touches. last_newsletter_core.filtering.FilterRule satisfies it structurally,
needing no import of this module.
"""

from __future__ import annotations

__arbor__ = {"ring": "adapters"}

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from last_newsletter_core.entities import EmailMessage
    from last_newsletter_core.ports import EmailSource


class MessageFilter(Protocol):
    """True means drop the message."""

    def matches(self, message: EmailMessage) -> bool: ...


class FilteredEmailSource:
    """Implements last_newsletter_core.ports.EmailSource."""

    def __init__(self, source: EmailSource, filters: Sequence[MessageFilter] = ()) -> None:
        self._source = source
        self._filters = tuple(filters)

    def fetch_since(self, since: datetime) -> list[EmailMessage]:
        messages = self._source.fetch_since(since)
        if not self._filters:
            return messages
        return [m for m in messages if not any(f.matches(m) for f in self._filters)]
